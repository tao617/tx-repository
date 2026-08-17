# Architecture

The system has three roles: Builder Sol, Runtime Answer Agent, and Private Scorer.

The agent-side Compose project (`findver-agent`) contains a read-only Agent Runtime and a fixed Model Gateway. The runtime joins only an internal Docker network and can read public tasks and reports and write its own run output. The gateway joins that internal network and a controlled egress network; credentials exist only in the gateway.

For each public task, the runner creates a new report session and `QuestionState`. A bounded asynchronous worker pool advances different questions concurrently while every Exploration, tool, Finalization, and Review step inside one question remains serial. The first frozen pool limit is 32, the effective size is the smaller of that limit and the remaining task population, and the existing host evaluation lock still prevents different conditions, models, or Compose projects from overlapping. Per-example state and traces remain separate. Partial predictions are durable in completion order; the completed file is atomically rebuilt in public-task order. The original single-call path remains available through the Baseline Runner.

Runtime and Gateway share explicitly bounded 32-connection clients. B-class API configs use the enumerated `deepseek_v4_openai` request profile and the only accepted DeepSeek control is `thinking.type=disabled`; generic API and Local configs do not send that field. Responses retain only the validated visible content, usage, response ID, latency, and one of the supported finish reasons. A non-empty hidden-reasoning field under disabled thinking is a protocol drift and fails closed without persisting its value.

After a complete batch, the host seals predictions into a deterministic submission artifact. Once the agent project is stopped, the WSL host verifies and copies the artifact from the agent outbox to a distinct scorer inbox.

The scorer-side Compose project (`findver-scorer`) has no network. Its read-only build context and mounts are independent of the runtime. It validates the archive and hashes, scores against private gold, and writes either aggregate output or development-only detailed feedback.
