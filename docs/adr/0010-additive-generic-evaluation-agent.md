# ADR 0010: Additive generic evaluation Agent with static skill profiles

- Status: Accepted
- Date: 2026-08-24

## Context

The existing Runtime is a strong bounded evidence-verification Agent but its public
task, action, prompt, state, prediction, and scoring contracts are FinDVer-specific.
The user requested a general testing Agent that keeps the same Exploration,
Finalization, and Review reasoning framework while allowing the model to choose among
skills appropriate to other task families.

Changing the existing FinDVer action names or prediction schema would invalidate
historical comparisons. Allowing YAML to import arbitrary Python tools would also
weaken the Runtime boundary and make a task file capable of changing executable code.

## Decision

1. Keep the existing `findver-agent` execution path byte-for-byte compatible in its
   public task fields, prompts, four actions, state semantics, prediction schema,
   experiment plans, sealed submission, and Private Scorer handoff.
2. Add a separate `generic-eval-agent` entry point. It uses the same fixed Model
   Gateway, model backend, bounded per-task state, append-only traces, concurrent batch
   journal, and protocol-v2 phase semantics.
3. Define a strict generic public task envelope with `task_id`, `instruction`, `inputs`,
   addressable `context` units, and optional structured `data`.
4. Define a strict task profile that freezes the system instruction, answer contract,
   evidence policy, and a list of allowed skill names.
5. Keep skills in a code-owned static registry. A profile may select registered names
   but cannot import a module, provide executable code, change a skill schema, or add an
   arbitrary request field. Unknown names fail before the first model request.
6. During Exploration, the model chooses exactly one allowed skill or
   `submit_answer`. Finalization and Review allow only `submit_answer`. Every action
   carries bounded evidence status, missing-information, confidence, and risk metadata.
7. Ship five bounded built-ins: Unicode-aware `search_context`, exact
   `read_context`, the existing safe `calculator`, structured `lookup_data`, and
   `compare_values`. `submit_answer` is implicit and validated against the profile's
   enum, text, number, boolean, or JSON answer contract.
8. Preserve deterministic review policies and verified-draft fallback. Skill, parse,
   protocol, and model failures consume the active phase attempt, and resume rejects
   changed task, profile, Agent config, or batch hashes.
9. Keep generic predictions outside the FinDVer sealed-submission and scorer protocol.
   A future dataset-specific scorer adapter requires a separate reviewed contract.
10. Continue to prohibit browser, shell, Python execution, arbitrary file reads,
    Docker access, Gold, feedback, scorer access, and unrestricted network tools.

## Consequences

- Multiple task families can reuse one bounded Agent framework while choosing different
  local capabilities and answer contracts.
- Adding a new CLI-visible skill requires a reviewed code change and tests, not a YAML
  edit alone.
- FinDVer historical experiments remain comparable because their Runtime path is not
  routed through the generic prompt or action parser.
- The repository now has two result envelopes. Generic results need an explicit
  dataset-specific scoring layer before they can be treated as benchmark results.
- Generic context search is intentionally separate from the frozen FinDVer BM25 skill,
  so multilingual improvements do not alter FinDVer retrieval behavior.

## Rejected alternatives

- Rename and generalize the existing four FinDVer actions in place: changes model
  behavior and historical comparability.
- Let every task load arbitrary Python plugins from configuration: turns public data
  into a code-execution surface.
- Give all tasks every registered skill: increases prompt and capability surface and
  prevents task-level experimental control.
- Reuse the FinDVer prediction and Private Scorer schemas for unrelated task families:
  forces incompatible answers into `entailed`/`refuted` and confuses provenance.
