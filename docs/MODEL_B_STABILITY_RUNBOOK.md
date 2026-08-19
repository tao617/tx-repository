# Model-B stability development round

## Scope

Run exactly five `dev_feedback` conditions with `qwen3.5-27b` under the shared
`qwen3_5_27b_dashscope_stable` deployment:

1. `BRAG10_FINDVER_COT`
2. `BBM25_10`
3. `BHYBRID_RRF10`
4. `M2_SELECTIVE_REVIEW`
5. `BLC_FINDVER_COT`

This order leaves the high-token BLC row last. Keep at least one provider quota window
between rows. Do not execute other main or extension conditions from the multi-row plan.
Do not open `dev_holdout` or official `test` data.

## Frozen implementation

- Stability implementation commit: `f173bcb6f50cabcf3e433958aa680a7319cf9b5b`
- Execution commit: the exact clean `HEAD` embedded in each regenerated plan
- Model ID: `qwen3.5-27b`
- Prompt, method settings, retrieval artifacts, generation settings, strict parser, and
  scorer: unchanged
- Response envelope: `json_object`
- Thinking: disabled
- Admission: 240 RPM and 400000 estimated TPM
- Transport retries: at most 10
- Expected calls: 2800 one-call requests plus approximately 2097 M2 requests, based on
  the existing Model-B M2 mean of 2.996 calls per example
- Protocol maximum: 9100 calls if every M2 example uses all nine allowed attempts

## Bound plans

| Selected conditions | Plan |
|---|---|
| BLC, BRAG10, M2 | `runs/plans/findver-model-b-stability-dev-v2.plan.json` |
| BBM25_10 | `runs/plans/findver-model-b-dev-bm25-stable-v1.plan.json` |
| BHYBRID_RRF10 | `runs/plans/findver-model-b-dev-hybrid-rrf60-stable-v1.plan.json` |

The first plan contains additional unselected rows because the canonical main-matrix
planner validates all seven methods. Their presence does not authorize execution.
Because execution requires an exact clean-HEAD match, regenerate these ignored plan
files after the final tracked planning commit and verify their SHA256 values before use.

## Execution gate

No model call is authorized by a tracked template or prepared plan. Obtain explicit user
approval for this five-condition development round before launch. Use `.env.agent` only;
`.env.agent.a` remains the Model-A credential file.

The user approved the five-condition round on 2026-08-19. The initial matrix-V1 BRAG10
launch was stopped after 205 local HTTP 422 responses caused by a missing gateway schema
field; none reached the upstream model. Do not resume or score that partial V1 run. Use
the corrected matrix-V2 plan for BRAG10, M2, and BLC.

## Reporting gate

Before capability comparison, report for every condition:

- completed examples and strict valid-response rate;
- model calls and responses;
- transport retries and terminal errors;
- finish reasons, protocol drift, context errors, and local truncations;
- mean input/output tokens and wall-clock duration.

Do not use a failure-degraded row for capability comparison. The primary Model-B
direction checks are M2 versus BRAG10 and M2 versus Hybrid. BLC and BM25 are references.
