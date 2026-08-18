import json

import pytest
from pydantic import ValidationError

from findver_agent.cli import parser
from findver_agent.config import AppConfig, IterativeRAGConfig
from findver_agent.iterative_rag import IterativeRAGRunner
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PublicTask


class SequenceBackend:
    model_name = "mock-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    async def generate(self, messages, config):
        self.messages.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return ModelResponse(
            content=response,
            input_tokens=11,
            output_tokens=3,
            latency_ms=2.5,
        )

    async def aclose(self):
        return None


def action(name, arguments):
    return json.dumps({"action": name, "arguments": arguments})


def setup_case(tmp_path, *, seed_id=0):
    reports_path = tmp_path / "reports"
    reports_path.mkdir()
    (reports_path / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {"context": "Frozen seed evidence."},
                    {"context": "Unrelated narrative."},
                    {"context": "Dynamic recovery target amount was 42."},
                    {"context": "Another unrelated paragraph."},
                ]
            }
        ),
        encoding="utf-8",
    )
    retrieval = tmp_path / "retrieval.json"
    retrieval.write_text(
        json.dumps(
            {
                "metadata": {"retriever": "bm25", "top_k": 3},
                "items": {
                    "iterative-example": {
                        "report": "report.json",
                        "retrieved_context": [seed_id],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="iterative-example",
        statement="The dynamic recovery target amount was 42.",
        report="report.json",
    )
    config = IterativeRAGConfig(
        retrieval_file=retrieval,
        retriever="bm25",
        top_k=3,
        retrieval_rounds=3,
        results_per_round=3,
        auto_read_per_round=1,
        max_total_unique_paragraphs=4,
        finalization_steps=2,
    )
    return task, ReportStore(reports_path), config


@pytest.mark.asyncio
async def test_fixed_loop_never_stops_early_and_finalization_is_submit_only(tmp_path):
    task, reports, config = setup_case(tmp_path)
    backend = SequenceBackend(
        [
            action("search_report", {"query": "dynamic recovery target amount", "top_k": 9}),
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [0],
                    "explanation": "Premature answer must not stop fixed retrieval.",
                },
            ),
            "not-json",
            action("search_report", {"query": "must be rejected", "top_k": 3}),
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [0, 2],
                    "explanation": "The frozen and dynamically retrieved evidence support it.",
                },
            ),
        ]
    )
    run_dir = tmp_path / "run"
    runner = IterativeRAGRunner(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        iterative_config=config,
        report_store=reports,
        run_dir=run_dir,
    )

    prediction = await runner.run_question(task)

    assert prediction.status == "completed"
    assert prediction.evidence_ids == [0, 2]
    assert len(backend.messages) == config.retrieval_rounds + config.finalization_steps
    assert all("control" not in messages[0]["content"] for messages in backend.messages)
    trace = [
        json.loads(line)
        for line in next((run_dir / "traces").glob("*.jsonl")).read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    requests = [event for event in trace if event["event"] == "model_request"]
    responses = [event for event in trace if event["event"] == "model_response"]
    assert [event["payload"]["phase"] for event in requests] == [
        "iterative_retrieval",
        "iterative_retrieval",
        "iterative_retrieval",
        "finalization",
        "finalization",
    ]
    assert sum(event["payload"]["input_tokens"] for event in responses) == 55
    assert sum(event["payload"]["latency_ms"] for event in responses) == 12.5
    assert any(
        event["event"] == "dynamic_evidence_loaded"
        and event["payload"]["paragraph_ids"] == [2]
        for event in trace
    )
    assert not any(event["event"] == "review_triggered" for event in trace)
    errors = [event["payload"] for event in trace if event["event"] == "recoverable_error"]
    assert [error["error_type"] for error in errors] == ["protocol", "parse", "protocol"]


@pytest.mark.asyncio
async def test_finalization_retry_receives_allowed_ids_and_prior_rejection(tmp_path):
    task, reports, config = setup_case(tmp_path, seed_id=1)
    backend = SequenceBackend(
        [
            action(
                "search_report",
                {"query": "dynamic recovery target amount", "top_k": 3},
            ),
            "not-json",
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [1],
                    "explanation": "Retrieval rounds may not submit.",
                },
            ),
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [0],
                    "explanation": "The placeholder ID is not retrieved evidence.",
                },
            ),
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [1, 2],
                    "explanation": "The retrieved evidence supports the statement.",
                },
            ),
        ]
    )
    run_dir = tmp_path / "retry"
    runner = IterativeRAGRunner(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        iterative_config=config,
        report_store=reports,
        run_dir=run_dir,
    )

    prediction = await runner.run_question(task)

    assert prediction.status == "completed"
    assert prediction.evidence_ids == [1, 2]
    first_finalization = "\n".join(
        message["content"] for message in backend.messages[-2]
    )
    second_finalization = "\n".join(
        message["content"] for message in backend.messages[-1]
    )
    assert (
        "Allowed evidence IDs (cite only directly relevant IDs from this exact list):\n"
        "[1,2]" in first_finalization
    )
    assert '"evidence_ids":[0]' not in first_finalization
    assert "Previous finalization rejection:\nnone" in first_finalization
    assert "submit evidence_ids must be in retrieved evidence: 0" in second_finalization
    trace = [
        json.loads(line)
        for line in next((run_dir / "traces").glob("*.jsonl")).read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    errors = [
        event["payload"] for event in trace if event["event"] == "recoverable_error"
    ]
    assert [error["error_type"] for error in errors] == ["parse", "protocol", "skill"]


def test_iterative_rag_config_and_cli_are_strict(tmp_path):
    raw = {
        "run": {"mode": "iterative_rag", "backend_kind": "mock"},
        "backend": {
            "type": "openai_compatible",
            "base_url": "http://model-gateway:8080/v1",
            "model": "model-a",
        },
        "generation": {
            "temperature": 0,
            "top_p": 1,
            "max_output_tokens": 64,
            "max_context_tokens": 4096,
        },
        "iterative_rag": {
            "retrieval_file": str(tmp_path / "retrieval.json"),
            "retriever": "bm25",
            "top_k": 3,
            "retrieval_rounds": 3,
            "results_per_round": 5,
            "auto_read_per_round": 5,
            "max_total_unique_paragraphs": 3,
            "finalization_steps": 2,
        },
    }
    assert AppConfig.model_validate(raw).run.mode == "iterative_rag"
    parsed = parser().parse_args(
        [
            "iterative-rag",
            "--config",
            "config.yaml",
            "--tasks",
            "tasks.jsonl",
            "--reports",
            "reports",
            "--run-dir",
            "run",
        ]
    )
    assert parsed.command == "iterative-rag"

    raw["agent"] = {"max_steps": 1}
    with pytest.raises(ValidationError, match="agent configuration is not valid"):
        AppConfig.model_validate(raw)

    with pytest.raises(ValidationError, match="cannot exceed"):
        IterativeRAGConfig(
            retrieval_file=tmp_path / "retrieval.json",
            retriever="bm25",
            top_k=3,
            results_per_round=3,
            auto_read_per_round=4,
        )
