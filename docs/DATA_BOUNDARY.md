# Data Boundary

## Runtime-visible

- public task fields: `example_id`, `statement`, `report`
- the current task's named report
- local search/read/calculator/submit skills
- for experimental v3 only: the dynamically exposed subset of the nine code-owned
  report/table/numeric/frozen-rule/final Skills
- for experimental all-Skills smoke only: the configured, hash-verified synthetic rule
  corpus bundled under `configs/experimental/findoasis/`
- fixed Model Gateway endpoint
- the current question state, trace, final certificates and run output

## Builder-only

- source and tests
- development traces and run analysis
- development-only scorer feedback
- image build and experiment tooling

## Scorer-private

- private gold (`example_id`, `label`, `subset`)
- scorer validation and scoring implementation
- scorer inbox and outputs

Private material must never be present in the agent repository build context, image, environment, mounts, prompt, state, trace, or submission. Agent outbox and scorer inbox are different host directories. No runtime or Docker volume is shared between the two Compose projects.

## FinOASIS rule and certificate boundary

The tracked rule corpus is hand-authored synthetic test data. It is not a source of
financial, accounting, legal or regulatory guidance. Production rules require a
separately authorized source list, licences, exact versions, provenance hashes,
subject-matter review and a project-contract amendment before entering the Runtime.
Live internet rule retrieval and network fallback are prohibited.

V3 state may contain exact report evidence and complete synthetic rule records because
it is per-question Runtime output, not a public aggregate. Prompts receive exact report
text only after an explicit read and never receive full rule text. Aggregate summaries
contain counts/rates only. Final and specialist certificates are not added to the
evidence sidecar or three-file sealed submission, and scorer handoff remains disabled.

The v3 Docker smoke uses `FINDVER_REPORTS_SOURCE` only to select a host source for the
existing read-only `/reports` mount. It cannot add a mount target, write to reports,
expose a Docker socket, or give the Runtime another network.
