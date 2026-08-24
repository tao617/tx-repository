from pathlib import Path

from findver_agent.generic.cli import load_task_profile
from findver_agent.generic.config import load_generic_config
from findver_agent.generic.engine import GenericAgent
from findver_agent.generic.runner import load_generic_tasks


class UnusedBackend:
    model_context_window_tokens = 100_000
    request_profile = "openai_standard"
    thinking_mode = "unsupported"

    async def generate(self, messages, config):  # pragma: no cover - construction only
        raise AssertionError("example construction must not call the model")

    async def aclose(self):
        return None


def test_tracked_generic_example_constructs_the_runtime(tmp_path):
    root = Path(__file__).parents[2]
    config = load_generic_config(root / "configs" / "generic" / "example-api.yaml")
    profile = load_task_profile(
        root / "configs" / "generic" / "profiles" / "evidence_boolean.yaml"
    )
    tasks = load_generic_tasks(
        root / "tests" / "fixtures" / "generic_smoke_tasks.jsonl"
    )

    engine = GenericAgent(
        backend=UnusedBackend(),
        generation=config.generation,
        agent_config=config.agent,
        profile=profile,
        run_dir=tmp_path,
    )

    assert engine.profile.profile_id == "evidence-boolean-v1"
    assert [task.task_id for task in tasks] == ["generic-evidence-1"]
