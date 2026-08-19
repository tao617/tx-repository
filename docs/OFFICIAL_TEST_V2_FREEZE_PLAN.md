# Official Test V2 Freeze Plan

## Status and boundary

`findver-official-test-v2` is frozen but not prepared or authorized for execution.
It is a new record under ADR 0009. The historical V1 plan in
`docs/EXPERIMENT_PLAN.md` remains unchanged.

This plan authorizes no official-test access, model call, scorer run, or contract
change. The next permitted step is a Gold-free, read-only input-binding preflight
after separate user authorization. API execution requires another explicit approval
after that preflight has produced exact hashes and non-executing plans.

## Frozen provenance

| Item | Frozen value |
|---|---|
| Freeze ID | `findver-official-test-v2` |
| Immutable Git ref | `findver-official-test-v2-freeze` |
| Runtime code commit | Full SHA resolved from the immutable ref |
| Data source | `yilunzhao/FinDVer` commit `e8bb237def4ce555a606a45edba22666e31df248` |
| Population | Exactly 1,700 official-test examples |
| Model | Model A, exact ID `deepseek-v4-flash` |
| Deployment | `configs/deployments/deepseek_v4_flash_api.yaml`, SHA256 `60f89dbb49245261dc310bf41cc911c2e36c3bcad95fe1ad35dfb76c51bf2672` |
| Scorer | Private Scorer commit `6ec34204193dce0e2ed7d8644c40b31d3b5598bc` |
| Generation | temperature 0, top-p 1, seed 7, max output 1,024 |
| Runtime limits | prompt budget 32,768; context capacity 100,000; concurrency 32 |
| Transport | `deepseek_openai_chat`, thinking disabled, maximum 3 transport retries |
| Execution state | `frozen_not_prepared`; `execution_authorized: false` |

The final prepared plans must add exact SHA256 values for the 1,700-row public-task
file, report corpus identity, embedding Top-10, BM25 Top-10, and Hybrid RRF Top-10.
Those are mechanical provenance bindings, not parameters available for selection.

## Five-condition matrix

Execute in this fixed order after approval:

| Order | Condition | Retrieval | Calls per example |
|---:|---|---|---:|
| 1 | `BRAG10_FINDVER_COT` | official embedding Top-10 | 1 |
| 2 | `BBM25_10` | official BM25 Top-10 | 1 |
| 3 | `BHYBRID_RRF10` | fixed Hybrid RRF Top-10 | 1 |
| 4 | `BLC_FINDVER_COT` | full report | 1 |
| 5 | `M2_SELECTIVE_REVIEW` | official embedding Top-10 seed | maximum 9, actual reported |

No A_SCRATCH, M0, M1, BITER, top-k, budget, LC, or other development condition is
part of the official-test matrix. The four one-call rows require 6,800 calls. M2's
actual calls are data-dependent within its unchanged 6/2/1 budget and must be
reported rather than estimated as a fixed online budget.

Frozen condition files and current SHA256 values are:

| Condition | Configuration | SHA256 |
|---|---|---|
| BLC | `configs/conditions/bclass/main/BLC_FINDVER_COT.yaml` | `d43e53bb3f575f478dccbb8281efdafc3eb9f4eebafe7966f14f20f57c1802a3` |
| BRAG10 | `configs/conditions/bclass/main/BRAG10_FINDVER_COT.yaml` | `9b6eb3bb90d93809600146faa3d43c0c62808656495e00fdd1dda1956ffd95b8` |
| BM25 | `configs/conditions/bclass/controls/BBM25_10.yaml` | `9ed227b29526fe6c5dd1ce1fe346b1a5480726d90b5f3c77d63ea4f1d5318dfb` |
| Hybrid | `configs/conditions/bclass/controls/BHYBRID_RRF10.yaml` | `0b05e62ead4a6e6364e305a37ce336836ef69a562cc243b0f1d1b9d8dbd4fc1f` |
| M2 | `configs/conditions/bclass/main/M2_SELECTIVE_REVIEW.yaml` | `591aa607ba313ed0996323200d198f0675bccc0fcc43d39f6e5a83329b995c94` |

Hybrid is fixed to embedding Top-10 plus BM25 Top-10 with RRF `k=60`. Rank scores
are summed after paragraph-ID deduplication; exact ties use best source rank, worst
source rank, then paragraph ID. The selected Top-10 is finally sorted into original
document order. Gold is neither an input nor a validator.

## Hypotheses and statistics

### Primary

`M2_SELECTIVE_REVIEW` versus `BRAG10_FINDVER_COT` on Accuracy. Report the absolute
paired difference in percentage points, a 10,000-resample paired-bootstrap 95%
interval with seed 20260817, and a two-sided exact McNemar p-value at alpha 0.05.
The direction claim requires M2's point estimate to be positive.

### Key secondary control

M2 versus `BHYBRID_RRF10`, using the same paired difference, bootstrap interval, and
exact McNemar calculation. This comparison tests whether simple mixed retrieval is
an adequate explanation. It is labeled key secondary and does not replace the sole
primary test.

### Other secondary/descriptive comparisons

- M2 versus `BLC_FINDVER_COT` as the long-context system reference.
- M2 versus `BBM25_10` as the retrieval ablation.

Report their paired differences, intervals, and exact p-values without presenting
them as additional primary claims. Existing development-only ablations retain their
previous Holm treatment or appendix status and are not rerun on official test.

### Supportive evidence endpoints

Report aggregate Evidence Precision, Recall, and F1; seed recall; final-ledger
recall; and evidence recovery rate. Evidence quality may refine the M2-versus-Hybrid
system interpretation but cannot redefine Accuracy or select a new method.

## Execution and anti-peeking gates

Before any model call, all of the following must hold:

1. The immutable freeze ref exists and resolves to the commit used by every plan.
2. The tracked worktree is clean; the contract, deployment, conditions, prompts,
   parser, generation, RRF rule, and scorer pin match this record.
3. The Gold-free public task file contains exactly 1,700 unique ordered examples and
   only `example_id`, `statement`, and `report`.
4. Task, reports, embedding, BM25, and Hybrid artifacts have exact recorded hashes,
   matching populations, valid paragraph ranges, and source commit `e8bb237`.
5. The formal plan set selects exactly the five rows above, is
   `prepared_not_executed`, binds all condition/deployment/effective-config hashes,
   and passes offline executor recomposition without a model credential.
6. No Agent or Scorer container is running, the scorer inbox is empty, and a separate
   user approval explicitly authorizes the Model-A API calls.

Run all five Runtime rows, summarize, seal, and independently verify them before any
official-test aggregate score is read. Scoring begins only after Agent/Gateway cleanup.
The scorer runs networkless and releases only aggregate outputs. A transport-level
interruption may resume the identical bound run; invalid model outputs remain wrong
and are never selected for rerun.

## Frozen reporting table

For each condition report:

- Accuracy and absolute difference from BRAG10;
- valid-response, invalid, and file-completion rates;
- mean and total model calls;
- mean and total input/output tokens, latency, and provider cost under a tariff
  snapshot recorded before execution;
- recovered and terminal transport failures, finish reasons, protocol drift,
  context errors, and local truncations;
- the supportive evidence metrics applicable to that condition.

The manuscript decision is made from the frozen outcomes, not by changing the
system. A positive primary result supports transfer to official test. M2 above Hybrid
supports the adaptive recovery interpretation; close accuracy with stronger evidence
supports the broader hybrid-retrieval plus controlled-recovery framing. Hybrid above
M2 without an evidence advantage weakens the method claim and is reported as-is.

## Explicit exclusions

- No method, prompt, parser, retrieval cutoff, RRF constant, tie rule, output ceiling,
  controller budget, review trigger, or scorer change after official input access.
- No official-test per-example feedback or development iteration.
- No optional Model-B official-test rows in this freeze.
- No project-contract modification.
