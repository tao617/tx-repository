# Model-B Stability Development Report

## Scope and provenance

This report records the prespecified five-condition, 700-example Model-B
`dev_feedback` stability round authorized under ADR 0008. It is development
evidence, not an official-test, hidden-set, or leaderboard claim. The completed
Model-A results and all earlier Model-B runs remain unchanged.

- Model: `qwen3.5-27b`
- Agent commit: `acaad7b81ecf6a520d736cfcc3c487de364c8c55`
- Private Scorer commit: `6ec34204193dce0e2ed7d8644c40b31d3b5598bc`
- Public task SHA256: `f51d29db5200c7166f74c9f7920ad8557d5db46a3b700f49513ef2932d1da0f5`
- Official retrieval source commit: `e8bb237def4ce555a606a45edba22666e31df248`
- Main plan SHA256: `a5d763015e04398f2224037c639ed9dd80575d1ea71c363fcb0823ce18a17660`
- BM25 plan SHA256: `2ea77b16ebc33a0e97ab0ca54547faab44de52540f10c8568446a44f6b810e07`
- Hybrid plan SHA256: `e206235d9f5ac8ec926e717da29ce41d2c40c0149573c58e816ac9781dedf1d9`
- Population: 700 examples per condition
- Generation: temperature 0, top-p 1, seed 7, maximum output 1,024 tokens
- Stable deployment: non-thinking JSON-object mode, 240 requests/minute,
  400,000 tokens/minute, and at most 10 transport retries
- Prompt/parser: BRAG10, BM25, Hybrid, and BLC use the unchanged
  `findver_cot_json` prompt and strict parser; M2 uses its frozen v2 action
  protocol and selective-review policy
- Hybrid: embedding Top-10 plus BM25 Top-10, RRF `k=60`, paragraph-ID
  deduplication, fused Top-10, then original document order
- Paired bootstrap: 10,000 resamples, seed 20260817, percentile 95% interval
- McNemar: two-sided exact binomial

The corrected matrix V2 was executed in the prespecified order: BRAG10, BM25,
Hybrid, M2, then BLC. All Runtime runs and sealed archives completed before any
networkless Private Scorer operation began. Only aggregate scorer values crossed
the private boundary.

The earlier matrix-V1 BRAG10 attempt remains an unscored local transport
diagnostic. Its 205 partial HTTP 422 rows were caused by the local Gateway schema;
none reached the upstream model, and none is included below.

## Runtime and accuracy

| Condition | Accuracy | Correct | Valid output | Mean calls | Mean input tokens | Mean output tokens | Recovered retries | Length finishes | Wall time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `BRAG10_FINDVER_COT` | 71.29% | 499/700 | 99.14% | 1.000 | 3,481.5 | 181.3 | 0 | 6 | 7.52 min |
| `BBM25_10` | 72.00% | 504/700 | 99.43% | 1.000 | 3,469.8 | 171.5 | 6 | 4 | 8.17 min |
| `BHYBRID_RRF10` | 74.29% | 520/700 | 99.14% | 1.000 | 3,529.6 | 184.2 | 16 | 6 | 8.15 min |
| `M2_SELECTIVE_REVIEW` | **81.71%** | **572/700** | **99.71%** | **2.971** | **13,519.5** | **542.8** | **43** | **5** | **26.46 min** |
| `BLC_FINDVER_COT` | 79.43% | 556/700 | 98.43% | 1.000 | 54,305.3 | 188.1 | 410 | 11 | 173.68 min |

The round made 4,880 model calls, received 4,880 successful responses, and used
54,813,965 input plus 887,580 output tokens. All 475 transient transport retries
recovered. Every condition completed 700/700 examples with zero terminal
transport failures, zero protocol drift, zero provider context errors, and zero
local truncations. There were 32 length-finished model responses and 29 invalid
final predictions. Every invalid prediction was retained as an experimental
failure and was not selectively rerun.

BLC's 410 recovered retries reflect repeated transient rate-limit pressure from
its much larger inputs. They materially increased wall time but did not become
terminal failures. Its 98.43% effective response rate is therefore reported
separately from transport recovery rather than hidden by successful completion.

Sealed submission SHA256 values are:

- `BRAG10_FINDVER_COT`: `9f925bcda3be7873d2180ae1db63cb79a6ac6896147c81305b1f0a38a21da36b`
- `BBM25_10`: `0c28809af31d47fc32da3d3c1488e716addaf8df7af5d3c6d88e11b600b1462a`
- `BHYBRID_RRF10`: `90491987ddec5756773ec468b48f52b197253c74c26b8327499c38f4628f0a28`
- `M2_SELECTIVE_REVIEW`: `c23f5c5dbdab07ac51956844f1c62be4a531155397406c0a45942470884706c0`
- `BLC_FINDVER_COT`: `08b609dacb3fcd2629c0c80fe3996abbe655b2365822f5d688069495d6211655`

## Paired comparisons

Differences are M2 minus the reference condition.

| Reference | Accuracy difference | Paired-bootstrap 95% CI | Exact p | M2-only correct | Reference-only correct |
|---|---:|---:|---:|---:|---:|
| `BRAG10_FINDVER_COT` | **+10.43 pp** | **[+7.14, +13.71]** | **9.91e-10** | 109 | 36 |
| `BHYBRID_RRF10` | **+7.43 pp** | **[+4.29, +10.71]** | **0.0000131** | 96 | 44 |
| `BBM25_10` | +9.71 pp | [+6.14, +13.14] | 9.23e-8 | 115 | 47 |
| `BLC_FINDVER_COT` | +2.29 pp | [-0.57, +5.29] | 0.1561 | 64 | 48 |

M2 is positive against BRAG10 in every subset: +12.0 points on IE, +4.0 on
knowledge, and +14.0 on numeric. It is also positive against Hybrid in every
subset: +6.4 points on IE, +2.0 on knowledge, and +12.8 on numeric. Against BLC,
M2 is lower on IE (-6.0) and knowledge (-2.0) but higher on numeric (+14.0),
yielding the nonsignificant +2.29-point overall difference.

## Stability and migration decision

The prespecified Model-B gate is satisfied:

1. The single-call baselines no longer have large-scale formatting or terminal
   transport failures; their effective response rates range from 98.43% to
   99.43%.
2. M2 remains clearly positive against both embedding BRAG10 and simple Hybrid,
   with positive paired intervals and significant exact McNemar results.
3. The 572/700 M2 result reproduces the previous stable Model-B correct count
   under the corrected shared deployment, while preserving a 99.71% effective
   response rate.

The second-model result therefore supports transfer of the primary accuracy
claim and rules out simple embedding/BM25 fusion as an adequate explanation on
development data. Proceed to a single V2 freeze/ADR before any official-test
execution. Do not tune retrieval, RRF, prompt, parser, generation, or controller
settings from these results. The official test remains unopened, and the project
contract remains unchanged pending explicit user authorization.
