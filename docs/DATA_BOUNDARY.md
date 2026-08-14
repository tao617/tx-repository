# Data Boundary

## Runtime-visible

- public task fields: `example_id`, `statement`, `report`
- the current task's named report
- local search/read/calculator/submit skills
- fixed Model Gateway endpoint
- the current question state, trace, and run output

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

