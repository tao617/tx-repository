"""Bounded, resumable per-question agent loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from findver_agent.actions import (
    ActionParseError,
    CalculatorAction,
    ReadAction,
    SearchAction,
    SubmitAction,
    parse_action,
)
from findver_agent.config import AgentConfig
from findver_agent.model_backends.base import GenerationConfig, ModelBackend
from findver_agent.prompt_builder import PromptBuilder
from findver_agent.report_store import ReportStore
from findver_agent.schemas import Prediction, PredictionStatus, PublicTask
from findver_agent.skills import CalculatorSkill, ReadParagraphsSkill, SearchReportSkill, SubmitAnswerSkill
from findver_agent.skills.base import SkillError
from findver_agent.state import CalculationRecord, EvidenceRecord, SearchRecord, StateStore
from findver_agent.trace_writer import TraceWriter


class AgentOrchestrator:
    def __init__(
        self,
        *,
        backend: ModelBackend,
        generation: GenerationConfig,
        agent_config: AgentConfig,
        report_store: ReportStore,
        run_dir: Path,
    ) -> None:
        self.backend = backend
        self.generation = generation
        self.config = agent_config
        self.report_store = report_store
        self.state_store = StateStore(run_dir / "state")
        self.trace_root = run_dir / "traces"
        self.prompt_builder = PromptBuilder(generation, agent_config)

    async def run_question(self, task: PublicTask) -> Prediction:
        state = self.state_store.load_or_create(task, self.config.max_steps)
        trace = TraceWriter(self.trace_root, task.example_id)
        if state.closed:
            if state.prediction is None:
                raise ValueError("closed state has no prediction")
            return state.prediction

        session = self.report_store.open_session(task.report)
        search = SearchReportSkill(session)
        read = ReadParagraphsSkill(session, max_paragraphs=self.config.max_paragraphs_per_read)
        calculator = CalculatorSkill()
        submit = SubmitAnswerSkill(session, task.example_id)

        while state.step < self.config.max_steps:
            state.remaining_steps = self.config.max_steps - state.step
            messages = self.prompt_builder.build(state)
            trace.write("model_request", {"step": state.step, "messages": messages})
            try:
                state.usage.model_calls += 1
                response = await self.backend.generate(messages, self.generation)
                state.usage.input_tokens += response.input_tokens
                state.usage.output_tokens += response.output_tokens
                state.usage.latency_ms += response.latency_ms
                trace.write(
                    "model_response",
                    {
                        "step": state.step,
                        "content": response.content,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "latency_ms": response.latency_ms,
                        "response_id": response.response_id,
                    },
                )
            except Exception as error:
                self._record_error(state, trace, f"model error: {type(error).__name__}: {error}")
                continue

            try:
                action = parse_action(response.content)
            except ActionParseError as error:
                self._record_error(state, trace, str(error))
                continue

            trace.write("action", action.model_dump(mode="json"))
            try:
                if isinstance(action, SearchAction):
                    self._check_budget(
                        state.tool_counts.search_report,
                        self.config.max_search_calls,
                        "search_report",
                    )
                    observation = search.execute(**action.arguments.model_dump())
                    state.tool_counts.search_report += 1
                    state.search_queries.append(
                        SearchRecord(
                            query=action.arguments.query,
                            result_ids=[int(hit["paragraph_id"]) for hit in observation["hits"]],
                        )
                    )
                elif isinstance(action, ReadAction):
                    self._check_budget(
                        state.tool_counts.read_paragraphs,
                        self.config.max_read_calls,
                        "read_paragraphs",
                    )
                    known = {record.paragraph_id for record in state.evidence_ledger}
                    requested = set(action.arguments.paragraph_ids)
                    if len(known | requested) > self.config.max_total_unique_paragraphs:
                        raise SkillError("maximum unique paragraph budget would be exceeded")
                    observation = read.execute(**action.arguments.model_dump())
                    state.tool_counts.read_paragraphs += 1
                    existing = {record.paragraph_id: record for record in state.evidence_ledger}
                    for paragraph in observation["paragraphs"]:
                        paragraph_id = int(paragraph["paragraph_id"])
                        if paragraph_id in existing:
                            existing[paragraph_id].pinned = True
                            continue
                        state.evidence_ledger.append(
                            EvidenceRecord(
                                paragraph_id=paragraph_id,
                                exact_text=str(paragraph["text"]),
                                reason_selected="selected by the model for exact reading",
                                read_order=len(state.evidence_ledger),
                            )
                        )
                elif isinstance(action, CalculatorAction):
                    if not self.config.calculator_enabled:
                        raise SkillError("calculator is disabled for this run")
                    self._check_budget(
                        state.tool_counts.calculator,
                        self.config.max_calculator_calls,
                        "calculator",
                    )
                    observation = calculator.execute(**action.arguments.model_dump())
                    state.tool_counts.calculator += 1
                    state.calculations.append(
                        CalculationRecord(
                            expression=action.arguments.expression,
                            result=observation["result"],
                        )
                    )
                elif isinstance(action, SubmitAction):
                    if self.config.pre_submit_review and not state.review_requested:
                        state.draft_submission = action.arguments.model_dump(mode="json")
                        state.review_requested = True
                        observation = {
                            "accepted": False,
                            "review_required": True,
                            "instruction": "Review the evidence and submit the final answer.",
                        }
                        self._complete_step(state, trace, observation)
                        continue
                    if self.config.pre_submit_review and not state.review_completed:
                        state.review_completed = True
                    prediction = submit.execute(**action.arguments.model_dump())
                    observation = {
                        "accepted": True,
                        "review_completed": state.review_completed,
                        "prediction": prediction.model_dump(mode="json"),
                    }
                    self._complete_step(state, trace, observation)
                    state.prediction = prediction
                    state.closed = True
                    self.state_store.save(state)
                    trace.write("question_closed", {"status": "completed"})
                    return prediction
                else:  # pragma: no cover - discriminated parser makes this unreachable
                    raise SkillError("unknown action")
            except (SkillError, ValueError, TypeError) as error:
                self._record_error(state, trace, f"skill error: {error}")
                continue
            self._complete_step(state, trace, observation)

        prediction = Prediction(
            example_id=task.example_id,
            label=None,
            status=PredictionStatus.INVALID,
            evidence_ids=[],
            explanation="step budget exhausted without a valid submission",
        )
        state.prediction = prediction
        state.closed = True
        state.remaining_steps = 0
        self.state_store.save(state)
        trace.write("question_closed", {"status": "invalid", "reason": "step budget exhausted"})
        return prediction

    @staticmethod
    def _check_budget(current: int, maximum: int, skill: str) -> None:
        if current >= maximum:
            raise SkillError(f"{skill} call budget exhausted")

    def _complete_step(self, state, trace: TraceWriter, observation: dict[str, Any]) -> None:
        state.step += 1
        state.remaining_steps = max(0, self.config.max_steps - state.step)
        state.last_observation = observation
        trace.write("tool_result", observation)
        self.state_store.save(state)

    def _record_error(self, state, trace: TraceWriter, message: str) -> None:
        state.step += 1
        state.remaining_steps = max(0, self.config.max_steps - state.step)
        state.errors.append(message[:1000])
        state.last_observation = {"error": message[:1000]}
        trace.write("recoverable_error", {"step": state.step - 1, "error": message[:1000]})
        self.state_store.save(state)

