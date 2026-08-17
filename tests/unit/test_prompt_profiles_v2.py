import json

import pytest

from findver_agent.baseline import BaselineRunner
from findver_agent.config import AgentConfig, BaselineConfig
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.prompt_builder import PromptBuilder, select_evidence
from findver_agent.report_store import ReportStore
from findver_agent.schemas import Confidence, EvidenceStatus, Prediction, PublicTask, RiskFlag
from findver_agent.state import EvidenceRecord, InitialRetrievalState, QuestionState


class CapturingBackend:
    model_name = "mock"

    def __init__(self):
        self.messages = None

    async def generate(self, messages, config):
        self.messages = messages
        return ModelResponse(
            content=json.dumps(
                {
                    "action": "submit_answer",
                    "arguments": {
                        "label": "entailed",
                        "evidence_ids": [0],
                        "explanation": "The reported value supports it.",
                    },
                }
            )
        )

    async def aclose(self):
        return None


def report_case(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    (root / "report.json").write_text(
        json.dumps({"context": [{"context": "Revenue increased to 12."}]}),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="prompt-profile",
        statement="Revenue increased.",
        report="report.json",
    )
    return task, ReportStore(root)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("findver_direct_json", "judgment directly"),
        ("findver_cot_json", "step by step internally"),
    ],
)
async def test_findver_baseline_profiles_keep_strict_json_and_private_reasoning(
    tmp_path, profile, expected
):
    task, reports = report_case(tmp_path)
    backend = CapturingBackend()
    runner = BaselineRunner(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        baseline_config=BaselineConfig(prompt_type=profile),
        report_store=reports,
        run_dir=tmp_path / profile,
    )

    await runner.run_question(task)
    rendered = "\n".join(message["content"] for message in backend.messages)

    assert "financial expert" in rendered.lower()
    assert "financial facts and data" in rendered.lower()
    assert expected in rendered
    assert "strict JSON" in rendered
    assert "Do not expose long-form reasoning" in rendered or profile == "findver_direct_json"


def v2_state():
    task = PublicTask(
        example_id="prompt-v2",
        statement="Revenue increased.",
        report="report.json",
    )
    state = QuestionState.create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=6,
        finalization_steps=2,
        review_steps=1,
    )
    state.phase = "exploration"
    state.initial_retrieval_state = InitialRetrievalState(
        retrieval_file_sha256="a" * 64,
        retriever="bm25",
        top_k=3,
        report="report.json",
        paragraph_ids=[0],
        preload_as_evidence=True,
    )
    state.evidence_ledger.append(
        EvidenceRecord(
            paragraph_id=0,
            exact_text="Revenue increased to 12.",
            source="fixed_rag:bm25:top3",
            reason_selected="seeded by frozen upstream retrieval",
            read_order=0,
            pinned=True,
        )
    )
    state.evidence_status = EvidenceStatus.PARTIAL
    state.evidence_confidence = Confidence.MEDIUM
    state.open_questions = ["prior-year revenue"]
    state.risk_flags = [RiskFlag.RETRIEVAL_GAP]
    return state


def test_v2_exploration_prompt_exposes_operational_state_and_control_schema():
    state = v2_state()
    messages = PromptBuilder(
        GenerationConfig(max_context_tokens=4096),
        AgentConfig(protocol_version="v2", review_policy="selective"),
    ).build(state)
    rendered = "\n".join(message["content"] for message in messages)

    assert "Loaded frozen RAG Seed" in rendered
    assert "fixed_rag:bm25:top3" in rendered
    assert "prior-year revenue" in rendered
    assert "evidence status: partial" in rendered
    assert "retrieval_gap" in rendered
    assert "finalization reserved: 2" in rendered
    assert '"control"' in rendered
    assert '"action":"search_report"' in rendered


def test_v2_finalization_and_review_prompts_are_submit_only_and_show_review_state():
    state = v2_state()
    state.phase = "finalization"
    builder = PromptBuilder(
        GenerationConfig(max_context_tokens=4096),
        AgentConfig(protocol_version="v2", review_policy="selective"),
    )

    final_messages = builder.build(state)
    final_system = final_messages[0]["content"]

    assert '"action":"submit_answer"' in final_system
    assert '"action":"search_report"' not in final_system
    assert '"action":"read_paragraphs"' not in final_system
    assert '"action":"calculator"' not in final_system
    assert "values, units, and arithmetic" in final_messages[1]["content"]

    state.phase = "review"
    state.draft_prediction = Prediction(
        example_id="prompt-v2",
        label="entailed",
        status="completed",
        evidence_ids=[0],
        explanation="Revenue increased.",
    )
    state.review_trigger_reasons = ["low_confidence"]
    review_messages = builder.build(state)
    review_user = review_messages[1]["content"]

    assert "Verified draft" in review_user
    assert "low_confidence" in review_user
    assert "unsupported claim" in review_user


def test_recent_dynamic_evidence_survives_saturated_seed_budget():
    task = PublicTask(
        example_id="dynamic-visibility",
        statement="The recovered target value is supported.",
        report="report.json",
    )
    state = QuestionState.create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=6,
        finalization_steps=2,
        review_steps=1,
    )
    for paragraph_id in range(10):
        state.evidence_ledger.append(
            EvidenceRecord(
                paragraph_id=paragraph_id,
                exact_text=f"long frozen seed {paragraph_id} " + "s" * 2800,
                source="fixed_rag:text-embedding-3-large:top10",
                reason_selected="seeded by frozen upstream retrieval",
                read_order=paragraph_id,
                pinned=True,
            )
        )
    for offset in range(4):
        paragraph_id = 100 + offset
        state.evidence_ledger.append(
            EvidenceRecord(
                paragraph_id=paragraph_id,
                exact_text=f"recovered target evidence {offset} " + "d" * 1200,
                source="report",
                reason_selected="selected dynamically",
                read_order=10 + offset,
            )
        )

    selected = select_evidence(state, 24_000)
    selected_ids = [record.paragraph_id for record in selected]
    visibility = PromptBuilder(
        GenerationConfig(max_context_tokens=32_768),
        AgentConfig(protocol_version="v2"),
    ).evidence_visibility(state)

    assert selected_ids[:4] == [103, 102, 101, 100]
    assert set(range(100, 104)).issubset(selected_ids)
    assert len(set(range(10)) & set(selected_ids)) < 10
    assert visibility["ledger_evidence_ids"] == list(range(10)) + list(range(100, 104))
    assert visibility["prompt_visible_dynamic_evidence_ids"] == [103, 102, 101, 100]
