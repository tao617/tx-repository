import json

import pytest

from findver_agent.generic.config import GenericAgentConfig
from findver_agent.generic.engine import GenericAgent
from findver_agent.generic.models import (
    AnswerContract,
    ContextUnit,
    GenericTask,
    GenericTaskProfile,
)
from findver_agent.generic.skills import (
    GenericActionParseError,
    default_skill_catalog,
)
from findver_agent.model_backends.base import GenerationConfig, ModelResponse


class ScriptedBackend:
    model_context_window_tokens = 100_000
    request_profile = "openai_standard"
    thinking_mode = "unsupported"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, messages, config):
        self.calls.append((messages, config))
        return ModelResponse(content=json.dumps(self.responses.pop(0)))

    async def aclose(self):
        return None


def control(status, confidence, risk_flags=None):
    return {
        "evidence_status": status,
        "missing_information": [],
        "confidence": confidence,
        "risk_flags": risk_flags or [],
    }


def action(name, arguments, status="partial", confidence="medium", risk_flags=None):
    return {
        "action": name,
        "arguments": arguments,
        "control": control(status, confidence, risk_flags),
    }


def submit(answer, evidence_ids=None, *, risk_flags=None):
    return action(
        "submit_answer",
        {
            "answer": answer,
            "evidence_ids": evidence_ids or [],
            "explanation": "concise support",
        },
        status="sufficient",
        confidence="high",
        risk_flags=risk_flags,
    )


def test_catalog_exposes_only_profile_selected_skills_and_supports_unicode_search():
    task = GenericTask(
        task_id="search",
        instruction="Locate the Chinese revenue statement.",
        context=[
            ContextUnit(unit_id="a", text="公司收入同比增长百分之十。"),
            ContextUnit(unit_id="b", text="The office moved to another building."),
        ],
    )
    catalog = default_skill_catalog()
    skills = catalog.build(task, ["search_context"])
    result = skills["search_context"].execute(query="收入增长", top_k=2)
    assert result["hits"][0]["unit_id"] == "a"

    forbidden = json.dumps(action("calculator", {"expression": "1+1"}))
    with pytest.raises(GenericActionParseError, match="not in the task skill allowlist"):
        catalog.parse_action(forbidden, skills)


@pytest.mark.asyncio
async def test_generic_agent_lets_model_choose_skill_then_runs_selective_review(tmp_path):
    profile = GenericTaskProfile(
        profile_id="boolean-with-tools",
        allowed_skills=["calculator", "compare_values"],
        answer=AnswerContract(kind="enum", choices=["yes", "no"]),
        evidence_policy="none",
    )
    backend = ScriptedBackend(
        [
            action(
                "calculator",
                {"expression": "40+2"},
                risk_flags=["calculation"],
            ),
            submit("yes"),
            submit("yes"),
        ]
    )
    engine = GenericAgent(
        backend=backend,
        generation=GenerationConfig(),
        agent_config=GenericAgentConfig(
            exploration_steps=2,
            finalization_steps=2,
            review_steps=1,
            review_policy="selective",
        ),
        profile=profile,
        run_dir=tmp_path,
    )
    prediction = await engine.run_task(
        GenericTask(
            task_id="answer-42",
            instruction="Is 40 plus 2 equal to 42? Answer yes or no.",
        )
    )

    assert prediction.answer == "yes"
    assert prediction.status == "completed"
    assert len(backend.calls) == 3
    state = json.loads(next((tmp_path / "state").glob("*.json")).read_text())
    assert state["skill_counts"]["calculator"] == 1
    assert state["review_triggered"] is True
    assert state["review_completed"] is True
    assert state["termination_reason"] == "review_completed"


@pytest.mark.asyncio
async def test_required_read_evidence_is_enforced_without_changing_phase_framework(tmp_path):
    profile = GenericTaskProfile(
        profile_id="evidence-boolean",
        allowed_skills=["search_context", "read_context"],
        answer=AnswerContract(kind="boolean", explanation_required=True),
        evidence_policy="required_read",
    )
    backend = ScriptedBackend(
        [
            action("read_context", {"unit_ids": ["u1"]}),
            submit(False, ["u1"]),
        ]
    )
    engine = GenericAgent(
        backend=backend,
        generation=GenerationConfig(),
        agent_config=GenericAgentConfig(
            exploration_steps=2,
            finalization_steps=1,
            review_steps=0,
            review_policy="none",
        ),
        profile=profile,
        run_dir=tmp_path,
    )
    prediction = await engine.run_task(
        GenericTask(
            task_id="evidence-task",
            instruction="Is the claim supported?",
            context=[ContextUnit(unit_id="u1", text="The claim is not supported.")],
        )
    )

    assert prediction.answer is False
    assert prediction.evidence_ids == ["u1"]
    state = json.loads(next((tmp_path / "state").glob("*.json")).read_text())
    assert [item["unit_id"] for item in state["evidence_ledger"]] == ["u1"]
    assert state["exploration_step"] == 2
    assert state["finalization_step"] == 0


def test_unknown_profile_skill_fails_closed_before_model_use(tmp_path):
    profile = GenericTaskProfile(
        profile_id="bad-profile",
        allowed_skills=["unregistered_skill"],
    )
    with pytest.raises(ValueError, match="unknown skills"):
        GenericAgent(
            backend=ScriptedBackend([]),
            generation=GenerationConfig(),
            agent_config=GenericAgentConfig(),
            profile=profile,
            run_dir=tmp_path,
        )


def test_tracked_generic_examples_parse():
    from pathlib import Path

    from findver_agent.generic.cli import load_task_profile
    from findver_agent.generic.config import load_generic_config
    from findver_agent.generic.runner import load_generic_tasks

    root = Path(__file__).parents[2]
    config = load_generic_config(root / "configs" / "generic" / "example-api.yaml")
    profile = load_task_profile(
        root / "configs" / "generic" / "profiles" / "evidence_boolean.yaml"
    )
    tasks = load_generic_tasks(root / "tests" / "fixtures" / "generic_smoke_tasks.jsonl")

    assert config.agent.review_policy == "selective"
    assert profile.evidence_policy == "required_read"
    assert [task.task_id for task in tasks] == ["generic-evidence-1"]


@pytest.mark.asyncio
async def test_generic_batch_restores_task_order(tmp_path):
    import asyncio

    from findver_agent.generic.models import GenericPrediction, GenericPredictionStatus
    from findver_agent.generic.runner import run_generic_batch

    tasks_path = tmp_path / "tasks.jsonl"
    tasks_path.write_text(
        "".join(
            json.dumps({"task_id": task_id, "instruction": "Return it."}) + "\n"
            for task_id in ["one", "two", "three"]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text("config: 1\n", encoding="utf-8")
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("profile: 1\n", encoding="utf-8")
    profile = GenericTaskProfile(profile_id="batch")

    async def answer(task):
        await asyncio.sleep({"one": 0.003, "two": 0.002, "three": 0.001}[task.task_id])
        return GenericPrediction(
            task_id=task.task_id,
            status=GenericPredictionStatus.COMPLETED,
            answer=task.task_id,
        )

    final = await run_generic_batch(
        tasks_path=tasks_path,
        config_path=config_path,
        profile_path=profile_path,
        profile=profile,
        run_dir=tmp_path / "run",
        model="mock",
        backend_kind="mock",
        concurrency=3,
        answer=answer,
    )
    assert [
        json.loads(line)["task_id"]
        for line in final.read_text(encoding="utf-8").splitlines()
    ] == ["one", "two", "three"]
