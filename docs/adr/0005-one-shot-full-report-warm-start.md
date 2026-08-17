# ADR 0005: One-shot full-report warm start

- Status: Accepted
- Date: 2026-08-17

## Context

The completed Model-A development matrix contains a one-call full-report baseline,
a one-call embedding Top-10 baseline, a scratch Agent, and a Top-10-seeded Agent.
It does not measure whether one initial view of the complete report can improve the
existing budget-aware Agent without repeatedly paying the full-report context cost.

The Model-A development protocol is already frozen. The user authorized implementation
and offline verification of exactly one additional post-hoc exploratory condition, but
did not authorize a paid model run, Private Scorer run, holdout run, or hidden run.

## Decision

Add `LC_AGENT_FIRSTPASS` as an isolated Model-A `dev_feedback` extension with these
semantics:

1. Start from the scratch protocol-v2 Agent shape: six Exploration attempts, two
   reserved Finalization attempts, one selective Review attempt, the existing four
   Runtime actions, and no initial retrieval seed.
2. Include the complete report only in the first durably charged Exploration attempt.
   The report is never included in later Exploration, Finalization, or Review attempts.
3. Preserve at-most-once request semantics across resume. Transient transport retries
   inside the same model attempt reuse the identical messages. A model, parse, protocol,
   or skill failure consumes the charged attempt and does not cause reinjection in the
   next Agent attempt.
4. Serialize the report with the exact shared BLC paragraph representation and stable
   zero-based paragraph IDs. Full-report paragraphs are preview-only and are not added
   to the evidence ledger. A paragraph becomes legal final evidence only after an
   accepted `read_paragraphs` action adds it to the ledger.
5. Persist only bounded injection identity and status in per-question state. Do not
   persist a second copy of the report. The evidence-ledger sidecar remains schema v1;
   `initial_rag_evidence_ids` is empty and `final_agent_evidence_ids` contains only the
   formal ledger.
6. Record aggregate-safe injection, report-shape, context-estimate, overflow, and
   provider-usage telemetry. Traces remain inside the Agent run and are never added to
   the sealed submission or scorer handoff.
7. Implement the condition under the extension configuration and planner paths. Do not
   append it to or rename the frozen seven-condition main matrix.

## Comparison semantics

- `LC_AGENT_FIRSTPASS` versus `A_SCRATCH` estimates the incremental effect of the
  one-shot full-report warm start.
- `LC_AGENT_FIRSTPASS` versus `M2_SELECTIVE_REVIEW` compares two operational
  initialization strategies, but also differs in pinned-ledger seeding and prompt cost.
- `LC_AGENT_FIRSTPASS` versus `BLC_FINDVER_COT` compares complete system paths, not a
  pure controller effect under continuously identical context.
- Any difference-in-differences interaction is descriptive only. The conditions are
  not a strict causal two-by-two factorial because the Agent sees the full report only
  in its first attempt.

The extension does not alter the frozen M2-versus-BLC primary comparison, the five-test
Holm family, the selected M2 primary candidate, or existing results. It cannot replace
M2 or enter the current confirmatory holdout protocol based on `dev_feedback` results.

## Frozen feasibility and continuation rules

Before any separately authorized paid run, an exact-prompt offline preflight must cover
all 700 tasks with zero estimated 100,000-token context overflows. A completed run is
feasible only if it has:

- 700/700 file completion and at least 99 percent valid output;
- zero local truncations and zero provider context errors;
- exactly one full-report injection per example and none in Finalization or Review;
- no more than 46,376,030 provider-reported input tokens, five times the completed M2
  total.

It is eligible only for a separately frozen future exploratory study if all of the
following hold on `dev_feedback`: accuracy is at least 1.0 percentage point above M2;
the paired-bootstrap 95 percent interval lower bound is greater than -1.0 percentage
point; and submitted Evidence F1 is no more than 1.0 percentage point below M2. Long
document subgroup gains remain research leads and cannot change the current protocol.

## Consequences

- The experiment tests a practical warm-start policy at roughly one full-report charge
  per example instead of one per Agent call.
- Information visible in the preview can guide a read, search, or calculation, but it
  cannot bypass the formal evidence ledger.
- At-most-once injection can skip reinjection after a crash around request dispatch;
  this matches the existing durable-attempt semantics and avoids ambiguous duplicate
  model calls.
- A real execution, scorer change, holdout use, or hidden use still requires explicit
  authorization after implementation, testing, checkpointing, and a new hash-bound
  prepared plan.

## Rejected alternatives

- Repeat the full report on every Agent call: materially increases cost and overflow
  risk and changes the intended one-shot question.
- Reinject until the first accepted action: makes the number of full-report requests
  depend on formatting and skill failures and weakens the cost bound.
- Preload the whole report into the ledger: destroys the distinction between visible
  context and formally read evidence.
- Add the condition to the frozen main matrix or Holm family: changes a protocol whose
  existing development results have already been read.
