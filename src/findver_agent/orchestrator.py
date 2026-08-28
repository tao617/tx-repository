"""Bounded, resumable per-question agent loop."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from findver_agent.actions import (
    ActionParseError,
    CalculatorAction,
    ReadAction,
    SearchAction,
    SubmitAction,
    parse_action,
)
from findver_agent.config import AgentConfig
from findver_agent.fixed_retrieval import FixedRetrievalIndex
from findver_agent.findoasis.agent import FinOASISAgent
from findver_agent.model_backends.base import (
    GenerationConfig,
    ModelBackend,
    ProtocolDriftError,
    context_window_metadata,
)
from findver_agent.prompt_builder import PromptBuilder
from findver_agent.report_format import format_full_report
from findver_agent.report_store import ReportSession, ReportStore
from findver_agent.schemas import (
    Confidence,
    EvidenceStatus,
    Prediction,
    PredictionStatus,
    PublicTask,
    RiskFlag,
)
from findver_agent.skills import CalculatorSkill, ReadParagraphsSkill, SearchReportSkill, SubmitAnswerSkill
from findver_agent.skills.base import SkillError
from findver_agent.state import (
    CalculationRecord,
    EvidenceRecord,
    InitialRetrievalState,
    LongContextState,
    QuestionState,
    SearchRecord,
    StateStore,
)
from findver_agent.trace_writer import TraceWriter


ErrorKind = Literal["parse", "model", "skill", "protocol", "protocol_drift"]


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
        self._finoasis_agent: FinOASISAgent | None = None
        if self.config.protocol_version == "v3":
            self._finoasis_agent = FinOASISAgent(
                backend=backend,
                generation=generation,
                agent_config=agent_config,
                report_store=report_store,
                run_dir=run_dir,
            )
            # Compatibility handles for callers that inspect the orchestrator. The
            # objects are protocol-v3 implementations, never legacy State/Prompt.
            self.state_store = self._finoasis_agent.state_store
            self.trace_root = self._finoasis_agent.trace_root
            self.prompt_builder = self._finoasis_agent.prompt_builder
            self.initial_retrieval = None
            return
        self.state_store = StateStore(run_dir / "state")
        self.trace_root = run_dir / "traces"
        self.prompt_builder = PromptBuilder(generation, agent_config)
        retrieval = self.config.initial_retrieval
        self.initial_retrieval = None
        if retrieval.enabled:
            if retrieval.retrieval_file is None or retrieval.retriever is None:
                raise ValueError("enabled initial retrieval is incomplete")
            self.initial_retrieval = FixedRetrievalIndex(
                retrieval.retrieval_file,
                retriever=retrieval.retriever,
                top_k=retrieval.top_k,
            )

    async def run_question(self, task: PublicTask) -> Prediction:
        if self._finoasis_agent is not None:
            return await self._finoasis_agent.run_question(task)
        state_path_existed = self.state_store.path_for(task.example_id).exists()
        state = self.state_store.load_or_create(
            task,
            self.config.max_steps,
            protocol_version=self.config.protocol_version,
            exploration_steps=self.config.exploration_steps,
            finalization_steps=self.config.finalization_steps,
            review_steps=self.config.review_steps,
        )
        trace = TraceWriter(self.trace_root, task.example_id)
        session = self.report_store.open_session(task.report)
        self._initialize_retrieval(
            task,
            session,
            state,
            trace,
            resumed=state_path_existed,
        )
        self._initialize_long_context(
            task,
            session,
            state,
            trace,
            resumed=state_path_existed,
        )
        if state.closed:
            if state.prediction is None:
                raise ValueError("closed state has no prediction")
            return state.prediction
        if self.config.protocol_version == "v1":
            return await self._run_v1(task, session, state, trace)
        return await self._run_v2(task, session, state, trace)

    async def _run_v1(
        self,
        task: PublicTask,
        session: ReportSession,
        state: QuestionState,
        trace: TraceWriter,
    ) -> Prediction:
        search = SearchReportSkill(session)
        read = ReadParagraphsSkill(session, max_paragraphs=self.config.max_paragraphs_per_read)
        calculator = CalculatorSkill()
        submit = SubmitAnswerSkill(session, task.example_id)

        while state.step < self.config.max_steps:
            state.remaining_steps = self.config.max_steps - state.step
            messages = self.prompt_builder.build(state)
            context_metadata = context_window_metadata(
                messages,
                max_output_tokens=self.generation.max_output_tokens,
                model_context_window_tokens=getattr(
                    self.backend, "model_context_window_tokens", None
                ),
            )
            trace.write(
                "model_request",
                {
                    "step": state.step,
                    "messages": messages,
                    "request_profile": getattr(
                        self.backend, "request_profile", "generic_openai"
                    ),
                    "thinking_mode": getattr(
                        self.backend, "thinking_mode", "unsupported"
                    ),
                    **self.prompt_builder.evidence_visibility(state),
                    "prompt_budget_tokens": self.generation.prompt_budget_tokens,
                    **context_metadata,
                },
            )
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
                        "actual_provider_input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "latency_ms": response.latency_ms,
                        "response_id": response.response_id,
                        "finish_reason": response.finish_reason,
                        "rate_limit_wait_ms": response.rate_limit_wait_ms,
                        "transport_retries": response.transport_retries,
                    },
                )
            except Exception as error:
                kind: ErrorKind = (
                    "protocol_drift"
                    if isinstance(error, ProtocolDriftError)
                    else "model"
                )
                self._record_v1_error(
                    state,
                    trace,
                    f"model error: {type(error).__name__}: {error}",
                    kind=kind,
                )
                continue

            try:
                action = parse_action(response.content)
            except ActionParseError as error:
                self._record_v1_error(state, trace, str(error), kind="parse")
                continue

            trace.write("action", action.model_dump(mode="json"))
            try:
                if isinstance(action, SearchAction):
                    observation = self._execute_search(action, state, search)
                elif isinstance(action, ReadAction):
                    observation = self._execute_read(action, state, read)
                elif isinstance(action, CalculatorAction):
                    observation = self._execute_calculator(action, state, calculator)
                elif isinstance(action, SubmitAction):
                    if self.config.pre_submit_review and not state.review_requested:
                        self._validate_submission(state, action)
                        draft_prediction = submit.execute(**action.arguments.model_dump())
                        state.draft_prediction = draft_prediction
                        state.draft_submission = action.arguments.model_dump(mode="json")
                        state.review_requested = True
                        state.review_triggered = True
                        state.review_trigger_reasons = ["mandatory_policy"]
                        trace.write(
                            "review_triggered",
                            {"policy": "mandatory", "reasons": ["mandatory_policy"]},
                        )
                        observation = {
                            "accepted": False,
                            "review_required": True,
                            "instruction": "Review the evidence and submit the final answer.",
                        }
                        self._complete_v1_step(state, trace, observation)
                        continue
                    if self.config.pre_submit_review and not state.review_completed:
                        state.review_completed = True
                    if self.config.pre_submit_review:
                        self._validate_submission(state, action)
                    prediction = submit.execute(**action.arguments.model_dump())
                    if self.config.pre_submit_review and state.draft_prediction is not None:
                        state.review_changed_label = prediction.label != state.draft_prediction.label
                        state.review_changed_evidence = prediction.evidence_ids != state.draft_prediction.evidence_ids
                        state.review_changed_explanation = prediction.explanation != state.draft_prediction.explanation
                    observation = {
                        "accepted": True,
                        "review_completed": state.review_completed,
                        "prediction": prediction.model_dump(mode="json"),
                    }
                    self._complete_v1_step(state, trace, observation)
                    state.prediction = prediction
                    state.closed = True
                    self.state_store.save(state)
                    trace.write("question_closed", {"status": "completed"})
                    return prediction
                else:  # pragma: no cover - discriminated parser makes this unreachable
                    raise SkillError("unknown action")
            except (SkillError, ValueError, TypeError) as error:
                self._record_v1_error(
                    state, trace, f"skill error: {error}", kind="skill"
                )
                continue
            self._complete_v1_step(state, trace, observation)

        if self.config.pre_submit_review and state.draft_prediction is not None:
            state.prediction = state.draft_prediction
            state.closed = True
            state.remaining_steps = 0
            state.review_fallback_used = True
            state.review_failure_reason = "v1 review step budget exhausted"
            state.termination_reason = "review_fallback"
            self.state_store.save(state)
            trace.write(
                "question_closed",
                {"status": "completed", "reason": "review_fallback"},
            )
            return state.draft_prediction

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

    async def _run_v2(
        self,
        task: PublicTask,
        session: ReportSession,
        state: QuestionState,
        trace: TraceWriter,
    ) -> Prediction:
        if state.phase_budgets is None:
            raise ValueError("protocol v2 state is missing phase budgets")
        search = SearchReportSkill(session)
        read = ReadParagraphsSkill(session, max_paragraphs=self.config.max_paragraphs_per_read)
        calculator = CalculatorSkill()
        submit = SubmitAnswerSkill(session, task.example_id)
        if state.phase == "initialization":
            self._transition(state, trace, "exploration", reason="initialization_complete")

        while not state.closed:
            if state.phase == "exploration" and (
                state.exploration_step >= state.phase_budgets.exploration
            ):
                state.forced_finalization = True
                state.forced_finalization_evidence_status = state.evidence_status
                self._transition(
                    state,
                    trace,
                    "finalization",
                    reason="exploration_budget_exhausted",
                )
                continue
            if state.phase == "finalization" and (
                state.finalization_step >= state.phase_budgets.finalization
            ):
                return self._close_v2_invalid(
                    task,
                    state,
                    trace,
                    reason="finalization_budget_exhausted",
                )
            if state.phase == "review" and state.review_step >= state.phase_budgets.review:
                return self._review_fallback_or_invalid(
                    task,
                    state,
                    trace,
                    reason="review_budget_exhausted",
                )
            if state.phase not in {"exploration", "finalization", "review"}:
                raise ValueError(f"invalid active v2 phase: {state.phase}")

            phase = state.phase
            self._begin_v2_attempt(state)
            full_report_preview = self._claim_long_context_preview(state, session)
            long_context_injected = full_report_preview is not None
            messages = self.prompt_builder.build(
                state,
                full_report_preview=full_report_preview,
            )
            context_metadata = context_window_metadata(
                messages,
                max_output_tokens=self.generation.max_output_tokens,
                model_context_window_tokens=getattr(
                    self.backend, "model_context_window_tokens", None
                ),
            )
            if long_context_injected:
                long_context = state.long_context_state
                if long_context is None:  # pragma: no cover - claim validates state
                    raise ValueError("long-context state is missing after injection")
                trace.write(
                    "input_context",
                    {
                        "phase": phase,
                        "phase_attempt": self._phase_step(state, phase),
                        "long_context_injected": True,
                        "long_context_scope": self.config.long_context.scope,
                        "report_serialized_sha256": long_context.serialized_sha256,
                        "report_paragraph_count": long_context.paragraph_count,
                        "report_character_count": long_context.report_character_count,
                        "assembled_paragraph_count": long_context.paragraph_count,
                        "full_report_assembled": True,
                        "local_truncation": False,
                        "prompt_budget_tokens": self.generation.prompt_budget_tokens,
                        **context_metadata,
                    },
                )
            trace.write(
                "model_request",
                {
                    "step": state.step - 1,
                    "phase": phase,
                    "phase_attempt": self._phase_step(state, phase),
                    "messages": messages,
                    "request_profile": getattr(
                        self.backend, "request_profile", "generic_openai"
                    ),
                    "thinking_mode": getattr(
                        self.backend, "thinking_mode", "unsupported"
                    ),
                    "long_context_injected": long_context_injected,
                    **self.prompt_builder.evidence_visibility(state),
                    "prompt_budget_tokens": self.generation.prompt_budget_tokens,
                    **context_metadata,
                },
            )
            try:
                response = await self.backend.generate(messages, self.generation)
                state.usage.input_tokens += response.input_tokens
                state.usage.output_tokens += response.output_tokens
                state.usage.latency_ms += response.latency_ms
                trace.write(
                    "model_response",
                    {
                        "step": state.step - 1,
                        "phase": phase,
                        "phase_attempt": self._phase_step(state, phase),
                        "content": response.content,
                        "input_tokens": response.input_tokens,
                        "actual_provider_input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "latency_ms": response.latency_ms,
                        "response_id": response.response_id,
                        "finish_reason": response.finish_reason,
                        "rate_limit_wait_ms": response.rate_limit_wait_ms,
                        "transport_retries": response.transport_retries,
                        "long_context_injected": long_context_injected,
                    },
                )
            except Exception as error:
                kind: ErrorKind = (
                    "protocol_drift"
                    if isinstance(error, ProtocolDriftError)
                    else "model"
                )
                self._record_v2_error(
                    state,
                    trace,
                    phase,
                    kind,
                    f"model error: {type(error).__name__}: {error}",
                )
                continue

            try:
                action = parse_action(response.content, protocol_version="v2")
            except ActionParseError as error:
                self._record_v2_error(state, trace, phase, "parse", str(error))
                continue

            trace.write(
                "action",
                {"phase": phase, **action.model_dump(mode="json")},
            )
            control = action.control
            if control is None:  # protocol v2 parsing enforces this
                raise ValueError("protocol v2 action is missing control metadata")
            if (
                phase == "exploration"
                and control.evidence_status == EvidenceStatus.SUFFICIENT
                and not isinstance(action, SubmitAction)
            ):
                self._record_v2_error(state, trace, phase, "protocol", "exploration protocol inconsistency: sufficient evidence requires submit_answer")
                continue
            if phase in {"finalization", "review"} and not isinstance(action, SubmitAction):
                self._record_v2_error(
                    state,
                    trace,
                    phase,
                    "protocol",
                    f"{phase} protocol error: only submit_answer is allowed",
                )
                continue
            candidate_risks = set(state.risk_flags) | set(control.risk_flags)
            if control.evidence_status == EvidenceStatus.CONFLICTING:
                candidate_risks.add(RiskFlag.CONFLICTING_EVIDENCE)
            if (
                phase == "finalization"
                and isinstance(action, SubmitAction)
                and control.evidence_status != EvidenceStatus.SUFFICIENT
                and control.confidence != Confidence.LOW
                and candidate_risks.isdisjoint(
                    {
                        RiskFlag.CONFLICTING_EVIDENCE,
                        RiskFlag.RETRIEVAL_GAP,
                        RiskFlag.TABLE_ALIGNMENT,
                        RiskFlag.WEAK_SUPPORT,
                    }
                )
            ):
                self._record_v2_error(state, trace, phase, "protocol", "insufficient finalization evidence requires low confidence or a support risk flag")
                continue

            try:
                if isinstance(action, SearchAction):
                    observation = self._execute_search(action, state, search)
                elif isinstance(action, ReadAction):
                    observation = self._execute_read(action, state, read)
                elif isinstance(action, CalculatorAction):
                    observation = self._execute_calculator(action, state, calculator)
                elif isinstance(action, SubmitAction):
                    self._validate_submission(state, action)
                    prediction = submit.execute(**action.arguments.model_dump())
                    self._apply_action_control(state, action)
                    if phase == "review":
                        if state.draft_prediction is None:
                            raise SkillError("review requires a verified draft")
                        state.review_changed_label = prediction.label != state.draft_prediction.label
                        state.review_changed_evidence = prediction.evidence_ids != state.draft_prediction.evidence_ids
                        state.review_changed_explanation = prediction.explanation != state.draft_prediction.explanation
                        self._complete_v2_attempt(
                            state,
                            trace,
                            {
                                "accepted": True,
                                "review_completed": True,
                                "prediction": prediction.model_dump(mode="json"),
                            },
                        )
                        state.review_completed = True
                        return self._close_v2_completed(
                            state,
                            trace,
                            prediction,
                            reason="review_completed",
                        )
                    accepted = self._accept_v2_draft(
                        state,
                        trace,
                        prediction,
                        action.arguments.model_dump(mode="json"),
                        phase=phase,
                    )
                    if accepted is not None:
                        return accepted
                    continue
                else:  # pragma: no cover - discriminated parser makes this unreachable
                    raise SkillError("unknown action")
            except (SkillError, ValueError, TypeError) as error:
                self._record_v2_error(
                    state,
                    trace,
                    phase,
                    "skill",
                    f"skill error: {error}",
                )
                continue
            self._apply_action_control(state, action)
            self._complete_v2_attempt(state, trace, observation)

        if state.prediction is None:  # pragma: no cover - loop closes through helpers
            raise ValueError("closed v2 state has no prediction")
        return state.prediction

    def _execute_search(
        self,
        action: SearchAction,
        state: QuestionState,
        search: SearchReportSkill,
    ) -> dict[str, Any]:
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
        return observation

    def _execute_read(
        self,
        action: ReadAction,
        state: QuestionState,
        read: ReadParagraphsSkill,
    ) -> dict[str, Any]:
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
        return observation

    def _execute_calculator(
        self,
        action: CalculatorAction,
        state: QuestionState,
        calculator: CalculatorSkill,
    ) -> dict[str, Any]:
        if not self.config.calculator_enabled:
            raise SkillError("calculator is disabled for this run")
        self._check_budget(
            state.tool_counts.calculator,
            self.config.max_calculator_calls,
            "calculator",
        )
        observation = calculator.execute(**action.arguments.model_dump())
        state.tool_counts.calculator += 1
        self._add_risk_flag(state, RiskFlag.CALCULATION)
        state.calculations.append(
            CalculationRecord(
                expression=action.arguments.expression,
                result=observation["result"],
            )
        )
        return observation

    @staticmethod
    def _add_risk_flag(state: QuestionState, risk_flag: RiskFlag) -> None:
        if risk_flag not in state.risk_flags:
            state.risk_flags.append(risk_flag)

    def _apply_action_control(self, state: QuestionState, action: Any) -> None:
        control = action.control
        if control is None:  # protocol v2 parsing enforces this
            raise ValueError("protocol v2 action is missing control metadata")
        state.evidence_status = control.evidence_status
        state.evidence_confidence = control.confidence
        state.open_questions = list(control.missing_information)
        for risk_flag in control.risk_flags:
            self._add_risk_flag(state, risk_flag)
        if control.evidence_status == EvidenceStatus.CONFLICTING:
            self._add_risk_flag(state, RiskFlag.CONFLICTING_EVIDENCE)

    @staticmethod
    def _validate_submission(state: QuestionState, action: SubmitAction) -> None:
        if not action.arguments.explanation.strip():
            raise SkillError("submit explanation must be non-empty")
        known_ids = {record.paragraph_id for record in state.evidence_ledger}
        unknown_ids = sorted(set(action.arguments.evidence_ids) - known_ids)
        if unknown_ids:
            raise SkillError(
                "submit evidence_ids must already be read: "
                + ",".join(str(item) for item in unknown_ids)
            )

    def _review_trigger_reasons(self, state: QuestionState) -> list[str]:
        if self.config.review_policy == "none":
            return []
        if self.config.review_policy == "mandatory":
            return ["mandatory_policy"]
        reasons: list[str] = []
        if state.tool_counts.calculator > 0:
            reasons.append("calculator_used")
        draft_risks = set(state.draft_risk_flags)
        if RiskFlag.CONFLICTING_EVIDENCE in draft_risks:
            reasons.append("conflicting_evidence")
        if state.draft_confidence == Confidence.LOW:
            reasons.append("low_confidence")
        if (
            state.forced_finalization
            and state.forced_finalization_evidence_status != EvidenceStatus.SUFFICIENT
        ):
            reasons.append("forced_finalization_insufficient_evidence")
        if RiskFlag.WEAK_SUPPORT in draft_risks:
            reasons.append("weak_support")
        if RiskFlag.TABLE_ALIGNMENT in draft_risks:
            reasons.append("table_alignment")
        return reasons

    def _accept_v2_draft(
        self,
        state: QuestionState,
        trace: TraceWriter,
        prediction: Prediction,
        submission: dict[str, Any],
        *,
        phase: str,
    ) -> Prediction | None:
        state.draft_prediction = prediction
        state.draft_submission = submission
        state.draft_confidence = state.evidence_confidence
        state.draft_evidence_status = state.evidence_status
        state.draft_risk_flags = list(state.risk_flags)
        self._complete_v2_attempt(
            state,
            trace,
            {
                "accepted": True,
                "as_draft": True,
                "prediction": prediction.model_dump(mode="json"),
            },
        )
        reasons = self._review_trigger_reasons(state)
        if reasons:
            state.review_triggered = True
            state.review_requested = True
            state.review_trigger_reasons = reasons
            trace.write(
                "review_triggered",
                {"policy": self.config.review_policy, "reasons": reasons},
            )
            self._transition(
                state,
                trace,
                "review",
                reason=f"{self.config.review_policy}_review",
            )
            return None
        reason = (
            "submitted_during_exploration"
            if phase == "exploration"
            else "submitted_during_finalization"
        )
        return self._close_v2_completed(state, trace, prediction, reason=reason)


    def _close_v2_completed(
        self,
        state: QuestionState,
        trace: TraceWriter,
        prediction: Prediction,
        *,
        reason: str,
    ) -> Prediction:
        state.prediction = prediction
        state.closed = True
        state.phase = "closed"
        state.remaining_steps = 0
        state.termination_reason = reason
        self.state_store.save(state)
        trace.write("question_closed", {"status": "completed", "reason": reason})
        return prediction

    def _close_v2_invalid(
        self,
        task: PublicTask,
        state: QuestionState,
        trace: TraceWriter,
        *,
        reason: str,
    ) -> Prediction:
        prediction = Prediction(
            example_id=task.example_id,
            label=None,
            status=PredictionStatus.INVALID,
            evidence_ids=[],
            explanation="finalization budget exhausted without a valid submission",
        )
        state.prediction = prediction
        state.closed = True
        state.phase = "closed"
        state.remaining_steps = 0
        state.termination_reason = reason
        self.state_store.save(state)
        trace.write("question_closed", {"status": "invalid", "reason": reason})
        return prediction

    def _review_fallback_or_invalid(
        self,
        task: PublicTask,
        state: QuestionState,
        trace: TraceWriter,
        *,
        reason: str,
    ) -> Prediction:
        if state.review_failure_reason is None:
            state.review_failure_reason = reason
        if state.draft_prediction is None:
            return self._close_v2_invalid(task, state, trace, reason=reason)
        state.review_fallback_used = True
        return self._close_v2_completed(
            state,
            trace,
            state.draft_prediction,
            reason="review_fallback",
        )

    def _begin_v2_attempt(self, state: QuestionState) -> None:
        if state.phase == "exploration":
            state.exploration_step += 1
        elif state.phase == "finalization":
            state.finalization_step += 1
        elif state.phase == "review":
            state.review_step += 1
        else:  # pragma: no cover - caller validates active phase
            raise ValueError(f"cannot begin attempt in phase {state.phase}")
        state.step += 1
        state.usage.model_calls += 1
        self._update_v2_remaining(state)
        self.state_store.save(state)

    def _complete_v2_attempt(
        self,
        state: QuestionState,
        trace: TraceWriter,
        observation: dict[str, Any],
    ) -> None:
        state.last_observation = observation
        self._update_v2_remaining(state)
        trace.write("tool_result", {"phase": state.phase, **observation})
        self.state_store.save(state)

    def _record_v2_error(
        self,
        state: QuestionState,
        trace: TraceWriter,
        phase: str,
        kind: ErrorKind,
        message: str,
    ) -> None:
        bounded = message[:1000]
        state.errors.append(f"{phase} {kind} error: {bounded}")
        if phase == "review":
            state.review_failure_reason = f"{kind}: {bounded}"
        phase_counts = getattr(state.phase_errors, phase)
        setattr(phase_counts, kind, getattr(phase_counts, kind) + 1)
        state.last_observation = {
            "phase": phase,
            "error_type": kind,
            "error": bounded,
        }
        self._update_v2_remaining(state)
        trace.write(
            "recoverable_error",
            {
                "step": state.step - 1,
                "phase": phase,
                "phase_attempt": self._phase_step(state, phase),
                "error_type": kind,
                "error": bounded,
            },
        )
        self.state_store.save(state)

    def _transition(
        self,
        state: QuestionState,
        trace: TraceWriter,
        phase: Literal["exploration", "finalization", "review"],
        *,
        reason: str,
    ) -> None:
        previous = state.phase
        state.phase = phase
        self._update_v2_remaining(state)
        self.state_store.save(state)
        trace.write(
            "phase_transition",
            {"from": previous, "to": phase, "reason": reason},
        )

    def _update_v2_remaining(self, state: QuestionState) -> None:
        if state.phase_budgets is None:
            return
        if state.phase == "initialization":
            remaining = (
                state.phase_budgets.exploration
                + state.phase_budgets.finalization
                + state.phase_budgets.review
            )
        elif state.phase == "exploration":
            remaining = (
                max(0, state.phase_budgets.exploration - state.exploration_step)
                + state.phase_budgets.finalization
                + state.phase_budgets.review
            )
        elif state.phase == "finalization":
            remaining = (
                max(0, state.phase_budgets.finalization - state.finalization_step)
                + state.phase_budgets.review
            )
        elif state.phase == "review":
            remaining = max(0, state.phase_budgets.review - state.review_step)
        else:
            remaining = 0
        state.remaining_steps = remaining

    @staticmethod
    def _phase_step(state: QuestionState, phase: str) -> int:
        return int(getattr(state, f"{phase}_step"))

    def _initialize_long_context(
        self,
        task: PublicTask,
        session: ReportSession,
        state: QuestionState,
        trace: TraceWriter,
        *,
        resumed: bool,
    ) -> None:
        configured = self.config.long_context
        if not configured.enabled:
            if state.long_context_state is not None:
                raise ValueError(
                    "long-context resume mismatch: saved state enables a preview but config disables it"
                )
            return

        serialized = format_full_report(session)
        expected = LongContextState(
            report=task.report,
            serialized_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            paragraph_count=len(session.paragraphs),
            report_character_count=sum(
                len(paragraph.text) for paragraph in session.paragraphs
            ),
        )
        if resumed:
            saved = state.long_context_state
            if saved is None or (
                saved.report,
                saved.serialized_sha256,
                saved.paragraph_count,
                saved.report_character_count,
            ) != (
                expected.report,
                expected.serialized_sha256,
                expected.paragraph_count,
                expected.report_character_count,
            ):
                raise ValueError(
                    "long-context resume mismatch: report identity or serialization changed"
                )
            return
        if state.long_context_state is not None:
            raise ValueError("new question state unexpectedly contains long-context state")
        state.long_context_state = expected
        self.state_store.save(state)
        trace.write(
            "long_context_initialized",
            {
                "scope": configured.scope,
                "source": configured.source,
                "preload_as_evidence": configured.preload_as_evidence,
                "report_serialized_sha256": expected.serialized_sha256,
                "report_paragraph_count": expected.paragraph_count,
                "report_character_count": expected.report_character_count,
            },
        )

    def _claim_long_context_preview(
        self,
        state: QuestionState,
        session: ReportSession,
    ) -> str | None:
        if not self.config.long_context.enabled:
            return None
        long_context = state.long_context_state
        if long_context is None:
            raise ValueError("enabled long_context is missing durable state")
        if (
            state.phase != "exploration"
            or state.exploration_step != 1
            or long_context.injected
        ):
            return None
        serialized = format_full_report(session)
        if hashlib.sha256(serialized.encode("utf-8")).hexdigest() != (
            long_context.serialized_sha256
        ):
            raise ValueError("long-context report changed before injection")
        long_context.injected = True
        long_context.injection_attempt = 1
        self.state_store.save(state)
        return serialized

    def _initialize_retrieval(
        self,
        task: PublicTask,
        session: ReportSession,
        state: QuestionState,
        trace: TraceWriter,
        *,
        resumed: bool,
    ) -> None:
        configured = self.config.initial_retrieval
        if not configured.enabled:
            if state.initial_retrieval_state is not None:
                raise ValueError(
                    "initial retrieval resume mismatch: saved state has a seed but config disables it"
                )
            return
        if self.initial_retrieval is None:
            raise ValueError("enabled initial retrieval index is missing")

        paragraph_ids = self.initial_retrieval.paragraph_ids(task, session)
        expected = InitialRetrievalState(
            retrieval_file_sha256=self.initial_retrieval.file_sha256,
            retriever=self.initial_retrieval.retriever,
            top_k=self.initial_retrieval.top_k,
            report=task.report,
            paragraph_ids=paragraph_ids,
            preload_as_evidence=configured.preload_as_evidence,
        )
        if resumed:
            if state.initial_retrieval_state != expected:
                raise ValueError(
                    "initial retrieval resume mismatch: hash, retriever, top_k, report, or paragraph ids changed"
                )
            self._validate_seeded_evidence(state, session, expected)
            return
        if state.initial_retrieval_state is not None:
            raise ValueError("new question state unexpectedly contains initial retrieval")
        if (
            configured.preload_as_evidence
            and len(paragraph_ids) > self.config.max_total_unique_paragraphs
        ):
            raise ValueError(
                "initial retrieval exceeds maximum unique paragraph budget"
            )

        if configured.preload_as_evidence:
            source = f"fixed_rag:{expected.retriever}:top{expected.top_k}"
            for paragraph_id in paragraph_ids:
                state.evidence_ledger.append(
                    EvidenceRecord(
                        paragraph_id=paragraph_id,
                        exact_text=session.read(paragraph_id).text,
                        source=source,
                        reason_selected="seeded by frozen upstream retrieval",
                        read_order=len(state.evidence_ledger),
                        pinned=True,
                    )
                )
        state.initial_retrieval_state = expected
        self.state_store.save(state)
        trace.write(
            "retrieval_seed_loaded",
            {
                "retriever": expected.retriever,
                "top_k": expected.top_k,
                "retrieval_file_sha256": expected.retrieval_file_sha256,
                "paragraph_ids": expected.paragraph_ids,
                "preload_as_evidence": expected.preload_as_evidence,
            },
        )

    @staticmethod
    def _validate_seeded_evidence(
        state: QuestionState,
        session: ReportSession,
        retrieval: InitialRetrievalState,
    ) -> None:
        if not retrieval.preload_as_evidence:
            return
        records: dict[int, EvidenceRecord] = {}
        for record in state.evidence_ledger:
            if record.paragraph_id in records:
                raise ValueError("initial retrieval resume mismatch: duplicate evidence id")
            records[record.paragraph_id] = record
        expected_source = f"fixed_rag:{retrieval.retriever}:top{retrieval.top_k}"
        for paragraph_id in retrieval.paragraph_ids:
            record = records.get(paragraph_id)
            if (
                record is None
                or not record.pinned
                or record.source != expected_source
                or record.reason_selected != "seeded by frozen upstream retrieval"
                or record.exact_text != session.read(paragraph_id).text
            ):
                raise ValueError(
                    "initial retrieval resume mismatch: seeded evidence changed"
                )

    @staticmethod
    def _check_budget(current: int, maximum: int, skill: str) -> None:
        if current >= maximum:
            raise SkillError(f"{skill} call budget exhausted")

    def _complete_v1_step(
        self,
        state: QuestionState,
        trace: TraceWriter,
        observation: dict[str, Any],
    ) -> None:
        state.step += 1
        state.remaining_steps = max(0, self.config.max_steps - state.step)
        state.last_observation = observation
        trace.write("tool_result", observation)
        self.state_store.save(state)

    def _record_v1_error(
        self,
        state: QuestionState,
        trace: TraceWriter,
        message: str,
        *,
        kind: ErrorKind | None = None,
    ) -> None:
        state.step += 1
        state.remaining_steps = max(0, self.config.max_steps - state.step)
        state.errors.append(message[:1000])
        state.last_observation = {
            "error": message[:1000],
            **({"error_type": kind} if kind is not None else {}),
        }
        trace.write(
            "recoverable_error",
            {
                "step": state.step - 1,
                "error": message[:1000],
                **({"error_type": kind} if kind is not None else {}),
            },
        )
        self.state_store.save(state)
