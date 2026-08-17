#!/usr/bin/env python3
"""Deterministic builder-only OpenAI-compatible upstream for Docker smoke tests."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock


ACTION = json.dumps(
    {
        "action": "submit_answer",
        "arguments": {
            "label": "entailed",
            "evidence_ids": [],
            "explanation": "deterministic mock completion",
        },
        "control": {
            "evidence_status": "sufficient",
            "missing_information": [],
            "confidence": "high",
            "risk_flags": [],
        },
    },
    separators=(",", ":"),
)


def _action(
    action: str,
    arguments: dict[str, object],
    *,
    evidence_status: str = "partial",
    confidence: str = "medium",
    risk_flags: tuple[str, ...] = (),
) -> str:
    missing_information = (
        []
        if evidence_status == "sufficient"
        else ["deterministic mock needs another verification step"]
    )
    return json.dumps(
        {
            "action": action,
            "arguments": arguments,
            "control": {
                "evidence_status": evidence_status,
                "missing_information": missing_information,
                "confidence": confidence,
                "risk_flags": list(risk_flags),
            },
        },
        separators=(",", ":"),
    )


STATEFUL_M2_RESPONSES = (
    _action("search_report", {"query": "assets fair value", "top_k": 3}),
    _action("read_paragraphs", {"paragraph_ids": [0]}),
    _action("calculator", {"expression": "1+1"}, risk_flags=("calculation",)),
    _action("search_report", {"query": "long-term debt", "top_k": 3}),
    _action("read_paragraphs", {"paragraph_ids": [1]}),
    _action("calculator", {"expression": "32253+278400"}),
    _action(
        "search_report",
        {"query": "prohibited finalization action", "top_k": 1},
        risk_flags=("weak_support",),
    ),
    _action(
        "submit_answer",
        {
            "label": "entailed",
            "evidence_ids": [0],
            "explanation": "Paragraph 0 supports the deterministic smoke answer.",
        },
        evidence_status="sufficient",
        confidence="high",
    ),
    "not-json-review-response",
)

SCENARIOS = {
    "immediate-submit": (ACTION,),
    "m2-review-fallback": STATEFUL_M2_RESPONSES,
}


class Handler(BaseHTTPRequestHandler):
    expected_model = "builder-mock-upstream"
    responses = (ACTION,)
    repeat_last = True
    request_index = 0
    response_lock = Lock()

    @classmethod
    def next_response(cls) -> tuple[int, str]:
        with cls.response_lock:
            call_number = cls.request_index + 1
            if cls.request_index >= len(cls.responses):
                if not cls.repeat_last:
                    raise IndexError("mock scenario response sequence exhausted")
                content = cls.responses[-1]
            else:
                content = cls.responses[cls.request_index]
            cls.request_index += 1
            return call_number, content

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
        try:
            call_number, content = self.next_response()
        except IndexError:
            self.send_error(409, "mock scenario response sequence exhausted")
            return
        body = json.dumps(
            {
                "id": f"mock-completion-{call_number}",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
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
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), default="immediate-submit")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    Handler.responses = SCENARIOS[args.scenario]
    Handler.repeat_last = args.scenario == "immediate-submit"
    Handler.request_index = 0
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
