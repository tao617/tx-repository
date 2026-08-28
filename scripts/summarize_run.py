#!/usr/bin/env python3
"""Summarize aggregate-only reliability and efficiency metrics for one run."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from findver_agent.findoasis.contracts import (
    FinalCertificateStatus,
    ObligationStatus,
    ObligationType,
    SkillName,
)
from findver_agent.findoasis.state import FinOASISQuestionState


PHASES = (
    "exploration",
    "finalization",
    "review",
    "iterative_retrieval",
    "legacy",
    "baseline",
)
ERROR_KINDS = ("parse", "model", "skill", "protocol", "protocol_drift")
FINISH_REASONS = ("stop", "length", "content_filter")
TOOL_NAMES = ("search_report", "read_paragraphs", "calculator")
VISIBILITY_KEYS = (
    "ledger_evidence_ids",
    "prompt_visible_evidence_ids",
    "prompt_omitted_evidence_ids",
    "dynamic_ledger_evidence_ids",
    "prompt_visible_dynamic_evidence_ids",
)
SAFE_TERMINATION_REASONS = {
    "step budget exhausted",
    "submitted_during_exploration",
    "submitted_during_finalization",
    "review_completed",
    "review_fallback",
    "review_budget_exhausted",
    "finalization_budget_exhausted",
    "iterative_rag_finalized",
    "budget_exhausted_fallback",
    "certificate_verified",
    "review_verified",
}
FINOASIS_FAILURE_CATEGORIES = frozenset(
    {
        "binding_failure",
        "program_failure",
        "unit_failure",
        "period_failure",
        "type_failure",
        "relation_failure",
        "rule_integrity_failure",
    }
)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _load_predictions(path: Path) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"prediction line {line_number} must be an object")
            predictions.append(value)
    return predictions


def _strict_valid(prediction: dict[str, Any]) -> bool:
    evidence_ids = prediction.get("evidence_ids")
    return (
        prediction.get("status") == "completed"
        and prediction.get("label") in {"entailed", "refuted"}
        and isinstance(evidence_ids, list)
        and all(type(item) is int and item >= 0 for item in evidence_ids)
        and len(evidence_ids) == len(set(evidence_ids))
        and isinstance(prediction.get("explanation"), str)
        and bool(prediction["explanation"].strip())
    )


def _error_kind(payload: dict[str, Any], *, baseline: bool = False) -> str:
    configured = payload.get("error_type", payload.get("kind"))
    if configured in ERROR_KINDS:
        return str(configured)
    message = str(payload.get("error", "")).casefold()
    if "model error" in message or (baseline and "context" in message):
        return "model"
    if "skill error" in message or message.startswith("skillerror"):
        return "skill"
    return "parse"


def _mean(value: int | float, denominator: int) -> float:
    return round(value / denominator, 6)


def _valid_id_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(type(item) is int and item >= 0 for item in value)
        and len(value) == len(set(value))
    )


def _terminal_final_certificate(state: FinOASISQuestionState):
    reference = state.prediction_certificate_ref or state.draft_certificate_ref
    if reference is not None:
        return state.final_verification_certificate_ledger.get(reference)
    if state.final_verification_certificate_ledger:
        return list(state.final_verification_certificate_ledger.values())[-1]
    return None


def _finoasis_summary(
    states: list[FinOASISQuestionState],
    *,
    exposed_by_skill: Counter[str],
    exposure_attempts: int,
    failure_categories: Counter[str],
) -> dict[str, Any]:
    """Build a text-free protocol-v3 aggregate from validated state ledgers."""

    question_count = len(states)
    obligation_types = tuple(item.value for item in ObligationType)
    obligation_statuses = tuple(item.value for item in ObligationStatus)
    skill_names = tuple(item.value for item in SkillName)
    opened_by_type: Counter[str] = Counter()
    status_by_type = {
        status: Counter() for status in obligation_statuses
    }
    called_by_skill: Counter[str] = Counter()
    rejected_by_skill: Counter[str] = Counter()
    final_statuses: Counter[str] = Counter()
    unresolved_at_submit = 0
    total_obligations = 0
    satisfied_obligations = 0
    bound_values = program_executions = numeric_certificates = 0
    relation_failures = 0
    rule_searches = rules_read = applicability_checks = 0
    applicability_results: Counter[str] = Counter()
    consumed_specialist_certificates = 0
    producer_skill_calls = 0
    model_calls = input_tokens = output_tokens = local_skill_calls = 0
    latency_ms = 0.0
    phase_attempts: Counter[str] = Counter()

    for state in states:
        final_statuses[state.final_certificate_status.value] += 1
        total_obligations += len(state.obligations)
        for obligation in state.obligations:
            opened_by_type[obligation.type.value] += 1
            status_by_type[obligation.status.value][obligation.type.value] += 1
            satisfied_obligations += int(
                obligation.status is ObligationStatus.SATISFIED
            )

        final_certificate = _terminal_final_certificate(state)
        if final_certificate is not None:
            unresolved_at_submit += len(
                set(final_certificate.unresolved_obligation_ids)
            )
            consumed_specialist_certificates += len(
                set(final_certificate.numeric_certificate_refs)
                | set(final_certificate.rule_certificate_refs)
            )

        for skill, count in state.skill_call_counts.items():
            called_by_skill[skill.value] += count
        for skill, count in state.skill_rejection_counts.items():
            rejected_by_skill[skill.value] += count
        producer_skill_calls += state.skill_call_counts.get(
            SkillName.EXECUTE_FINANCIAL_PROGRAM, 0
        )
        producer_skill_calls += state.skill_call_counts.get(
            SkillName.CHECK_RULE_APPLICABILITY, 0
        )

        bound_values += len(state.numeric_value_ledger)
        program_executions += len(state.financial_program_ledger)
        numeric_certificates += len(state.numeric_certificate_ledger)
        relation_failures += sum(
            certificate.relation_satisfied is False
            for certificate in state.numeric_certificate_ledger.values()
        )

        rule_searches += len(state.rule_search_history)
        rules_read += len(state.rule_evidence_ledger)
        applicability_checks += len(
            state.rule_applicability_certificate_ledger
        )
        for certificate in state.rule_applicability_certificate_ledger.values():
            applicability_results[certificate.result.value] += 1

        model_calls += state.usage.model_calls
        input_tokens += state.usage.input_tokens
        output_tokens += state.usage.output_tokens
        latency_ms += state.usage.latency_ms
        local_skill_calls += state.usage.local_skill_calls
        phase_attempts["exploration"] += state.phase_attempts.exploration_used
        phase_attempts["finalization"] += state.phase_attempts.finalization_used
        phase_attempts["review"] += state.phase_attempts.review_used

    rejected_total = sum(rejected_by_skill.values())
    called_total = sum(called_by_skill.values())
    attempted_skill_calls = called_total + rejected_total
    program_failures = failure_categories["program_failure"]
    program_attempts = numeric_certificates + program_failures
    relation_failures += failure_categories["relation_failure"]

    return {
        "instrumented_questions": question_count,
        "obligations": {
            "total": total_obligations,
            "mean_per_question": (
                _mean(total_obligations, question_count) if question_count else 0.0
            ),
            "opened_by_type": {
                name: int(opened_by_type[name]) for name in obligation_types
            },
            "satisfied_by_type": {
                name: int(status_by_type["satisfied"][name])
                for name in obligation_types
            },
            "partial_by_type": {
                name: int(status_by_type["partial"][name])
                for name in obligation_types
            },
            "conflicting_by_type": {
                name: int(status_by_type["conflicting"][name])
                for name in obligation_types
            },
            "blocked_by_type": {
                name: int(status_by_type["blocked"][name])
                for name in obligation_types
            },
            "pending_by_type": {
                name: int(status_by_type["pending"][name])
                for name in obligation_types
            },
            "unresolved_at_submit": unresolved_at_submit,
            "satisfaction_rate": (
                _mean(satisfied_obligations, total_obligations)
                if total_obligations
                else 0.0
            ),
            "final_certificate_status_counts": {
                status.value: int(final_statuses[status.value])
                for status in FinalCertificateStatus
            },
        },
        "skill_routing": {
            "exposed_count_by_skill": {
                name: int(exposed_by_skill[name]) for name in skill_names
            },
            "called_count_by_skill": {
                name: int(called_by_skill[name]) for name in skill_names
            },
            "rejected_unavailable_calls": rejected_total,
            "rejected_unavailable_by_skill": {
                name: int(rejected_by_skill[name]) for name in skill_names
            },
            "mean_exposed_skills_per_attempt": (
                _mean(sum(exposed_by_skill.values()), exposure_attempts)
                if exposure_attempts
                else 0.0
            ),
            "mean_called_skills_per_question": (
                _mean(called_total, question_count) if question_count else 0.0
            ),
            "avoidable_call_rate": (
                _mean(rejected_total, attempted_skill_calls)
                if attempted_skill_calls
                else 0.0
            ),
            "certificate_consumed_skill_rate": (
                _mean(consumed_specialist_certificates, producer_skill_calls)
                if producer_skill_calls
                else 0.0
            ),
            "certificate_consumed_specialist_calls": (
                consumed_specialist_certificates
            ),
        },
        "numeric": {
            "bound_values": bound_values,
            "binding_failures": failure_categories["binding_failure"],
            "program_execution_count": program_executions,
            "program_pass_rate": (
                _mean(numeric_certificates, program_attempts)
                if program_attempts
                else 0.0
            ),
            "unit_failures": failure_categories["unit_failure"],
            "period_failures": failure_categories["period_failure"],
            "type_failures": failure_categories["type_failure"],
            "relation_failures": relation_failures,
        },
        "rules": {
            "rule_searches": rule_searches,
            "rules_read": rules_read,
            "applicability_checks": applicability_checks,
            "applicable": applicability_results["applicable"],
            "not_applicable": applicability_results["not_applicable"],
            "undetermined": applicability_results["undetermined"],
            "hash_or_provenance_failures": failure_categories[
                "rule_integrity_failure"
            ],
        },
        "cost": {
            "model_calls": model_calls,
            "local_skill_calls": local_skill_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(latency_ms, 3),
            "phase_attempts": {
                phase: int(phase_attempts[phase])
                for phase in ("exploration", "finalization", "review")
            },
        },
    }


def summarize(
    run_dir: Path,
    *,
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
) -> dict[str, Any]:
    metadata = _load_object(run_dir / "run_metadata.json")
    predictions = _load_predictions(run_dir / "predictions.jsonl")
    expected = int(metadata["expected_examples"])
    if expected <= 0:
        raise ValueError("expected_examples must be positive")
    if len(predictions) > expected:
        raise ValueError("prediction count exceeds expected_examples")

    action_attempts: Counter[str] = Counter()
    phase_attempts: Counter[str] = Counter()
    trace_tool_calls: Counter[str] = Counter()
    termination_reasons: Counter[str] = Counter()
    phase_errors = {phase: Counter() for phase in PHASES}
    model_calls = model_responses = input_tokens = output_tokens = 0
    seed_paragraphs_from_trace = dynamic_paragraphs_from_trace = 0
    review_triggers_from_trace = 0
    max_steps_terminated = 0
    latency_ms = 0.0
    rate_limit_wait_ms = 0.0
    transport_retries = 0
    context_records = context_report_paragraphs = context_report_characters = 0
    context_assembled_paragraphs = context_full_report = context_local_truncations = 0
    provider_context_errors = 0
    context_request_records = estimated_input_tokens = 0
    actual_provider_input_records = actual_provider_input_tokens = 0
    context_windows: Counter[str] = Counter()
    prompt_budgets: Counter[str] = Counter()
    overflow_statuses: Counter[str] = Counter()
    legacy_context_limits: Counter[str] = Counter()
    long_context_injection_examples = long_context_injection_requests = 0
    long_context_injection_estimated_records = 0
    long_context_injection_estimated_tokens = 0
    long_context_injection_provider_records = 0
    long_context_injection_provider_tokens = 0
    long_context_injection_phases: Counter[str] = Counter()
    long_context_injection_attempts: Counter[str] = Counter()
    visibility_counts: Counter[str] = Counter()
    finish_reasons: Counter[str] = Counter()
    finoasis_exposed_by_skill: Counter[str] = Counter()
    finoasis_exposure_attempts = 0
    finoasis_failure_categories: Counter[str] = Counter()

    trace_files = sorted((run_dir / "traces").glob("*.jsonl"))
    for trace_path in trace_files:
        trace_seed_count: int | None = None
        trace_nonfull_context_count: int | None = None
        trace_long_context_injected = False
        with trace_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError(f"{trace_path.name}:{line_number} must be an object")
                event_name = event.get("event")
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    raise ValueError(
                        f"{trace_path.name}:{line_number} payload must be an object"
                    )
                if event_name == "model_request":
                    model_calls += 1
                    phase = payload.get("phase")
                    phase_attempts[str(phase) if phase in PHASES else "legacy"] += 1
                    available_skills = payload.get("available_skills")
                    if available_skills is not None:
                        if (
                            not isinstance(available_skills, list)
                            or len(available_skills) != len(set(available_skills))
                            or any(
                                not isinstance(skill, str)
                                or skill not in {item.value for item in SkillName}
                                for skill in available_skills
                            )
                        ):
                            raise ValueError(
                                f"{trace_path.name}:{line_number} has invalid v3 Skill exposure"
                            )
                        finoasis_exposure_attempts += 1
                        finoasis_exposed_by_skill.update(available_skills)
                    estimated = payload.get("estimated_input_tokens")
                    if type(estimated) is int and estimated >= 0:
                        context_request_records += 1
                        estimated_input_tokens += estimated
                        window = payload.get("model_context_window_tokens")
                        if type(window) is int and window > 0:
                            context_windows[str(window)] += 1
                        prompt_budget = payload.get("prompt_budget_tokens")
                        if type(prompt_budget) is int and prompt_budget > 0:
                            prompt_budgets[str(prompt_budget)] += 1
                        overflow_status = payload.get("overflow_status")
                        if overflow_status in {
                            "within_window", "estimated_overflow", "not_enforced"
                        }:
                            overflow_statuses[str(overflow_status)] += 1
                    injected = payload.get("long_context_injected", False)
                    if type(injected) is not bool:
                        raise ValueError(
                            f"{trace_path.name}:{line_number} has invalid long-context injection flag"
                        )
                    if injected:
                        trace_long_context_injected = True
                        long_context_injection_requests += 1
                        phase_name = str(phase) if phase in PHASES else "unknown"
                        long_context_injection_phases[phase_name] += 1
                        phase_attempt = payload.get("phase_attempt")
                        attempt_name = (
                            str(phase_attempt)
                            if type(phase_attempt) is int and phase_attempt >= 0
                            else "unknown"
                        )
                        long_context_injection_attempts[attempt_name] += 1
                        if type(estimated) is int and estimated >= 0:
                            long_context_injection_estimated_records += 1
                            long_context_injection_estimated_tokens += estimated
                    present_visibility = [
                        key for key in VISIBILITY_KEYS if key in payload
                    ]
                    if present_visibility:
                        if len(present_visibility) != len(VISIBILITY_KEYS) or any(
                            not _valid_id_list(payload.get(key))
                            for key in VISIBILITY_KEYS
                        ):
                            raise ValueError(
                                f"{trace_path.name}:{line_number} has invalid evidence visibility IDs"
                            )
                        ids = {key: list(payload[key]) for key in VISIBILITY_KEYS}
                        ledger = set(ids["ledger_evidence_ids"])
                        visible = set(ids["prompt_visible_evidence_ids"])
                        omitted = set(ids["prompt_omitted_evidence_ids"])
                        dynamic = set(ids["dynamic_ledger_evidence_ids"])
                        visible_dynamic = set(
                            ids["prompt_visible_dynamic_evidence_ids"]
                        )
                        if (
                            visible & omitted
                            or visible | omitted != ledger
                            or not dynamic <= ledger
                            or not visible_dynamic <= dynamic & visible
                        ):
                            raise ValueError(
                                f"{trace_path.name}:{line_number} has inconsistent evidence visibility IDs"
                            )
                        visibility_counts["instrumented_requests"] += 1
                        visibility_counts["ledger"] += len(ledger)
                        visibility_counts["visible"] += len(visible)
                        visibility_counts["omitted"] += len(omitted)
                        visibility_counts["dynamic_ledger"] += len(dynamic)
                        visibility_counts["dynamic_visible"] += len(visible_dynamic)
                elif event_name == "model_response":
                    model_responses += 1
                    input_tokens += int(payload.get("input_tokens", 0))
                    output_tokens += int(payload.get("output_tokens", 0))
                    latency_ms += float(payload.get("latency_ms", 0))
                    rate_limit_wait_ms += float(payload.get("rate_limit_wait_ms", 0))
                    transport_retries += int(payload.get("transport_retries", 0))
                    response_injected = payload.get("long_context_injected", False)
                    if type(response_injected) is not bool:
                        raise ValueError(
                            f"{trace_path.name}:{line_number} has invalid long-context injection flag"
                        )
                    actual_input = payload.get("actual_provider_input_tokens")
                    if type(actual_input) is int and actual_input >= 0:
                        actual_provider_input_records += 1
                        actual_provider_input_tokens += actual_input
                        if response_injected:
                            long_context_injection_provider_records += 1
                            long_context_injection_provider_tokens += actual_input
                    finish_reason = payload.get("finish_reason")
                    if finish_reason is not None:
                        if finish_reason not in FINISH_REASONS:
                            raise ValueError(
                                f"{trace_path.name}:{line_number} has unknown finish_reason"
                            )
                        finish_reasons[str(finish_reason)] += 1
                elif event_name == "action":
                    action_name = payload.get("action")
                    if isinstance(action_name, str):
                        action_attempts[action_name] += 1
                elif event_name == "tool_result":
                    skill = payload.get("skill")
                    if skill in TOOL_NAMES:
                        trace_tool_calls[str(skill)] += 1
                    elif {"expression", "result"}.issubset(payload):
                        trace_tool_calls["calculator"] += 1
                elif event_name == "retrieval_seed_loaded":
                    paragraph_ids = payload.get("paragraph_ids", [])
                    if isinstance(paragraph_ids, list):
                        trace_seed_count = len(paragraph_ids)
                elif event_name == "dynamic_evidence_loaded":
                    paragraph_ids = payload.get("paragraph_ids", [])
                    if isinstance(paragraph_ids, list):
                        dynamic_paragraphs_from_trace += len(paragraph_ids)
                elif event_name == "review_triggered":
                    review_triggers_from_trace += 1
                elif event_name == "recoverable_error":
                    phase = payload.get("phase")
                    phase_name = str(phase) if phase in PHASES else "legacy"
                    phase_errors[phase_name][_error_kind(payload)] += 1
                    error_text = payload.get("error")
                    if (
                        payload.get("error_type") == "model"
                        and isinstance(error_text, str)
                        and (
                            "context window" in error_text.casefold()
                            or "context length" in error_text.casefold()
                        )
                    ):
                        provider_context_errors += 1
                elif event_name == "runtime_error":
                    phase = payload.get("phase")
                    phase_name = str(phase) if phase in PHASES else "legacy"
                    phase_errors[phase_name][_error_kind(payload)] += 1
                    categories = payload.get("failure_categories", [])
                    if (
                        not isinstance(categories, list)
                        or len(categories) != len(set(categories))
                        or any(
                            not isinstance(category, str)
                            or category not in FINOASIS_FAILURE_CATEGORIES
                            for category in categories
                        )
                    ):
                        raise ValueError(
                            f"{trace_path.name}:{line_number} has invalid v3 failure categories"
                        )
                    finoasis_failure_categories.update(categories)
                elif event_name == "baseline_error":
                    phase_errors["baseline"][_error_kind(payload, baseline=True)] += 1
                    provider_context_errors += int(
                        payload.get("provider_context_error") is True
                    )
                elif event_name == "input_context":
                    context_records += 1
                    context_report_paragraphs += int(
                        payload.get("report_paragraph_count", 0)
                    )
                    context_report_characters += int(
                        payload.get("report_character_count", 0)
                    )
                    assembled = int(payload.get("assembled_paragraph_count", 0))
                    context_assembled_paragraphs += assembled
                    is_full = payload.get("full_report_assembled") is True
                    context_full_report += int(is_full)
                    context_local_truncations += int(
                        payload.get("local_truncation") is True
                    )
                    if not is_full:
                        trace_nonfull_context_count = assembled
                    limit = payload.get("model_context_limit")
                    if type(limit) is int and limit > 0:
                        legacy_context_limits[str(limit)] += 1
                elif event_name == "question_closed":
                    reason = payload.get("reason")
                    status = payload.get("status", "unknown")
                    if not isinstance(reason, str) or not reason:
                        reason = f"{status}_unspecified"
                    elif reason not in SAFE_TERMINATION_REASONS:
                        # Error strings may contain provider or task material.
                        reason = f"{status}_other"
                    termination_reasons[reason] += 1
                    if reason == "step budget exhausted":
                        max_steps_terminated += 1
        if trace_seed_count is not None:
            seed_paragraphs_from_trace += trace_seed_count
        elif trace_nonfull_context_count is not None:
            seed_paragraphs_from_trace += trace_nonfull_context_count
        long_context_injection_examples += int(trace_long_context_injected)

    state_files = sorted((run_dir / "state").glob("*.json"))
    state_tool_calls: Counter[str] = Counter()
    seed_paragraphs_from_state = dynamic_paragraphs_from_state = 0
    review_completed = review_triggered = review_fallbacks = review_label_changes = 0
    has_state_tool_metrics = False
    has_state_seed_metrics = False
    has_state_evidence_metrics = False
    has_state_review_metrics = False
    finoasis_states: list[FinOASISQuestionState] = []
    for state_path in state_files:
        state = _load_object(state_path)
        if state.get("schema_version") == 3:
            finoasis_states.append(FinOASISQuestionState.model_validate(state))
        tool_counts = state.get("tool_counts")
        if isinstance(tool_counts, dict):
            has_state_tool_metrics = True
            for tool in TOOL_NAMES:
                state_tool_calls[tool] += int(tool_counts.get(tool, 0))
        initial = state.get("initial_retrieval_state")
        if isinstance(initial, dict):
            has_state_seed_metrics = True
            paragraph_ids = initial.get("paragraph_ids", [])
            if isinstance(paragraph_ids, list):
                seed_paragraphs_from_state += len(paragraph_ids)
        evidence = state.get("evidence_ledger")
        if isinstance(evidence, list):
            has_state_evidence_metrics = True
            dynamic_paragraphs_from_state += sum(
                1
                for record in evidence
                if isinstance(record, dict)
                and not str(record.get("source", "report")).startswith("fixed_rag:")
            )
        if any(key.startswith("review_") for key in state):
            has_state_review_metrics = True
        review_completed += int(state.get("review_completed") is True)
        review_triggered += int(state.get("review_triggered") is True)
        review_fallbacks += int(state.get("review_fallback_used") is True)
        review_label_changes += int(state.get("review_changed_label") is True)

    tool_calls = state_tool_calls if has_state_tool_metrics else trace_tool_calls
    seed_paragraphs = (
        seed_paragraphs_from_state
        if has_state_seed_metrics
        else seed_paragraphs_from_trace
    )
    dynamic_paragraphs = (
        dynamic_paragraphs_from_state
        if has_state_evidence_metrics
        else dynamic_paragraphs_from_trace
    )
    if not has_state_review_metrics:
        review_triggered = review_triggers_from_trace

    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError("latency total must be finite and non-negative")
    if not math.isfinite(rate_limit_wait_ms) or rate_limit_wait_ms < 0:
        raise ValueError("rate-limit wait total must be finite and non-negative")
    if transport_retries < 0:
        raise ValueError("transport retry total must be non-negative")
    invalid = sum(
        1 for prediction in predictions if prediction.get("status") != "completed"
    )
    strict_valid = sum(1 for prediction in predictions if _strict_valid(prediction))
    exploration_attempts = phase_attempts["exploration"]
    if metadata.get("mode") == "agent":
        exploration_attempts += phase_attempts["legacy"]
    phase_error_output = {
        phase: {kind: int(phase_errors[phase].get(kind, 0)) for kind in ERROR_KINDS}
        for phase in PHASES
    }
    totals = {
        "steps": model_calls,
        "model_calls": model_calls,
        "model_responses": model_responses,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": round(latency_ms, 3),
        "rate_limit_wait_ms": round(rate_limit_wait_ms, 3),
        "transport_retries": transport_retries,
        "exploration_steps": exploration_attempts,
        "finalization_attempts": phase_attempts["finalization"],
        "review_attempts": phase_attempts["review"],
        "iterative_retrieval_attempts": phase_attempts["iterative_retrieval"],
        "search_calls": tool_calls["search_report"],
        "read_calls": tool_calls["read_paragraphs"],
        "calculator_calls": tool_calls["calculator"],
        "seed_paragraphs": seed_paragraphs,
        "dynamic_paragraphs": dynamic_paragraphs,
        "review_triggered": review_triggered,
        "review_completed": review_completed,
        "review_fallbacks": review_fallbacks,
        "review_label_changes": review_label_changes,
        "max_steps_terminated": max_steps_terminated,
        "action_attempts": dict(sorted(action_attempts.items())),
        "termination_reasons": dict(sorted(termination_reasons.items())),
        "phase_errors": phase_error_output,
        "finish_reason_counts": {
            reason: int(finish_reasons.get(reason, 0))
            for reason in FINISH_REASONS
        },
        "length_finish_reason_count": int(finish_reasons.get("length", 0)),
        "protocol_drift_count": sum(
            phase_errors[phase].get("protocol_drift", 0) for phase in PHASES
        ),
    }
    means = {
        "steps": _mean(model_calls, expected),
        "model_calls": _mean(model_calls, expected),
        "input_tokens": _mean(input_tokens, expected),
        "output_tokens": _mean(output_tokens, expected),
        "latency_ms": _mean(latency_ms, expected),
        "exploration_steps": _mean(exploration_attempts, expected),
        "finalization_attempts": _mean(phase_attempts["finalization"], expected),
        "review_attempts": _mean(phase_attempts["review"], expected),
        "iterative_retrieval_attempts": _mean(
            phase_attempts["iterative_retrieval"], expected
        ),
        "search_calls": _mean(tool_calls["search_report"], expected),
        "read_calls": _mean(tool_calls["read_paragraphs"], expected),
        "calculator_calls": _mean(tool_calls["calculator"], expected),
        "seed_paragraphs": _mean(seed_paragraphs, expected),
        "dynamic_paragraphs": _mean(dynamic_paragraphs, expected),
        "action_attempts": {
            name: _mean(count, expected)
            for name, count in sorted(action_attempts.items())
        },
        "review_completed": _mean(review_completed, expected),
        "max_steps_terminated": _mean(max_steps_terminated, expected),
    }
    summary: dict[str, Any] = {
        "schema_version": 2,
        "run": {
            key: metadata.get(key)
            for key in (
                "status",
                "mode",
                "model",
                "backend",
                "config_sha256",
                "public_tasks_sha256",
                "expected_examples",
                "completed_examples",
                "configured_concurrency",
                "effective_concurrency",
                "peak_concurrency",
                "wall_clock_duration_seconds",
            )
        },
        "execution": {
            "configured_concurrency": int(
                metadata.get("configured_concurrency", 1)
            ),
            "effective_concurrency": int(
                metadata.get("effective_concurrency", 1)
            ),
            "peak_concurrency": int(metadata.get("peak_concurrency", 1)),
            "wall_clock_duration_seconds": round(
                float(metadata.get("wall_clock_duration_seconds", 0.0)), 6
            ),
        },
        "rates": {
            "file_completion_rate": _mean(len(predictions), expected),
            "valid_output_rate": _mean(strict_valid, expected),
            "invalid_rate": _mean(invalid, expected),
            "review_trigger_rate": _mean(review_triggered, expected),
            "prediction_coverage": _mean(len(predictions), expected),
            "invalid": _mean(invalid, expected),
            "strict_valid": _mean(strict_valid, expected),
            "review_trigger": _mean(review_triggered, expected),
        },
        "totals": totals,
        "means_per_expected_example": means,
        "evidence_visibility": {
            "instrumented_model_requests": visibility_counts[
                "instrumented_requests"
            ],
            "ledger_request_occurrences": visibility_counts["ledger"],
            "visible_request_occurrences": visibility_counts["visible"],
            "omitted_request_occurrences": visibility_counts["omitted"],
            "dynamic_ledger_request_occurrences": visibility_counts[
                "dynamic_ledger"
            ],
            "dynamic_visible_request_occurrences": visibility_counts[
                "dynamic_visible"
            ],
            "overall_visibility_rate": (
                _mean(visibility_counts["visible"], visibility_counts["ledger"])
                if visibility_counts["ledger"]
                else 0.0
            ),
            "dynamic_visibility_rate": (
                _mean(
                    visibility_counts["dynamic_visible"],
                    visibility_counts["dynamic_ledger"],
                )
                if visibility_counts["dynamic_ledger"]
                else 0.0
            ),
        },
        "long_context": {
            "instrumented_examples": context_records,
            "instrumented_model_requests": context_request_records,
            "full_report_injection_examples": long_context_injection_examples,
            "full_report_injection_requests": long_context_injection_requests,
            "injection_phase_counts": dict(
                sorted(long_context_injection_phases.items())
            ),
            "injection_attempt_counts": dict(
                sorted(long_context_injection_attempts.items())
            ),
            "instrumented_injection_requests": (
                long_context_injection_estimated_records
            ),
            "mean_injection_estimated_input_tokens": (
                _mean(
                    long_context_injection_estimated_tokens,
                    long_context_injection_estimated_records,
                )
                if long_context_injection_estimated_records
                else 0.0
            ),
            "instrumented_injection_provider_responses": (
                long_context_injection_provider_records
            ),
            "mean_injection_actual_provider_input_tokens": (
                _mean(
                    long_context_injection_provider_tokens,
                    long_context_injection_provider_records,
                )
                if long_context_injection_provider_records
                else 0.0
            ),
            "mean_estimated_input_tokens": (
                _mean(estimated_input_tokens, context_request_records)
                if context_request_records
                else 0.0
            ),
            "instrumented_provider_responses": actual_provider_input_records,
            "mean_actual_provider_input_tokens": (
                _mean(actual_provider_input_tokens, actual_provider_input_records)
                if actual_provider_input_records
                else 0.0
            ),
            "configured_model_context_windows": dict(
                sorted(context_windows.items())
            ),
            "configured_prompt_budgets": dict(sorted(prompt_budgets.items())),
            "overflow_status_counts": dict(sorted(overflow_statuses.items())),
            "mean_report_paragraphs": (
                _mean(context_report_paragraphs, context_records)
                if context_records
                else 0.0
            ),
            "mean_report_characters": (
                _mean(context_report_characters, context_records)
                if context_records
                else 0.0
            ),
            "mean_assembled_paragraphs": (
                _mean(context_assembled_paragraphs, context_records)
                if context_records
                else 0.0
            ),
            "full_report_assembly_rate": (
                _mean(context_full_report, context_records)
                if context_records
                else 0.0
            ),
            "local_truncation_count": context_local_truncations,
            "provider_context_error_count": provider_context_errors,
            "legacy_configured_context_limits": dict(
                sorted(legacy_context_limits.items())
            ),
        },
    }
    if finoasis_states:
        summary["findoasis_v3"] = _finoasis_summary(
            finoasis_states,
            exposed_by_skill=finoasis_exposed_by_skill,
            exposure_attempts=finoasis_exposure_attempts,
            failure_categories=finoasis_failure_categories,
        )
    if input_cost_per_million is not None or output_cost_per_million is not None:
        if input_cost_per_million is None or output_cost_per_million is None:
            raise ValueError("both input and output prices are required")
        if input_cost_per_million < 0 or output_cost_per_million < 0:
            raise ValueError("prices must be non-negative")
        input_cost = input_tokens * input_cost_per_million / 1_000_000
        output_cost = output_tokens * output_cost_per_million / 1_000_000
        summary["estimated_cost_usd"] = {
            "input": round(input_cost, 8),
            "output": round(output_cost, 8),
            "total": round(input_cost + output_cost, 8),
            "input_per_million_tokens": input_cost_per_million,
            "output_per_million_tokens": output_cost_per_million,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    args = parser.parse_args()
    result = summarize(
        args.run_dir,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
