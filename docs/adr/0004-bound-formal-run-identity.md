# ADR 0004: Hash-bound formal-run identity

- Status: Accepted
- Date: 2026-08-16

## Context

The B-class planner froze model IDs, inputs, configurations, and a code commit, but its output was preparation-only. The generic launcher still accepted a mutable environment file and independent positional arguments. A formal run could therefore be started with a different upstream model or artifact while retaining a plausible run name, and a resume did not prove that it used the same frozen plan row.

A configured prompt-input limit is also not the same property as a provider/model context-window capacity. Both must be explicit without sending a nonstandard context-window field to an OpenAI-compatible API.

## Decision

B-class plan schema version 2 records an explicit `model_context_window_tokens` capacity for each model and every planned run. Formal execution uses `scripts/run_bclass_plan.py` to select exactly one plan row. Before launching, it fails closed unless:

- the plan is still `prepared_not_executed` and the row ID is unique;
- task, planned retrieval, and condition-config paths are confined to their expected repository directories;
- task, retrieval, and config SHA256 values match the plan;
- the configuration's backend kind and command match the row;
- the plan row's model context capacity equals both its frozen config specification and the effective Runtime config;
- the mode-0600 environment file defines exactly one `MODEL_NAME`, equal to the planned effective model ID;
- Git `HEAD` equals the frozen commit and the tracked worktree is clean; and
- an effectively configured retrieval file, when present, hashes to the planned retrieval artifact.

The executor creates an immutable validated run-identity object containing the plan hash, matrix/condition/run IDs, effective upstream model ID, Runtime model alias, backend kind, start commit and cleanliness assertion, config/task/planned-and-effective-retrieval hashes, and declared model context capacity. The generic launcher locks the executor-provided identity before sourcing credentials, rechecks the effective model, and passes the identity into Runtime.

Runtime validates the identity against its mounted config, task file, run directory, model alias, and backend before writing output. Resume requires byte-equivalent structured identity in `run_metadata.json`. Sealing copies the validated identity into `manifest.json` and binds its run ID, model alias, backend, commit, config hash, and task hash.

Legacy, historical, and builder-only smoke runs may omit a run identity. They remain distinguishable because their metadata and manifests contain `run_identity: null`. The executor does not authorize any paid, second-model, holdout, or hidden run.

## Consequences

- A B-class formal result has one auditable chain from frozen plan row through Runtime metadata to sealed manifest.
- Changing a model, task, retrieval artifact, config, commit, backend, run name, or identity during resume fails closed.
- Provider context capacity is recorded as provenance; request construction continues to use the standard API schema.
- Direct launcher calls remain available for compatibility and smoke testing but are not the formal B-class execution path.

## Rejected alternatives

- Trust the run directory name: names are descriptive, not cryptographic provenance.
- Record only the model alias: the fixed gateway alias does not identify the upstream model.
- Read the Git commit only at seal time: code may have changed after execution began.
- Put context-window capacity into each model request: it is a local scheduling and validation constraint, not a portable OpenAI-compatible request field.
