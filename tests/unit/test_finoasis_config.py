from copy import deepcopy

import pytest
from pydantic import ValidationError

from findver_agent.config import AppConfig, FinOasisConfig


SKILLS = (
    "search_report",
    "read_paragraphs",
    "read_table_region",
    "bind_financial_value",
    "execute_financial_program",
    "search_financial_rules",
    "read_financial_rules",
    "check_rule_applicability",
    "submit_answer",
)


def _budgets(enabled):
    return {name: 1 if name in enabled else 0 for name in SKILLS}


def _findoasis(enabled=("search_report", "read_paragraphs", "submit_answer")):
    return {
        "experimental": True,
        "official_test_authorized": False,
        "real_model_execution_authorized": False,
        "scorer_handoff_authorized": False,
        "enabled_skills": list(enabled),
        "skill_budgets": _budgets(enabled),
        "obligation_policy": {
            "seeding": "conservative",
            "skill_exposure": "dynamic",
            "model_may_open_obligations": True,
            "model_may_satisfy_obligations": False,
            "model_may_waive_mandatory": False,
            "normal_submit_requires_all_mandatory": True,
            "budget_exhausted_submit": "low_confidence_best_effort",
        },
        "rule_corpus": {
            "enabled": False,
            "read_only": True,
            "network_fallback": False,
        },
    }


def _agent_config(protocol_version="v3"):
    return {
        "run": {"mode": "agent", "backend_kind": "mock"},
        "backend": {
            "type": "openai_compatible",
            "base_url": "http://model-gateway:8080/v1",
            "model": "mock",
        },
        "generation": {"prompt_budget_tokens": 4096},
        "agent": {
            "protocol_version": protocol_version,
            "calculator_enabled": False,
            "review_steps": 0,
            "review_policy": "none",
            "cross_question_memory": False,
            "scorer_feedback": False,
            "findoasis": _findoasis(),
        },
    }


def test_protocol_v3_accepts_explicit_strict_finoasis_configuration():
    config = AppConfig.model_validate(_agent_config())

    assert config.agent is not None
    assert config.agent.protocol_version == "v3"
    assert isinstance(config.agent.findoasis, FinOasisConfig)
    assert config.agent.findoasis.enabled_skills == (
        "search_report",
        "read_paragraphs",
        "submit_answer",
    )
    assert config.agent.findoasis.skill_budgets.submit_answer == 1
    assert config.agent.findoasis.rule_corpus.enabled is False


def test_protocol_v3_accepts_hash_bound_local_rule_corpus():
    raw = _agent_config()
    enabled = SKILLS
    raw["agent"]["findoasis"] = _findoasis(enabled)
    raw["agent"]["findoasis"]["rule_corpus"] = {
        "enabled": True,
        "rule_root": "/rules/frozen",
        "manifest_path": "synthetic/manifest.json",
        "records_path": "synthetic/records.jsonl",
        "corpus_id": "synthetic-finance-rules-v1",
        "manifest_sha256": "a" * 64,
        "records_sha256": "b" * 64,
        "read_only": True,
        "network_fallback": False,
    }

    config = AppConfig.model_validate(raw)

    assert config.agent is not None and config.agent.findoasis is not None
    assert config.agent.findoasis.rule_corpus.rule_root.as_posix() == "/rules/frozen"
    assert config.agent.findoasis.obligation_policy.skill_exposure == "dynamic"


@pytest.mark.parametrize("protocol_version", ["v1", "v2"])
def test_legacy_protocols_reject_finoasis_without_changing_legacy_defaults(
    protocol_version,
):
    raw = _agent_config(protocol_version)
    with pytest.raises(ValidationError, match="only for protocol v3"):
        AppConfig.model_validate(raw)

    raw["agent"].pop("findoasis")
    raw["agent"]["calculator_enabled"] = True
    raw["agent"]["review_steps"] = 1
    config = AppConfig.model_validate(raw)
    assert config.agent is not None
    assert config.agent.protocol_version == protocol_version
    assert config.agent.findoasis is None
    assert "findoasis" not in config.model_dump(mode="json", exclude_none=True)["agent"]


def test_protocol_v3_requires_explicit_finoasis_configuration():
    raw = _agent_config()
    raw["agent"].pop("findoasis")
    with pytest.raises(ValidationError, match="requires explicit findoasis"):
        AppConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("calculator_enabled", True, "legacy calculator"),
        ("pre_submit_review", True, "legacy pre_submit_review"),
        ("review_policy", "mandatory", "mandatory legacy review"),
        ("review_steps", 1, "review_steps=0"),
    ],
)
def test_protocol_v3_rejects_legacy_execution_and_review_switches(
    field, value, message
):
    raw = _agent_config()
    raw["agent"][field] = value
    with pytest.raises(ValidationError, match=message):
        AppConfig.model_validate(raw)


def test_protocol_v3_rejects_initial_retrieval_and_long_context():
    raw = _agent_config()
    raw["agent"]["initial_retrieval"] = {
        "enabled": True,
        "retrieval_file": "/retrieval/top10.json",
        "retriever": "bm25",
    }
    with pytest.raises(ValidationError, match="legacy initial_retrieval"):
        AppConfig.model_validate(raw)

    raw = _agent_config()
    raw["agent"]["long_context"] = {"enabled": True}
    with pytest.raises(ValidationError, match="legacy long_context"):
        AppConfig.model_validate(raw)


def test_protocol_v3_accepts_bounded_selective_review_only():
    raw = _agent_config()
    raw["agent"].update({"review_policy": "selective", "review_steps": 1})
    config = AppConfig.model_validate(raw)
    assert config.agent is not None
    assert (config.agent.review_policy, config.agent.review_steps) == ("selective", 1)

    raw["agent"]["review_steps"] = 0
    with pytest.raises(ValidationError, match="at least one review step"):
        AppConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("findoasis", "unexpected"), True),
        (("findoasis", "skill_budgets", "calculator"), 1),
        (("findoasis", "obligation_policy", "waive_all"), True),
        (("findoasis", "rule_corpus", "download_url"), "https://example.invalid"),
    ],
)
def test_finoasis_nested_models_forbid_unknown_fields(path, value):
    raw = _agent_config()
    target = raw["agent"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AppConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("experimental", False),
        ("official_test_authorized", True),
        ("real_model_execution_authorized", True),
        ("scorer_handoff_authorized", True),
    ],
)
def test_finoasis_cannot_relax_experimental_authorization_boundary(flag, value):
    raw = _agent_config()
    raw["agent"]["findoasis"][flag] = value
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_finoasis_allowlist_and_budgets_must_match_exactly():
    raw = _agent_config()
    raw["agent"]["findoasis"]["enabled_skills"].append("search_report")
    with pytest.raises(ValidationError, match="duplicates"):
        AppConfig.model_validate(raw)

    raw = _agent_config()
    raw["agent"]["findoasis"]["enabled_skills"].remove("submit_answer")
    raw["agent"]["findoasis"]["skill_budgets"]["submit_answer"] = 0
    with pytest.raises(ValidationError, match="include submit_answer"):
        AppConfig.model_validate(raw)

    raw = _agent_config()
    raw["agent"]["findoasis"]["skill_budgets"]["search_report"] = 0
    with pytest.raises(ValidationError, match="positive budget"):
        AppConfig.model_validate(raw)

    raw = _agent_config()
    raw["agent"]["findoasis"]["skill_budgets"]["read_table_region"] = 1
    with pytest.raises(ValidationError, match="zero budget"):
        AppConfig.model_validate(raw)


def test_rule_skill_dependencies_and_corpus_identity_fail_closed():
    raw = _agent_config()
    enabled = ("read_financial_rules", "submit_answer")
    raw["agent"]["findoasis"] = _findoasis(enabled)
    with pytest.raises(ValidationError, match="requires search_financial_rules"):
        AppConfig.model_validate(raw)

    raw = _agent_config()
    enabled = (
        "search_financial_rules",
        "read_financial_rules",
        "check_rule_applicability",
        "submit_answer",
    )
    raw["agent"]["findoasis"] = _findoasis(enabled)
    with pytest.raises(ValidationError, match="exactly when rule Skills"):
        AppConfig.model_validate(raw)

    raw = _agent_config()
    enabled = ("search_report", "read_paragraphs", "submit_answer")
    raw["agent"]["findoasis"] = _findoasis(enabled)
    raw["agent"]["findoasis"]["rule_corpus"] = {
        "enabled": True,
        "rule_root": "/rules",
        "manifest_path": "../manifest.json",
        "records_path": "records.jsonl",
        "corpus_id": "synthetic",
        "manifest_sha256": "a" * 64,
        "records_sha256": "b" * 64,
        "read_only": True,
        "network_fallback": False,
    }
    with pytest.raises(ValidationError, match="traversal-free"):
        AppConfig.model_validate(raw)


def test_finoasis_validation_does_not_mutate_input():
    raw = _agent_config()
    original = deepcopy(raw)
    AppConfig.model_validate(raw)
    assert raw == original
