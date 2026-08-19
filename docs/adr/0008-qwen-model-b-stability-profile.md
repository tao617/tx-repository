# ADR 0008: Qwen Model-B stability deployment

- Status: Accepted
- Date: 2026-08-19
- Amended: 2026-08-19 after the first approved launch exposed a local gateway schema omission

## Context

The prespecified Model-B replication requires stable one-call BRAG10, BM25 Top-10,
Hybrid RRF Top-10, and BLC rows, with valid-response rate reported alongside capability.
The immutable first Qwen run does not meet that gate. Aggregate Runtime traces show that
BRAG10 had 180 terminal HTTP 429 errors, while BLC had 276 strict JSON parse errors and
29 terminal HTTP 429 errors. The common BLC parse failure was extra content after an
otherwise complete JSON object. These are transport and response-envelope failures, not
evidence that should be compared as task capability.

DashScope documents `response_format={"type":"json_object"}` for Qwen JSON output and
lists the Qwen3.5 open-source series as supported in non-thinking mode. The existing
FinDVer prompt already asks for strict JSON and the Qwen deployment already disables
thinking. The provider documentation recommends omitting an output-token cap in this
mode, but the experiment protocol precommits a 1024-token cap for cross-model parity.

## Decision

1. Keep deployment `qwen3_5_27b_dashscope`, its plans, sealed outputs, and scores
   immutable as historical evidence.
2. Add a separate deployment, `qwen3_5_27b_dashscope_stable`, for the Model-B stability
   round. It keeps exact model ID `qwen3.5-27b`, the existing DashScope chat dialect,
   disabled thinking, 100000-token context capacity, and the same gateway boundary.
3. Add one closed deployment setting, `response_format`, whose only non-default value is
   `json_object`. Runtime maps it to the fixed top-level request field
   `response_format={"type":"json_object"}`. It is accepted only by the reviewed
   DashScope adapter; arbitrary request dictionaries remain forbidden. Historical
   deployments default to `text` and retain byte-for-byte request behavior.
4. Freeze the stable deployment at 240 RPM, 400000 estimated TPM, and at most ten
   transport retries. These conservative admission limits address the observed 429s;
   they do not change prompts or answer parsing.
5. Preserve temperature 0, top-p 1, seed 7, maximum output 1024, prompt-construction
   budget 32768, prompt profiles, method budgets, retrieval artifacts, concurrency 32,
   strict action parser, prediction schema, and Private Scorer contract.
6. Because the deployment configuration changes, rerun M2 under this deployment along
   with BLC, BRAG10, BBM25_10, and BHYBRID_RRF10. Do not combine the new one-call rows
   with the historical M2 row for the primary cross-condition comparison.
7. Report strict valid-response rate and transport/finish diagnostics before capability
   comparisons. Failed outputs remain invalid; the parser does not repair or select
   among multiple objects.
8. Require explicit user approval before any smoke or full Model-B API execution.
9. The fixed Model Gateway validates and forwards the same closed
   `response_format={"type":"json_object"}` structure. It rejects null, text mode,
   schema extensions, strings, and arbitrary request fields.

## Consequences

- The stability round is a five-condition rerun rather than the originally estimated
  four new one-call rows, because M2 must share the effective Model-B configuration.
- JSON conformance is handled at the provider response envelope without changing the
  requested answer schema or accepting malformed responses.
- The unchanged 1024-token cap can still yield rare `length` finishes. Such outputs are
  reported as invalid rather than silently repaired.
- Plans bind the new deployment file and canonical effective-config hash, so the JSON
  response setting and admission limits are auditable even though the historical run
  identity schema is unchanged.
- The first approved BRAG10 launch under matrix V1 was stopped after 205 partial rows
  when every request received local HTTP 422. No request reached the upstream model.
  The partial run remains an aborted transport diagnostic and is not scored. Matrix V2
  uniquely identifies the corrected rerun.

## Rejected alternatives

- Relax the strict parser or extract the first valid object: this would change the
  output contract and hide formatting failures.
- Retry parse failures with extra model calls: this would make the one-call baselines
  no longer single-call conditions.
- Reuse the historical M2 result: its deployment configuration is not identical to the
  stabilized baselines.
- Remove the 1024-token cap only for Qwen: this would change a frozen generation setting
  and weaken cross-model parity.

## Reference

- Alibaba Cloud Model Studio, “How to make Qwen generate a JSON string”:
  https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output
