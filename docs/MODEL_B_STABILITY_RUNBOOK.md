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

- Code commit: `f173bcb6f50cabcf3e433958aa680a7319cf9b5b`
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

| Selected conditions | Plan | SHA256 |
|---|---|---|
| BLC, BRAG10, M2 | `runs/plans/findver-model-b-stability-dev-v1.plan.json` | `2f0a8ab72a6ca818c337df12fc61a4fb611bcba651dbd414be8de85116350cb5` |
| BBM25_10 | `runs/plans/findver-model-b-dev-bm25-stable-v1.plan.json` | `b2807042131ec4e0578652cb79e633fa0a076dca97ee6193b090f4c1b089f7ae` |
| BHYBRID_RRF10 | `runs/plans/findver-model-b-dev-hybrid-rrf60-stable-v1.plan.json` | `4e72110cd3e47f4b267950594f7f4bfe1de89189d713c21007702dcf37a1e2f3` |

The first plan contains additional unselected rows because the canonical main-matrix
planner validates all seven methods. Their presence does not authorize execution.

## Execution gate

No model call is authorized by a tracked template or prepared plan. Obtain explicit user
approval for this five-condition development round before launch. Use `.env.agent` only;
`.env.agent.a` remains the Model-A credential file.

## Reporting gate

Before capability comparison, report for every condition:

- completed examples and strict valid-response rate;
- model calls and responses;
- transport retries and terminal errors;
- finish reasons, protocol drift, context errors, and local truncations;
- mean input/output tokens and wall-clock duration.

Do not use a failure-degraded row for capability comparison. The primary Model-B
direction checks are M2 versus BRAG10 and M2 versus Hybrid. BLC and BM25 are references.
