import ast
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from findver_agent.config import FinOasisRuleCorpusConfig
from findver_agent.financial_rules.applicability import (
    check_rule_applicability,
    rule_applicability_certificate_sha256,
)
from findver_agent.financial_rules.corpus import (
    FrozenRuleCorpus,
    RuleCorpusError,
    rule_record_sha256,
)
from findver_agent.financial_rules.models import RuleApplicabilityResult


FIXTURE_ROOT = Path("tests/fixtures/finoasis_rule_corpus").resolve()
MANIFEST_SHA256 = "549461e4b4a2fb1b8357b30f03589f62562db7a4b26ac8d38074b34080a4dc33"
RECORDS_SHA256 = "4a3085d2b0d32a320fbc8e5b99527221e1abd161a3a277239732804873fe3436"


def config(root=FIXTURE_ROOT, **updates):
    values = {
        "enabled": True,
        "rule_root": root,
        "manifest_path": Path("manifest.json"),
        "records_path": Path("records.json"),
        "corpus_id": "finoasis-synthetic-rules-v1",
        "manifest_sha256": MANIFEST_SHA256,
        "records_sha256": RECORDS_SHA256,
        "read_only": True,
        "network_fallback": False,
    }
    values.update(updates)
    return FinOasisRuleCorpusConfig.model_validate(values)


def rule_evidence(corpus, rule_id, sequence=1):
    record = corpus.record(rule_id)
    return SimpleNamespace(
        rule_evidence_id=f"rule-evidence-{sequence:04d}",
        rule_id=rule_id,
        rule_sha256=rule_record_sha256(record),
        corpus_id=corpus.corpus_id,
        manifest_sha256=corpus.manifest_sha256,
        records_sha256=corpus.records_sha256,
        text=record.text,
    )


def document(text, reference="ev-1"):
    return SimpleNamespace(evidence_id=reference, exact_text=text)


def applicability(
    corpus,
    rules,
    docs,
    *,
    effective_date="2024-12-31",
    jurisdiction="US",
    entity_scope="public issuer",
    predicate_ids=(),
):
    return check_rule_applicability(
        corpus=corpus,
        rule_evidence=rules,
        document_evidence=docs,
        effective_date=effective_date,
        jurisdiction=jurisdiction,
        entity_scope=entity_scope,
        predicate_ids=predicate_ids,
        certificate_id="rule-certificate-0001",
    )


def rewrite_corpus(root, records_value):
    records_bytes = (json.dumps(records_value, indent=2) + "\n").encode()
    (root / "records.json").write_bytes(records_bytes)
    records_sha = hashlib.sha256(records_bytes).hexdigest()
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
    manifest["records_sha256"] = records_sha
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
    (root / "manifest.json").write_bytes(manifest_bytes)
    return hashlib.sha256(manifest_bytes).hexdigest(), records_sha


def test_frozen_corpus_loads_hashes_sources_and_deterministic_search():
    corpus = FrozenRuleCorpus.load(config())
    assert corpus.corpus_id == "finoasis-synthetic-rules-v1"
    assert corpus.manifest.schema_version == 1
    assert len(corpus.records) == 4
    assert all(record.source_reference for record in corpus.records)

    first = corpus.search(
        query="performance obligation revenue",
        jurisdiction="US",
        as_of_date="2024-12-31",
        top_k=10,
    )
    second = corpus.search(
        query="performance obligation revenue",
        jurisdiction="US",
        as_of_date="2024-12-31",
        top_k=10,
    )
    assert first == second
    assert first[0].rule_id == "synthetic-us-revenue-current"
    assert all(len(hit.snippet) <= 240 for hit in first)
    identifiers = {hit.rule_id for hit in first}
    assert "synthetic-us-revenue-expired" in identifiers
    assert "synthetic-eu-revenue-current" in identifiers
    expired = next(
        hit for hit in first if hit.rule_id == "synthetic-us-revenue-expired"
    )
    assert expired.jurisdiction == "US"
    assert expired.effective_to is not None
    assert expired.effective_to.isoformat() == "2019-12-31"


@pytest.mark.parametrize("member", ["manifest", "records"])
def test_configured_file_hash_tampering_fails_closed(tmp_path, member):
    root = tmp_path / "rules"
    shutil.copytree(FIXTURE_ROOT, root)
    path = root / f"{member}.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(RuleCorpusError, match=f"{member} hash"):
        FrozenRuleCorpus.load(config(root))


def test_path_escape_unknown_fields_duplicate_ids_and_missing_source_are_rejected(
    tmp_path,
):
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    root = tmp_path / "rules"
    shutil.copytree(FIXTURE_ROOT, root)
    (root / "escape.json").symlink_to(outside)
    escaped = config(
        root,
        manifest_path=Path("escape.json"),
        manifest_sha256=hashlib.sha256(outside.read_bytes()).hexdigest(),
    )
    with pytest.raises(RuleCorpusError, match="escapes"):
        FrozenRuleCorpus.load(escaped)

    records = json.loads((FIXTURE_ROOT / "records.json").read_text())
    records["unknown"] = True
    manifest_sha, records_sha = rewrite_corpus(root, records)
    with pytest.raises(RuleCorpusError, match="schema"):
        FrozenRuleCorpus.load(
            config(
                root,
                manifest_sha256=manifest_sha,
                records_sha256=records_sha,
            )
        )

    records = json.loads((FIXTURE_ROOT / "records.json").read_text())
    records["records"].append(records["records"][0])
    manifest_sha, records_sha = rewrite_corpus(root, records)
    with pytest.raises(RuleCorpusError, match="duplicate"):
        FrozenRuleCorpus.load(
            config(
                root,
                manifest_sha256=manifest_sha,
                records_sha256=records_sha,
            )
        )

    records = json.loads((FIXTURE_ROOT / "records.json").read_text())
    records["records"][0]["source_reference"] = ""
    manifest_sha, records_sha = rewrite_corpus(root, records)
    with pytest.raises(RuleCorpusError, match="schema"):
        FrozenRuleCorpus.load(
            config(
                root,
                manifest_sha256=manifest_sha,
                records_sha256=records_sha,
            )
        )

    records = json.loads((FIXTURE_ROOT / "records.json").read_text())
    records["records"][0]["predicates"][0]["kind"] = "document_not_contains"
    manifest_sha, records_sha = rewrite_corpus(root, records)
    with pytest.raises(RuleCorpusError, match="schema"):
        FrozenRuleCorpus.load(
            config(
                root,
                manifest_sha256=manifest_sha,
                records_sha256=records_sha,
            )
        )


def test_applicable_certificate_is_hash_deterministic_and_evidence_bound():
    corpus = FrozenRuleCorpus.load(config())
    rule = rule_evidence(corpus, "synthetic-us-revenue-current")
    doc = document("The identified performance obligation was satisfied.")
    first = applicability(corpus, [rule], [doc])
    second = applicability(corpus, [rule], [doc])

    assert first.result is RuleApplicabilityResult.APPLICABLE
    assert first.effective_date_check is True
    assert first.jurisdiction_check is True
    assert first.entity_scope_check is True
    assert first.predicates[0].satisfied is True
    assert first.predicates[0].evidence_refs == ["ev-1"]
    assert rule_applicability_certificate_sha256(
        first
    ) == rule_applicability_certificate_sha256(second)


@pytest.mark.parametrize(
    ("rule_id", "updates", "diagnostic"),
    [
        (
            "synthetic-us-revenue-expired",
            {},
            "effective date falls outside",
        ),
        (
            "synthetic-us-revenue-current",
            {"jurisdiction": "EU"},
            "jurisdiction does not match",
        ),
        (
            "synthetic-us-revenue-current",
            {"entity_scope": "bank"},
            "entity scope does not match",
        ),
    ],
)
def test_expired_jurisdiction_and_entity_mismatch_are_explicit_not_applicable(
    rule_id, updates, diagnostic
):
    corpus = FrozenRuleCorpus.load(config())
    rule = rule_evidence(corpus, rule_id)
    doc = document(
        "The performance obligation was satisfied and delivery occurred."
    )
    certificate = applicability(corpus, [rule], [doc], **updates)
    assert certificate.result is RuleApplicabilityResult.NOT_APPLICABLE
    assert any(diagnostic in item for item in certificate.diagnostics)


def test_failed_predicate_is_explicit_not_applicable():
    corpus = FrozenRuleCorpus.load(config())
    certificate = applicability(
        corpus,
        [rule_evidence(corpus, "synthetic-us-revenue-current")],
        [document("The report has no matching recognition fact.")],
    )
    assert certificate.result is RuleApplicabilityResult.NOT_APPLICABLE
    assert certificate.predicates[0].satisfied is False


def test_conflicting_rules_and_missing_date_are_undetermined():
    corpus = FrozenRuleCorpus.load(config())
    current = rule_evidence(corpus, "synthetic-us-revenue-current", 1)
    conflict = rule_evidence(corpus, "synthetic-us-revenue-conflict", 2)
    docs = [
        document(
            "The performance obligation was satisfied before performance.",
        )
    ]
    conflicting = applicability(corpus, [current, conflict], docs)
    missing_date = applicability(
        corpus,
        [current],
        docs,
        effective_date="unknown",
    )
    assert conflicting.result is RuleApplicabilityResult.UNDETERMINED
    assert conflicting.conflict_rule_ids
    assert missing_date.result is RuleApplicabilityResult.UNDETERMINED
    assert missing_date.effective_date_check is None

    rewritten = conflicting.model_dump(mode="json")
    rewritten["result"] = "applicable"
    with pytest.raises(ValueError, match="applicable result requires"):
        type(conflicting).model_validate(rewritten)


def test_certificate_rejects_unbound_predicate_and_conflict_references():
    corpus = FrozenRuleCorpus.load(config())
    certificate = applicability(
        corpus,
        [rule_evidence(corpus, "synthetic-us-revenue-current")],
        [document("The performance obligation was satisfied.")],
    )

    unbound_predicate = certificate.model_dump(mode="json")
    unbound_predicate["predicates"][0]["evidence_refs"] = ["ev-unbound"]
    with pytest.raises(ValueError, match="predicate evidence"):
        type(certificate).model_validate(unbound_predicate)

    unbound_conflict = certificate.model_dump(mode="json")
    unbound_conflict["result"] = "undetermined"
    unbound_conflict["conflict_rule_ids"] = ["rule-unselected"]
    with pytest.raises(ValueError, match="selected rule evidence"):
        type(certificate).model_validate(unbound_conflict)


def test_rule_modules_have_no_network_dynamic_execution_or_write_capability():
    paths = [
        Path("src/findver_agent/financial_rules/models.py"),
        Path("src/findver_agent/financial_rules/corpus.py"),
        Path("src/findver_agent/financial_rules/applicability.py"),
    ]
    called_names = set()
    imported_roots = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called_names.update(
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
        imported_roots.update(
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        )
    assert not {"eval", "exec", "compile", "__import__", "open"} & called_names
    assert not {"socket", "requests", "urllib", "httpx", "subprocess"} & imported_roots
