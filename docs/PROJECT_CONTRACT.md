# Project Contract

These constraints are invariant for the offline FinDVer experiment.

- The Runtime Answer Agent cannot read gold data, scorer code or outputs, or per-example builder feedback.
- The scorer is never exposed as a runtime skill or endpoint.
- Agent Runtime and Private Scorer use different containers, Compose projects, Docker networks, host mounts, and build contexts.
- The scorer uses `network_mode: none`, exposes no ports, and calls no model.
- A submission is copied in one direction by the WSL host only after the agent Compose project has stopped.
- API or local-model traffic from the runtime goes only to the fixed Model Gateway. The runtime has no browser, search engine, arbitrary internet, shell, Python-execution, generic file-read, or Docker-socket skill.
- Each question has a fresh session and isolated persistent `QuestionState`; no state crosses question boundaries.
- Public tasks contain only `example_id`, `statement`, and `report`. They do not reveal subset or any gold-derived field.
- No answer may be hard-coded by `example_id`, statement wording, or feedback-derived lookup.
- Detailed feedback is development-only. Final results come from a frozen system evaluated on a hidden set without per-example feedback.
- Baseline and Agent use the same public tasks, reports, model adapter, generation settings, prediction schema, and scorer.
- Sealed submissions contain exactly `predictions.jsonl`, `manifest.json`, and `SHA256SUMS`; no trace, prompt, state, secret, source, gold, or feedback.

If chat context conflicts with this contract, this contract wins.

