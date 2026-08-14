"""Append-only raw per-question trace writer."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from findver_agent.state import safe_example_filename


class TraceWriter:
    def __init__(self, root: Path, example_id: str) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.example_id = example_id
        self.path = root / safe_example_filename(example_id, ".jsonl")
        self._sequence = 0
        if self.path.exists():
            with self.path.open(encoding="utf-8") as handle:
                self._sequence = sum(1 for line in handle if line.strip())

    def write(self, event: str, payload: dict[str, Any]) -> None:
        record = {
            "sequence": self._sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "example_id": self.example_id,
            "event": event,
            "payload": payload,
        }
        data = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._sequence += 1

