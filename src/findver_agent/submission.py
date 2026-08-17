"""Deterministic sealed-submission creation and validation."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from findver_agent.evidence_sidecar import (
    SIDECAR_NAME,
    SIDECAR_SCHEMA_VERSION,
    EvidenceSidecarError,
    build_evidence_ledger_sidecar,
    load_evidence_ledger_sidecar,
    write_immutable_sidecar,
)
from findver_agent.run_identity import RunIdentity
from findver_agent.schemas import Prediction, PredictionStatus


ALLOWED_MEMBERS = ("predictions.jsonl", "manifest.json", "SHA256SUMS")
MAX_MEMBER_BYTES = 64 * 1024 * 1024
FORBIDDEN_PREDICTION_KEYS = {
    "entailment_label",
    "gold_label",
    "relevant_context",
    "result",
    "correct",
    "extracted_label",
    "gold_explanation",
    "subset",
    "feedback",
    "scorer",
}


class SubmissionError(ValueError):
    """A run or archive violates the sealed submission contract."""


class SubmissionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$", min_length=1, max_length=256)
    status: Literal["sealed"]
    model: str = Field(min_length=1)
    backend: Literal["api", "local", "mock"]
    agent_enabled: bool
    git_commit: str = Field(min_length=1)
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    public_tasks_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    predictions_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_identity: RunIdentity | None = None
    evidence_ledger_sidecar_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    evidence_ledger_sidecar_schema_version: Literal[1] | None = None
    expected_examples: int = Field(ge=0)
    submitted_examples: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def counts_and_times_are_consistent(self) -> "SubmissionManifest":
        if self.expected_examples != self.submitted_examples:
            raise ValueError("submitted example count must equal expected example count")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if (self.evidence_ledger_sidecar_sha256 is None) != (
            self.evidence_ledger_sidecar_schema_version is None
        ):
            raise ValueError("evidence ledger sidecar hash and schema version must be paired")
        if self.run_identity is not None:
            identity = self.run_identity
            bound_fields = {
                "run ID": (self.run_id, identity.plan_run_id),
                "model alias": (self.model, identity.model_alias),
                "backend": (self.backend, identity.backend_kind),
                "git commit": (self.git_commit, identity.git_commit_at_start),
                "config SHA256": (self.config_sha256, identity.config_sha256),
                "public tasks SHA256": (
                    self.public_tasks_sha256,
                    identity.public_tasks_sha256,
                ),
            }
            for name, (manifest_value, identity_value) in bound_fields.items():
                if manifest_value != identity_value:
                    raise ValueError(f"manifest {name} must match run identity")
        return self


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_predictions(data: bytes) -> list[Prediction]:
    predictions: list[Prediction] = []
    seen: set[str] = set()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SubmissionError("predictions.jsonl must be UTF-8") from error
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise SubmissionError(f"invalid prediction JSON on line {line_number}") from error
        if not isinstance(raw, dict):
            raise SubmissionError(f"prediction on line {line_number} is not an object")
        forbidden = set(raw) & FORBIDDEN_PREDICTION_KEYS
        if forbidden:
            raise SubmissionError(f"prediction contains forbidden fields: {sorted(forbidden)}")
        try:
            prediction = Prediction.model_validate(raw)
        except ValueError as error:
            raise SubmissionError(f"invalid prediction on line {line_number}: {error}") from error
        if prediction.example_id in seen:
            raise SubmissionError(f"duplicate prediction id: {prediction.example_id}")
        if prediction.status == PredictionStatus.COMPLETED and prediction.label is None:
            raise SubmissionError("completed prediction must have a label")
        if prediction.status != PredictionStatus.COMPLETED and prediction.label is not None:
            raise SubmissionError("non-completed prediction cannot have a label")
        seen.add(prediction.example_id)
        predictions.append(prediction)
    return predictions


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name in ALLOWED_MEMBERS:
                data = files[name]
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def seal_submission(run_dir: Path, output: Path, *, repository_root: Path | None = None) -> str:
    run_dir = run_dir.resolve(strict=True)
    metadata_path = run_dir / "run_metadata.json"
    predictions_path = run_dir / "predictions.jsonl"
    if (run_dir / "predictions.partial.jsonl").exists():
        raise SubmissionError("cannot seal while partial predictions exist")
    if not metadata_path.is_file() or not predictions_path.is_file():
        raise SubmissionError("completed metadata and predictions.jsonl are required")
    if output.exists():
        raise SubmissionError("output submission already exists")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "completed":
        raise SubmissionError("run metadata is not completed")
    predictions_data = predictions_path.read_bytes()
    predictions = _load_predictions(predictions_data)
    expected_ids = metadata.get("task_ids")
    if not isinstance(expected_ids, list) or any(not isinstance(item, str) for item in expected_ids):
        raise SubmissionError("run metadata does not contain task_ids")
    prediction_ids = [prediction.example_id for prediction in predictions]
    if prediction_ids != expected_ids:
        raise SubmissionError(
            "prediction IDs do not exactly match public task order"
        )
    if metadata.get("expected_examples") != len(expected_ids):
        raise SubmissionError("metadata expected count does not match task_ids")
    sidecar_sha256 = None
    sidecar_schema_version = None
    if metadata.get("agent_enabled") is True:
        try:
            sidecar_data = build_evidence_ledger_sidecar(run_dir, expected_ids)
            sidecar_sha256 = write_immutable_sidecar(
                run_dir / SIDECAR_NAME,
                sidecar_data,
            )
        except EvidenceSidecarError as error:
            raise SubmissionError(str(error)) from error
        sidecar_schema_version = SIDECAR_SCHEMA_VERSION
    identity_data = metadata.get("run_identity")
    run_identity = None
    if identity_data is not None:
        try:
            run_identity = RunIdentity.model_validate(identity_data)
        except ValueError as error:
            raise SubmissionError("run metadata contains an invalid run identity") from error
    repository_root = repository_root or Path(__file__).resolve().parents[2]
    manifest = SubmissionManifest(
        run_id=run_dir.name,
        status="sealed",
        model=metadata["model"],
        backend=metadata["backend"],
        agent_enabled=metadata["agent_enabled"],
        git_commit=(
            run_identity.git_commit_at_start
            if run_identity is not None
            else metadata.get("git_commit") or _git_commit(repository_root)
        ),
        config_sha256=metadata["config_sha256"],
        public_tasks_sha256=metadata["public_tasks_sha256"],
        predictions_sha256=sha256_bytes(predictions_data),
        run_identity=run_identity,
        evidence_ledger_sidecar_sha256=sidecar_sha256,
        evidence_ledger_sidecar_schema_version=sidecar_schema_version,
        expected_examples=len(expected_ids),
        submitted_examples=len(predictions),
        started_at=metadata["started_at"],
        completed_at=metadata["completed_at"],
    )
    manifest_data = (
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    sums_data = (
        f"{sha256_bytes(predictions_data)}  predictions.jsonl\n"
        f"{sha256_bytes(manifest_data)}  manifest.json\n"
    ).encode("ascii")
    archive_data = _tar_bytes(
        {
            "predictions.jsonl": predictions_data,
            "manifest.json": manifest_data,
            "SHA256SUMS": sums_data,
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(archive_data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        os.replace(temporary, output)
        directory = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return sha256_bytes(archive_data)


def _safe_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if member.name not in ALLOWED_MEMBERS:
        raise SubmissionError(f"archive contains an unexpected member: {member.name}")
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise SubmissionError(f"archive member path is unsafe: {member.name}")
    if not member.isreg() or member.issym() or member.islnk():
        raise SubmissionError(f"archive member is not a regular file: {member.name}")
    if member.size < 0 or member.size > MAX_MEMBER_BYTES:
        raise SubmissionError(f"archive member is too large: {member.name}")


def _parse_sums(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise SubmissionError("SHA256SUMS must be ASCII") from error
    sums: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64 or any(character not in "0123456789abcdef" for character in parts[0]):
            raise SubmissionError("invalid SHA256SUMS line")
        if parts[1] in sums:
            raise SubmissionError("duplicate SHA256SUMS entry")
        sums[parts[1]] = parts[0]
    if set(sums) != {"predictions.jsonl", "manifest.json"}:
        raise SubmissionError("SHA256SUMS must cover exactly predictions.jsonl and manifest.json")
    return sums


def verify_submission_archive(
    path: Path,
    *,
    evidence_ledger_sidecar: Path | None = None,
) -> tuple[SubmissionManifest, list[Prediction]]:
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) != len(ALLOWED_MEMBERS):
                raise SubmissionError("archive must contain exactly three files")
            files: dict[str, bytes] = {}
            for member in members:
                _safe_member(member)
                if member.name in files:
                    raise SubmissionError(f"duplicate archive member: {member.name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SubmissionError(f"cannot read archive member: {member.name}")
                files[member.name] = extracted.read(MAX_MEMBER_BYTES + 1)
                if len(files[member.name]) > MAX_MEMBER_BYTES:
                    raise SubmissionError(f"archive member is too large: {member.name}")
    except (tarfile.TarError, OSError) as error:
        raise SubmissionError(f"invalid submission archive: {error}") from error
    if set(files) != set(ALLOWED_MEMBERS):
        raise SubmissionError("archive member set is invalid")
    sums = _parse_sums(files["SHA256SUMS"])
    for name, expected in sums.items():
        if sha256_bytes(files[name]) != expected:
            raise SubmissionError(f"hash mismatch for {name}")
    try:
        manifest = SubmissionManifest.model_validate_json(files["manifest.json"])
    except ValueError as error:
        raise SubmissionError(f"invalid manifest: {error}") from error
    predictions = _load_predictions(files["predictions.jsonl"])
    if sha256_bytes(files["predictions.jsonl"]) != manifest.predictions_sha256:
        raise SubmissionError("manifest predictions hash mismatch")
    if len(predictions) != manifest.submitted_examples:
        raise SubmissionError("manifest submitted count mismatch")
    if evidence_ledger_sidecar is not None:
        if manifest.evidence_ledger_sidecar_sha256 is None:
            if evidence_ledger_sidecar.exists():
                raise SubmissionError("unexpected evidence ledger sidecar")
        else:
            try:
                load_evidence_ledger_sidecar(
                    evidence_ledger_sidecar,
                    expected_sha256=manifest.evidence_ledger_sidecar_sha256,
                    expected_ids=[
                        prediction.example_id for prediction in predictions
                    ],
                )
            except EvidenceSidecarError as error:
                raise SubmissionError(str(error)) from error
    return manifest, predictions
