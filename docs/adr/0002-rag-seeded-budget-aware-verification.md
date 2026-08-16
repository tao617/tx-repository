# ADR 0002: RAG-seeded budget-aware evidence verification

- Status: Accepted
- Date: 2026-08-16

## Context

The frozen development matrix preserves a direct one-call baseline, fixed-RAG baselines, and a search/read/calculation agent. The B-class upgrade must distinguish evidence-control gains from gains caused only by extra model calls, improve valid completion under bounded budgets, and preserve the runtime/scorer isolation established by ADR 0001.

Fixed retrieval currently represents only one embedding top-10 artifact. The legacy agent has one shared step ceiling, so exploration can consume the opportunity to produce a well-formed final answer. Mandatory review can spend a turn on every question and, unless carefully guarded, can turn a valid answer into an invalid result. Existing actions also lack a bounded representation of evidence gaps and risk.

## Decision

Adopt a versioned **RAG-Seeded Budget-Aware Evidence Verification Agent** with the following linked decisions.

1. Generalize fixed retrieval to validated, hash-bound top-3/top-5/top-10 artifacts for BM25, `text-embedding-3-large`, and `contriever-msmarco`. Accept the original FinDVer list format and the current wrapped format. Preserve `FixedEmbeddingIndex` as a compatibility alias.
2. Optionally preload each question's frozen retrieval paragraphs into its evidence ledger as pinned evidence. Initialization records retriever, cutoff, file SHA256, report, and paragraph IDs and is idempotent across resume. The seed consumes no tool, exploration, or model call, while still counting toward prompt and evidence-efficiency measurements.
3. Preserve protocol v1 and introduce protocol v2 with separate exploration, finalization, and review counters. Exploration cannot spend the reserved finalization or review budgets. Exhausted exploration transfers to finalization, where only `submit_answer` is allowed and malformed answers may use the remaining finalization attempts.
4. Add bounded evidence status, missing-information, confidence, and risk metadata to v2 action JSON. This metadata drives gap-directed action selection without a new runtime skill, hidden-reasoning record, or judge-model call.
5. Validate the first submission completely before retaining it as a draft. Use deterministic review policies `none`, `mandatory`, and `selective`. Selective review triggers on calculator use, conflicting evidence, low confidence, forced finalization with insufficient evidence, weak support, or table-alignment risk.
6. Permit review to replace a draft only with another valid submission. Any review failure or exhausted review budget returns the already verified draft and records fallback and change metadata.
7. Add a non-agent budget-matched iterative-RAG baseline with a fixed configured number of query-generation/search/read rounds followed by strict finalization. It has no evidence controller, adaptive stopping, or review.
8. Keep evidence-quality labels and statistical comparisons on the Private Scorer side. The Agent repository may define aggregate-only contracts and schemas but must not copy scorer code or gold-derived data into runtime or its build context.

## Budget and state semantics

The first v2 development budget is six exploration attempts, two finalization attempts, and one review attempt. Model, parse, protocol, and skill failures consume only their current phase's attempt. State stores a schema version, protocol version, phase, phase counters, initial-retrieval identity, structured control fields, verified draft, review metadata, phase-specific error counts, and termination reason.

Resume fails explicitly when a configured retrieval SHA256, retriever, cutoff, report, or paragraph list differs from the persisted initialization. Existing v1 state remains readable and retains historical behavior.

## Prompt and comparison semantics

Add strict-JSON FinDVer direct and CoT baseline profiles while keeping current profiles unchanged. Agent exploration shows only bounded operational state and the four existing actions. Finalization and review expose only the `submit_answer` schema. CoT prompts request internal checking but never require public chain-of-thought.

The iterative-RAG baseline and main agent share the model, seed, report search/read implementations, public tasks, generation parameters, prediction schema, and scorer. Experiments report maximum budgets and actual calls, input tokens, output tokens, and latency instead of attempting online token equality.

## Consequences

- The method can recover evidence outside the frozen seed without making top-k a visibility boundary.
- A valid draft survives review failures, and exploration cannot consume all opportunities to submit.
- Versioned state and hash-bound retrieval make resume stricter; incompatible runs stop rather than silently changing evidence.
- Seeded and dynamic evidence need separate aggregate accounting.
- The fixed-loop baseline adds implementation and experiment configurations but supplies a direct control for additional-call explanations.
- Private evidence metrics remain blocked when the separate scorer repository is unavailable; this is recorded rather than bypassing the isolation boundary.

## Rejected alternatives

- A separate planner, verifier, or evidence-judge model: adds calls and changes the experimental question.
- A new retrieval or sufficiency runtime skill: expands the allowlist and risks weakening isolation.
- Truncating paragraph-ID-reordered top-10 artifacts to create top-3/top-5: does not preserve upstream ranking semantics.
- Letting exploration borrow finalization or review budget: recreates max-step invalid failures.
- Saving unvalidated review drafts: permits a review format error to destroy a valid answer.
- Token-perfect online budget matching: unnecessary complexity; actual resource use is reported instead.
