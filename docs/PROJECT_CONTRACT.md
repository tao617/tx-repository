# Project Contract

These constraints are invariant for the offline FinDVer experiment and the additive
generic evaluation Runtime unless a bullet explicitly scopes itself to one mode.

- The Runtime Answer Agent cannot read gold data, scorer code or outputs, or per-example builder feedback.
- The scorer is never exposed as a runtime skill or endpoint.
- Agent Runtime and Private Scorer use different containers, Compose projects, Docker networks, host mounts, and build contexts.
- The scorer uses `network_mode: none`, exposes no ports, and calls no model.
- A FinDVer submission and, for FinDVer Agent runs, one schema-validated evidence-ledger sidecar are copied in one direction by the WSL host only after the agent Compose project has stopped.
- The FinDVer evidence-ledger sidecar contains only example identifiers, frozen-seed paragraph IDs, and final-ledger paragraph IDs. It contains no text, labels, predictions, Gold, feedback, prompts, traces, or general state. Its SHA256 and schema version are bound into the sealed submission manifest.
- API or local-model traffic from either Runtime mode goes only to the fixed Model Gateway. Neither Runtime has a browser, search engine, arbitrary internet, shell, Python-execution, generic file-read, or Docker-socket skill.
- FinDVer execution mode exposes exactly `search_report`, `read_paragraphs`, `calculator`, and `submit_answer`; its prompt, action protocol, state machine, prediction schema, experiment plans, and scorer handoff remain unchanged by the generic path.
- Generic evaluation mode may expose only a task-profile-selected subset of reviewed, code-owned bounded skills from a static registry. YAML and public task data cannot import code, name arbitrary modules, add request extensions, or bypass skill argument validation and call budgets.
- Each question or generic task has a fresh session and isolated persistent state; no state crosses task boundaries.
- FinDVer public tasks contain only `example_id`, `statement`, and `report`. They do not reveal subset or any gold-derived field.
- Generic public tasks may contain only the strict public envelope `task_id`, `instruction`, `inputs`, `context`, and `data`; dataset adapters must remove Gold, feedback, scorer fields, and private metadata before Runtime ingestion.
- No answer may be hard-coded by example/task ID, statement wording, or feedback-derived lookup.
- Detailed feedback is development-only. Final results come from a frozen system evaluated on a hidden set without per-example feedback.
- FinDVer Baseline and Agent use the same public tasks, reports, model adapter, generation settings, prediction schema, and scorer.
- FinDVer sealed submissions still contain exactly `predictions.jsonl`, `manifest.json`, and `SHA256SUMS`; no trace, prompt, state, secret, source, gold, or feedback. The separately transferred, hash-bound evidence-ledger sidecar is the only permitted auxiliary per-example artifact.
- Generic predictions are a separate result envelope and are never accepted by the FinDVer Private Scorer or handoff without a separately reviewed dataset-specific adapter and protocol.

If chat context conflicts with this contract, this contract wins.
