# Architecture

The system has three roles: Builder Sol, Runtime Answer Agent, and Private Scorer.

The agent-side Compose project (`findver-agent`) contains a read-only Agent Runtime and a fixed Model Gateway. The runtime joins only an internal Docker network and can read public tasks and reports and write its own run output. The gateway joins that internal network and a controlled egress network; credentials exist only in the gateway.

For each public task, the runner creates a new report session and `QuestionState`. A bounded loop rebuilds the model prompt from structured state, accepts one JSON action, validates and executes one of four local skills (`search_report`, `read_paragraphs`, `calculator`, `submit_answer`), and appends raw observations to a trace. The original single-call path remains available through the Baseline Runner.

After a complete batch, the host seals predictions into a deterministic submission artifact. Once the agent project is stopped, the WSL host verifies and copies the artifact from the agent outbox to a distinct scorer inbox.

The scorer-side Compose project (`findver-scorer`) has no network. Its read-only build context and mounts are independent of the runtime. It validates the archive and hashes, scores against private gold, and writes either aggregate output or development-only detailed feedback.

