"""Mechanical, evidence-bound applicability checking for frozen rules."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Sequence

from .corpus import FrozenRuleCorpus, rule_record_sha256
from .models import (
    RuleApplicabilityCertificate,
    RuleApplicabilityResult,
    RulePredicateResult,
    RuleRecord,
)


_UNKNOWN = {"", "?", "n/a", "na", "none", "unknown", "unspecified"}


class RuleApplicabilityError(ValueError):
    """Applicability inputs do not bind to trusted corpus/document evidence."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def rule_applicability_certificate_sha256(
    certificate: RuleApplicabilityCertificate,
) -> str:
    return hashlib.sha256(
        _canonical_json(certificate.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()


def _scope_matches(expected: str, actual: str) -> bool:
    expected_key = " ".join(expected.casefold().split())
    actual_key = " ".join(actual.casefold().split())
    return expected_key in {"all", actual_key}


def check_rule_applicability(
    *,
    corpus: FrozenRuleCorpus,
    rule_evidence: Sequence[object],
    document_evidence: Sequence[object],
    effective_date: str,
    jurisdiction: str,
    entity_scope: str,
    predicate_ids: Sequence[str],
    certificate_id: str,
) -> RuleApplicabilityCertificate:
    if not rule_evidence:
        raise RuleApplicabilityError("at least one read rule evidence entry is required")
    if not document_evidence:
        raise RuleApplicabilityError("at least one document evidence entry is required")

    rules: list[RuleRecord] = []
    rule_refs: list[str] = []
    for evidence in rule_evidence:
        if (
            getattr(evidence, "corpus_id") != corpus.corpus_id
            or getattr(evidence, "manifest_sha256") != corpus.manifest_sha256
            or getattr(evidence, "records_sha256") != corpus.records_sha256
        ):
            raise RuleApplicabilityError("rule evidence corpus identity is stale")
        rule = corpus.record(str(getattr(evidence, "rule_id")))
        if getattr(evidence, "rule_sha256") != rule_record_sha256(rule):
            raise RuleApplicabilityError("rule evidence record hash is stale")
        if getattr(evidence, "text") != rule.text:
            raise RuleApplicabilityError("rule evidence text differs from frozen corpus")
        rules.append(rule)
        rule_refs.append(str(getattr(evidence, "rule_evidence_id")))

    document_by_ref: dict[str, object] = {}
    for evidence in document_evidence:
        reference = str(getattr(evidence, "evidence_id"))
        if reference in document_by_ref:
            raise RuleApplicabilityError("document evidence refs must be unique")
        document_by_ref[reference] = evidence

    required_predicates = {
        predicate.predicate_id
        for rule in rules
        for predicate in rule.predicates
        if predicate.required
    }
    selected_predicates = set(predicate_ids) if predicate_ids else required_predicates
    available_predicates = {
        predicate.predicate_id for rule in rules for predicate in rule.predicates
    }
    if selected_predicates - available_predicates:
        raise RuleApplicabilityError("applicability references an unknown predicate")
    if required_predicates - selected_predicates:
        raise RuleApplicabilityError("required rule predicates cannot be omitted")

    missing_metadata = []
    parsed_date: date | None
    if effective_date.strip().casefold() in _UNKNOWN:
        parsed_date = None
        missing_metadata.append("effective date is unknown")
    else:
        try:
            parsed_date = date.fromisoformat(effective_date)
        except ValueError:
            parsed_date = None
            missing_metadata.append("effective date is not ISO YYYY-MM-DD")
    jurisdiction_known = jurisdiction.strip().casefold() not in _UNKNOWN
    entity_scope_known = entity_scope.strip().casefold() not in _UNKNOWN
    if not jurisdiction_known:
        missing_metadata.append("jurisdiction is unknown")
    if not entity_scope_known:
        missing_metadata.append("entity scope is unknown")

    effective_check = (
        None
        if parsed_date is None
        else all(
            parsed_date >= rule.effective_from
            and (rule.effective_to is None or parsed_date <= rule.effective_to)
            for rule in rules
        )
    )
    jurisdiction_check = (
        None
        if not jurisdiction_known
        else all(_scope_matches(rule.jurisdiction, jurisdiction) for rule in rules)
    )
    entity_scope_check = (
        None
        if not entity_scope_known
        else all(_scope_matches(rule.entity_scope, entity_scope) for rule in rules)
    )

    predicate_results: list[RulePredicateResult] = []
    for rule in rules:
        for predicate in rule.predicates:
            if predicate.predicate_id not in selected_predicates:
                continue
            matching_refs = [
                reference
                for reference, evidence in document_by_ref.items()
                if predicate.term.casefold()
                in str(getattr(evidence, "exact_text")).casefold()
            ]
            satisfied = bool(matching_refs)
            if predicate.kind == "document_not_contains":
                satisfied = not satisfied
                matching_refs = list(document_by_ref) if satisfied else matching_refs
            predicate_results.append(
                RulePredicateResult(
                    rule_id=rule.rule_id,
                    predicate_id=predicate.predicate_id,
                    satisfied=satisfied,
                    evidence_refs=matching_refs,
                )
            )

    selected_rule_ids = {rule.rule_id for rule in rules}
    conflicts = sorted(
        {
            conflict
            for rule in rules
            for conflict in rule.conflicts_with
            if conflict in selected_rule_ids
        }
    )
    predicate_failure = any(not item.satisfied for item in predicate_results)
    checks = (effective_check, jurisdiction_check, entity_scope_check)
    if conflicts or any(check is None for check in checks):
        result = RuleApplicabilityResult.UNDETERMINED
    elif any(check is False for check in checks) or predicate_failure:
        result = RuleApplicabilityResult.NOT_APPLICABLE
    else:
        result = RuleApplicabilityResult.APPLICABLE

    diagnostics = [*missing_metadata]
    if conflicts:
        diagnostics.append("selected rule evidence contains an explicit rule conflict")
    if effective_check is False:
        diagnostics.append("effective date falls outside a selected rule interval")
    if jurisdiction_check is False:
        diagnostics.append("jurisdiction does not match a selected rule")
    if entity_scope_check is False:
        diagnostics.append("entity scope does not match a selected rule")
    if predicate_failure:
        diagnostics.append("one or more required document predicates failed")
    if not diagnostics:
        diagnostics.append("all mechanical applicability checks passed")

    return RuleApplicabilityCertificate(
        certificate_id=certificate_id,
        corpus_id=corpus.corpus_id,
        manifest_sha256=corpus.manifest_sha256,
        records_sha256=corpus.records_sha256,
        rule_evidence_refs=rule_refs,
        rule_ids=[rule.rule_id for rule in rules],
        document_evidence_refs=list(document_by_ref),
        effective_date=effective_date,
        jurisdiction=jurisdiction,
        entity_scope=entity_scope,
        effective_date_check=effective_check,
        jurisdiction_check=jurisdiction_check,
        entity_scope_check=entity_scope_check,
        predicates=predicate_results,
        conflict_rule_ids=conflicts,
        result=result,
        diagnostics=list(dict.fromkeys(diagnostics))[:8],
    )


__all__ = [
    "RuleApplicabilityError",
    "check_rule_applicability",
    "rule_applicability_certificate_sha256",
]
