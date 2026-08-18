# ADR 0006: Composable API deployments and Qwen3.5-27B Model-B parity

- Status: Accepted
- Date: 2026-08-18
- Amended: 2026-08-18 after the user replaced the model-specific configuration design

## Context

The frozen B-class methods must be reproducible across hosted models without copying
the seven main conditions and four Model-B extensions for every provider. DeepSeek and
Qwen use OpenAI-compatible chat endpoints, but disabled thinking is represented by
different request fields. A model-named request profile or model-named configuration
directory would couple experiment methods to a deployment and make later additions
require code and configuration duplication.

The user authorized a Qwen3.5-27B API implementation, offline verification, and a small
Gold-free smoke. This does not authorize a 700-example paid row, Private Scorer handoff,
holdout, or hidden execution. Historical DeepSeek configs, schema-v2 plans, results, and
launch paths must remain usable and must not be rewritten.

## Decision

1. Split new experiment configuration into three layers:
   - one canonical model-independent file for each of the seven main conditions and
     four Model-B extensions;
   - closed transport adapters named by API dialect, currently `openai_standard`,
     `deepseek_openai_chat`, and `dashscope_openai_chat`;
   - one deployment YAML per hosted model, containing model ID, transport profile,
     gateway alias, context capacity, thinking mode, timeout/retry policy, and optional
     RPM/TPM admission limits.
2. A transport adapter is the only component allowed to add provider-specific request
   fields. It builds from the common chat-completion fields plus an immutable whitelist:
   DeepSeek adds only `thinking={"type":"disabled"}`, DashScope adds only
   `enable_thinking=false`, and the standard adapter adds neither. `extra_body` and
   arbitrary request-extension dictionaries remain forbidden.
3. Keep `generic_openai` and `deepseek_v4_openai` only as compatibility names while
   loading historical configs and schema-v2 plans. New deployments and schema-v3 plans
   use the dialect names above. No compatibility name is added for the abandoned
   model-bound Qwen profile.
4. Record Qwen as deployment `qwen3_5_27b_dashscope`: exact model ID `qwen3.5-27b`,
   API backend, 100000-token context capacity, disabled thinking, 540 RPM, and 850000
   estimated TPM. Admission limits are deployment data and are not properties of the
   DashScope dialect.
5. The schema-v3 planner composes each selected deployment with each canonical condition.
   Every run binds the condition path/SHA256, deployment path/SHA256, and canonical
   serialized effective Runtime config/SHA256. Adding another model that uses an
   existing dialect therefore requires only a deployment YAML.
6. The executor recomposes and validates all three bindings before launch. It
   materializes the exact credential-free effective config in the ignored Runtime data
   area and mounts only that file read-only. It selects no model-specific config
   directory. The schema-v2 executor branch and historical DeepSeek config directories
   remain unchanged as a compatibility path.
7. Preserve temperature 0, top-p 1, seed 7, maximum output 1024, prompt-construction
   budget 32768, method settings, retrieval artifacts, concurrency 32, prediction schema,
   scorer contract, and the fixed Model Gateway boundary.
8. Reject nonempty `reasoning_content` under disabled thinking without persisting its
   value. Preserve the accepted finish reasons and bounded retry behavior.
9. Keep `LC_AGENT_FIRSTPASS` outside the four Model-B parity extensions under ADR 0005.
10. Permit only offline plans, contract checks, and a small Gold-free smoke before a
    separately authorized formal row. Do not infer authorization for any 700-example run.

## Consequences

- New method settings live only under `configs/conditions/`; Qwen does not have copied
  `qwen_api` or `qwen_ablations` trees.
- Provider and capacity differences are reviewable in `configs/deployments/`, while
  transport behavior is centralized and closed in one adapter module.
- Historical DeepSeek files and results remain byte-for-byte untouched. New plans use
  schema v3; existing schema-v2 plans continue through the compatibility executor.
- The fourteen-row paired plan uses the same seven condition hashes for both models.
  The four extension rows remain separate plans because retrieval identity is plan-level.
- Qwen native JSON mode, native tools, provider retrieval, and per-model prompt/parser
  changes remain excluded. Formatting failures remain experimental outcomes.

## Rejected alternatives

- Copy conditions into per-model directories: this creates drift-prone method copies.
- Name the protocol after Qwen3.5: the wire dialect is shared by other DashScope models.
- Put arbitrary provider fields in deployment YAML: this bypasses adapter review and
  violates the request whitelist.
- Omit the Qwen thinking field: the provider default would not reproduce the frozen
  disabled-thinking protocol.
- Enable provider-native structured output or tools: this changes the tested method.
