# Architecture

The system has three roles: Builder Sol, Runtime Answer Agent, and Private Scorer.

The agent-side Compose project (`findver-agent`) contains a read-only Agent Runtime and a fixed Model Gateway. The runtime joins only an internal Docker network and can read public tasks and reports and write its own run output. The gateway joins that internal network and a controlled egress network; credentials exist only in the gateway.

For each public task, the runner creates a new report session and `QuestionState`. A bounded asynchronous worker pool advances different questions concurrently while every Exploration, tool, Finalization, and Review step inside one question remains serial. The first frozen pool limit is 32, the effective size is the smaller of that limit and the remaining task population, and the existing host evaluation lock still prevents different conditions, models, or Compose projects from overlapping. Per-example state and traces remain separate. Partial predictions are durable in completion order; the completed file is atomically rebuilt in public-task order. The original single-call path remains available through the Baseline Runner.

## Experimental FinOASIS protocol v3

Protocol v3 is dispatched before any legacy state, prompt or retrieval object is built.
It creates an isolated `FinOASISQuestionState` with a typed obligation graph and exact
evidence, numeric value, claim value, program, rule evidence, specialist certificate and
final certificate ledgers. Resume identity binds the public task, exact report, canonical
experimental config, immutable Skill Registry, obligation policy and optional frozen
rule corpus.

The Registry is static code; configuration can only select a subset and assign bounded
call budgets. A pure resolver evaluates active obligation types and dependencies plus
trusted Runtime facts. The prompt receives only the resulting contracts, bounded counts,
search snippets and exact text already read into the ledger. Report and rule text cannot
register a Skill or alter its schema. An unavailable action is rejected after the model
attempt is durably charged and cannot mutate the proof state.

Table access is additive to the stable report paragraph order. Exact table-cell evidence
can become an immutable typed `ValueRef`. A reference-only FinDSL executes with Decimal
semantics and emits a hash-bound `NumericCertificate`. Knowledge Skills read only a
configured frozen local corpus and emit a mechanical `RuleApplicabilityCertificate`;
there is no network fallback. `ClaimCertificateVerifier` replays every consumed
specialist certificate before the final obligation can be satisfied. Selective Review
keeps a certificate-bound draft and may fall back only to that replayed draft.

The public prediction and sealing pipeline is unchanged. Full v3 certificates stay in
per-question state and traces; the aggregate summary includes only counts and rates. No
certificate scorer sidecar is defined.

Runtime and Gateway share explicitly bounded 32-connection clients. New B-class plans compose one canonical condition with a deployment and a closed API-dialect adapter. `deepseek_openai_chat` may add only `thinking.type=disabled`, `dashscope_openai_chat` may add only `enable_thinking=false`, and `openai_standard` adds neither; no arbitrary request-extension dictionary exists. Historical request-profile names remain loader compatibility only. Responses retain only the validated visible content, usage, response ID, latency, and one of the supported finish reasons. A non-empty hidden-reasoning field under disabled thinking is a protocol drift and fails closed without persisting its value.

After a complete batch, the host seals predictions into a deterministic submission artifact. Once the agent project is stopped, the WSL host verifies and copies the artifact from the agent outbox to a distinct scorer inbox.

The scorer-side Compose project (`findver-scorer`) has no network. Its read-only build context and mounts are independent of the runtime. It validates the archive and hashes, scores against private gold, and writes either aggregate output or development-only detailed feedback.
