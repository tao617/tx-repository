# Scorer Protocol

The host supplies one sealed `submission-<run_id>.tar.gz`. The archive must contain exactly:

- `predictions.jsonl`
- `manifest.json`
- `SHA256SUMS`

The scorer rejects partial or malformed submissions, extra or duplicate entries, links, non-regular files, absolute or traversing paths, hash mismatches, unknown or duplicate IDs, and schema violations. Missing or invalid labels score as incorrect; the full gold count is the accuracy denominator. Scoring is deterministic and never calls a model.

`dev-detailed` produces `summary.json` and private `feedback.jsonl`. `final-aggregate` produces only `summary.json`. The summary reports aggregate overall and IE/Numeric/Knowledge accuracy, coverage, and correct/wrong/valid/missing/invalid counts. Neither mode mutates the submission, and aggregate output contains no gold content or per-example data.

The gold path is fixed inside the scorer container by `FINDVER_GOLD_PATH`, not supplied by the runtime. Scorer output must resolve beneath its private output root. A host lock prevents Agent execution, handoff, and Scorer execution from overlapping.

Evidence-quality and paired statistical analysis follow `docs/PRIVATE_EVIDENCE_METRICS.md`. Its per-example input schema is private scorer-side material; only the aggregate output schema may cross the scorer boundary. The implementation belongs in the separate networkless Private Scorer repository. Because that repository is unavailable in this workspace, the adapter implementation remains blocked and no scorer-completion claim is made here.
