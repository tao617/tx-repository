import hashlib
import json

import pytest

from findver_agent.config import AgentConfig
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PublicTask
from findver_agent.state import StateStore


class AbortRun(BaseException):
    pass


class CapturingBackend:
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
            input_tokens=17,
            output_tokens=5,
            latency_ms=2,
        )

    async def aclose(self):
        return None


def action(name, arguments):
    return json.dumps({"action": name, "arguments": arguments})


def setup_case(tmp_path, *, ids=(0, 1), top_k=3):
    reports_path = tmp_path / "reports"
    reports_path.mkdir()
    (reports_path / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {"context": "Seed evidence zero."},
                    {"context": "Seed evidence one."},
                    {"context": "Dynamic evidence outside the seed."},
                    {"context": "Other text."},
                ]
            }
        ),
        encoding="utf-8",
    )
    retrieval = tmp_path / "retrieval.json"
    retrieval.write_text(
        json.dumps(
            {
                "metadata": {"retriever": "bm25", "top_k": top_k},
                "items": {
                    "seed-example": {
                        "report": "report.json",
                        "retrieved_context": list(ids),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="seed-example",
        statement="The seed and dynamic evidence support the claim.",
        report="report.json",
    )
    return task, ReportStore(reports_path), retrieval


def seeded_config(retrieval, **overrides):
    values = {
        "max_steps": 4,
        "initial_retrieval": {
            "enabled": True,
            "retrieval_file": retrieval,
            "retriever": "bm25",
            "top_k": 3,
            "preload_as_evidence": True,
        },
    }
    values.update(overrides)
    return AgentConfig(**values)


@pytest.mark.asyncio
async def test_seed_is_pinned_prompt_evidence_without_consuming_action_budget(tmp_path):
    task, reports, retrieval = setup_case(tmp_path)
    backend = CapturingBackend(
        [
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [0, 1],
                    "explanation": "The seeded evidence supports the statement.",
                },
            )
        ]
    )
    run_dir = tmp_path / "run"
    engine = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=seeded_config(retrieval),
        report_store=reports,
        run_dir=run_dir,
    )

    await engine.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(task, 4)

    assert state.step == 1
    assert state.usage.model_calls == 1
    assert state.usage.input_tokens == 17
    assert state.tool_counts.model_dump() == {
        "search_report": 0,
        "read_paragraphs": 0,
        "calculator": 0,
    }
    assert [record.paragraph_id for record in state.evidence_ledger] == [0, 1]
    assert all(record.pinned for record in state.evidence_ledger)
    assert all(record.source == "fixed_rag:bm25:top3" for record in state.evidence_ledger)
    assert all(
        record.reason_selected == "seeded by frozen upstream retrieval"
        for record in state.evidence_ledger
    )
    assert "Seed evidence zero." in backend.messages[0][1]["content"]
    assert state.initial_retrieval_state.retrieval_file_sha256 == hashlib.sha256(
        retrieval.read_bytes()
    ).hexdigest()
    trace_lines = (next((run_dir / "traces").glob("*.jsonl"))).read_text(
        encoding="utf-8"
    ).splitlines()
    seed_events = [json.loads(line) for line in trace_lines if "retrieval_seed_loaded" in line]
    assert len(seed_events) == 1
    assert seed_events[0]["payload"]["paragraph_ids"] == [0, 1]


@pytest.mark.asyncio
async def test_agent_can_search_and_read_outside_seed(tmp_path):
    task, reports, retrieval = setup_case(tmp_path, ids=(0,))
    backend = CapturingBackend(
        [
            action("search_report", {"query": "dynamic outside", "top_k": 3}),
            action("read_paragraphs", {"paragraph_ids": [2]}),
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [0, 2],
                    "explanation": "Seed and dynamically read evidence support it.",
                },
            ),
        ]
    )
    run_dir = tmp_path / "run"
    engine = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=seeded_config(retrieval),
        report_store=reports,
        run_dir=run_dir,
    )

    await engine.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(task, 4)

    assert [record.paragraph_id for record in state.evidence_ledger] == [0, 2]
    assert state.tool_counts.search_report == 1
    assert state.tool_counts.read_paragraphs == 1
    assert state.evidence_ledger[1].source == "report"


@pytest.mark.asyncio
async def test_seed_resume_is_idempotent_and_hash_bound(tmp_path):
    task, reports, retrieval = setup_case(tmp_path, ids=(0,))
    run_dir = tmp_path / "run"
    interrupted = AgentOrchestrator(
        backend=CapturingBackend([AbortRun()]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=seeded_config(retrieval),
        report_store=reports,
        run_dir=run_dir,
    )
    with pytest.raises(AbortRun):
        await interrupted.run_question(task)

    resumed = AgentOrchestrator(
        backend=CapturingBackend(
            [
                action(
                    "submit_answer",
                    {
                        "label": "entailed",
                        "evidence_ids": [0],
                        "explanation": "The seed supports it.",
                    },
                )
            ]
        ),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=seeded_config(retrieval),
        report_store=reports,
        run_dir=run_dir,
    )
    await resumed.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(task, 4)
    assert [record.paragraph_id for record in state.evidence_ledger] == [0]

    value = json.loads(retrieval.read_text(encoding="utf-8"))
    value["metadata"]["provenance_note"] = "same records, different file hash"
    retrieval.write_text(json.dumps(value), encoding="utf-8")
    changed = AgentOrchestrator(
        backend=CapturingBackend([]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=seeded_config(retrieval),
        report_store=reports,
        run_dir=run_dir,
    )
    with pytest.raises(ValueError, match="initial retrieval resume mismatch"):
        await changed.run_question(task)


@pytest.mark.asyncio
async def test_seed_counts_toward_unique_paragraph_limit(tmp_path):
    task, reports, retrieval = setup_case(tmp_path, ids=(0, 1))
    engine = AgentOrchestrator(
        backend=CapturingBackend([]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=seeded_config(retrieval, max_total_unique_paragraphs=1),
        report_store=reports,
        run_dir=tmp_path / "run",
    )

    with pytest.raises(ValueError, match="exceeds maximum unique paragraph"):
        await engine.run_question(task)
