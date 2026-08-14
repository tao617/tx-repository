#!/usr/bin/env python3
"""Deterministic builder-only OpenAI-compatible upstream for Docker smoke tests."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ACTION = json.dumps(
    {
        "action": "submit_answer",
        "arguments": {
            "label": "entailed",
            "evidence_ids": [],
            "explanation": "deterministic mock completion",
        },
    },
    separators=(",", ":"),
)


class Handler(BaseHTTPRequestHandler):
    expected_model = "builder-mock-upstream"

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        if payload.get("model") != self.expected_model:
            self.send_error(400, "gateway did not rewrite the model alias")
            return
        body = json.dumps(
            {
                "id": "mock-completion",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": ACTION}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
            separators=(",", ":"),
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
