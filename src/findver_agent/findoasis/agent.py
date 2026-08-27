"""Bounded, resumable FinOASIS protocol-v3 agent loop."""

from __future__ import annotations

import hashlib
from pathlib import Path

from findver_agent.config import AgentConfig
from findver_agent.model_backends.base import (
    GenerationConfig,
    ModelBackend,
    ProtocolDriftError,
    context_window_metadata,
)
from findver_agent.report_store import ReportSession, ReportStore
from findver_agent.schemas import Prediction, PredictionStatus, PublicTask
from findver_agent.skills import ReadParagraphsSkill, SearchReportSkill
from findver_agent.skills.base import SkillError
from findver_agent.trace_writer import TraceWriter

from .actions import (
    Action,
    ActionParseError,
    ReadParagraphsAction,
    SearchReportAction,
    parse_action,
)
from .contracts import (
    FinalCertificateStatus,
    ObligationStatus,
    ObligationType,
    QuestionPhase,
    SkillName,
    SkillResult,
    SkillResultStatus,
)
from .prompt_builder import PromptBuilder
from .registry import REGISTRY, REGISTRY_SHA256
from .router import RuntimeFacts, resolve_available_skills
from .seeder import seed_obligations
from .state import (
    BoundedObservation,
    EvidenceLedgerEntry,
    FinOASISQuestionState,
    FinOASISStateStore,
    ReportSearchHit,
    ReportSearchRecord,
    ResumeIdentity,
    SkillAvailabilityRecord,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


class FinOASISAgent:
    """Independent protocol-v3 loop; legacy protocol objects are never constructed."""

    def __init__(
        self,
        *,
        backend: ModelBackend,
        generation: GenerationConfig,
        agent_config: AgentConfig,
        report_store: ReportStore,
        run_dir: Path,
    ) -> None:
        if agent_config.protocol_version != "v3" or agent_config.findoasis is None:
            raise ValueError("FinOASISAgent requires an explicit protocol-v3 config")
        self.backend = backend
        self.generation = generation
        self.config = agent_config
        self.findoasis_config = agent_config.findoasis
        self.report_store = report_store
        self.state_store = FinOASISStateStore(run_dir / "state")
        self.trace_root = run_dir / "traces"
        self.prompt_builder = PromptBuilder()

    async def run_question(self, task: PublicTask) -> Prediction:
        session = self.report_store.open_session(task.report)
        identity = self._resume_identity(task)
        state_path_existed = self.state_store.path_for(task.example_id).exists()
        total_steps = (
            self.config.exploration_steps
            + self.config.finalization_steps
            + self.config.review_steps
        )
        state = self.state_store.load_or_create(
            task,
            identity,
            total_steps,
            exploration_steps=self.config.exploration_steps,
            finalization_steps=self.config.finalization_steps,
            review_steps=self.config.review_steps,
        )
        trace = TraceWriter(self.trace_root, task.example_id)

        if not state_path_existed:
            self._initialize_obligations(state, trace)
        if state.closed:
            if state.prediction is None:
                raise ValueError("closed protocol-v3 state has no prediction")
            return state.prediction

        search = SearchReportSkill(session)
        read = ReadParagraphsSkill(
            session,
            max_paragraphs=self.config.max_paragraphs_per_read,
        )

        while not state.closed:
            if self._advance_exhausted_phase(state, trace):
                continue

            facts = self._runtime_facts(state)
            resolution = resolve_available_skills(
                state, self.findoasis_config, facts
            )
            if not resolution.available_skills:
                if state.phase is QuestionPhase.EXPLORATION:
                    state.forced_finalization = True
                    state.phase = QuestionPhase.FINALIZATION
                    self.state_store.save(state)
                    trace.write(
                        "phase_transition",
                        {"phase": "finalization", "reason": "no_available_skill"},
                    )
                    continue
                return self._close_invalid(
                    state,
                    trace,
                    "no Skill is available in the current phase",
                )

            contracts = tuple(REGISTRY[name] for name in resolution.available_skills)
            messages = self.prompt_builder.build(
                state,
                contracts,
                phase_budget=self._phase_budget_summary(state),
            )
            trace.write(
                "model_request",
                {
                    "step": state.step,
                    "phase": state.phase.value,
                    "available_skills": [name.value for name in resolution.available_skills],
                    "messages": messages,
                    **context_window_metadata(
                        messages,
                        max_output_tokens=self.generation.max_output_tokens,
                        model_context_window_tokens=getattr(
                            self.backend, "model_context_window_tokens", None
                        ),
                    ),
                },
            )

            # Charge and persist before external model execution. A process interruption
            # therefore resumes from the next bounded attempt instead of replaying one.
            state.charge_attempt()
            state.usage.model_calls += 1
            self.state_store.save(state)
            try:
                response = await self.backend.generate(messages, self.generation)
            except Exception as error:
                kind = (
                    "protocol_drift"
                    if isinstance(error, ProtocolDriftError)
                    else "model"
                )
                state.record_error(kind, f"{type(error).__name__}: {error}")
                self.state_store.save(state)
                trace.write(
                    "runtime_error",
                    {"step": state.step, "kind": kind, "message": str(error)[:500]},
                )
                continue

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
                    "finish_reason": response.finish_reason,
                },
            )
            try:
                action = parse_action(response.content)
            except ActionParseError as error:
                state.record_error("parse", str(error))
                self.state_store.save(state)
                trace.write(
                    "runtime_error",
                    {"step": state.step, "kind": "parse", "message": str(error)[:500]},
                )
                continue

            trace.write("action", action.model_dump(mode="json"))
            skill_name = SkillName(action.action)
            decision = resolution.decision_for(skill_name)
            if (
                not decision.available
                or action.control.target_obligation_id
                not in decision.target_obligation_ids
            ):
                self._reject_unavailable(state, action, resolution)
                self.state_store.save(state)
                trace.write(
                    "skill_rejected",
                    {
                        "step": state.step,
                        "skill": skill_name.value,
                        "target_obligation_id": action.control.target_obligation_id,
                        "reason": decision.reason,
                    },
                )
                continue

            candidate = state.model_copy(deep=True)
            try:
                self._execute_action(candidate, action, search=search, read=read)
                self._apply_model_control(candidate, action)
                candidate.skill_call_counts[skill_name] = (
                    candidate.skill_call_counts.get(skill_name, 0) + 1
                )
                candidate.usage.local_skill_calls += 1
                candidate.skill_availability_history.append(
                    self._availability_record(
                        candidate,
                        resolution,
                        selected=skill_name,
                        target=action.control.target_obligation_id,
                    )
                )
                candidate = FinOASISQuestionState.model_validate(
                    candidate.model_dump(mode="python")
                )
            except (SkillError, ValueError, TypeError) as error:
                state.record_error("skill", str(error))
                state.last_observation = BoundedObservation(
                    skill=skill_name,
                    status="invalid",
                    target_obligation_id=action.control.target_obligation_id,
                    diagnostics=[str(error)[:500]],
                )
                self.state_store.save(state)
                trace.write(
                    "runtime_error",
                    {"step": state.step, "kind": "skill", "message": str(error)[:500]},
                )
                continue

            state._adopt(candidate)
            self.state_store.save(state)
            trace.write(
                "skill_result",
                {
                    "step": state.step,
                    "skill": skill_name.value,
                    "target_obligation_id": action.control.target_obligation_id,
                    "observation": (
                        state.last_observation.model_dump(mode="json")
                        if state.last_observation is not None
                        else None
                    ),
                },
            )

        assert state.prediction is not None
        return state.prediction

    def _resume_identity(self, task: PublicTask) -> ResumeIdentity:
        report_path = (self.report_store.root / task.report).resolve(strict=True)
        if report_path.parent != self.report_store.root:
            raise ValueError("report escaped the ReportStore root")
        corpus = self.findoasis_config.rule_corpus
        return ResumeIdentity.create(
            task,
            report_sha256=_sha256_bytes(report_path.read_bytes()),
            config_sha256=_sha256_text(self.config.model_dump_json()),
            registry_sha256=REGISTRY_SHA256,
            obligation_policy_sha256=_sha256_text(
                self.findoasis_config.obligation_policy.model_dump_json()
            ),
            rule_corpus_id=corpus.corpus_id,
            rule_manifest_sha256=corpus.manifest_sha256,
            rule_records_sha256=corpus.records_sha256,
        )

    def _initialize_obligations(
        self, state: FinOASISQuestionState, trace: TraceWriter
    ) -> None:
        if state.obligations or state.next_obligation_sequence != 1:
            raise ValueError("new protocol-v3 state must have an empty obligation graph")
        state.phase = QuestionPhase.EXPLORATION
        proposals = seed_obligations(state.statement)
        for proposal in proposals:
            state.open_obligation(proposal)
        self.state_store.save(state)
        trace.write(
            "obligations_seeded",
            {
                "count": len(proposals),
                "types": [proposal.type.value for proposal in proposals],
            },
        )

    def _runtime_facts(self, state: FinOASISQuestionState) -> RuntimeFacts:
        candidates: list[int] = []
        for record in state.report_search_history:
            for hit in record.hits:
                if hit.paragraph_id not in candidates:
                    candidates.append(hit.paragraph_id)
        read_ids = [
            entry.paragraph_id
            for entry in state.evidence_ledger.values()
            if entry.source == "report_paragraph"
        ]
        return RuntimeFacts(
            search_candidate_paragraph_ids=tuple(candidates),
            read_paragraph_ids=tuple(dict.fromkeys(read_ids)),
            bound_value_refs=tuple(state.numeric_value_ledger),
            read_rule_evidence_refs=tuple(state.rule_evidence_ledger),
            rule_corpus_valid=False,
            budget_exhausted=state.phase
            in {QuestionPhase.FINALIZATION, QuestionPhase.REVIEW},
        )

    def _execute_action(
        self,
        state: FinOASISQuestionState,
        action: Action,
        *,
        search: SearchReportSkill,
        read: ReadParagraphsSkill,
    ) -> None:
        target = action.control.target_obligation_id
        target_obligation = state.obligation(target)
        if isinstance(action, SearchReportAction):
            result = search.execute(**action.arguments.model_dump())
            hits = [ReportSearchHit.model_validate(item) for item in result["hits"]]
            state.report_search_history.append(
                ReportSearchRecord(
                    query=action.arguments.query,
                    target_obligation_id=target,
                    step=state.step,
                    hits=hits,
                )
            )
            state.apply_skill_result(
                SkillResult(
                    status=SkillResultStatus.PARTIAL,
                    target_obligation_id=target,
                    partial_obligation_ids=[target],
                    diagnostics=[f"report search returned {len(hits)} candidates"],
                )
            )
            state.last_observation = BoundedObservation(
                skill=SkillName.SEARCH_REPORT,
                status="partial",
                target_obligation_id=target,
                references=[f"paragraph:{hit.paragraph_id}" for hit in hits],
            )
            return

        if isinstance(action, ReadParagraphsAction):
            candidates = {
                hit.paragraph_id
                for record in state.report_search_history
                for hit in record.hits
            }
            requested = set(action.arguments.paragraph_ids)
            if not requested <= candidates:
                raise SkillError("read_paragraphs may read only current search candidates")
            already_read = {
                entry.paragraph_id
                for entry in state.evidence_ledger.values()
                if entry.source == "report_paragraph"
            }
            if requested & already_read:
                raise SkillError("read_paragraphs cannot reread ledgered paragraphs")
            result = read.execute(**action.arguments.model_dump())
            evidence_refs: list[str] = []
            for paragraph in result["paragraphs"]:
                paragraph_id = int(paragraph["paragraph_id"])
                text = str(paragraph["text"])
                evidence_ref = f"report-paragraph:{paragraph_id}"
                state.evidence_ledger[evidence_ref] = EvidenceLedgerEntry(
                    evidence_id=evidence_ref,
                    source="report_paragraph",
                    paragraph_id=paragraph_id,
                    exact_text=text,
                    exact_text_sha256=_sha256_text(text),
                )
                evidence_refs.append(evidence_ref)
            satisfies = target_obligation.type is ObligationType.DOCUMENT_FACT
            skill_result = SkillResult(
                status=(
                    SkillResultStatus.SATISFIED
                    if satisfies
                    else SkillResultStatus.PARTIAL
                ),
                target_obligation_id=target,
                satisfied_obligation_ids=[target] if satisfies else [],
                partial_obligation_ids=[] if satisfies else [target],
                evidence_refs=evidence_refs,
                diagnostics=[f"read {len(evidence_refs)} exact report paragraphs"],
            )
            state.apply_skill_result(skill_result)
            state.last_observation = BoundedObservation(
                skill=SkillName.READ_PARAGRAPHS,
                status="satisfied" if satisfies else "partial",
                target_obligation_id=target,
                references=evidence_refs,
            )
            return

        raise SkillError(f"{action.action} is not implemented by this Runtime phase")

    def _apply_model_control(
        self, state: FinOASISQuestionState, action: Action
    ) -> None:
        control = action.control
        if (
            control.open_obligations
            and not self.findoasis_config.obligation_policy.model_may_open_obligations
        ):
            raise ValueError("configuration forbids model-opened obligations")
        for proposal in control.open_obligations:
            state.open_obligation(proposal)
        state.apply_model_deltas(control.obligation_deltas)
        state.confidence = control.confidence

    def _reject_unavailable(self, state, action, resolution) -> None:
        skill = SkillName(action.action)
        decision = resolution.decision_for(skill)
        known_ids = {obligation.obligation_id for obligation in state.obligations}
        target = (
            action.control.target_obligation_id
            if action.control.target_obligation_id in known_ids
            else None
        )
        state.skill_rejection_counts[skill] = (
            state.skill_rejection_counts.get(skill, 0) + 1
        )
        state.record_error(
            "protocol",
            f"unavailable Skill {skill.value}: {decision.reason}",
        )
        state.skill_availability_history.append(
            self._availability_record(
                state,
                resolution,
                rejected=skill,
                target=target,
            )
        )
        state.last_observation = BoundedObservation(
            skill=skill,
            status="rejected",
            target_obligation_id=target,
            diagnostics=[decision.reason],
        )

    @staticmethod
    def _availability_record(
        state: FinOASISQuestionState,
        resolution,
        *,
        selected: SkillName | None = None,
        rejected: SkillName | None = None,
        target: str | None = None,
    ) -> SkillAvailabilityRecord:
        reasons = [
            f"{decision.skill.value}: {decision.reason}"[:160]
            for decision in resolution.decisions
        ]
        return SkillAvailabilityRecord(
            phase=state.phase,
            step=state.step,
            available_skills=list(resolution.available_skills),
            selected_skill=selected,
            rejected_skill=rejected,
            target_obligation_id=target,
            availability_reasons=list(dict.fromkeys(reasons)),
        )

    def _advance_exhausted_phase(
        self, state: FinOASISQuestionState, trace: TraceWriter
    ) -> bool:
        attempts = state.phase_attempts
        if attempts.used_for(state.phase) < attempts.limit_for(state.phase):
            return False
        if state.phase is QuestionPhase.EXPLORATION:
            state.phase = QuestionPhase.FINALIZATION
            state.forced_finalization = True
            self.state_store.save(state)
            trace.write(
                "phase_transition",
                {"phase": "finalization", "reason": "exploration_budget_exhausted"},
            )
            return True
        if (
            state.phase is QuestionPhase.FINALIZATION
            and self.config.review_policy != "none"
            and attempts.review_limit > 0
        ):
            state.phase = QuestionPhase.REVIEW
            self.state_store.save(state)
            trace.write(
                "phase_transition",
                {"phase": "review", "reason": "finalization_budget_exhausted"},
            )
            return True
        self._close_invalid(state, trace, f"{state.phase.value} budget exhausted")
        return True

    @staticmethod
    def _phase_budget_summary(state: FinOASISQuestionState) -> str:
        used = state.phase_attempts.used_for(state.phase)
        limit = state.phase_attempts.limit_for(state.phase)
        return (
            f"attempt {used + 1}/{limit}; {limit - used - 1} "
            f"{state.phase.value} attempts remain afterward"
        )

    def _close_invalid(
        self,
        state: FinOASISQuestionState,
        trace: TraceWriter,
        reason: str,
    ) -> Prediction:
        prediction = Prediction(
            example_id=state.example_id,
            label=None,
            status=PredictionStatus.INVALID,
            evidence_ids=[],
            explanation=reason,
        )
        state.unresolved_obligation_ids = [
            obligation.obligation_id
            for obligation in state.obligations
            if obligation.status is not ObligationStatus.SATISFIED
        ]
        state.final_certificate_status = FinalCertificateStatus.INCOMPLETE
        state.prediction = prediction
        state.termination_reason = reason[:160]
        state.phase = QuestionPhase.CLOSED
        state.closed = True
        self.state_store.save(state)
        trace.write("question_closed", {"status": "invalid", "reason": reason[:500]})
        return prediction


__all__ = ["FinOASISAgent"]
