# ADR 0007: Prespecified BM25 and hybrid-RRF retrieval controls

- Status: Accepted
- Date: 2026-08-19

## Context

The completed 700-example development matrix shows M2 ahead of the embedding
Top-10 one-call baseline, but it does not isolate whether BM25 alone or a simple
embedding/BM25 mixture explains that result. The user authorized a staged plan
that first adds exactly these two retrieval controls on Model A, then repeats the
key stable comparison on Model B before any new official-test freeze.

The historical seven-condition matrix, its results, and its main/extension
configuration files must remain unchanged. The project contract also remains
unchanged. Real model execution still requires a separate approval immediately
before the API calls begin.

## Decision

1. Add `BBM25_10`, a one-call baseline using the official FinDVer BM25 Top-10
   ranking from source commit `e8bb237`.
2. Add `BHYBRID_RRF10`, a one-call baseline that takes the official
   `text-embedding-3-large` Top-10 and BM25 Top-10 ranked lists, assigns reciprocal
   rank scores with the fixed constant `k=60`, sums scores after paragraph-ID
   deduplication, and retains the fused Top-10.
3. Resolve exact RRF ties deterministically by best source rank, worst source
   rank, and paragraph ID. After selection, order both controls by original
   paragraph ID before prompt construction.
4. Use exactly the BRAG10 prompt profile, generation settings, strict action
   parser, scorer contract, one-call budget, and concurrency. Only the frozen
   retrieval artifact and retriever identity differ.
5. Build the development artifacts only from Gold-free public tasks, reports,
   and official ranked retrieval outputs. Store no scores, labels, Gold,
   feedback, or scorer data in Runtime artifacts.
6. Bind each control in its own schema-v3 plan because formal run identity has
   one plan-level retrieval hash. Preserve the old main and extension plans
   rather than adding the controls to completed matrices.
7. Keep the tracked manifest `execution_authorized: false`. Do not launch either
   700-example Model-A row until the user gives the required pre-experiment
   approval.

## Continuation rule

- If M2 clearly exceeds Hybrid, proceed to the planned Model-B stability stage.
- If M2 and Hybrid are close, retain the experiment but describe the contribution
  as a hybrid-retrieval plus controlled evidence-recovery system.
- If Hybrid exceeds M2, stop before official test and revisit the method framing.

No development result may be used to change `k`, input/output cutoffs, tie rules,
prompt, or generation settings.

## Consequences

- The new controls directly address BM25/embedding confounding without rerunning
  the completed A_SCRATCH, M0, M1, BITER2, M2, or other development rows.
- Hybrid provenance is explicit and reproducible, while Runtime still sees only
  paragraph IDs and report text.
- A later official-test V2 ADR and plan remain necessary. This ADR does not open
  `dev_holdout`, `final_hidden`, or the 1,700-example official test.
