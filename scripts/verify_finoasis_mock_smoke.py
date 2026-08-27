#!/usr/bin/env python3
"""Verify the credential-free, four-path protocol-v3 Docker smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from findver_agent.findoasis.contracts import ObligationType, SkillName
from findver_agent.findoasis.state import FinOASISQuestionState
from findver_agent.runner import load_public_tasks


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _states(run_dir: Path) -> dict[str, FinOASISQuestionState]:
    values = [
        FinOASISQuestionState.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((run_dir / "state").glob("*.v3.json"))
    ]
    return {state.example_id: state for state in values}


def _events(run_dir: Path) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for path in sorted((run_dir / "traces").glob("*.jsonl")):
        records = _load_jsonl(path)
        if not records:
            raise ValueError(f"empty trace: {path.name}")
        example_id = records[0].get("example_id")
        if not isinstance(example_id, str) or example_id in result:
            raise ValueError("trace example IDs must be unique strings")
        result[example_id] = records
    return result


def verify(run_dir: Path, tasks_path: Path) -> None:
    tasks = load_public_tasks(tasks_path)
    expected_ids = [task.example_id for task in tasks]
    predictions = _load_jsonl(run_dir / "predictions.jsonl")
    if [item.get("example_id") for item in predictions] != expected_ids:
        raise ValueError("predictions are not in the four-task fixture order")
    if any(
        item.get("status") != "completed"
        or item.get("label") not in {"entailed", "refuted"}
        for item in predictions
    ):
        raise ValueError("every FinOASIS mock prediction must be complete and labeled")

    states = _states(run_dir)
    events = _events(run_dir)
    if set(states) != set(expected_ids) or set(events) != set(expected_ids):
        raise ValueError("state and trace populations must match the mock tasks")

    ie = states["finoasis-smoke-ie"]
    numeric = states["finoasis-smoke-numeric"]
    knowledge = states["finoasis-smoke-knowledge"]
    mixed = states["finoasis-smoke-mixed"]
    forbidden_ie_skills = {
        "read_table_region",
        "bind_financial_value",
        "execute_financial_program",
        "search_financial_rules",
        "read_financial_rules",
        "check_rule_applicability",
    }
    ie_exposures = [
        event["payload"]["available_skills"]
        for event in events[ie.example_id]
        if event.get("event") == "model_request"
    ]
    if any(set(exposure) & forbidden_ie_skills for exposure in ie_exposures):
        raise ValueError("IE-only mock exposed a Numeric or Knowledge Skill")

    numeric_final = numeric.final_verification_certificate_ledger[
        numeric.prediction_certificate_ref
    ]
    if not numeric_final.numeric_certificate_refs or numeric_final.rule_certificate_refs:
        raise ValueError("numeric mock did not finish with only a numeric certificate")
    if any(
        skill in numeric.skill_call_counts
        for skill in (
            SkillName.SEARCH_FINANCIAL_RULES,
            SkillName.READ_FINANCIAL_RULES,
            SkillName.CHECK_RULE_APPLICABILITY,
        )
    ):
        raise ValueError("numeric mock called a Knowledge Skill")

    knowledge_final = knowledge.final_verification_certificate_ledger[
        knowledge.prediction_certificate_ref
    ]
    if knowledge_final.numeric_certificate_refs or not knowledge_final.rule_certificate_refs:
        raise ValueError("knowledge mock did not finish with only a rule certificate")
    if SkillName.EXECUTE_FINANCIAL_PROGRAM in knowledge.skill_call_counts:
        raise ValueError("knowledge mock called FinDSL")

    mixed_types = {obligation.type for obligation in mixed.obligations}
    if not {
        ObligationType.NUMERIC_OPERATION,
        ObligationType.DOMAIN_RULE,
        ObligationType.RULE_APPLICABILITY,
    } <= mixed_types:
        raise ValueError("mixed mock did not seed both specialist obligation families")
    mixed_final = mixed.final_verification_certificate_ledger[
        mixed.prediction_certificate_ref
    ]
    if not mixed_final.numeric_certificate_refs or not mixed_final.rule_certificate_refs:
        raise ValueError("mixed final certificate did not bind both proof families")

    summary = json.loads(
        (run_dir / "efficiency-summary.json").read_text(encoding="utf-8")
    )
    v3 = summary.get("findoasis_v3")
    if not isinstance(v3, dict) or v3.get("instrumented_questions") != 4:
        raise ValueError("aggregate summary lacks four-question v3 instrumentation")
    if v3["numeric"]["program_execution_count"] != 2:
        raise ValueError("aggregate summary has the wrong FinDSL execution count")
    if v3["rules"]["applicability_checks"] != 2:
        raise ValueError("aggregate summary has the wrong applicability count")
    rendered = json.dumps(summary, ensure_ascii=False)
    if any(
        task.statement in rendered
        for task in tasks
    ) or "The exact report paragraph" in rendered:
        raise ValueError("aggregate summary leaked task or evidence text")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=Path)
    args = parser.parse_args()
    verify(args.run_dir, args.tasks)
    print("verified credential-free FinOASIS v3 Docker smoke")


if __name__ == "__main__":
    main()
