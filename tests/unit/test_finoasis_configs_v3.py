from pathlib import Path

from findver_agent.config import load_config
from findver_agent.financial_rules.corpus import FrozenRuleCorpus


ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = ROOT / "configs" / "experimental" / "findoasis"
CONFIGS = {
    path.name: path for path in sorted(CONFIG_ROOT.glob("M3_*.yaml"))
}


def test_all_reviewed_finoasis_experimental_configs_load_strictly():
    assert set(CONFIGS) == {
        "M3_OBLIGATION_ONLY.yaml",
        "M3_NUMERIC.yaml",
        "M3_ALL_SKILLS_SYNTHETIC.yaml",
        "M3_ALL_SKILLS_ALWAYS_EXPOSED.yaml",
    }

    for path in CONFIGS.values():
        config = load_config(path)
        assert config.run.backend_kind == "mock"
        assert config.agent is not None
        assert config.agent.protocol_version == "v3"
        assert config.agent.findoasis is not None
        assert config.agent.findoasis.experimental is True
        assert config.agent.findoasis.official_test_authorized is False
        assert config.agent.findoasis.real_model_execution_authorized is False
        assert config.agent.findoasis.scorer_handoff_authorized is False


def test_method_configs_keep_numeric_rules_and_ablation_boundaries_explicit():
    obligation = load_config(CONFIGS["M3_OBLIGATION_ONLY.yaml"])
    numeric = load_config(CONFIGS["M3_NUMERIC.yaml"])
    all_skills = load_config(CONFIGS["M3_ALL_SKILLS_SYNTHETIC.yaml"])
    ablation = load_config(CONFIGS["M3_ALL_SKILLS_ALWAYS_EXPOSED.yaml"])
    assert obligation.agent is not None and obligation.agent.findoasis is not None
    assert numeric.agent is not None and numeric.agent.findoasis is not None
    assert all_skills.agent is not None and all_skills.agent.findoasis is not None
    assert ablation.agent is not None and ablation.agent.findoasis is not None

    assert obligation.agent.findoasis.enabled_skills == (
        "search_report",
        "read_paragraphs",
        "submit_answer",
    )
    assert "execute_financial_program" in numeric.agent.findoasis.enabled_skills
    assert "search_financial_rules" not in numeric.agent.findoasis.enabled_skills
    assert all_skills.agent.findoasis.obligation_policy.skill_exposure == "dynamic"
    assert (
        ablation.agent.findoasis.obligation_policy.skill_exposure
        == "always_exposed_ablation"
    )


def test_container_synthetic_corpus_is_hash_bound_and_loadable_at_host_root():
    config = load_config(CONFIGS["M3_ALL_SKILLS_SYNTHETIC.yaml"])
    assert config.agent is not None and config.agent.findoasis is not None
    corpus_config = config.agent.findoasis.rule_corpus.model_copy(
        update={"rule_root": CONFIG_ROOT / "synthetic_rule_corpus"}
    )
    corpus = FrozenRuleCorpus.load(corpus_config)

    assert corpus.corpus_id == "finoasis-synthetic-rules-v1"
    assert corpus.manifest_sha256 == (
        "549461e4b4a2fb1b8357b30f03589f62562db7a4b26ac8d38074b34080a4dc33"
    )
    assert corpus.records_sha256 == (
        "4a3085d2b0d32a320fbc8e5b99527221e1abd161a3a277239732804873fe3436"
    )
    assert "not financial, accounting, legal, or regulatory guidance" in (
        corpus.manifest.license_note
    )
