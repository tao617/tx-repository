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


def _v3_action(
    action: str,
    arguments: dict[str, object],
    target_obligation_id: str,
    *,
    confidence: str = "high",
    risk_flags: tuple[str, ...] = (),
) -> str:
    return json.dumps(
        {
            "action": action,
            "arguments": arguments,
            "control": {
                "target_obligation_id": target_obligation_id,
                "open_obligations": [],
                "obligation_deltas": [],
                "confidence": confidence,
                "risk_flags": list(risk_flags),
                "expected_skill_effect": "advance the deterministic mock proof",
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

FINOASIS_IE_RESPONSES = (
    _v3_action(
        "search_report",
        {"query": "facility opened Shanghai", "top_k": 2},
        "obl-0001",
    ),
    _v3_action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
    _v3_action(
        "submit_answer",
        {
            "label": "entailed",
            "evidence_ids": [0],
            "explanation": "The exact report paragraph supports the facility claim.",
        },
        "obl-0002",
    ),
)

FINOASIS_NUMERIC_RESPONSES = (
    _v3_action(
        "search_report",
        {"query": "revenue 2024 2023", "top_k": 2},
        "obl-0001",
    ),
    _v3_action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
    _v3_action(
        "read_table_region",
        {
            "table_id": "table:0000",
            "row_indices": [1],
            "column_indices": [1, 2],
        },
        "obl-0002",
    ),
    _v3_action(
        "bind_financial_value",
        {
            "evidence_ref": "table-cell:table:0000:1:1",
            "raw_value": "$ 1,200",
            "metric": "Revenue",
            "entity": "synthetic issuer",
            "period": "2024",
            "numeric_type": "money",
            "currency": "unknown",
            "unit": "unknown",
            "scale": "unknown",
        },
        "obl-0002",
        risk_flags=("calculation",),
    ),
    _v3_action(
        "bind_financial_value",
        {
            "evidence_ref": "table-cell:table:0000:1:2",
            "raw_value": "$ 1,000",
            "metric": "Revenue",
            "entity": "synthetic issuer",
            "period": "2023",
            "numeric_type": "money",
            "currency": "unknown",
            "unit": "unknown",
            "scale": "unknown",
        },
        "obl-0002",
        risk_flags=("calculation",),
    ),
    _v3_action(
        "execute_financial_program",
        {
            "program": {
                "op": "greater_than",
                "args": [
                    {"kind": "value_ref", "ref": "value-0001"},
                    {"kind": "value_ref", "ref": "value-0002"},
                ],
            }
        },
        "obl-0004",
        risk_flags=("calculation",),
    ),
    _v3_action(
        "submit_answer",
        {
            "label": "entailed",
            "evidence_ids": [0],
            "explanation": "The evidence-bound table values verify the increase.",
        },
        "obl-0005",
    ),
)

FINOASIS_KNOWLEDGE_RESPONSES = (
    _v3_action(
        "search_report",
        {"query": "performance obligation satisfied", "top_k": 2},
        "obl-0001",
    ),
    _v3_action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
    _v3_action(
        "search_financial_rules",
        {
            "query": "performance obligation revenue recognition",
            "jurisdiction": "US",
            "as_of_date": "2024-12-31",
            "top_k": 3,
        },
        "obl-0002",
        risk_flags=("rule_applicability",),
    ),
    _v3_action(
        "read_financial_rules",
        {"rule_ids": ["synthetic-us-revenue-current"]},
        "obl-0002",
        risk_flags=("rule_applicability",),
    ),
    _v3_action(
        "check_rule_applicability",
        {
            "rule_evidence_refs": ["rule-evidence-0001"],
            "document_evidence_refs": ["report-paragraph:0"],
            "jurisdiction": "US",
            "effective_date": "2024-12-31",
            "entity_scope": "public issuer",
            "applicability_predicate_ids": [
                "predicate:performance-obligation"
            ],
        },
        "obl-0003",
        risk_flags=("rule_applicability",),
    ),
    _v3_action(
        "submit_answer",
        {
            "label": "entailed",
            "evidence_ids": [0],
            "explanation": "The report fact and applicable frozen rule support the claim.",
        },
        "obl-0004",
    ),
)

FINOASIS_MIXED_RESPONSES = (
    _v3_action(
        "search_report",
        {"query": "performance obligation revenue 2024 2023", "top_k": 2},
        "obl-0001",
    ),
    _v3_action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
    _v3_action(
        "read_table_region",
        {
            "table_id": "table:0000",
            "row_indices": [1],
            "column_indices": [1, 2],
        },
        "obl-0002",
    ),
    _v3_action(
        "bind_financial_value",
        {
            "evidence_ref": "table-cell:table:0000:1:1",
            "raw_value": "$ 1,200",
            "metric": "Revenue",
            "entity": "synthetic issuer",
            "period": "2024",
            "numeric_type": "money",
            "currency": "unknown",
            "unit": "unknown",
            "scale": "unknown",
        },
        "obl-0002",
        risk_flags=("calculation",),
    ),
    _v3_action(
        "bind_financial_value",
        {
            "evidence_ref": "table-cell:table:0000:1:2",
            "raw_value": "$ 1,000",
            "metric": "Revenue",
            "entity": "synthetic issuer",
            "period": "2023",
            "numeric_type": "money",
            "currency": "unknown",
            "unit": "unknown",
            "scale": "unknown",
        },
        "obl-0002",
        risk_flags=("calculation",),
    ),
    _v3_action(
        "execute_financial_program",
        {
            "program": {
                "op": "greater_than",
                "args": [
                    {"kind": "value_ref", "ref": "value-0001"},
                    {"kind": "value_ref", "ref": "value-0002"},
                ],
            }
        },
        "obl-0004",
        risk_flags=("calculation",),
    ),
    _v3_action(
        "search_financial_rules",
        {
            "query": "performance obligation revenue recognition",
            "jurisdiction": "US",
            "as_of_date": "2024-12-31",
            "top_k": 3,
        },
        "obl-0005",
        risk_flags=("rule_applicability",),
    ),
    _v3_action(
        "read_financial_rules",
        {"rule_ids": ["synthetic-us-revenue-current"]},
        "obl-0005",
        risk_flags=("rule_applicability",),
    ),
    _v3_action(
        "check_rule_applicability",
        {
            "rule_evidence_refs": ["rule-evidence-0001"],
            "document_evidence_refs": ["report-paragraph:0"],
            "jurisdiction": "US",
            "effective_date": "2024-12-31",
            "entity_scope": "public issuer",
            "applicability_predicate_ids": [
                "predicate:performance-obligation"
            ],
        },
        "obl-0006",
        risk_flags=("rule_applicability",),
    ),
    _v3_action(
        "submit_answer",
        {
            "label": "entailed",
            "evidence_ids": [0],
            "explanation": "The replayed numeric and rule certificates jointly support the claim.",
        },
        "obl-0007",
    ),
)

FINOASIS_V3_RESPONSES = (
    *FINOASIS_IE_RESPONSES,
    *FINOASIS_NUMERIC_RESPONSES,
    *FINOASIS_KNOWLEDGE_RESPONSES,
    *FINOASIS_MIXED_RESPONSES,
)

SCENARIOS = {
    "immediate-submit": (ACTION,),
    "m2-review-fallback": STATEFUL_M2_RESPONSES,
    "finoasis-v3": FINOASIS_V3_RESPONSES,
}


class Handler(BaseHTTPRequestHandler):
    expected_model = "builder-mock-upstream"
    responses = (ACTION,)
    repeat_last = True
    require_disabled_thinking = True
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
        if self.require_disabled_thinking:
            if payload.get("thinking") != {"type": "disabled"}:
                self.send_error(400, "DeepSeek thinking was not explicitly disabled")
                return
        elif "thinking" in payload:
            self.send_error(400, "mock profile unexpectedly sent a thinking field")
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
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
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
    Handler.require_disabled_thinking = args.scenario != "finoasis-v3"
    Handler.request_index = 0
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
