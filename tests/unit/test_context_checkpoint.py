import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "context_checkpoint.py"
SPEC = importlib.util.spec_from_file_location("context_checkpoint", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_changed_files_preserves_first_porcelain_status_prefix(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "git",
        lambda *args: " M README.md\n?? new-file.txt\nR  old.txt -> renamed.txt",
    )

    assert MODULE.changed_files() == ["README.md", "new-file.txt", "renamed.txt"]
