# Data Boundary

## Runtime-visible: FinDVer mode

- public task fields: `example_id`, `statement`, `report`
- the current task's named report
- local `search_report`, `read_paragraphs`, `calculator`, and `submit_answer` skills
- fixed Model Gateway endpoint
- the current question state, trace, and run output

## Runtime-visible: generic mode

- strict public task fields: `task_id`, `instruction`, `inputs`, `context`, and `data`
- one reviewed task profile containing the static skill allowlist and answer contract
- only the code-owned bounded skills selected by that profile, plus `submit_answer`
- fixed Model Gateway endpoint
- the current task state, trace, and generic run output

Task profiles and task data cannot dynamically import code, select arbitrary modules,
add network access, or expose unrestricted file/execution tools.

## Builder-only

- source and tests
- development traces and run analysis
- development-only scorer feedback
- image build and experiment tooling
- dataset adapters that remove private fields before producing public generic tasks

## Scorer-private

- private gold (`example_id`, `label`, `subset`) for FinDVer
- any dataset-specific private Gold and deterministic scoring adapter for generic tasks
- scorer validation and scoring implementation
- scorer inbox and outputs

Private material must never be present in an Agent repository build context, image,
environment, mounts, prompt, state, trace, or submission/result. Agent outbox and scorer
inbox are different host directories. No runtime or Docker volume is shared between an
Agent execution and a Private Scorer project.
