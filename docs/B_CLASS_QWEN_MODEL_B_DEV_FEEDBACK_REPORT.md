# B-Class Qwen Model-B Development Report

## Scope and provenance

This report records aggregate-only `dev_feedback` results for the seven main
Qwen Model-B conditions and four previously approved parity extensions. It is
development evidence, not a holdout, hidden-set, leaderboard, or production
claim. Neither `dev_holdout` nor `final_hidden` was used.

- Model: `qwen3.5-27b` through DashScope
- Agent commit bound into every run: `c2d3073ee0ee3de06476ff61869ec9ad08e6fb3c`
- Private Scorer commit: `6ec34204193dce0e2ed7d8644c40b31d3b5598bc`
- Main formal-plan SHA256: `400dd0ced81eb08aec71f6c4d0bb9b9958ab7999853bda99bed1d56fc06af0a2`
- Top-3 plan SHA256: `44acb71055aece58d73d220b65cd16afb13e09dc3c1caa081c08c1de1b9f7719`
- Top-5 plan SHA256: `ad3949bea66edbf464f9887b188f200003b3a8e3f9fe521bbb348fc13d808a1d`
- BITER2 plan SHA256: `25294403653721089064803f370302dfe9c247d279a6b2dabffd6372bcbab1ac`
- Budget-4 plan SHA256: `ad4c27fb42479f12eedea51b92dea5a373a591dcee1c1c4c274fbfe764ce0535`
- Public task SHA256: `f51d29db5200c7166f74c9f7920ad8557d5db46a3b700f49513ef2932d1da0f5`
- Top-3 retrieval SHA256: `4c85f4cc3ea07c45ae6320032f0bad34b6f095aa8751a84f3ca0fe423e5ac8d7`
- Top-5 retrieval SHA256: `78bce403b92d96858df689c15fb9afc3dd6b19a139d57b953e391ccb2f7d358d`
- Top-10 retrieval SHA256: `2c29496e6762b3df2d51b01c246800b0512d396090785199d414703dbbf752e5`
- Population: 700 examples per condition; 7,700 submitted predictions total
- Generation: temperature 0, top-p 1, seed 7, maximum output 1,024 tokens
- Transport: `dashscope_openai_chat`, thinking disabled, 100K model context,
  32 configured workers, 540 requests/minute, and 850,000 tokens/minute
- Paired bootstrap: 10,000 resamples, seed 20260817, percentile 95% interval
- McNemar: two-sided exact binomial

The 11 frozen runs made 22,970 model calls and recorded 113,006,779 input and
3,252,882 output tokens. All predictions were sealed and independently
verified before scoring. Accuracy, evidence quality, and paired analyses ran
inside the networkless Private Scorer; only aggregate values crossed the
scorer boundary. No per-example feedback was produced or returned to Runtime.

The scorer's public manifest validator initially lacked the already-frozen
DashScope transport profile and paired RPM/TPM identity fields. The validator
was extended without changing scoring logic, Gold, or predictions, covered by
30 passing scorer tests, and committed before any Qwen aggregate was accepted.

## Qwen results and execution cost

| Condition | Accuracy | Correct | Valid output | Mean calls | Mean input tokens | Mean output tokens | Wall time |
|---|---:|---:|---:|---:|---:|---:|---:|
| `BLC_FINDVER_COT` | 45.29% | 317/700 | 56.43% | 1.000 | 51,238.6 | 169.7 | 82.82 min |
| `BRAG10_FINDVER_COT` | 48.29% | 338/700 | 70.71% | 1.000 | 2,662.6 | 124.5 | 6.39 min |
| `BITER_RAG10` | 79.29% | 555/700 | 99.43% | 4.021 | 17,158.2 | 328.7 | 17.39 min |
| `A_SCRATCH` | 79.00% | 553/700 | 99.86% | 5.730 | 10,613.4 | 823.2 | 14.04 min |
| `M0_RAG10_SEEDED` | 80.29% | 562/700 | 99.29% | 2.306 | 9,041.9 | 186.9 | 8.56 min |
| `M1_BUDGET_AWARE` | 81.29% | 569/700 | 99.86% | 2.546 | 11,873.5 | 434.7 | 10.66 min |
| `M2_SELECTIVE_REVIEW` | **81.71%** | **572/700** | 99.86% | 2.996 | 13,738.4 | 533.5 | 12.69 min |
| `RAG3_SEEDED` | 77.86% | 545/700 | 100.00% | 3.971 | 9,741.6 | 657.7 | 10.60 min |
| `RAG5_SEEDED` | 78.43% | 549/700 | 99.71% | 3.477 | 10,571.3 | 594.9 | 10.59 min |
| `BITER2_RAG10` | 78.71% | 551/700 | 99.29% | 3.019 | 12,507.1 | 292.9 | 12.38 min |
| `M2_BUDGET4` | 81.14% | 568/700 | 99.71% | 2.749 | 12,291.6 | 500.5 | 11.44 min |

M2 is the Qwen point-estimate leader. Its selective-review trigger rate was
47.71%; 332 reviews completed, two used the frozen fallback, and nine changed
the submitted label. All 11 runs had zero disabled-thinking protocol drift,
zero provider context errors, and zero local truncations.

The two one-call paths are execution outliers. BLC had 305 failed model
responses, 333 transport retries, and 31.10 aggregate hours of rate-limit wait;
BRAG10 had 205 failed model responses and 88 retries. Their conditional
accuracies among valid outputs were 80.25% (317/395) and 68.28% (338/495), but
formal accuracy correctly counts every invalid output against the 700-example
denominator. These rows must therefore not be read as clean capability-only
comparisons. They were retained as observed, with no paid retry or prompt/parser
tuning after results.

## Same-condition comparison with Model A

Candidate-minus-baseline differences below are Qwen minus Model A. Exact p
values are unadjusted and descriptive across the 11 comparisons.

| Condition | Qwen | Model A | Difference | Paired-bootstrap 95% CI | Exact p |
|---|---:|---:|---:|---:|---:|
| `BLC_FINDVER_COT` | 45.29% | 79.71% | -34.43 pp | [-38.43, -30.29] | <1e-51 |
| `BRAG10_FINDVER_COT` | 48.29% | 74.71% | -26.43 pp | [-30.43, -22.57] | <1e-35 |
| `BITER_RAG10` | 79.29% | 76.57% | +2.71 pp | [-0.57, +6.00] | 0.123775 |
| `A_SCRATCH` | 79.00% | 79.86% | -0.86 pp | [-3.86, +2.14] | 0.645497 |
| `M0_RAG10_SEEDED` | 80.29% | 79.57% | +0.71 pp | [-2.43, +3.86] | 0.720673 |
| `M1_BUDGET_AWARE` | 81.29% | 79.71% | +1.57 pp | [-1.43, +4.43] | 0.338185 |
| `M2_SELECTIVE_REVIEW` | 81.71% | 82.29% | -0.57 pp | [-3.43, +2.29] | 0.772989 |
| `RAG3_SEEDED` | 77.86% | 79.43% | -1.57 pp | [-4.57, +1.29] | 0.342581 |
| `RAG5_SEEDED` | 78.43% | 80.86% | -2.43 pp | [-5.43, +0.43] | 0.125005 |
| `BITER2_RAG10` | 78.71% | 75.86% | +2.86 pp | [-0.57, +6.29] | 0.120529 |
| `M2_BUDGET4` | 81.14% | 81.29% | -0.14 pp | [-3.00, +2.71] | 1.000000 |

Apart from the two degraded one-call rows, every same-condition interval
contains zero. The principal M2 comparison is close: Qwen is four examples
behind Model A, with 52 Qwen-only correct and 56 Model-A-only correct examples.
By subset, Qwen M2 is +0.4 pp on IE and +1.2 pp on numeric, but -4.0 pp on
knowledge. This is evidence of comparable development performance for the
Agent paths, not proof of equivalence and not a hidden-set result.

## Frozen Qwen method comparisons

The previously frozen development comparison structure was applied within
Qwen. M2 versus BLC is the primary method contrast. The five secondary
comparators use a Holm step-down family; this analysis remains descriptive
because `dev_feedback` has already been read.

M2 minus BLC is +36.43 pp with a 95% interval of [+32.29, +40.43], exact
p<1e-54, 281 M2-only correct examples, and 26 BLC-only correct examples. The
effect includes BLC's failed responses and therefore measures the deployed
method as run, not reasoning quality alone.

| Comparator | M2 difference | Paired-bootstrap 95% CI | Exact p | Holm p | M2-only | Comparator-only |
|---|---:|---:|---:|---:|---:|---:|
| `BRAG10_FINDVER_COT` | +33.43 pp | [+29.43, +37.29] | <1e-51 | <1e-50 | 255 | 21 |
| `BITER2_RAG10` | +3.00 pp | [0.00, +5.86] | 0.050442 | 0.201769 | 63 | 42 |
| `A_SCRATCH` | +2.71 pp | [0.00, +5.43] | 0.067052 | 0.201769 | 58 | 39 |
| `M0_RAG10_SEEDED` | +1.43 pp | [-0.71, +3.57] | 0.252854 | 0.505709 | 36 | 26 |
| `M1_BUDGET_AWARE` | +0.43 pp | [-0.86, +1.71] | 0.647606 | 0.647606 | 11 | 8 |

Only M2 versus BRAG10 survives the five-comparison Holm correction, and that
result is dominated by BRAG10's incomplete outputs. Among the robust Agent
paths, M2 has the highest point estimate but no corrected pair establishes a
clear advantage.

## Exploratory sensitivity analyses

| Candidate versus reference | Accuracy difference | Paired-bootstrap 95% CI | Exact p |
|---|---:|---:|---:|
| `RAG3_SEEDED` versus M2 | -3.86 pp | [-6.29, -1.43] | 0.002118 |
| `RAG5_SEEDED` versus M2 | -3.29 pp | [-5.43, -1.14] | 0.003202 |
| `M2_BUDGET4` versus M2 | -0.57 pp | [-1.71, +0.57] | 0.454498 |
| `BITER2_RAG10` versus BITER3 | -0.57 pp | [-1.43, +0.14] | 0.289062 |

For Qwen, both reduced seed sets significantly underperform Top-10 M2 on this
development set. Budget-4 reduces model calls by 8.25%, input tokens by 10.53%,
output tokens by 6.18%, and wall time by 9.80%, at a non-significant 0.57-point
accuracy loss. BITER2 reduces calls by 24.94%, input tokens by 27.11%, and wall
time by 28.82% relative to BITER3, also at a non-significant 0.57-point loss.
No additional top-k, BITER-round, or exploration-budget tuning is authorized
from these results.

## Evidence analysis against Qwen BLC

Evidence metrics are aggregate, estimation-only analyses. `A_SCRATCH` has no
initial retrieval, so initial recall and recovery rate are not defined for that
row.

| Candidate | Submitted F1 | F1 difference | Paired-bootstrap 95% CI | Initial recall | Final Agent recall | Recovery rate |
|---|---:|---:|---:|---:|---:|---:|
| `A_SCRATCH` | 53.34% | +23.79 pp | [+20.67, +26.91] | n/a | 58.63% | n/a |
| `M0_RAG10_SEEDED` | 54.88% | +25.33 pp | [+22.24, +28.41] | 68.01% | 73.45% | 16.69% |
| `M1_BUDGET_AWARE` | **55.19%** | +25.64 pp | [+22.56, +28.72] | 68.01% | 73.93% | 18.45% |
| `M2_SELECTIVE_REVIEW` | 55.07% | +25.52 pp | [+22.45, +28.56] | 68.01% | **74.00%** | **18.72%** |
| `RAG3_SEEDED` | 53.63% | +24.08 pp | [+21.03, +27.17] | 43.60% | 60.42% | 29.56% |
| `RAG5_SEEDED` | 53.03% | +23.48 pp | [+20.46, +26.47] | 54.53% | 64.89% | 23.05% |
| `M2_BUDGET4` | 54.81% | +25.26 pp | [+22.19, +28.32] | 68.01% | 73.25% | 16.42% |

M1 has the highest submitted-evidence F1 by 0.12 pp over M2, while M2 has the
highest final evidence recall and recovery rate among the Top-10 Agent rows.
Budget-4 preserves nearly all submitted F1 but recovers fewer initially missed
Gold paragraphs. Accuracy conditional on recovered evidence was 81.42% for M2
(92/113), compared with 82.18% for Budget-4 (83/101); the denominators differ,
so this conditional statistic is not a paired accuracy claim.

## Decision

M2 remains the Qwen primary operating point: it has the best accuracy point
estimate, near-parity with Model A under the same condition, and the strongest
final evidence recall. M1 is a credible lower-call alternative, and Budget-4
is the clearest lower-cost operating point. BITER2 is attractive when latency
and call count dominate, but it is not promoted over M2.

The Qwen one-call paths require a separately authorized transport-reliability
investigation before they can serve as fair capability baselines. The observed
formal rows remain immutable and will not be silently repaired. No Qwen
`dev_holdout` or `final_hidden` run follows from this report; either requires a
new frozen plan and explicit authorization.
