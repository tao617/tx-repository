import gzip
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from findver_agent.evidence_sidecar import (
    SIDECAR_NAME,
    EvidenceSidecarError,
    load_evidence_ledger_sidecar,
    sha256_bytes,
)
from findver_agent.run_identity import RunIdentity
from findver_agent.state import safe_example_filename
from findver_agent.submission import SubmissionError, seal_submission, verify_submission_archive


def make_completed_run(tmp_path, *, partial=False, agent_enabled=True):
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    predictions = [
        {
            "example_id": "one",
            "label": "entailed",
            "status": "completed",
            "evidence_ids": [1],
            "explanation": "Supported.",
        },
        {
            "example_id": "two",
            "label": None,
            "status": "invalid",
            "evidence_ids": [],
            "explanation": "No submission.",
        },
    ]
    name = "predictions.partial.jsonl" if partial else "predictions.jsonl"
    (run_dir / name).write_text(
        "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in predictions),
        encoding="utf-8",
    )
    now = datetime.now(timezone.utc).isoformat()
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "agent" if agent_enabled else "baseline",
                "model": "mock-model",
                "backend": "mock",
                "agent_enabled": agent_enabled,
                "config_sha256": "a" * 64,
                "public_tasks_sha256": "b" * 64,
                "expected_examples": 2,
                "task_ids": ["one", "two"],
                "completed_examples": 2,
                "started_at": now,
                "completed_at": now,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "traces").mkdir()
    (run_dir / "traces" / "private-trace.jsonl").write_text("secret trace", encoding="utf-8")
    if agent_enabled:
        state_root = run_dir / "state"
        state_root.mkdir()
        states = {
            "one": {
                "example_id": "one",
                "statement": "private statement must not cross",
                "initial_retrieval_state": {
                    "paragraph_ids": [1],
                    "preload_as_evidence": True,
                },
                "evidence_ledger": [
                    {"paragraph_id": 1, "exact_text": "private report text"},
                    {"paragraph_id": 3, "exact_text": "more private report text"},
                ],
            },
            "two": {
                "example_id": "two",
                "statement": "another private statement",
                "initial_retrieval_state": None,
                "evidence_ledger": [
                    {"paragraph_id": 2, "exact_text": "unsealed evidence text"},
                ],
            },
        }
        for example_id, state in states.items():
            (state_root / safe_example_filename(example_id, ".json")).write_text(
                json.dumps(state),
                encoding="utf-8",
            )
    return run_dir


def test_seal_is_deterministic_and_contains_only_protocol_files(tmp_path):
    run_dir = make_completed_run(tmp_path)
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    first_hash = seal_submission(run_dir, first, repository_root=Path.cwd())
    second_hash = seal_submission(run_dir, second, repository_root=Path.cwd())

    assert first_hash == second_hash == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first.read_bytes() == second.read_bytes()
    assert first.stat().st_mode & 0o777 == 0o444
    with tarfile.open(first, "r:gz") as archive:
        assert archive.getnames() == ["predictions.jsonl", "manifest.json", "SHA256SUMS"]
        assert all("trace" not in name for name in archive.getnames())
    sidecar = run_dir / SIDECAR_NAME
    manifest, predictions = verify_submission_archive(
        first,
        evidence_ledger_sidecar=sidecar,
    )
    assert manifest.status == "sealed"
    assert manifest.evidence_ledger_sidecar_schema_version == 1
    assert manifest.evidence_ledger_sidecar_sha256 == hashlib.sha256(
        sidecar.read_bytes()
    ).hexdigest()
    assert sidecar.stat().st_mode & 0o777 == 0o444
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert "private" not in sidecar_text
    assert [json.loads(line) for line in sidecar_text.splitlines()] == [
        {"example_id": "one", "initial_rag_evidence_ids": [1], "final_agent_evidence_ids": [1, 3]},
        {"example_id": "two", "initial_rag_evidence_ids": [], "final_agent_evidence_ids": [2]},
    ]
    assert len(predictions) == 2


def test_seal_rejects_partial_run(tmp_path):
    run_dir = make_completed_run(tmp_path, partial=True)
    with pytest.raises(SubmissionError, match="partial"):
        seal_submission(run_dir, tmp_path / "submission.tar.gz", repository_root=Path.cwd())


def _write_archive(path, members):
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for info, data in members:
                    archive.addfile(info, io.BytesIO(data) if data is not None else None)


def _regular(name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def test_archive_rejects_extra_and_traversing_members(tmp_path):
    for bad_name in ("trace.jsonl", "../manifest.json"):
        archive = tmp_path / f"bad-{bad_name.replace('/', '-')}.tar.gz"
        members = [_regular(name, b"x") for name in ("predictions.jsonl", "manifest.json", "SHA256SUMS")]
        members.append(_regular(bad_name, b"secret"))
        _write_archive(archive, members)
        with pytest.raises(SubmissionError):
            verify_submission_archive(archive)


def test_archive_rejects_symbolic_link(tmp_path):
    archive = tmp_path / "link.tar.gz"
    link = tarfile.TarInfo("manifest.json")
    link.type = tarfile.SYMTYPE
    link.linkname = "/private/gold.jsonl"
    members = [
        _regular("predictions.jsonl", b""),
        (link, None),
        _regular("SHA256SUMS", b""),
    ]
    _write_archive(archive, members)
    with pytest.raises(SubmissionError, match="regular file"):
        verify_submission_archive(archive)


def test_archive_rejects_hash_mismatch(tmp_path):
    run_dir = make_completed_run(tmp_path)
    valid = tmp_path / "valid.tar.gz"
    seal_submission(run_dir, valid, repository_root=Path.cwd())
    with tarfile.open(valid, "r:gz") as source:
        data = {name: source.extractfile(name).read() for name in source.getnames()}
    data["predictions.jsonl"] += b"\n"
    tampered = tmp_path / "tampered.tar.gz"
    _write_archive(tampered, [_regular(name, data[name]) for name in ("predictions.jsonl", "manifest.json", "SHA256SUMS")])
    with pytest.raises(SubmissionError, match="hash mismatch"):
        verify_submission_archive(tampered)



def test_evidence_ledger_sidecar_tampering_is_rejected(tmp_path):
    run_dir = make_completed_run(tmp_path)
    archive = tmp_path / "submission.tar.gz"
    seal_submission(run_dir, archive, repository_root=Path.cwd())
    sidecar = run_dir / SIDECAR_NAME
    sidecar.chmod(0o600)
    sidecar.write_bytes(sidecar.read_bytes() + b"\n")

    with pytest.raises(SubmissionError, match="sidecar hash mismatch"):
        verify_submission_archive(archive, evidence_ledger_sidecar=sidecar)


def test_non_agent_submission_has_no_sidecar(tmp_path):
    run_dir = make_completed_run(tmp_path, agent_enabled=False)
    archive = tmp_path / "submission.tar.gz"
    seal_submission(run_dir, archive, repository_root=Path.cwd())

    manifest, _ = verify_submission_archive(
        archive,
        evidence_ledger_sidecar=run_dir / SIDECAR_NAME,
    )

    assert manifest.evidence_ledger_sidecar_sha256 is None
    assert not (run_dir / SIDECAR_NAME).exists()


def test_sealed_manifest_binds_frozen_run_identity(tmp_path):
    run_dir = make_completed_run(tmp_path)
    metadata_path = run_dir / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["backend"] = "api"
    identity = RunIdentity(
        plan_sha256="c" * 64,
        matrix_id="run",
        condition_id="condition",
        plan_run_id="run-001",
        effective_model_id="provider/model-a",
        model_alias="mock-model",
        backend_kind="api",
        git_commit_at_start="d" * 40,
        config_sha256="a" * 64,
        public_tasks_sha256="b" * 64,
        planned_retrieval_sha256="e" * 64,
        model_context_window_tokens=100_000,
    )
    metadata["run_identity"] = identity.model_dump(mode="json")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    archive = tmp_path / "submission.tar.gz"

    seal_submission(run_dir, archive, repository_root=Path.cwd())
    manifest, _ = verify_submission_archive(
        archive,
        evidence_ledger_sidecar=run_dir / SIDECAR_NAME,
    )

    assert manifest.run_identity == identity
    assert manifest.git_commit == identity.git_commit_at_start

    invalid = manifest.model_dump(mode="json")
    invalid["model"] = "substituted-model"
    with pytest.raises(ValueError, match="model alias"):
        type(manifest).model_validate(invalid)


@pytest.mark.parametrize(
    ("sidecar_text", "message"),
    [
        (
            '{"example_id":"two","initial_rag_evidence_ids":[],"final_agent_evidence_ids":[]}\n'
            '{"example_id":"one","initial_rag_evidence_ids":[],"final_agent_evidence_ids":[]}\n',
            "population or order",
        ),
        (
            '{"example_id":"one","initial_rag_evidence_ids":[],"final_agent_evidence_ids":[]}\n'
            '{"example_id":"one","initial_rag_evidence_ids":[],"final_agent_evidence_ids":[]}\n',
            "duplicate evidence ledger",
        ),
        (
            '{"example_id":"one","initial_rag_evidence_ids":[],"final_agent_evidence_ids":[],"text":"forbidden"}\n'
            '{"example_id":"two","initial_rag_evidence_ids":[],"final_agent_evidence_ids":[]}\n',
            "line 1 is invalid",
        ),
        (
            '{"example_id":"one","initial_rag_evidence_ids":[],"final_agent_evidence_ids":[]}\n\n'
            '{"example_id":"two","initial_rag_evidence_ids":[],"final_agent_evidence_ids":[]}\n',
            "blank record",
        ),
    ],
)
def test_evidence_sidecar_schema_population_and_order_fail_closed(
    tmp_path,
    sidecar_text,
    message,
):
    sidecar = tmp_path / SIDECAR_NAME
    data = sidecar_text.encode("utf-8")
    sidecar.write_bytes(data)

    with pytest.raises(EvidenceSidecarError, match=message):
        load_evidence_ledger_sidecar(
            sidecar,
            expected_sha256=sha256_bytes(data),
            expected_ids=["one", "two"],
        )
