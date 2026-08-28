import hashlib
import json
from pathlib import Path

import pytest
import yaml

from findver_agent.actions import ActionParseError, parse_action
from findver_agent.config import AgentConfig
from findver_agent.evidence_sidecar import (
    SIDECAR_NAME,
    SIDECAR_SCHEMA_VERSION,
    EvidenceLedgerRecord,
)
from findver_agent.findoasis.actions import parse_action as parse_v3_action
from findver_agent.model_backends.base import GenerationConfig
from findver_agent.prompt_builder import PromptBuilder
from findver_agent.schemas import Confidence, EvidenceStatus, PublicTask, RiskFlag
from findver_agent.state import (
    CalculationRecord,
    EvidenceRecord,
    QuestionState,
    SearchRecord,
)
from findver_agent.submission import ALLOWED_MEMBERS, SubmissionManifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_TEST_V2_SPEC = "experiments/official_test_v2_freeze.yaml"
OFFICIAL_TEST_V2_SPEC_SHA256 = (
    "962a42dec60324f8f672d0059e96e790954600904bccb654ec1da6436c859a46"
)
OFFICIAL_TEST_V2_ARTIFACT_SHA256 = {
    "configs/deployments/deepseek_v4_flash_api.yaml": (
        "60f89dbb49245261dc310bf41cc911c2e36c3bcad95fe1ad35dfb76c51bf2672"
    ),
    "configs/conditions/bclass/main/BRAG10_FINDVER_COT.yaml": (
        "9b6eb3bb90d93809600146faa3d43c0c62808656495e00fdd1dda1956ffd95b8"
    ),
    "configs/conditions/bclass/controls/BBM25_10.yaml": (
        "9ed227b29526fe6c5dd1ce1fe346b1a5480726d90b5f3c77d63ea4f1d5318dfb"
    ),
    "configs/conditions/bclass/controls/BHYBRID_RRF10.yaml": (
        "0b05e62ead4a6e6364e305a37ce336836ef69a562cc243b0f1d1b9d8dbd4fc1f"
    ),
    "configs/conditions/bclass/main/BLC_FINDVER_COT.yaml": (
        "d43e53bb3f575f478dccbb8281efdafc3eb9f4eebafe7966f14f20f57c1802a3"
    ),
    "configs/conditions/bclass/main/M2_SELECTIVE_REVIEW.yaml": (
        "591aa607ba313ed0996323200d198f0675bccc0fcc43d39f6e5a83329b995c94"
    ),
}
LEGACY_M2_CONFIG_SHA256 = {
    "configs/bclass/api/M2_SELECTIVE_REVIEW.yaml": (
        "18556167ecdc7e216bb27580f33925f52a884bcc931feff2bb4f7b2c515f36ae"
    ),
    "configs/bclass/local/M2_SELECTIVE_REVIEW.yaml": (
        "a3841139a69abe0a64bf3f638b6554464a7176bd20c1cb7b5e8bc659279043a7"
    ),
}
LEGACY_STATE_SNAPSHOT_SHA256 = {
    "v1": "f670810dd4abaf685dc88d64d79cd8cbfe02a3362c8a0b74406f0bd4c3a87325",
    "v2": "9f0a5a65a8368e775cc45e1afd73f3d38df1cd406ce784cbeda17094e599ad62",
}
LEGACY_PROMPT_SNAPSHOT_SHA256 = {
    "v1": "1e05e979a57a8df5b424446de3a12784f522afc1b9c809509b7b568c4a07886d",
    "v2": "2811bb1e0e7a38ae7f2454b1bf927361e727656b8e2683b04f9820a9149bdf60",
}


def _sha256_file(relative_path: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / relative_path).read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _legacy_state(protocol_version: str) -> QuestionState:
    task = PublicTask(
        example_id="compatibility-snapshot",
        statement="Revenue increased from 100 million to 120 million.",
        report="compatibility-report.json",
    )
    state = QuestionState.create(
        task,
        8,
        protocol_version=protocol_version,
        exploration_steps=6,
        finalization_steps=2,
        review_steps=1,
    )
    state.phase = "exploration"
    state.step = 2
    state.remaining_steps = 6 if protocol_version == "v1" else 7
    state.exploration_step = 2 if protocol_version == "v2" else 0
    state.evidence_status = EvidenceStatus.PARTIAL
    state.evidence_confidence = Confidence.MEDIUM
    state.risk_flags = [RiskFlag.RETRIEVAL_GAP]
    state.open_questions = ["Confirm the reporting period."]
    state.search_queries.append(
        SearchRecord(query="revenue 120 million", result_ids=[7, 9])
    )
    state.evidence_ledger.append(
        EvidenceRecord(
            paragraph_id=7,
            exact_text="Revenue increased from $100 million to $120 million in 2025.",
            reason_selected="Directly reports both values.",
            read_order=1,
        )
    )
    state.calculations.append(
        CalculationRecord(expression="(120-100)/100*100", result=20)
    )
    state.last_observation = {"kind": "read", "paragraph_ids": [7]}
    return state


def test_official_test_v2_spec_and_bound_artifact_hashes_are_frozen():
    assert _sha256_file(OFFICIAL_TEST_V2_SPEC) == OFFICIAL_TEST_V2_SPEC_SHA256

    specification = yaml.safe_load(
        (REPOSITORY_ROOT / OFFICIAL_TEST_V2_SPEC).read_text(encoding="utf-8")
    )
    assert specification["freeze_id"] == "findver-official-test-v2"
    assert specification["status"] == "frozen_not_prepared"
    assert specification["data"]["expected_examples"] == 1700
    assert specification["data"]["public_task_fields"] == [
        "example_id",
        "statement",
        "report",
    ]
    assert specification["model"]["deployment"] == (
        "configs/deployments/deepseek_v4_flash_api.yaml"
    )
    assert specification["model"]["deployment_sha256"] == (
        OFFICIAL_TEST_V2_ARTIFACT_SHA256[specification["model"]["deployment"]]
    )

    conditions = specification["conditions"]
    assert [(item["order"], item["condition_id"]) for item in conditions] == [
        (1, "BRAG10_FINDVER_COT"),
        (2, "BBM25_10"),
        (3, "BHYBRID_RRF10"),
        (4, "BLC_FINDVER_COT"),
        (5, "M2_SELECTIVE_REVIEW"),
    ]
    assert {
        item["config"]: item["config_sha256"] for item in conditions
    } == {
        path: digest
        for path, digest in OFFICIAL_TEST_V2_ARTIFACT_SHA256.items()
        if path.startswith("configs/conditions/")
    }
    assert conditions[-1]["config_sha256"] == (
        "591aa607ba313ed0996323200d198f0675bccc0fcc43d39f6e5a83329b995c94"
    )
    assert specification["execution_gates"] == {
        "official_input_access_authorized": False,
        "artifact_hashes_bound": False,
        "formal_plans_prepared": False,
        "api_calls_authorized": False,
        "score_only_after_all_rows_sealed": True,
    }
    assert {
        path: _sha256_file(path) for path in OFFICIAL_TEST_V2_ARTIFACT_SHA256
    } == OFFICIAL_TEST_V2_ARTIFACT_SHA256
    assert {
        path: _sha256_file(path) for path in LEGACY_M2_CONFIG_SHA256
    } == LEGACY_M2_CONFIG_SHA256


def test_sealed_archive_and_sidecar_schema_contract_are_frozen():
    assert ALLOWED_MEMBERS == (
        "predictions.jsonl",
        "manifest.json",
        "SHA256SUMS",
    )
    assert SIDECAR_NAME == "evidence-ledger.jsonl"
    assert SIDECAR_SCHEMA_VERSION == 1
    assert tuple(EvidenceLedgerRecord.model_fields) == (
        "example_id",
        "initial_rag_evidence_ids",
        "final_agent_evidence_ids",
    )
    assert EvidenceLedgerRecord(example_id="compatibility-record").model_dump() == {
        "example_id": "compatibility-record",
        "initial_rag_evidence_ids": [],
        "final_agent_evidence_ids": [],
    }

    record_schema = EvidenceLedgerRecord.model_json_schema()
    assert record_schema["additionalProperties"] is False
    assert record_schema["required"] == ["example_id"]
    assert set(record_schema["properties"]) == {
        "example_id",
        "initial_rag_evidence_ids",
        "final_agent_evidence_ids",
    }
    manifest_properties = SubmissionManifest.model_json_schema()["properties"]
    sidecar_hash_schema = manifest_properties["evidence_ledger_sidecar_sha256"]
    assert sidecar_hash_schema["default"] is None
    assert {"pattern": "^[a-f0-9]{64}$", "type": "string"} in (
        sidecar_hash_schema["anyOf"]
    )
    assert {"type": "null"} in sidecar_hash_schema["anyOf"]
    sidecar_version_schema = manifest_properties[
        "evidence_ledger_sidecar_schema_version"
    ]
    assert sidecar_version_schema["default"] is None
    assert {"const": 1, "type": "integer"} in sidecar_version_schema["anyOf"]
    assert {"type": "null"} in sidecar_version_schema["anyOf"]


def test_legacy_parsers_reject_a_valid_protocol_v3_action():
    action = json.dumps(
        {
            "action": "read_table_region",
            "arguments": {
                "table_id": "table-1",
                "row_indices": [0],
                "column_indices": [1],
            },
            "control": {
                "target_obligation_id": "obl-0001",
                "open_obligations": [],
                "obligation_deltas": [],
                "confidence": "medium",
                "risk_flags": ["table_alignment"],
                "expected_skill_effect": "Read the exact table cell.",
            },
        },
        separators=(",", ":"),
    )

    assert parse_v3_action(action).action == "read_table_region"
    for protocol_version in ("v1", "v2"):
        with pytest.raises(ActionParseError, match="invalid action"):
            parse_action(action, protocol_version=protocol_version)


@pytest.mark.parametrize("protocol_version", ["v1", "v2"])
def test_legacy_state_and_prompt_canonical_snapshots(protocol_version):
    state = _legacy_state(protocol_version)
    agent_config = (
        AgentConfig()
        if protocol_version == "v1"
        else AgentConfig(protocol_version="v2", review_policy="selective")
    )
    messages = PromptBuilder(
        GenerationConfig(prompt_budget_tokens=4096),
        agent_config,
    ).build(state)

    assert _canonical_sha256(state.model_dump(mode="json")) == (
        LEGACY_STATE_SNAPSHOT_SHA256[protocol_version]
    )
    assert _canonical_sha256(messages) == LEGACY_PROMPT_SNAPSHOT_SHA256[protocol_version]
