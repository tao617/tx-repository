"""Bounded, resumable generic Agent with profile-selected Runtime skills."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue

from findver_agent.generic.config import GenericAgentConfig
from findver_agent.generic.models import (
    GenericConfidence,
    GenericEvidenceStatus,
    GenericPrediction,
    GenericPredictionStatus,
    GenericRiskFlag,
    GenericSubmitArguments,
    GenericTask,
    GenericTaskProfile,
)
from findver_agent.generic.prompt_builder import GenericPromptBuilder
from findver_agent.generic.skills import (
    GenericActionParseError,
    ParsedGenericAction,
    RuntimeSkill,
    SkillCatalog,
    default_skill_catalog,
)
from findver_agent.generic.state import (
    GenericEvidenceRecord,
    GenericQuestionState,
    GenericSkillRecord,
    GenericStateStore,
)
from findver_agent.model_backends.base import (
    GenerationConfig,
    ModelBackend,
    ProtocolDriftError,
    context_window_metadata,
)
from findver_agent.skills.base import SkillError
from findver_agent.trace_writer import TraceWriter


ErrorKind = Literal["parse", "model", "skill", "protocol", "protocol_drift"]
ActivePhase = Literal["exploration", "finalization", "review"]


class GenericAgent:
    """Protocol-v2-style reasoning loop whose skill set is selected by a task profile."""

    def __init__(
        self,
        *,
        backend: ModelBackend,
        generation: GenerationConfig,
        agent_config: GenericAgentConfig,
        profile: GenericTaskProfile,
        run_dir: Path,
        skill_catalog: SkillCatalog | None = None,
    ) -> None:
        self.backend = backend
        self.generation = generation
        self.config = agent_config
        self.profile = profile
        self.catalog = skill_catalog or default_skill_catalog()
        unknown = set(profile.allowed_skills) - self.catalog.names
        if unknown:
            raise ValueError(f"task profile references unknown skills: {sorted(unknown)}")
        unknown_limits = set(agent_config.skill_call_limits) - set(profile.allowed_skills)
        if unknown_limits:
            raise ValueError(
                "skill_call_limits contains skills outside the profile allowlist: "
                f"{sorted(unknown_limits)}"
            )
        if profile.evidence_policy == "required_read" and "read_context" not in profile.allowed_skills:
            raise ValueError("required_read evidence policy requires the read_context skill")
        self.state_store = GenericStateStore(run_dir / "state")
        self.trace_root = run_dir / "traces"

    async def run_task(self, task: GenericTask) -> GenericPrediction:
        skills = self.catalog.build(task, self.profile.allowed_skills)
        prompt_builder = GenericPromptBuilder(self.generation, self.profile, skills)
        state = self.state_store.load_or_create(task, self.profile, self.config)
        trace = TraceWriter(self.trace_root, task.task_id)
        if state.closed:
            if state.prediction is None:
                raise ValueError("closed generic state has no prediction")
            return state.prediction
        if state.phase == "initialization":
            self._transition(state, trace, "exploration", "initialization_complete")
            self.state_store.save(state)

        while not state.closed:
            if state.phase == "exploration" and (
                state.exploration_step >= state.phase_budgets.exploration
            ):
                state.forced_finalization = True
                self._transition(
                    state, trace, "finalization", "exploration_budget_exhausted"
                )
                self.state_store.save(state)
                continue
            if state.phase == "finalization" and (
                state.finalization_step >= state.phase_budgets.finalization
            ):
                return self._close_invalid(
                    state, trace, "finalization_budget_exhausted"
                )
            if state.phase == "review" and (
                state.review_step >= state.phase_budgets.review
            ):
                return self._review_fallback_or_invalid(
                    state, trace, "review_budget_exhausted"
                )
            if state.phase not in {"exploration", "finalization", "review"}:
                raise ValueError(f"invalid active generic phase: {state.phase}")

            phase = cast(ActivePhase, state.phase)
            self._begin_attempt(state, phase)
            self.state_store.save(state)
            messages = prompt_builder.build(task, state)
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
                    "step": state.step - 1,
                    "phase": phase,
                    "phase_attempt": self._phase_step(state, phase),
                    "messages": messages,
                    "allowed_skills": list(self.profile.allowed_skills),
                    "profile_id": self.profile.profile_id,
                    "request_profile": getattr(
                        self.backend, "request_profile", "generic_openai"
                    ),
                    "thinking_mode": getattr(
                        self.backend, "thinking_mode", "unsupported"
                    ),
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
                    },
                )
            except Exception as error:
                kind: ErrorKind = (
                    "protocol_drift"
                    if isinstance(error, ProtocolDriftError)
                    else "model"
                )
                self._record_error(
                    state,
                    trace,
                    phase,
                    kind,
                    f"model error: {type(error).__name__}: {error}",
                )
                continue

            try:
                action = self.catalog.parse_action(response.content, skills)
            except GenericActionParseError as error:
                self._record_error(state, trace, phase, "parse", str(error))
                continue

            trace.write(
                "action",
                {
                    "phase": phase,
                    "action": action.action,
                    "arguments": action.arguments.model_dump(mode="json"),
                    "control": action.control.model_dump(mode="json"),
                },
            )
            if phase in {"finalization", "review"} and action.action != "submit_answer":
                self._record_error(
                    state,
                    trace,
                    phase,
                    "protocol",
                    f"{phase} protocol error: only submit_answer is allowed",
                )
                continue
            if (
                phase == "exploration"
                and action.control.evidence_status == GenericEvidenceStatus.SUFFICIENT
                and action.action != "submit_answer"
            ):
                self._record_error(
                    state,
                    trace,
                    phase,
                    "protocol",
                    "exploration protocol inconsistency: sufficient evidence requires submit_answer",
                )
                continue
            if (
                phase == "finalization"
                and action.action == "submit_answer"
                and action.control.evidence_status != GenericEvidenceStatus.SUFFICIENT
                and action.control.confidence != GenericConfidence.LOW
                and not action.control.risk_flags
            ):
                self._record_error(
                    state,
                    trace,
                    phase,
                    "protocol",
                    "insufficient finalization evidence requires low confidence or a risk flag",
                )
                continue

            try:
                if action.action == "submit_answer":
                    prediction = self._prediction_from_submit(task, state, action)
                    self._apply_control(state, action)
                    if phase == "review":
                        if state.draft_prediction is None:
                            raise SkillError("review requires a verified draft")
                        state.review_completed = True
                        state.review_changed_answer = (
                            prediction.answer != state.draft_prediction.answer
                        )
                        state.review_changed_evidence = (
                            prediction.evidence_ids
                            != state.draft_prediction.evidence_ids
                        )
                        state.review_changed_explanation = (
                            prediction.explanation
                            != state.draft_prediction.explanation
                        )
                        return self._close_completed(
                            state, trace, prediction, "review_completed"
                        )
                    accepted = self._accept_draft(
                        state, trace, prediction, phase=phase
                    )
                    if accepted is not None:
                        return accepted
                    continue

                skill = skills[action.action]
                observation = self._execute_skill(
                    task,
                    state,
                    phase,
                    action,
                    skill,
                )
                self._apply_control(state, action)
                state.last_observation = observation
                self.state_store.save(state)
                trace.write(
                    "skill_observation",
                    {
                        "phase": phase,
                        "action": action.action,
                        "observation": observation,
                    },
                )
            except (SkillError, ValueError, TypeError) as error:
                self._record_error(
                    state,
                    trace,
                    phase,
                    "skill",
                    f"skill error: {error}",
                )
                continue

        if state.prediction is None:
            raise ValueError("closed generic state has no prediction")
        return state.prediction

    def _begin_attempt(
        self, state: GenericQuestionState, phase: ActivePhase
    ) -> None:
        state.step += 1
        state.usage.model_calls += 1
        if phase == "exploration":
            state.exploration_step += 1
        elif phase == "finalization":
            state.finalization_step += 1
        else:
            state.review_step += 1
        total = (
            state.phase_budgets.exploration
            + state.phase_budgets.finalization
            + state.phase_budgets.review
        )
        state.remaining_steps = max(0, total - state.step)

    @staticmethod
    def _phase_step(state: GenericQuestionState, phase: ActivePhase) -> int:
        return {
            "exploration": state.exploration_step,
            "finalization": state.finalization_step,
            "review": state.review_step,
        }[phase]

    def _execute_skill(
        self,
        task: GenericTask,
        state: GenericQuestionState,
        phase: ActivePhase,
        action: ParsedGenericAction,
        skill: RuntimeSkill,
    ) -> dict[str, JsonValue]:
        current = state.skill_counts[action.action]
        limit = self.config.skill_limit(action.action)
        if current >= limit:
            raise SkillError(f"{action.action} call budget is exhausted")
        arguments = action.arguments.model_dump(mode="json")
        if action.action == "read_context":
            requested = cast(list[str], arguments.get("unit_ids", []))
            known = {record.unit_id for record in state.evidence_ledger}
            if len(known | set(requested)) > self.config.max_total_evidence_units:
                raise SkillError("maximum unique evidence-unit budget would be exceeded")
        raw_observation = skill.execute(**arguments)
        state.skill_counts[action.action] = current + 1
        if action.action == "calculator":
            self._add_risk_flag(state, GenericRiskFlag.CALCULATION)
        if action.action == "read_context":
            self._record_read_evidence(task, state, raw_observation)
        observation = self._bounded_observation(raw_observation)
        state.skill_history.append(
            GenericSkillRecord(
                action=action.action,
                arguments=arguments,
                observation=observation,
                phase=phase,
                step=state.step,
            )
        )
        if len(state.skill_history) > self.config.max_history_records:
            state.skill_history = state.skill_history[-self.config.max_history_records :]
        return observation

    def _record_read_evidence(
        self,
        task: GenericTask,
        state: GenericQuestionState,
        observation: Mapping[str, JsonValue],
    ) -> None:
        units = observation.get("units")
        if not isinstance(units, list):
            raise SkillError("read_context returned an invalid units observation")
        public_units = {unit.unit_id: unit.text for unit in task.context}
        known = {record.unit_id for record in state.evidence_ledger}
        for raw in units:
            if not isinstance(raw, dict):
                raise SkillError("read_context returned a malformed unit")
            unit_id = raw.get("unit_id")
            text = raw.get("text")
            if not isinstance(unit_id, str) or not isinstance(text, str):
                raise SkillError("read_context returned a malformed unit")
            if public_units.get(unit_id) != text:
                raise SkillError("read_context observation does not match public context")
            if unit_id not in known:
                state.evidence_ledger.append(
                    GenericEvidenceRecord(
                        unit_id=unit_id,
                        exact_text=text,
                        read_order=len(state.evidence_ledger),
                    )
                )
                known.add(unit_id)

    def _bounded_observation(
        self, observation: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        value = dict(observation)
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= self.config.max_observation_characters:
            return value
        preview_limit = max(1, self.config.max_observation_characters - 128)
        return {
            "truncated": True,
            "original_characters": len(encoded),
            "preview": encoded[:preview_limit],
        }

    def _prediction_from_submit(
        self,
        task: GenericTask,
        state: GenericQuestionState,
        action: ParsedGenericAction,
    ) -> GenericPrediction:
        arguments = cast(GenericSubmitArguments, action.arguments)
        answer = self.profile.answer.validate_answer(arguments.answer)
        if self.profile.answer.explanation_required and not arguments.explanation.strip():
            raise SkillError("the task profile requires a non-empty explanation")
        self._validate_evidence(task, state, arguments.evidence_ids)
        return GenericPrediction(
            task_id=task.task_id,
            status=GenericPredictionStatus.COMPLETED,
            answer=answer,
            evidence_ids=list(arguments.evidence_ids),
            explanation=arguments.explanation,
        )

    def _validate_evidence(
        self,
        task: GenericTask,
        state: GenericQuestionState,
        evidence_ids: list[str],
    ) -> None:
        available = {unit.unit_id for unit in task.context}
        unknown = set(evidence_ids) - available
        if unknown:
            raise SkillError(f"submitted evidence contains unknown unit IDs: {sorted(unknown)}")
        policy = self.profile.evidence_policy
        if policy == "none" and evidence_ids:
            raise SkillError("this task profile does not allow evidence IDs")
        if policy in {"read_only", "required_read"}:
            read = {record.unit_id for record in state.evidence_ledger}
            unread = set(evidence_ids) - read
            if unread:
                raise SkillError(
                    f"submitted evidence must be read through read_context: {sorted(unread)}"
                )
        if policy == "required_read" and not evidence_ids:
            raise SkillError("this task profile requires at least one read evidence unit")

    def _accept_draft(
        self,
        state: GenericQuestionState,
        trace: TraceWriter,
        prediction: GenericPrediction,
        *,
        phase: ActivePhase,
    ) -> GenericPrediction | None:
        state.draft_prediction = prediction
        reasons = self._review_reasons(state)
        if reasons:
            state.review_triggered = True
            state.review_trigger_reasons = reasons
            state.last_observation = {
                "draft_accepted": True,
                "review_required": True,
                "review_reasons": reasons,
            }
            self._transition(state, trace, "review", "review_policy_triggered")
            self.state_store.save(state)
            trace.write(
                "review_triggered",
                {"policy": self.config.review_policy, "reasons": reasons, "phase": phase},
            )
            return None
        return self._close_completed(state, trace, prediction, "submission_accepted")

    def _review_reasons(self, state: GenericQuestionState) -> list[str]:
        if self.config.review_policy == "none":
            return []
        if self.config.review_policy == "mandatory":
            return ["mandatory_policy"]
        reasons: list[str] = []
        if state.confidence == GenericConfidence.LOW:
            reasons.append("low_confidence")
        if state.evidence_status != GenericEvidenceStatus.SUFFICIENT:
            reasons.append(f"evidence_{state.evidence_status.value}")
        if state.forced_finalization:
            reasons.append("forced_finalization")
        if state.skill_counts.get("calculator", 0) > 0:
            reasons.append("calculator_used")
        reasons.extend(f"risk_{flag.value}" for flag in state.risk_flags)
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _add_risk_flag(
        state: GenericQuestionState, risk_flag: GenericRiskFlag
    ) -> None:
        if risk_flag not in state.risk_flags:
            state.risk_flags.append(risk_flag)

    def _apply_control(
        self, state: GenericQuestionState, action: ParsedGenericAction
    ) -> None:
        state.evidence_status = action.control.evidence_status
        state.confidence = action.control.confidence
        state.open_questions = list(action.control.missing_information)
        if action.control.evidence_status == GenericEvidenceStatus.CONFLICTING:
            self._add_risk_flag(state, GenericRiskFlag.CONFLICTING_EVIDENCE)
        for flag in action.control.risk_flags:
            self._add_risk_flag(state, flag)

    def _record_error(
        self,
        state: GenericQuestionState,
        trace: TraceWriter,
        phase: ActivePhase,
        kind: ErrorKind,
        message: str,
    ) -> None:
        bounded = message[:1_000]
        state.errors.append(bounded)
        state.last_observation = {"error_kind": kind, "error": bounded}
        self.state_store.save(state)
        trace.write(
            "attempt_error",
            {
                "phase": phase,
                "phase_attempt": self._phase_step(state, phase),
                "kind": kind,
                "error": bounded,
            },
        )

    def _transition(
        self,
        state: GenericQuestionState,
        trace: TraceWriter,
        target: ActivePhase,
        reason: str,
    ) -> None:
        previous = state.phase
        state.phase = target
        trace.write(
            "phase_transition",
            {"from": previous, "to": target, "reason": reason},
        )

    def _close_completed(
        self,
        state: GenericQuestionState,
        trace: TraceWriter,
        prediction: GenericPrediction,
        reason: str,
    ) -> GenericPrediction:
        state.prediction = prediction
        state.closed = True
        state.phase = "closed"
        state.termination_reason = reason
        self.state_store.save(state)
        trace.write(
            "question_closed",
            {"status": "completed", "reason": reason},
        )
        return prediction

    def _close_invalid(
        self,
        state: GenericQuestionState,
        trace: TraceWriter,
        reason: str,
    ) -> GenericPrediction:
        prediction = GenericPrediction(
            task_id=state.task_id,
            status=GenericPredictionStatus.INVALID,
            answer=None,
            evidence_ids=[],
            explanation="generic agent did not produce a valid submission",
        )
        state.prediction = prediction
        state.closed = True
        state.phase = "closed"
        state.termination_reason = reason
        self.state_store.save(state)
        trace.write(
            "question_closed",
            {"status": "invalid", "reason": reason},
        )
        return prediction

    def _review_fallback_or_invalid(
        self,
        state: GenericQuestionState,
        trace: TraceWriter,
        reason: str,
    ) -> GenericPrediction:
        if state.draft_prediction is None:
            return self._close_invalid(state, trace, reason)
        state.review_fallback_used = True
        state.review_failure_reason = reason
        return self._close_completed(
            state,
            trace,
            state.draft_prediction,
            "review_fallback",
        )
