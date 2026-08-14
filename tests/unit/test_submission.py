import gzip
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from findver_agent.submission import SubmissionError, seal_submission, verify_submission_archive


def make_completed_run(tmp_path, *, partial=False):
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
                "mode": "agent",
                "model": "mock-model",
                "backend": "mock",
                "agent_enabled": True,
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
    manifest, predictions = verify_submission_archive(first)
    assert manifest.status == "sealed"
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

