# ADR 0001: Isolated runtime and scorer

- Status: Accepted
- Date: 2026-08-14

## Context

The experiment compares direct and agentic use of the same model. Runtime access to gold labels, detailed feedback, or scorer behavior would invalidate the comparison.

## Decision

Use two Compose projects and build contexts. The agent project contains only the runtime and fixed Model Gateway. The private scorer lives under a separate restricted WSL directory, has `network_mode: none`, and sees only a read-only submission inbox, read-only gold mount, and writable output mount. The WSL host performs a hash-checked one-way copy only after stopping the agent project.

The existing one-call prompt is preserved as a Baseline Runner, but the original evaluation path that mixes gold and model output is not used by the new runtime or scorer.

## Consequences

The boundary is suitable for repeatable experiments on one trusted WSL host, but it does not defend against a malicious host administrator. Moving the unchanged scorer contract to a separate machine can strengthen that boundary later.

