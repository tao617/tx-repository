# ADR 0009: Model-A official-test V2 confirmation freeze

- Status: Accepted
- Date: 2026-08-19

## Context

The original frozen protocol in `docs/EXPERIMENT_PLAN.md` names BLC as the sole
primary accuracy comparator for M2. That record remains valid historical V1 and
must not be overwritten. Subsequent prespecified development controls established
that M2 exceeds simple embedding/BM25 RRF on Model A and on a stable Model B, while
the Model-B one-call baselines now have normal effective-response rates. The user
therefore authorized one new V2 freeze record before the 1,700-example official
test confirmation.

This authorization is for the freeze record only. It does not authorize access to
the official-test inputs, artifact construction from those inputs, model calls,
Private Scorer execution, or a project-contract change.

## Decision

1. Preserve the V1 plan and all completed development results unchanged. Add the
   separate V2 plan in `docs/OFFICIAL_TEST_V2_FREEZE_PLAN.md` and the structured,
   non-executing specification in `experiments/official_test_v2_freeze.yaml`.
2. Freeze the core confirmation to Model A with exact upstream model ID
   `deepseek-v4-flash` and deployment `deepseek_v4_flash_api`. The five and only
   five official-test conditions are BRAG10, BM25 Top-10, Hybrid RRF Top-10, BLC,
   and M2.
3. Freeze M2 versus BRAG10 as the sole primary accuracy comparison. Use a
   two-sided exact McNemar test at alpha 0.05 and report the M2-minus-BRAG10
   accuracy difference with a 10,000-resample paired-bootstrap 95% interval.
4. Freeze M2 versus Hybrid as the key secondary retrieval-control comparison,
   using the same paired estimates and exact test but making no additional primary
   type-I-error claim. M2 versus BLC and M2 versus BM25 are secondary/descriptive.
5. Keep Evidence Precision/Recall/F1, seed recall, final-ledger recall, and evidence
   recovery as aggregate supportive endpoints. They may qualify the system
   interpretation when M2 and Hybrid are close, but they cannot replace or redefine
   the primary accuracy endpoint after results are seen.
6. Freeze the data source to `yilunzhao/FinDVer` commit
   `e8bb237def4ce555a606a45edba22666e31df248` and an exact 1,700-example public-task
   population. Before any model call, bind the task, report corpus, embedding
   Top-10, BM25 Top-10, and derived Hybrid artifacts by SHA256 in non-executing
   schema-v3 plans. Runtime receives only the contract-allowed public task fields.
7. Freeze Hybrid to embedding Top-10 plus BM25 Top-10, RRF `k=60`, the ADR 0007
   deterministic tie rule, paragraph-ID deduplication, fused Top-10, and final
   document order. No Gold may be used during artifact construction or validation.
8. Freeze temperature 0, top-p 1, seed 7, maximum output 1,024 tokens,
   prompt-construction budget 32,768, concurrency 32, disabled thinking, existing
   prompt profiles, strict parsers, method budgets, prediction schema, and scorer
   contract. The Private Scorer implementation is pinned to commit
   `6ec34204193dce0e2ed7d8644c40b31d3b5598bc` unless a separately reviewed
   security-only successor is explicitly approved before input access.
9. Name the immutable Git ref `findver-official-test-v2-freeze`. The ref is created
   on the focused commit containing this ADR, the V2 plan, and its specification.
   Every prepared execution plan must bind the ref's resolved full commit SHA; a
   moved, missing, or mismatched ref invalidates preparation.
10. Execute no official-test row until the exact input hashes and five selected plan
    rows have passed offline recomposition on the frozen ref and the user has given
    a separate pre-experiment API approval. All five Runtime rows must complete and
    seal before aggregate scoring is read.
11. Treat missing and invalid predictions as wrong. Infrastructure interruption may
    resume only the identical hash-bound run. Do not selectively rerun invalid
    examples, repair model output, change a ceiling, or tune any method from official
    results.

## Interpretation rule

- A positive M2-minus-BRAG10 estimate is required for the primary direction claim;
  exact p below 0.05 supports a confirmatory significance statement. A positive but
  nonsignificant result is reported as uncertain rather than retuned.
- A positive M2-minus-Hybrid estimate supports the adaptive evidence-recovery
  interpretation. If their accuracies are close, evidence-quality aggregates may
  support a broader hybrid-retrieval plus controlled-recovery system claim.
- If Hybrid exceeds M2 without a compensating evidence-quality advantage, weaken the
  method claim and report the frozen result. Do not reopen the official test for
  method revision.

## Consequences

- The official-test main comparison differs from historical V1 without rewriting V1.
- A complete confirmation needs only five Model-A rows; A_SCRATCH, M0, M1, BITER,
  top-k, and budget studies remain development evidence.
- An optional Model-B official-test extension is outside this freeze and requires its
  own plan and authorization.
- Exact official input hashes are deliberately absent until the separate input-binding
  step. Their absence blocks execution rather than weakening the freeze.
- The project contract remains byte-for-byte unchanged.

## Rejected alternatives

- Change the old V1 primary comparator in place: this would erase experiment history.
- Add all development ablations to official test: this increases cost and creates
  avoidable multiplicity without addressing the three stated goals.
- Select retrieval cutoffs, RRF parameters, prompts, or budgets from official results:
  this converts the confirmation set into another development set.
- Score conditions as they finish and decide whether to continue: this permits
  outcome-dependent stopping.
