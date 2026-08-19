# Model-A Retrieval Controls Development Report

## Scope and provenance

This report records the two prespecified 700-example `dev_feedback` retrieval
controls authorized under ADR 0007. It is development evidence, not a holdout,
official-test, hidden-set, or leaderboard claim. No completed historical row was
rerun or changed.

- Model: `deepseek-v4-flash`
- Agent commit: `12e6550a81b8afb7be3d492ef2835c87cb8db19d`
- Private Scorer commit: `6ec34204193dce0e2ed7d8644c40b31d3b5598bc`
- Public task SHA256: `f51d29db5200c7166f74c9f7920ad8557d5db46a3b700f49513ef2932d1da0f5`
- Official retrieval source commit: `e8bb237def4ce555a606a45edba22666e31df248`
- BM25 artifact SHA256: `a34a46867967ab2d213669b1d3b4d1bad6bfd5bf634864be05a075ef56a0d45c`
- Hybrid artifact SHA256: `6b32ed0fda3eb0ddc11da83932bee06c0dd4fb62001bbafbcc764bd48986b365`
- BM25 plan SHA256: `21ed7f824ec5a2b991aae2a8ee2202a8e9137414dbc7c5d5802a8dfee4abc757`
- Hybrid plan SHA256: `656f00f366ab2f42bfe367204d4dfdc5244295995ead395db49c8c48bba2a406`
- Population: 700 examples per condition
- Generation: temperature 0, top-p 1, seed 7, maximum output 1,024 tokens
- Prompt/parser: exactly the BRAG10 `findver_cot_json` profile and strict action parser
- Hybrid: embedding Top-10 plus BM25 Top-10, RRF `k=60`, deduplicated fused Top-10,
  then original document order
- Paired bootstrap: 10,000 resamples, seed 20260817, percentile 95% interval
- McNemar: two-sided exact binomial

Both runs used the fixed Model Gateway boundary and completed before any
networkless Private Scorer operation began. Only aggregate scorer values crossed
the private boundary.

## Runtime and accuracy

| Condition | Accuracy | Correct | Valid output | Mean calls | Mean input tokens | Mean output tokens | Transport retries | Wall time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `BRAG10_FINDVER_COT` | 74.71% | 523/700 | 99.86% | 1.000 | 3,045.2 | 101.7 | — | — |
| `BBM25_10` | 74.00% | 518/700 | 100.00% | 1.000 | 3,195.1 | 100.8 | 0 | 35.74 s |
| `BHYBRID_RRF10` | 77.71% | 544/700 | 100.00% | 1.000 | 3,152.7 | 100.6 | 0 | 35.89 s |
| `M2_SELECTIVE_REVIEW` | **82.29%** | **576/700** | **100.00%** | 3.260 | 13,250.3 | 374.2 | — | — |

The two new rows made exactly 1,400 model calls and received 1,400 successful
responses. Both had 700 `stop` finishes, zero invalid outputs, zero length
finishes, zero protocol drift, zero provider context errors, and zero local
truncations. Their sealed submission SHA256 values are:

- `BBM25_10`: `1b2e331a5d1f59a7c3f35fe80b90740a0a6cbe9df0ba4f1400d94c7c58f96acd`
- `BHYBRID_RRF10`: `a67312b66166b1e748943e49670b3049caa8cb9e55d2d67ada04354f71b4052e`

## Paired comparisons

Differences are row candidate minus reference.

| Candidate versus reference | Accuracy difference | Paired-bootstrap 95% CI | Exact p | Candidate-only | Reference-only |
|---|---:|---:|---:|---:|---:|
| `M2` versus `BHYBRID_RRF10` | **+4.57 pp** | **[+1.43, +7.71]** | **0.005536** | 79 | 47 |
| `M2` versus `BBM25_10` | +8.29 pp | [+5.00, +11.71] | 0.00000339 | 106 | 48 |
| `BHYBRID_RRF10` versus `BRAG10` | +3.00 pp | [+0.43, +5.57] | 0.027534 | 52 | 31 |
| `BHYBRID_RRF10` versus `BBM25_10` | +3.71 pp | [+1.00, +6.43] | 0.009548 | 60 | 34 |
| `BBM25_10` versus `BRAG10` | -0.71 pp | [-4.00, +2.57] | 0.734539 | 67 | 72 |

M2 exceeds Hybrid on IE by 3.6 points and numeric by 9.2 points; the two tie on
knowledge at 82.0%. BM25 alone is not stronger than embedding BRAG10. Hybrid is
stronger than either single retriever, but it remains clearly below M2.

## Decision

The prespecified continuation criterion is satisfied: M2 clearly outperforms
the simple embedding/BM25 Hybrid on accuracy, with a positive paired interval
and significant exact McNemar result. The adaptive evidence-recovery argument
therefore remains the primary method interpretation on development data.

Proceed to the planned Model-B stability stage. Do not open or run the official
test yet, and do not tune the retrieval cutoffs, RRF constant, tie rule, prompt,
or generation settings from these results.
