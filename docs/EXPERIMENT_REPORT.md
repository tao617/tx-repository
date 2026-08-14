# Experiment Report

Date: 2026-08-14  
Environment: WSL Ubuntu 24.04, Python 3.12, Docker 29.1.3, Compose 2.40.3

## Completed validation

- Agent repository tests: 69 passed; one Starlette deprecation warning.
- Independent Private Scorer tests: 10 passed.
- Agent Runtime, Model Gateway, and Private Scorer images built successfully without passing host proxy variables.
- Build contexts are controlled by separate allowlists; private gold, credentials, scorer source, feedback, and run artifacts are excluded from Agent/Gateway images.
- Container definitions enforce read-only roots, all capabilities dropped, `no-new-privileges`, no host ports, and no Docker socket.
- Agent network is internal; only the Gateway has egress. Scorer network mode is `none`.
- Agent, handoff, and Scorer launchers share one host `flock`, pin their Compose project names, and reject overlapping execution.
- Agent output is an exact per-run bind mount rather than a writable mount of the whole runs directory. Scorer output is canonicalized and constrained below its private output root.

## End-to-end runs

| Run | Backend | Result | Evidence path |
|---|---|---|---|
| `smoke-agent` | API Mock | completed | Agent → Gateway → fixed Mock upstream → sealed archive → host handoff → Scorer |
| `smoke-local` | Local Mock | completed | Same text-JSON protocol with local model alias |
| `real-api-smoke-8` | real API | completed | Direct Gateway egress; 3 model calls, Search → Read → Submit, 0 errors |
| `real-api-smoke-9` | real API | completed | Default direct launcher; stack stopped automatically |
| `smoke-post-audit` | API Mock | completed | Rebuilt images and exact per-run output mount after final isolation fixes |
| `post-audit-final` | networkless Scorer | scored | Aggregate-only output contained only `summary.json`, including subset aggregates |

The real API credential was loaded at runtime from the external mode-`0600` `.env.agent`; it was not copied into an image or repository. A marker scan found no API key, authorization header, bearer token, or base URL field in successful run artifacts. Direct container egress was the working configuration; the host proxy was not inherited.

Several preceding `real-api-smoke-*` directories retain failed diagnostics from proxy experiments. They are ignored local run artifacts and are excluded from the public release.

## Scorer protocol run

The one-question Mock archive was scored against the 700-record development gold file. This demonstrated the fixed denominator: 699 missing predictions were counted wrong. Development mode produced a private feedback file; final-aggregate mode produced only `summary.json`. Overall plus IE/Numeric/Knowledge aggregate metrics were emitted without per-example or gold content.

The released `testmini` annotations are development-only. No final-hidden gold was available, so no hidden-set score is claimed.

## Experiment support

Both API and local configuration families now cover B0 direct, B1 chain-of-thought, B2 fixed BM25, A0 Agent without calculator, A1 full Agent, and A2 mandatory pre-submit review. The run summarizer reports aggregate steps, action attempts, tokens, model calls, latency, invalid rate, and optional cost without copying questions, evidence, or sample IDs.

## Credential decision

- `.env.agent`: sourced only by the controlled launcher and injected only into the fixed Model Gateway.
- `.env.scorer`: not used or copied. The deterministic Private Scorer has no network and must not hold an API credential.

## Experiment limits

The validation used deterministic Mock API/local runs and small real-model smoke runs. A full 700-item paid API comparison was not launched without an explicit spend/time budget. The six-condition matrix, common submit protocol, sealing path, independent scorer, and aggregate efficiency reporter are ready for that controlled run.
