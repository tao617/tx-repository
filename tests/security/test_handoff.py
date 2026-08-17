from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_handoff_is_host_only_and_one_way() -> None:
    text = (ROOT / "scripts" / "handoff_submission.sh").read_text(encoding="utf-8")
    assert "docker ps" in text
    assert "findver-agent" in text
    assert "findver-scorer" in text
    assert "flock -n 9" in text
    assert 'exec 9<"$lock_path"' in text
    assert "install -m 0444" in text
    assert "sha256sum" in text
    assert "docker compose" not in text
    assert "feedback" not in text.lower()
    assert "gold" not in text.lower()
