from findver_agent.schemas import PublicTask
from findver_agent.state import QuestionState, StateStore
from findver_agent.trace_writer import TraceWriter


def test_question_state_round_trip_and_safe_filename(tmp_path):
    task = PublicTask(example_id="../../private/gold", statement="Claim", report="report.json")
    store = StateStore(tmp_path / "state")
    state = QuestionState.create(task, max_steps=8)
    state.errors.append("recoverable")
    store.save(state)

    path = store.path_for(task.example_id)
    assert path.parent == tmp_path / "state"
    assert "private" not in path.name
    restored = store.load_or_create(task, max_steps=8)
    assert restored == state


def test_trace_is_append_only_and_contains_raw_payload(tmp_path):
    writer = TraceWriter(tmp_path / "traces", "example-1")
    writer.write("tool_result", {"paragraphs": [{"paragraph_id": 1, "text": "Exact evidence"}]})
    writer.write("tool_result", {"result": 11.9})

    lines = writer.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "Exact evidence" in lines[0]
    assert '"sequence":1' in lines[1]

