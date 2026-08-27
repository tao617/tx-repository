import json
from pathlib import Path

import yaml

from findver_agent.config import AppConfig
from findver_agent.findoasis.contracts import ObligationType, SkillName
from findver_agent.findoasis.state import FinOASISQuestionState
from findver_agent.model_backends.base import ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.runner import load_public_tasks, run_batch
from scripts.summarize_run import summarize
from tests.fixtures.mock_openai_server import FINOASIS_V3_RESPONSES


ROOT = Path(__file__).resolve().parents[2]


class SequenceBackend:
    model_name = "external-model-name"
    model_context_window_tokens = 32768

    def __init__(self):
        self.responses = list(FINOASIS_V3_RESPONSES)

    async def generate(self, messages, config):
        del messages, config
        return ModelResponse(
            content=self.responses.pop(0),
            input_tokens=1,
            output_tokens=1,
            latency_ms=0.125,
        )

    async def aclose(self):
        return None


def _config() -> AppConfig:
    path = (
        ROOT
        / "configs"
        / "experimental"
        / "findoasis"
        / "M3_ALL_SKILLS_SYNTHETIC.yaml"
    )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["agent"]["findoasis"]["rule_corpus"]["rule_root"] = str(
        (ROOT / "tests" / "fixtures" / "finoasis_rule_corpus").resolve()
    )
    return AppConfig.model_validate(raw)


def _events(run_dir: Path) -> dict[str, list[dict[str, object]]]:
    by_example: dict[str, list[dict[str, object]]] = {}
    for path in (run_dir / "traces").glob("*.jsonl"):
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        by_example[records[0]["example_id"]] = records
    return by_example


def _states(run_dir: Path) -> dict[str, FinOASISQuestionState]:
    values = [
        FinOASISQuestionState.model_validate_json(path.read_text(encoding="utf-8"))
        for path in (run_dir / "state").glob("*.v3.json")
    ]
    return {state.example_id: state for state in values}


async def test_four_task_mock_run_verifies_dynamic_ie_numeric_rule_and_mixed_paths(
    tmp_path,
):
    config_path = (
        ROOT
        / "configs"
        / "experimental"
        / "findoasis"
        / "M3_ALL_SKILLS_SYNTHETIC.yaml"
    )
    tasks_path = ROOT / "tests" / "fixtures" / "finoasis_smoke_tasks.jsonl"
    reports_path = ROOT / "tests" / "fixtures" / "finoasis_smoke_reports"
    run_dir = tmp_path / "finoasis-v3-run"
    config = _config()
    assert config.agent is not None
    backend = SequenceBackend()
    orchestrator = AgentOrchestrator(
        backend=backend,
        generation=config.generation,
        agent_config=config.agent,
        report_store=ReportStore(reports_path),
        run_dir=run_dir,
    )

    predictions_path = await run_batch(
        tasks_path=tasks_path,
        config_path=config_path,
        run_dir=run_dir,
        mode="agent",
        model=backend.model_name,
        backend_kind="mock",
        concurrency=1,
        answer=orchestrator.run_question,
    )

    predictions = [
        json.loads(line)
        for line in predictions_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(predictions) == 4
    assert all(prediction["status"] == "completed" for prediction in predictions)
    assert not backend.responses

    events = _events(run_dir)
    states = _states(run_dir)
    ie = states["finoasis-smoke-ie"]
    numeric = states["finoasis-smoke-numeric"]
    knowledge = states["finoasis-smoke-knowledge"]
    mixed = states["finoasis-smoke-mixed"]

    ie_exposures = [
        event["payload"]["available_skills"]
        for event in events["finoasis-smoke-ie"]
        if event["event"] == "model_request"
    ]
    assert all(
        not set(exposure)
        & {
            "read_table_region",
            "bind_financial_value",
            "execute_financial_program",
            "search_financial_rules",
            "read_financial_rules",
            "check_rule_applicability",
        }
        for exposure in ie_exposures
    )
    assert ie.skill_call_counts == {
        SkillName.SEARCH_REPORT: 1,
        SkillName.READ_PARAGRAPHS: 1,
        SkillName.SUBMIT_ANSWER: 1,
    }

    numeric_exposures = [
        event["payload"]["available_skills"]
        for event in events["finoasis-smoke-numeric"]
        if event["event"] == "model_request"
    ]
    assert all(
        "execute_financial_program" not in exposure
        for exposure in numeric_exposures[:5]
    )
    assert "execute_financial_program" in numeric_exposures[5]
    assert not {
        SkillName.SEARCH_FINANCIAL_RULES,
        SkillName.READ_FINANCIAL_RULES,
        SkillName.CHECK_RULE_APPLICABILITY,
    } & set(numeric.skill_call_counts)
    numeric_final = numeric.final_verification_certificate_ledger[
        numeric.prediction_certificate_ref
    ]
    assert numeric_final.numeric_certificate_refs == ["numeric-certificate-0001"]
    assert numeric_final.rule_certificate_refs == []

    assert SkillName.EXECUTE_FINANCIAL_PROGRAM not in knowledge.skill_call_counts
    knowledge_final = knowledge.final_verification_certificate_ledger[
        knowledge.prediction_certificate_ref
    ]
    assert knowledge_final.numeric_certificate_refs == []
    assert knowledge_final.rule_certificate_refs == ["rule-certificate-0001"]

    assert {obligation.type for obligation in mixed.obligations} >= {
        ObligationType.NUMERIC_OPERATION,
        ObligationType.DOMAIN_RULE,
        ObligationType.RULE_APPLICABILITY,
    }
    mixed_final = mixed.final_verification_certificate_ledger[
        mixed.prediction_certificate_ref
    ]
    assert mixed_final.numeric_certificate_refs == ["numeric-certificate-0001"]
    assert mixed_final.rule_certificate_refs == ["rule-certificate-0001"]

    summary = summarize(run_dir)
    v3 = summary["findoasis_v3"]
    assert v3["instrumented_questions"] == 4
    assert v3["obligations"]["total"] == 18
    assert v3["obligations"]["satisfaction_rate"] == 1.0
    assert v3["skill_routing"]["rejected_unavailable_calls"] == 0
    assert v3["skill_routing"]["certificate_consumed_skill_rate"] == 1.0
    assert v3["numeric"] == {
        "bound_values": 4,
        "binding_failures": 0,
        "program_execution_count": 2,
        "program_pass_rate": 1.0,
        "unit_failures": 0,
        "period_failures": 0,
        "type_failures": 0,
        "relation_failures": 0,
    }
    assert v3["rules"] == {
        "rule_searches": 2,
        "rules_read": 2,
        "applicability_checks": 2,
        "applicable": 2,
        "not_applicable": 0,
        "undetermined": 0,
        "hash_or_provenance_failures": 0,
    }
    assert v3["cost"] == {
        "model_calls": 26,
        "local_skill_calls": 26,
        "input_tokens": 26,
        "output_tokens": 26,
        "latency_ms": 3.25,
        "phase_attempts": {"exploration": 26, "finalization": 0, "review": 0},
    }

    rendered = json.dumps(summary)
    for private_text in (
        "facility in Shanghai",
        "The exact report paragraph",
        "performance obligation was satisfied",
        "$ 1,200",
    ):
        assert private_text not in rendered

    assert [task.example_id for task in load_public_tasks(tasks_path)] == [
        prediction["example_id"] for prediction in predictions
    ]
