# B-Class Model A Development Report

## Scope and provenance

This report records aggregate-only `dev_feedback` results for the seven main
Model A conditions and the four approved development extensions. It is
development evidence, not a holdout, hidden-set, or leaderboard claim.

- Model: `deepseek-v4-flash`
- Main-condition Agent commit: `c6e203777629e8ceb31d00c5e60bd1fad4d2ed12`
- Top-3 Agent commit: `0233a48f9a03d82ac92d1971aa17148da6b8f8d`
- Top-5 and BITER2 Agent commit: `863700392f942a3542df8d161f66511ec6640f6b`
- Budget-4 Agent commit: `2ce96aa51ae422b66db143f892a88d359db1776e`
- Private Scorer commit: `4bbcc70b3ab362b04743f7527d4d8ffe6acb8f8d`
- Public task SHA256: `f51d29db5200c7166f74c9f7920ad8557d5db46a3b700f49513ef2932d1da0f5`
- Population: 700 examples per condition
- Generation: temperature 0, top-p 1, seed 7, maximum output 1024 tokens
- Transport: API profile `deepseek_v4_openai`, thinking disabled, concurrency 32
- Paired bootstrap: 10,000 resamples, seed 20260817, percentile 95% interval
- McNemar: two-sided exact binomial

All accuracy, evidence-quality, and paired analyses were produced inside the
networkless Private Scorer. Only aggregate values crossed the scorer boundary.

## Seven main conditions

| Condition | Accuracy | Correct | Valid output | Mean calls | Mean input tokens | Mean output tokens |
|---|---:|---:|---:|---:|---:|---:|
| `BLC_FINDVER_COT` | 79.71% | 558/700 | 99.29% | 1.000 | 49,214.9 | 107.3 |
| `BRAG10_FINDVER_COT` | 74.71% | 523/700 | 99.86% | 1.000 | 3,045.2 | 101.7 |
| `BITER_RAG10` | 76.57% | 536/700 | 100.00% | 4.001 | 15,070.9 | 226.2 |
| `A_SCRATCH` | 79.86% | 559/700 | 99.86% | 5.620 | 9,445.3 | 572.3 |
| `M0_RAG10_SEEDED` | 79.57% | 557/700 | 100.00% | 2.269 | 7,825.2 | 131.9 |
| `M1_BUDGET_AWARE` | 79.71% | 558/700 | 100.00% | 2.581 | 10,796.0 | 270.9 |
| `M2_SELECTIVE_REVIEW` | **82.29%** | **576/700** | **100.00%** | 3.260 | 13,250.3 | 374.2 |

M2 is the development-set point-estimate leader. Its selective-review trigger
rate was 66.14%; it completed 463 reviews and changed 18 labels. There were no
length finishes or disabled-thinking protocol drifts.

## Approved extensions

| Condition | Accuracy | Correct | Valid output | Mean calls | Mean input tokens | Mean output tokens |
|---|---:|---:|---:|---:|---:|---:|
| `RAG3_SEEDED` | 79.43% | 556/700 | 99.71% | 4.014 | 8,835.0 | 430.5 |
| `RAG5_SEEDED` | 80.86% | 566/700 | 99.86% | 3.591 | 9,900.2 | 395.1 |
| `BITER2_RAG10` | 75.86% | 531/700 | 100.00% | 3.003 | 10,924.8 | 191.2 |
| `M2_BUDGET4` | 81.29% | 569/700 | 100.00% | 3.026 | 12,004.1 | 355.8 |

Top-3 lost accuracy and increased Agent calls because weaker seed coverage
caused more dynamic exploration and review. Top-5 recovered part of that loss
but did not exceed M2. BITER2 matched M2's average call count more closely than
BITER3 but remained substantially less accurate. Budget-4 reduced M2 calls by
7.19%, input tokens by 9.40%, and output tokens by 4.92%, with a one-point
accuracy reduction whose interval includes zero.

## Frozen holdout comparisons

The protocol is frozen before any holdout result is read. The sole primary
candidate is M2, the sole primary comparator is BLC, and accuracy is the primary
endpoint. The primary test is two-sided exact McNemar at alpha 0.05; its paired
bootstrap interval is the effect estimate. Because this is one hypothesis, it
has no multiplicity adjustment.

On the current development data, M2 minus BLC is +2.57 percentage points with a
95% interval of [-0.57, +5.57], exact p=0.126510, 71 M2-only correct examples,
and 53 BLC-only correct examples. The point estimate favors M2, but the primary
development comparison is not statistically significant.

The five frozen secondary method comparisons form one Holm step-down family at
familywise alpha 0.05. These adjusted development results are descriptive of
the already-read development set; the same frozen family will be used on
holdout.

| Comparator | M2 difference | Paired-bootstrap 95% CI | Exact p | Holm p | M2-only | Comparator-only |
|---|---:|---:|---:|---:|---:|---:|
| `BRAG10_FINDVER_COT` | +7.57 pp | [+4.29, +10.86] | 0.000009 | 0.000047 | 97 | 44 |
| `BITER2_RAG10` | +6.43 pp | [+3.43, +9.43] | 0.000070 | 0.000281 | 85 | 40 |
| `A_SCRATCH` | +2.43 pp | [-0.29, +5.14] | 0.107352 | 0.111557 | 58 | 41 |
| `M0_RAG10_SEEDED` | +2.71 pp | [0.00, +5.43] | 0.055778 | 0.111557 | 54 | 35 |
| `M1_BUDGET_AWARE` | +2.57 pp | [+0.57, +4.57] | 0.019834 | 0.059503 | 36 | 18 |

Only M2 versus BRAG10 and M2 versus BITER2 survive the frozen five-comparison
Holm correction on development data.

## Exploratory sensitivity analyses

Top-k, budget, and BITER-round calibration are outside the confirmatory family.

| Candidate versus reference | Accuracy difference | Paired-bootstrap 95% CI | Exact p |
|---|---:|---:|---:|
| `RAG3_SEEDED` versus M2 | -2.86 pp | [-5.29, -0.43] | 0.030786 |
| `RAG5_SEEDED` versus M2 | -1.43 pp | [-3.57, +0.86] | 0.260435 |
| `M2_BUDGET4` versus M2 | -1.00 pp | [-2.86, +1.00] | 0.401062 |
| `BITER2_RAG10` versus BITER3 | -0.71 pp | [-2.57, +1.14] | 0.551484 |

Top-3's loss is concentrated in the IE subset (-7.6 pp versus M2). Top-5 is
lower on IE (-2.8 pp) and knowledge (-4.0 pp) but higher on numeric (+2.0 pp).
Budget-4 is lower on IE (-1.6 pp) and knowledge (-2.0 pp) and essentially tied
on numeric (+0.4 pp). BITER2 and BITER3 tie on IE and numeric; the point loss is
knowledge (-2.5 pp). No further BITER round tuning is permitted.

## Evidence analysis against BLC

Evidence metrics and all subgroup analyses are estimation-only; they do not
create additional confirmatory hypotheses.

| Candidate | Submitted F1 | F1 difference | Paired-bootstrap 95% CI | Initial RAG recall | Final Agent recall | Recovery rate |
|---|---:|---:|---:|---:|---:|---:|
| `RAG3_SEEDED` | 54.84% | +4.77 pp | [+2.17, +7.45] | 43.60% | 62.08% | 32.49% (399/1,228) |
| `RAG5_SEEDED` | 55.43% | +5.36 pp | [+2.83, +7.93] | 54.53% | 68.08% | 29.87% (302/1,011) |
| `M2_SELECTIVE_REVIEW` | 56.00% | +5.93 pp | [+3.45, +8.47] | 68.01% | 76.01% | 25.51% (188/737) |
| `M2_BUDGET4` | 56.00% | +5.93 pp | [+3.38, +8.53] | 68.01% | 75.10% | 22.80% (168/737) |

M2 submitted-evidence precision was 55.23% and recall was 62.88%. Accuracy
conditional on recovered Gold evidence was 90.00% (135/150). Budget-4 retained
nearly identical submitted Evidence F1 while recovering fewer initially missed
Gold paragraphs; its conditional accuracy on recovered evidence was 88.72%
(118/133).

## Budget and protocol decisions

M2 used more than four Exploration calls on 107/700 examples (15.29%), which
justified the budget-4 sensitivity run. Only 39/700 examples (5.57%) entered
Finalization after six Exploration calls, and none reached a max-step
termination. Budget 8 therefore has too small an affected population for the
additional paid development run and is not authorized.

M2 remains the frozen primary method because it has the highest accuracy point
estimate. Budget-4 is retained as a lower-cost operating point, not as the
primary candidate. BLC remains the primary baseline because it is the strongest
one-call condition. The calibrated two-round BITER replaces BITER3 in the
secondary comparison family because it is closer to M2's actual call budget;
the BITER2-versus-BITER3 calibration stays exploratory.

No further Model-A top-k, BITER-round, or exploration-budget development tuning
is planned before holdout. Model B, `dev_holdout`, and `final_hidden` remain
unrun and require their separately frozen inputs and authorization.
