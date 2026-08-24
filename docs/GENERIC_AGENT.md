# Generic evaluation Agent

The generic Agent is an additive Runtime path. It does not replace or change the
existing FinDVer Agent, prompts, actions, prediction schema, experiment plans, or
Private Scorer contract.

It keeps the current protocol-v2 reasoning shape:

1. bounded **Exploration** attempts;
2. reserved **Finalization** attempts in which only `submit_answer` is legal;
3. optional deterministic **Review** with verified-draft fallback;
4. one durable state file and one append-only trace per task;
5. parse, protocol, model, and skill failures charged to the active phase;
6. completion-order partial journaling and task-order final output.

The difference is that a task profile selects a static skill allowlist and an answer
contract. During Exploration, the LLM chooses one skill from that allowlist or submits
an answer. YAML cannot import Python or add arbitrary tools.

## Built-in skills

| Skill | Purpose |
|---|---|
| `search_context` | Unicode-aware BM25 search over public context units, including CJK character/bigram tokens |
| `read_context` | Exact bounded reads that add units to the evidence ledger |
| `calculator` | The existing AST-allowlisted arithmetic calculator |
| `lookup_data` | Bounded traversal of public structured JSON data |
| `compare_values` | Exact, case-folded, or tolerant numeric comparison |
| `submit_answer` | Implicit final action; always validated by the task profile |

There is still no browser, shell, Python-execution skill, arbitrary file reader,
credential access, scorer access, Gold access, or unrestricted network tool.

## Public task format

Tasks are UTF-8 JSONL. Every line has the same strict envelope:

```json
{
  "task_id": "example-001",
  "instruction": "Choose the correct answer.",
  "inputs": {
    "question": "What is 40 + 2?",
    "options": {"A": 40, "B": 41, "C": 42, "D": 43}
  },
  "context": [
    {"unit_id": "note-0", "title": "Optional title", "text": "Optional evidence text"}
  ],
  "data": {
    "table": [[40, 2], [42, 1]]
  }
}
```

`inputs` are shown directly to the model. Context text is exposed only through
`search_context` or `read_context`; the prompt contains only the unit IDs and titles.
`data` is exposed only through `lookup_data`. A task may omit context or data.

## Task profiles

A profile freezes the task instructions, allowed skills, answer type, and evidence
policy. Examples are tracked under `configs/generic/profiles/`.

Supported answer contracts are:

- `enum`: one exact configured string;
- `text`: one non-empty bounded string;
- `number`: one finite number, optionally bounded;
- `boolean`: a JSON boolean;
- `json`: bounded JSON, optionally with required top-level keys.

Evidence policies are:

- `none`: evidence IDs are forbidden;
- `optional`: any existing context unit may be cited;
- `read_only`: cited units must first be read with `read_context`;
- `required_read`: at least one cited unit must first be read.

## Run command

The new entry point uses the same fixed Model Gateway and OpenAI-compatible backend:

```bash
generic-eval-agent run \
  --config configs/generic/example-api.yaml \
  --profile configs/generic/profiles/evidence_boolean.yaml \
  --tasks tests/fixtures/generic_smoke_tasks.jsonl \
  --run-dir /tmp/generic-evidence-run
```

The run directory contains:

```text
predictions.partial.jsonl   # while incomplete
predictions.jsonl           # complete and restored to task order
run_metadata.json           # config/profile/task hashes and runtime metrics
state/*.json                # durable per-task state
traces/*.jsonl              # append-only model/action/skill events
```

These generic predictions intentionally do not use the FinDVer sealed-submission or
Private Scorer schema. A dataset-specific scorer adapter should consume the generic
prediction envelope separately.

## Adding a task-specific skill

Skills are code-owned and explicitly registered. A skill supplies a Pydantic argument
model, a short prompt description, and a bounded `execute` method:

```python
class DateDifferenceSkill:
    name = "date_difference"
    description = "Compute an exact bounded difference between two ISO dates."
    arguments_model = DateDifferenceArguments

    def __init__(self, task: GenericTask) -> None:
        self.task = task

    def execute(self, **kwargs: object) -> dict[str, JsonValue]:
        arguments = self.arguments_model.model_validate(kwargs)
        # Deterministic, bounded implementation.
        return {"days": days}

catalog = default_skill_catalog()
catalog.register("date_difference", DateDifferenceSkill)
engine = GenericAgent(..., skill_catalog=catalog)
```

A profile may then allow `date_difference`. Unknown names fail before the first model
request. The CLI uses only the tracked default catalog; adding a CLI-visible skill
therefore requires a reviewed code change and tests rather than a YAML import path.

## Compatibility rule

The original `findver-agent` entry point remains the authoritative FinDVer path. New
profiles and skills must not rename its actions, change its prompts, alter its state
machine, modify its prediction schema, or enter the existing scorer handoff. This keeps
historical FinDVer experiments comparable while allowing other task families to reuse
the same bounded Agent design.
