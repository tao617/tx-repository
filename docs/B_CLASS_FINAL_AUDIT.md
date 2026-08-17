# B-Class Final Audit

## Scope

This is the single final `ultra` audit required by the B-class upgrade plan. It was executed once on 2026-08-16 from commit `2f65c8f1b0d4189b7dae3c9b56afdbc7cc732943`, after all implementation phases and the Phase 5 Docker/mock checks. No paid API, second-model formal, top-k ablation, budget ablation, or `final_hidden` run was performed.

## Results

| # | Required check | Result | Verifiable evidence |
|---:|---|---|---|
| 1 | Runtime has no gold/subset/relevant-context/feedback leak | pass | Public validators accepted 700 main, 3 pilot, and 1 smoke records with exactly `example_id`, `statement`, and `report`; the Runtime context allowlist accepted 106 files. `explanation` remains only the required prediction/action field, not private gold explanation data. |
| 2 | Retrieval file contains no forbidden fields | pass | `FixedRetrievalIndex` recursively validated the official 700-record artifact and all report bounds; SHA256 is `2c29496e6762b3df2d51b01c246800b0512d396090785199d414703dbbf752e5`, retriever `text-embedding-3-large`, top-k 10. |
| 3 | Runtime added no unrestricted network, shell, Python, or file skill | pass | The complete skill allowlist is exactly `SearchReportSkill`, `ReadParagraphsSkill`, `CalculatorSkill`, and `SubmitAnswerSkill`. Runtime bundle validation passed; model traffic remains limited to the fixed Gateway backend. |
| 4 | Agent and Private Scorer remain isolated | pass | Agent and scorer use different repository/build roots, Compose project names, networks, and disjoint mount targets. Scorer retains `network_mode: none`, no ports/dependencies/Docker socket, and its unchanged offline suite passed 10/10. No Agent or Scorer container remained active. |
| 5 | Submission still contains exactly three files | pass | A new Mock API archive was sealed and verified at SHA256 `0b1b0ae34f43427730127719249aaa153d7525eb22966c7572b4649f78be6f55`; members were exactly `predictions.jsonl`, `manifest.json`, and `SHA256SUMS`. |
| 6 | Historical configs and formal results were not overwritten | pass | `git diff --quiet` against pre-upgrade commit `c3e9ebbcd5563f8bbc25cfac248d5931326f19ca` passed for B0/B1/B2/B3/A0/A1/A2 API configs, `docs/EXPERIMENT_REPORT.md`, and the frozen pilot/formal manifests. |
| 7 | RAG Seed consumes no exploration tool/model budget | pass | The real M2 Mock state loaded top-10 seed evidence while tool counts stayed search/read/calculator = 0 and the first exploration response was model call 1; retrieval/seed integration tests passed. |
| 8 | Finalization is independently reserved | pass | Phase-budget tests confirm exploration exhaustion transitions to submit-only Finalization, cannot consume its attempts, and supports retry before INVALID. |
| 9 | Review falls back to a valid draft | pass | Selective/mandatory/none tests confirm deterministic triggers, full draft validation, successful replacement, and fallback without INVALID on review error/exhaustion. |
| 10 | Old and new state behave as designed | pass | State tests confirm legacy v1 state loading, v2 initialization/budgets/counters, phase-bound resume, and rejection of protocol/retrieval identity changes. |
| 11 | Iterative RAG has no dynamic controller | pass | Its real Mock trace had exactly 3 configured retrieval requests followed by strict finalization, no review event, and 4 actual calls; tests confirm no adaptive early stop, controller, or non-submit final acceptance. |
| 12 | All old and new configs load | pass | Host tests load historical configs plus all 17 B-class configs. The rebuilt networkless Runtime image also loaded all 17 and its CLI help succeeded. |
| 13 | Mock API and Mock Local paths pass | pass | New runs `bclass-phase5-mock-api-dc0e011` and `bclass-phase5-mock-local-dc0e011` completed with one model call each; iterative entry run completed with four calls. Aggregate summaries were produced and credential markers were absent. |
| 14 | Compose isolation remains valid | pass | API and Local Agent Compose profiles and scorer Compose expanded successfully. Structural assertions verified separate projects/build contexts, Agent internal networking, scorer networklessness, disjoint mounts, no ports, and no Docker socket. |
| 15 | All tests pass | pass | 80 focused final-audit tests passed, followed by 158/158 full Agent tests. One pre-existing Starlette/httpx deprecation warning remains. |

## Post-audit hardening status

The table above remains the immutable evidence for the 2026-08-16 audit and is not retroactively rewritten by later work. The subsequent hardening series explicitly amended the project contract to allow one hash-bound, paragraph-ID-only ledger sidecar outside the three-file archive; bound formal run identity; prevented rejected actions from mutating control state; preserved dynamic prompt visibility; and separated the 32768-token prompt-construction budget from a hash-bound 100000-token B-class model capacity.

- Agent summaries now expose unambiguous primary rate names while retaining documented compatibility aliases.
- A deterministic nine-call M2 scenario, strict offline verifier, and public GitHub Actions jobs cover the stateful Docker path without real credentials.
- Post-fix user-side run `bclass-stateful-local-20260817-03` rebuilt both images and passed strict offline verification with eight actions, nine model calls, `review_fallback`, calculator-only persisted/draft risk, and no rejected-action pollution. The GitHub Actions result must still be observed on the exact pushed commit before public CI verification is claimed.
- Independent official `text-embedding-3-large` top-3 and top-5 outputs were imported from frozen FinDVer commit `e8bb237def4ce555a606a45edba22666e31df248`, validated against all 700 public tasks and reports, and wrapped without Gold or top-10 truncation.

## Outstanding external items

- The private evidence-metrics, paired-bootstrap, and McNemar adapter is not implemented in this Agent workspace. The separate Private Scorer was inspected read-only for isolation and regression only; no gold, scorer source, outputs, or feedback were copied here.
- Formal paid API, second-model, `dev_holdout`, and `final_hidden` evaluations require explicit authorization and frozen private manifests.
