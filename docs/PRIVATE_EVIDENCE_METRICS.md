# Private Evidence Analysis Contract

## Boundary and implementation status

This contract is for a separate, networkless Private Scorer or scorer-side analysis process. The Agent Runtime must never receive the analysis input, gold labels, gold evidence, scorer code, per-example comparisons, or scorer output. Only an output conforming to the aggregate schema may leave the scorer boundary.

The implementation is complete in the separate, networkless Private Scorer repository at commit `37aad0d`. That repository, its private inputs, and its outputs remain outside this Agent workspace and Runtime build context. This repository continues to carry only the metric definitions and adapter schemas.

The schemas are:

- `docs/private_metrics/evidence_analysis_input.schema.json`: private, per-example scorer input; never copied into the Runtime or a public result.
- `docs/private_metrics/evidence_analysis_output.schema.json`: aggregate-only output permitted to cross the scorer boundary.

For Agent runs, `evidence-ledger.jsonl` is transferred beside, not inside, the sealed submission. It contains only `example_id`, `initial_rag_evidence_ids`, and `final_agent_evidence_ids`. The sealed manifest binds its schema version and SHA256. Handoff rejects a missing, unexpected, malformed, population-mismatched, or hash-mismatched sidecar. The scorer-side adapter combines this non-Gold ID-only artifact with private Gold only after the runtime has stopped.

The private input deliberately contains no statement text, report text, explanation text, or model trace. It binds candidate and strongest-baseline labels, evidence ID sets, document length, frozen retrieval identity, and statistical settings for one paired population.

## Evidence sets and primary metrics

For example `i`, define:

- `G_i`: all annotated gold evidence paragraph IDs;
- `P_i`: paragraph IDs cited in the candidate's final submitted answer;
- `S_i`: paragraph IDs in the frozen initial RAG seed;
- `L_i`: all paragraph IDs read into the Agent's final evidence ledger, including the seed.

All sets are deduplicated before calculation. An invalid or missing candidate has an empty `P_i`; its `L_i` may contain evidence read before failure. Examples with an empty gold-evidence set are excluded from recall-based metrics and reported through the metric denominator. No denominator-zero metric is replaced with zero: its value is `null`.

Primary evidence metrics use the following deterministic definitions:

```text
precision_i = |P_i intersect G_i| / |P_i|
recall_i    = |P_i intersect G_i| / |G_i|
f1_i        = 2 * precision_i * recall_i / (precision_i + recall_i)
```

`Evidence Precision`, `Evidence Recall`, and `Evidence F1` are macro means over eligible examples. An empty submitted set has precision and F1 equal to zero when gold evidence exists. `All-Gold Evidence Recall` is the fraction of recall-eligible examples for which `G_i` is a subset of `P_i`.

```text
Initial RAG Recall          = mean_i |S_i intersect G_i| / |G_i|
Final Agent Evidence Recall = mean_i |L_i intersect G_i| / |G_i|
Evidence Recovery Rate      = sum_i |(L_i intersect G_i) minus S_i|
                              -------------------------------------
                              sum_i |G_i minus S_i|
```

The recovery numerator therefore counts gold paragraphs found by the final Agent ledger that were absent from the frozen seed. The denominator counts all gold paragraphs missed by the seed. The output includes both counts and returns a `null` rate when the denominator is zero.

## Conditional correctness

Correctness means exact equality between the candidate prediction label and private gold label; missing or invalid labels are incorrect. The scorer reports aggregate counts and rates for these mutually defined conditions:

- `recovered_evidence`: `|(L_i intersect G_i) minus S_i| > 0`;
- `full_initial_recall`: `G_i` is a subset of `S_i`;
- `partial_initial_recall`: initial recall is strictly between zero and one;
- `zero_initial_recall`: `S_i intersect G_i` is empty.

The required outputs are `P(correct | recovered evidence)`, `P(correct | full initial recall)`, `P(correct | partial initial recall)`, and `P(correct | zero initial recall)`, represented as aggregate numerator, denominator, and nullable rate.

## Paired statistical interface

Candidate and strongest-baseline records must be paired by the same private `example_id` population before calculation. Hash mismatches, duplicate IDs, missing pairs, or different populations fail closed.

Paired bootstrap uses example-level paired resampling with replacement, an explicit seed, an explicit resample count, and a fixed 95% percentile interval. The output records the candidate-minus-baseline point difference, lower and upper bounds, seed, and resample count. At minimum, accuracy and the primary evidence F1 comparison are supported when both systems provide the necessary evidence.

McNemar uses the paired label-correctness table. The output records candidate-correct/baseline-wrong and candidate-wrong/baseline-correct discordant counts, a two-sided exact-binomial p-value, and the corresponding statistic. No per-example correctness value is emitted.

## Reserved long-context groups

Document length groups are configured privately using explicit paragraph-count cutoffs for `short`, `medium`, and `long`. Evidence positions are derived from `(paragraph_id + 0.5) / document_paragraph_count` into `front`, `middle`, and `back` thirds. An example with gold evidence in multiple thirds may contribute to multiple position groups; this must be stated in the aggregate output metadata.

The isolated adapter implements these aggregate groups. This does not authorize a synthetic long-context study or a paid evaluation run.
