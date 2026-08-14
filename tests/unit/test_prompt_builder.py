from findver_agent.model_backends.base import GenerationConfig
from findver_agent.prompt_builder import PromptBuilder
from findver_agent.schemas import PublicTask
from findver_agent.state import EvidenceRecord, QuestionState


def test_prompt_is_rebuilt_from_state_without_example_id_or_subset():
    task = PublicTask(example_id="secret-mapping-key", statement="Revenue increased.", report="report.json")
    state = QuestionState.create(task, max_steps=2)
    state.evidence_ledger.append(
        EvidenceRecord(
            paragraph_id=3,
            exact_text="Revenue was 12 in 2024 and 10 in 2023.",
            reason_selected="exact values",
            read_order=0,
        )
    )
    state.step = 1
    state.remaining_steps = 1

    messages = PromptBuilder(GenerationConfig(max_context_tokens=4096)).build(state)
    rendered = "\n".join(message["content"] for message in messages)

    assert "secret-mapping-key" not in rendered
    assert "subset" not in rendered.lower()
    assert "[paragraph id = 3]" in rendered
    assert "must call submit_answer" in rendered

