"""Deterministic, ID-only evidence-ledger sidecars for private analysis."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from findver_agent.state import safe_example_filename


SIDECAR_NAME = "evidence-ledger.jsonl"
SIDECAR_SCHEMA_VERSION = 1
MAX_SIDECAR_BYTES = 64 * 1024 * 1024


class EvidenceSidecarError(ValueError):
    """A ledger sidecar is missing, malformed, or inconsistent with a run."""


class EvidenceLedgerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    example_id: str = Field(min_length=1, max_length=256)
    initial_rag_evidence_ids: list[int] = Field(default_factory=list)
    final_agent_evidence_ids: list[int] = Field(default_factory=list)

    @field_validator("initial_rag_evidence_ids", "final_agent_evidence_ids")
    @classmethod
    def ids_are_unique_nonnegative(cls, value: list[int]) -> list[int]:
        if any(type(item) is not int or item < 0 for item in value):
            raise ValueError("paragraph IDs must be non-negative integers")
        if len(value) != len(set(value)):
            raise ValueError("paragraph IDs must be unique")
        return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_from_state(path: Path, example_id: str) -> EvidenceLedgerRecord:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceSidecarError(
            f"cannot read question state for {example_id}"
        ) from error
    if not isinstance(state, dict) or state.get("example_id") != example_id:
        raise EvidenceSidecarError("question state does not match expected example ID")

    initial = state.get("initial_retrieval_state")
    initial_ids: list[int] = []
    seed_preloaded = False
    if initial is not None:
        if not isinstance(initial, dict) or not isinstance(
            initial.get("paragraph_ids"), list
        ):
            raise EvidenceSidecarError("initial retrieval state is malformed")
        initial_ids = list(initial["paragraph_ids"])
        seed_preloaded = initial.get("preload_as_evidence") is True

    ledger = state.get("evidence_ledger")
    if not isinstance(ledger, list):
        raise EvidenceSidecarError("question state evidence ledger is malformed")
    ledger_ids: list[int] = []
    for item in ledger:
        if not isinstance(item, dict) or type(item.get("paragraph_id")) is not int:
            raise EvidenceSidecarError(
                "question state contains a malformed evidence record"
            )
        ledger_ids.append(item["paragraph_id"])

    try:
        record = EvidenceLedgerRecord(
            example_id=example_id,
            initial_rag_evidence_ids=initial_ids,
            final_agent_evidence_ids=ledger_ids,
        )
    except ValueError as error:
        raise EvidenceSidecarError(
            "question state contains invalid paragraph IDs"
        ) from error
    if seed_preloaded and not set(record.initial_rag_evidence_ids).issubset(
        record.final_agent_evidence_ids
    ):
        raise EvidenceSidecarError(
            "preloaded seed IDs are missing from the final evidence ledger"
        )
    return record


def build_evidence_ledger_sidecar(run_dir: Path, expected_ids: list[str]) -> bytes:
    state_root = run_dir / "state"
    if not state_root.is_dir():
        raise EvidenceSidecarError("Agent run is missing its state directory")
    expected_paths = {
        state_root / safe_example_filename(example_id, ".json")
        for example_id in expected_ids
    }
    actual_paths = set(state_root.glob("*.json"))
    if actual_paths != expected_paths:
        raise EvidenceSidecarError(
            "Agent state files do not exactly match the run population"
        )

    lines = [
        _record_from_state(
            state_root / safe_example_filename(example_id, ".json"), example_id
        ).model_dump_json()
        for example_id in expected_ids
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_immutable_sidecar(path: Path, data: bytes) -> str:
    if len(data) > MAX_SIDECAR_BYTES:
        raise EvidenceSidecarError("evidence ledger sidecar is too large")
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise EvidenceSidecarError(
                "existing evidence ledger sidecar does not match run state"
            )
        os.chmod(path, 0o444)
        return sha256_bytes(data)

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
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
    return sha256_bytes(data)


def load_evidence_ledger_sidecar(
    path: Path,
    *,
    expected_sha256: str,
    expected_ids: list[str],
) -> list[EvidenceLedgerRecord]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise EvidenceSidecarError(
            "evidence ledger sidecar is missing or unreadable"
        ) from error
    if len(data) > MAX_SIDECAR_BYTES:
        raise EvidenceSidecarError("evidence ledger sidecar is too large")
    if sha256_bytes(data) != expected_sha256:
        raise EvidenceSidecarError("evidence ledger sidecar hash mismatch")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceSidecarError("evidence ledger sidecar must be UTF-8") from error
    lines = text.splitlines()
    if any(not line.strip() for line in lines):
        raise EvidenceSidecarError(
            "evidence ledger sidecar contains a blank record"
        )

    records: list[EvidenceLedgerRecord] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvidenceSidecarError(
                f"evidence ledger sidecar line {line_number} is invalid JSON"
            ) from error
        try:
            record = EvidenceLedgerRecord.model_validate(raw)
        except ValueError as error:
            raise EvidenceSidecarError(
                f"evidence ledger sidecar line {line_number} is invalid"
            ) from error
        if record.example_id in seen:
            raise EvidenceSidecarError(
                f"duplicate evidence ledger sidecar ID: {record.example_id}"
            )
        seen.add(record.example_id)
        records.append(record)

    actual_ids = [record.example_id for record in records]
    if actual_ids != expected_ids:
        raise EvidenceSidecarError(
            "evidence ledger sidecar population or order does not match predictions"
        )
    return records
