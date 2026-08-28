"""Bounded, resumable FinOASIS protocol-v3 agent loop."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from findver_agent.config import AgentConfig
from findver_agent.financial_dsl.claim_parser import parse_claim_values
from findver_agent.financial_dsl.executor import (
    FinDSLExecutionError,
    execute_financial_program,
    numeric_certificate_sha256,
)
from findver_agent.financial_rules.applicability import (
    RuleApplicabilityError,
    check_rule_applicability,
    rule_applicability_certificate_sha256,
)
from findver_agent.financial_rules.corpus import (
    FrozenRuleCorpus,
    RuleCorpusError,
    rule_record_sha256,
)
from findver_agent.financial_rules.models import RuleApplicabilityResult
from findver_agent.model_backends.base import (
    GenerationConfig,
    ModelBackend,
    ProtocolDriftError,
    context_window_metadata,
)
from findver_agent.report_store import ReportSession, ReportStore
from findver_agent.schemas import Confidence, Prediction, PredictionStatus, PublicTask
from findver_agent.skills import ReadParagraphsSkill, SearchReportSkill
from findver_agent.skills.base import SkillError
from findver_agent.trace_writer import TraceWriter

from .actions import (
    Action,
    ActionParseError,
    BindFinancialValueArguments,
    BindFinancialValueAction,
    CheckRuleApplicabilityAction,
    ExecuteFinancialProgramAction,
    ReadParagraphsAction,
    ReadFinancialRulesAction,
    ReadTableRegionAction,
    SearchFinancialRulesAction,
    SearchReportAction,
    SubmitAnswerAction,
    parse_action,
)
from .claim_verifier import (
    ClaimCertificateVerifier,
    ClaimVerificationResult,
    claim_verification_certificate_sha256,
)
from .contracts import (
    CertificateEnvelope,
    CertificateKind,
    FinalCertificateStatus,
    Obligation,
    ObligationStatus,
    ObligationType,
    QuestionPhase,
    SkillName,
    SkillResult,
    SkillResultStatus,
)
from .operand_slots import match_operand_slots
from .prompt_builder import PromptBuilder
from .registry import REGISTRY, REGISTRY_SHA256
from .router import RuleApplicabilityMetadata, RuntimeFacts, resolve_available_skills
from .seeder import seed_obligations
from .state import (
    BoundedObservation,
    EvidenceLedgerEntry,
    FinOASISQuestionState,
    FinOASISStateStore,
    FinancialProgramLedgerEntry,
    NumericValueLedgerEntry,
    RuleEvidenceLedgerEntry,
    RuleSearchHitRecord,
    RuleSearchRecord,
    ReportSearchHit,
    ReportSearchRecord,
    ResumeIdentity,
    SkillAvailabilityRecord,
    TableCandidateRecord,
)
from .table_region import TableRegionError, TableRegionReader
from .value_binding import ValueAmbiguityFlag, bind_financial_value


_UNKNOWN_METADATA = {"", "?", "n/a", "na", "none", "unknown", "unspecified"}
_UNIT_METADATA_ALIASES = {
    "usd": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "cny": "CNY",
    "rmb": "CNY",
    "jpy": "JPY",
    "yen": "JPY",
    "percentage": "percentage",
    "percentage point": "percentage",
    "percentage points": "percentage",
    "percent": "percentage",
    "%": "percentage",
    "share": "shares",
    "shares": "shares",
}
_SCALE_METADATA_ALIASES = {
    "1": "one",
    "one": "one",
    "ones": "one",
    "1000": "thousand",
    "1e3": "thousand",
    "k": "thousand",
    "thousand": "thousand",
    "thousands": "thousand",
    "1000000": "million",
    "1e6": "million",
    "m": "million",
    "mn": "million",
    "million": "million",
    "millions": "million",
    "1000000000": "billion",
    "1e9": "billion",
    "b": "billion",
    "bn": "billion",
    "billion": "billion",
    "billions": "billion",
    "1000000000000": "trillion",
    "1e12": "trillion",
    "tn": "trillion",
    "trillion": "trillion",
    "trillions": "trillion",
}


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
        try:
            self.rule_corpus = (
                FrozenRuleCorpus.load(self.findoasis_config.rule_corpus)
                if self.findoasis_config.rule_corpus.enabled
                else None
            )
        except RuleCorpusError as error:
            raise ValueError(f"configured frozen rule corpus is invalid: {error}") from error
        self.claim_verifier = ClaimCertificateVerifier(self.rule_corpus)

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
        self._validate_rule_state_against_corpus(state)
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
        table_reader = TableRegionReader(session)

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
                if (
                    state.phase is QuestionPhase.REVIEW
                    and state.draft_prediction is not None
                    and state.draft_certificate_ref is not None
                ):
                    return self._close_with_review_fallback(
                        state,
                        trace,
                        "no Review Skill remained available",
                    )
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
                if state.phase is QuestionPhase.REVIEW and state.draft_prediction:
                    state.review_failure_reason = f"{kind}: {type(error).__name__}"[:160]
                self.state_store.save(state)
                trace.write(
                    "runtime_error",
                    {
                        "step": state.step,
                        "phase": state.phase.value,
                        "kind": kind,
                        "message": str(error)[:500],
                    },
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
                if state.phase is QuestionPhase.REVIEW and state.draft_prediction:
                    state.review_failure_reason = f"parse: {error}"[:160]
                self.state_store.save(state)
                trace.write(
                    "runtime_error",
                    {
                        "step": state.step,
                        "phase": state.phase.value,
                        "kind": "parse",
                        "message": str(error)[:500],
                    },
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
                self._execute_action(
                    candidate,
                    action,
                    session=session,
                    search=search,
                    read=read,
                    table_reader=table_reader,
                )
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
                if state.phase is QuestionPhase.REVIEW and state.draft_prediction:
                    state.review_failure_reason = f"skill: {error}"[:160]
                state.last_observation = BoundedObservation(
                    skill=skill_name,
                    status="invalid",
                    target_obligation_id=action.control.target_obligation_id,
                    diagnostics=[str(error)[:500]],
                )
                self.state_store.save(state)
                trace.write(
                    "runtime_error",
                    {
                        "step": state.step,
                        "phase": state.phase.value,
                        "kind": "skill",
                        "skill": skill_name.value,
                        "failure_categories": self._skill_failure_categories(
                            skill_name, str(error)
                        ),
                        "message": str(error)[:500],
                    },
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
            if skill_name is SkillName.SUBMIT_ANSWER and state.last_observation:
                references = state.last_observation.references
                if references:
                    final_certificate = (
                        state.final_verification_certificate_ledger.get(
                            references[0]
                        )
                    )
                    if final_certificate is not None:
                        trace.write(
                            "claim_certificate_verification",
                            {
                                "certificate_id": final_certificate.certificate_id,
                                "result": final_certificate.result.value,
                                "failure_codes": [
                                    item.value
                                    for item in final_certificate.failure_codes
                                ],
                                "numeric_certificate_count": len(
                                    final_certificate.numeric_certificate_refs
                                ),
                                "rule_certificate_count": len(
                                    final_certificate.rule_certificate_refs
                                ),
                                "unresolved_obligation_count": len(
                                    final_certificate.unresolved_obligation_ids
                                ),
                            },
                        )
                        if (
                            state.phase is QuestionPhase.REVIEW
                            and state.draft_certificate_ref
                            == final_certificate.certificate_id
                        ):
                            trace.write(
                                "review_triggered",
                                {"reasons": state.review_trigger_reasons},
                            )
            if state.closed:
                trace.write(
                    "question_closed",
                    {
                        "status": state.prediction.status.value,
                        "reason": state.termination_reason,
                        "final_certificate_status": state.final_certificate_status.value,
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
        claim_values = parse_claim_values(state.statement)
        state.claim_value_ledger = {
            claim.claim_value_id: claim for claim in claim_values
        }
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

    def _validate_rule_state_against_corpus(
        self, state: FinOASISQuestionState
    ) -> None:
        """Rebind persisted rule records to the currently hash-verified corpus."""

        if not state.rule_evidence_ledger:
            return
        if self.rule_corpus is None:
            raise ValueError("persisted rule evidence requires a frozen rule corpus")
        for evidence in state.rule_evidence_ledger.values():
            try:
                frozen = self.rule_corpus.record(evidence.rule_id)
            except RuleCorpusError as error:
                raise ValueError(
                    "persisted rule evidence is absent from the frozen corpus"
                ) from error
            if evidence.record != frozen or evidence.rule_sha256 != rule_record_sha256(
                frozen
            ):
                raise ValueError(
                    "persisted rule evidence differs from the frozen corpus record"
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
        rule_candidates = tuple(
            dict.fromkeys(
                hit.rule_id
                for record in state.rule_search_history
                for hit in record.hits
            )
        )
        applicability_metadata = self._applicability_metadata(state)
        return RuntimeFacts(
            search_candidate_paragraph_ids=tuple(candidates),
            read_paragraph_ids=tuple(dict.fromkeys(read_ids)),
            table_candidate_ids=tuple(
                candidate.table_id for candidate in state.table_candidates
            ),
            read_table_evidence_refs=tuple(
                reference
                for reference, entry in state.evidence_ledger.items()
                if entry.source == "table_cell"
            ),
            bound_value_refs=tuple(state.numeric_value_ledger),
            rule_corpus_valid=self.rule_corpus is not None,
            rule_candidate_ids=rule_candidates,
            read_rule_evidence_refs=tuple(state.rule_evidence_ledger),
            applicability_metadata=applicability_metadata,
            budget_exhausted=(
                state.forced_finalization
                and state.phase
                in {QuestionPhase.FINALIZATION, QuestionPhase.REVIEW}
            ),
        )

    @staticmethod
    def _applicability_metadata(
        state: FinOASISQuestionState,
    ) -> RuleApplicabilityMetadata | None:
        candidates = [
            obligation
            for obligation in state.obligations
            if obligation.type is ObligationType.RULE_APPLICABILITY
            and obligation.status is not ObligationStatus.SATISFIED
        ]
        if not candidates:
            return None
        obligation = candidates[0]
        metadata = obligation.metadata
        if not (
            metadata.jurisdiction
            and metadata.effective_date
            and metadata.entity_scope
        ):
            return None
        document_refs: list[str] = []
        for dependency_id in obligation.dependency_ids:
            dependency = state.obligation(dependency_id)
            if dependency.type is ObligationType.DOCUMENT_FACT:
                document_refs.extend(
                    reference
                    for reference in dependency.evidence_refs
                    if reference in state.evidence_ledger
                )
        return RuleApplicabilityMetadata(
            jurisdiction=metadata.jurisdiction,
            effective_date=metadata.effective_date,
            entity_scope=metadata.entity_scope,
            document_evidence_refs=tuple(dict.fromkeys(document_refs)),
        )

    def _execute_action(
        self,
        state: FinOASISQuestionState,
        action: Action,
        *,
        session: ReportSession,
        search: SearchReportSkill,
        read: ReadParagraphsSkill,
        table_reader: TableRegionReader,
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
            self._add_relevant_table_candidates(
                state,
                session=session,
                table_reader=table_reader,
                paragraph_ids={hit.paragraph_id for hit in hits},
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

        if isinstance(action, ReadTableRegionAction):
            if action.arguments.table_id not in {
                candidate.table_id for candidate in state.table_candidates
            }:
                raise SkillError("read_table_region may read only searched table candidates")
            try:
                region = table_reader.read(**action.arguments.model_dump())
            except TableRegionError as error:
                raise SkillError(str(error)) from error
            pending_entries: dict[str, EvidenceLedgerEntry] = {}
            for cell in region.cells:
                if not cell.text:
                    continue
                evidence_ref = (
                    f"table-cell:{cell.table_id}:{cell.row_index}:{cell.column_index}"
                )
                if evidence_ref in state.evidence_ledger or evidence_ref in pending_entries:
                    raise SkillError(
                        "read_table_region cannot reread a ledgered table cell"
                    )
                pending_entries[evidence_ref] = EvidenceLedgerEntry(
                    evidence_id=evidence_ref,
                    source="table_cell",
                    paragraph_id=cell.paragraph_id,
                    exact_text=cell.text,
                    exact_text_sha256=_sha256_text(cell.text),
                    table_id=cell.table_id,
                    row_index=cell.row_index,
                    column_index=cell.column_index,
                    header_path=self._bounded_unique(cell.header_path, maximum=8),
                    inferred_unit=cell.unit,
                    inferred_scale=cell.scale,
                    raw_source_start=cell.source_html_start,
                    raw_source_end=cell.source_html_end,
                    ambiguity_flags=self._bounded_unique(
                        cell.ambiguity_flags, maximum=8
                    ),
                )
            if not pending_entries:
                raise SkillError("selected table region contains no readable cells")
            state.evidence_ledger.update(pending_entries)
            structural_flags = {
                flag
                for cell in region.cells
                for flag in cell.ambiguity_flags
                if flag
                in {
                    "merged_cell",
                    "column_header_unresolved",
                    "row_header_ambiguous",
                    "nested_table_structure",
                }
            }
            satisfies = (
                target_obligation.type is ObligationType.TABLE_CELL
                and not structural_flags
            )
            references = list(pending_entries)
            state.apply_skill_result(
                SkillResult(
                    status=(
                        SkillResultStatus.SATISFIED
                        if satisfies
                        else SkillResultStatus.PARTIAL
                    ),
                    target_obligation_id=target,
                    satisfied_obligation_ids=[target] if satisfies else [],
                    partial_obligation_ids=[] if satisfies else [target],
                    evidence_refs=references,
                    diagnostics=[
                        f"read {len(references)} exact table cells"
                        + (
                            f" with flags {','.join(sorted(structural_flags))}"
                            if structural_flags
                            else ""
                        )
                    ],
                )
            )
            state.last_observation = BoundedObservation(
                skill=SkillName.READ_TABLE_REGION,
                status="satisfied" if satisfies else "partial",
                target_obligation_id=target,
                references=references[:20],
            )
            return

        if isinstance(action, BindFinancialValueAction):
            evidence = state.evidence_ledger.get(action.arguments.evidence_ref)
            if evidence is None:
                raise SkillError("bind_financial_value requires ledgered exact evidence")
            if any(
                item.evidence_ref == evidence.evidence_id
                and item.raw_value == action.arguments.raw_value
                for item in state.numeric_value_ledger.values()
            ):
                raise SkillError("the exact evidence value is already bound")
            value_id = f"value-{state.next_value_sequence:04d}"
            binding_arguments = self._trusted_binding_arguments(
                action.arguments, evidence
            )
            trusted_flags = self._value_ambiguity_flags(
                binding_arguments, evidence
            )
            try:
                value_ref = bind_financial_value(
                    binding_arguments,
                    evidence,
                    value_id=value_id,
                    mandatory=False,
                    ambiguity_flags=trusted_flags,
                )
            except ValueError as error:
                raise SkillError(str(error)) from error
            state.numeric_value_ledger[value_id] = NumericValueLedgerEntry(
                value_id=value_ref.value_id,
                evidence_ref=value_ref.evidence_ref,
                raw_value=value_ref.raw_value,
                normalized_value=value_ref.normalized_value,
                numeric_type=value_ref.numeric_type,
                currency=value_ref.currency,
                unit=value_ref.unit,
                scale=value_ref.scale,
                period=value_ref.period,
                entity=value_ref.entity,
                metric=value_ref.metric,
                paragraph_id=value_ref.paragraph_id,
                table_id=value_ref.table_id,
                row_index=value_ref.row_index,
                column_index=value_ref.column_index,
                text_span_start=value_ref.source_span_start,
                text_span_end=value_ref.source_span_end,
                ambiguity_flags=[flag.value for flag in value_ref.ambiguity_flags],
            )
            state.next_value_sequence += 1
            self._apply_value_binding_result(state, target, value_id)
            state.last_observation = BoundedObservation(
                skill=SkillName.BIND_FINANCIAL_VALUE,
                status=(
                    "satisfied"
                    if state.obligation(target).status is ObligationStatus.SATISFIED
                    else "partial"
                ),
                target_obligation_id=target,
                references=[value_id],
            )
            return

        if isinstance(action, ExecuteFinancialProgramAction):
            if target_obligation.type is not ObligationType.NUMERIC_OPERATION:
                raise SkillError(
                    "execute_financial_program requires a numeric-operation target"
                )
            program_id = f"program-{state.next_program_sequence:04d}"
            certificate_id = (
                f"numeric-certificate-{state.next_program_sequence:04d}"
            )
            try:
                execution = execute_financial_program(
                    action.arguments.program,
                    action.arguments.claim_relation,
                    values=state.numeric_value_ledger,
                    claims=state.claim_value_ledger,
                    program_id=program_id,
                    certificate_id=certificate_id,
                )
            except FinDSLExecutionError as error:
                raise SkillError(str(error)) from error
            if any(
                item.program_sha256 == execution.program_sha256
                for item in state.financial_program_ledger.values()
            ):
                raise SkillError("the canonical financial program was already executed")

            certificate = execution.certificate
            value_refs = [
                snapshot.ref
                for snapshot in certificate.normalized_operands
                if snapshot.kind == "value_ref"
            ]
            claim_refs = [
                snapshot.ref
                for snapshot in certificate.normalized_operands
                if snapshot.kind == "claim_value_ref"
            ]
            if action.arguments.claim_relation is not None:
                claim_refs.append(action.arguments.claim_relation.claim_ref)
                claim_refs = list(dict.fromkeys(claim_refs))
            constant_refs = [
                snapshot.ref
                for snapshot in certificate.normalized_operands
                if snapshot.kind == "constant_ref"
            ]
            self._validate_program_operand_refs(state, target_obligation, value_refs)
            state.financial_program_ledger[program_id] = (
                FinancialProgramLedgerEntry(
                    program_id=program_id,
                    program_sha256=execution.program_sha256,
                    operator=certificate.operator.value,
                    program=action.arguments.program,
                    claim_relation=action.arguments.claim_relation,
                    operand_value_refs=value_refs,
                    claim_value_refs=claim_refs,
                    constant_refs=constant_refs,
                    result_value=certificate.result,
                    result_type=certificate.result_type,
                    certificate_ref=certificate_id,
                )
            )
            state.numeric_certificate_ledger[certificate_id] = certificate
            state.next_program_sequence += 1
            envelope = CertificateEnvelope(
                certificate_id=certificate_id,
                kind=CertificateKind.NUMERIC,
                payload_sha256=numeric_certificate_sha256(certificate),
                claim_sha256=state.resume_identity.statement_sha256,
                evidence_refs=certificate.source_evidence_refs,
                verified=True,
                diagnostic=(
                    "claim relation satisfied"
                    if certificate.relation_satisfied
                    else "claim relation not satisfied"
                ),
            )
            state.apply_skill_result(
                SkillResult(
                    status=SkillResultStatus.SATISFIED,
                    target_obligation_id=target,
                    satisfied_obligation_ids=[target],
                    evidence_refs=[program_id],
                    certificate=envelope,
                    diagnostics=[
                        "verified deterministic Decimal program; "
                        f"relation_satisfied={str(certificate.relation_satisfied).lower()}"
                    ],
                )
            )
            state.last_observation = BoundedObservation(
                skill=SkillName.EXECUTE_FINANCIAL_PROGRAM,
                status="satisfied",
                target_obligation_id=target,
                references=[program_id, certificate_id],
            )
            return

        if isinstance(action, SearchFinancialRulesAction):
            if self.rule_corpus is None:
                raise SkillError("no validated frozen rule corpus is configured")
            if target_obligation.type is not ObligationType.DOMAIN_RULE:
                raise SkillError("rule search requires a domain-rule target")
            metadata = target_obligation.metadata
            if (
                metadata.jurisdiction
                and metadata.jurisdiction.casefold() not in _UNKNOWN_METADATA
                and action.arguments.jurisdiction.casefold()
                != metadata.jurisdiction.casefold()
            ):
                raise SkillError("rule search jurisdiction conflicts with obligation scope")
            if (
                metadata.effective_date
                and metadata.effective_date.casefold() not in _UNKNOWN_METADATA
                and action.arguments.as_of_date != metadata.effective_date
            ):
                raise SkillError("rule search date conflicts with obligation scope")
            try:
                hits = self.rule_corpus.search(**action.arguments.model_dump())
            except RuleCorpusError as error:
                raise SkillError(str(error)) from error
            history_hits = [
                RuleSearchHitRecord(
                    rule_id=hit.rule_id,
                    score=hit.score,
                    snippet=hit.snippet,
                )
                for hit in hits
            ]
            state.rule_search_history.append(
                RuleSearchRecord(
                    query=action.arguments.query,
                    jurisdiction=action.arguments.jurisdiction,
                    as_of_date=action.arguments.as_of_date,
                    target_obligation_id=target,
                    step=state.step,
                    hits=history_hits,
                )
            )
            state.apply_skill_result(
                SkillResult(
                    status=SkillResultStatus.PARTIAL,
                    target_obligation_id=target,
                    partial_obligation_ids=[target],
                    diagnostics=[f"frozen rule search returned {len(hits)} candidates"],
                )
            )
            state.last_observation = BoundedObservation(
                skill=SkillName.SEARCH_FINANCIAL_RULES,
                status="partial",
                target_obligation_id=target,
                references=[hit.rule_id for hit in hits],
            )
            return

        if isinstance(action, ReadFinancialRulesAction):
            if self.rule_corpus is None:
                raise SkillError("no validated frozen rule corpus is configured")
            if target_obligation.type is not ObligationType.DOMAIN_RULE:
                raise SkillError("rule read requires a domain-rule target")
            candidates = {
                hit.rule_id
                for record in state.rule_search_history
                if record.target_obligation_id == target
                for hit in record.hits
            }
            requested = set(action.arguments.rule_ids)
            if not requested <= candidates:
                raise SkillError("read_financial_rules may read only search candidates")
            already_read = {
                evidence.rule_id for evidence in state.rule_evidence_ledger.values()
            }
            if requested & already_read:
                raise SkillError("read_financial_rules cannot reread ledgered rules")
            references: list[str] = []
            for rule_id in action.arguments.rule_ids:
                try:
                    record = self.rule_corpus.record(rule_id)
                except RuleCorpusError as error:
                    raise SkillError(str(error)) from error
                evidence_id = f"rule-evidence-{state.next_rule_evidence_sequence:04d}"
                state.rule_evidence_ledger[evidence_id] = RuleEvidenceLedgerEntry(
                    rule_evidence_id=evidence_id,
                    rule_id=record.rule_id,
                    rule_sha256=rule_record_sha256(record),
                    corpus_id=self.rule_corpus.corpus_id,
                    manifest_sha256=self.rule_corpus.manifest_sha256,
                    records_sha256=self.rule_corpus.records_sha256,
                    record=record,
                )
                state.next_rule_evidence_sequence += 1
                references.append(evidence_id)
            state.apply_skill_result(
                SkillResult(
                    status=SkillResultStatus.SATISFIED,
                    target_obligation_id=target,
                    satisfied_obligation_ids=[target],
                    evidence_refs=references,
                    diagnostics=[f"read {len(references)} frozen rule records"],
                )
            )
            state.last_observation = BoundedObservation(
                skill=SkillName.READ_FINANCIAL_RULES,
                status="satisfied",
                target_obligation_id=target,
                references=references,
            )
            return

        if isinstance(action, CheckRuleApplicabilityAction):
            if self.rule_corpus is None:
                raise SkillError("no validated frozen rule corpus is configured")
            if target_obligation.type is not ObligationType.RULE_APPLICABILITY:
                raise SkillError(
                    "rule applicability check requires a rule-applicability target"
                )
            metadata = target_obligation.metadata
            trusted_scope = (
                metadata.jurisdiction,
                metadata.effective_date,
                metadata.entity_scope,
            )
            supplied_scope = (
                action.arguments.jurisdiction,
                action.arguments.effective_date,
                action.arguments.entity_scope,
            )
            if trusted_scope != supplied_scope:
                raise SkillError(
                    "applicability scope differs from Runtime obligation metadata"
                )
            try:
                rule_evidence = [
                    state.rule_evidence_ledger[reference]
                    for reference in action.arguments.rule_evidence_refs
                ]
                document_evidence = [
                    state.evidence_ledger[reference]
                    for reference in action.arguments.document_evidence_refs
                ]
            except KeyError as error:
                raise SkillError(
                    "applicability requires read rule and document evidence"
                ) from error
            allowed_rule_refs: set[str] = set()
            allowed_document_refs: set[str] = set()
            for dependency_id in target_obligation.dependency_ids:
                dependency = state.obligation(dependency_id)
                if dependency.type is ObligationType.DOMAIN_RULE:
                    allowed_rule_refs.update(
                        reference
                        for reference in dependency.evidence_refs
                        if reference in state.rule_evidence_ledger
                    )
                elif dependency.type is ObligationType.DOCUMENT_FACT:
                    allowed_document_refs.update(
                        reference
                        for reference in dependency.evidence_refs
                        if reference in state.evidence_ledger
                    )
            if not set(action.arguments.rule_evidence_refs) <= allowed_rule_refs:
                raise SkillError(
                    "applicability rule evidence is not attached to its domain dependency"
                )
            if not set(action.arguments.document_evidence_refs) <= allowed_document_refs:
                raise SkillError(
                    "applicability document evidence is not attached to its fact dependency"
                )
            combined_refs = [
                *action.arguments.rule_evidence_refs,
                *action.arguments.document_evidence_refs,
            ]
            if len(combined_refs) > 24:
                raise SkillError("applicability certificate exceeds evidence bounds")
            certificate_id = (
                f"rule-certificate-{state.next_rule_certificate_sequence:04d}"
            )
            try:
                certificate = check_rule_applicability(
                    corpus=self.rule_corpus,
                    rule_evidence=rule_evidence,
                    document_evidence=document_evidence,
                    effective_date=action.arguments.effective_date,
                    jurisdiction=action.arguments.jurisdiction,
                    entity_scope=action.arguments.entity_scope,
                    predicate_ids=action.arguments.applicability_predicate_ids,
                    certificate_id=certificate_id,
                )
            except (RuleApplicabilityError, RuleCorpusError) as error:
                raise SkillError(str(error)) from error
            state.rule_applicability_certificate_ledger[
                certificate_id
            ] = certificate
            state.next_rule_certificate_sequence += 1
            envelope = CertificateEnvelope(
                certificate_id=certificate_id,
                kind=CertificateKind.RULE_APPLICABILITY,
                payload_sha256=rule_applicability_certificate_sha256(certificate),
                claim_sha256=state.resume_identity.statement_sha256,
                evidence_refs=combined_refs,
                verified=True,
                diagnostic=f"mechanical applicability result: {certificate.result.value}",
            )
            conclusive = certificate.result in {
                RuleApplicabilityResult.APPLICABLE,
                RuleApplicabilityResult.NOT_APPLICABLE,
            }
            state.apply_skill_result(
                SkillResult(
                    status=(
                        SkillResultStatus.SATISFIED
                        if conclusive
                        else SkillResultStatus.PARTIAL
                    ),
                    target_obligation_id=target,
                    satisfied_obligation_ids=[target] if conclusive else [],
                    partial_obligation_ids=[] if conclusive else [target],
                    evidence_refs=combined_refs,
                    certificate=envelope,
                    diagnostics=[
                        f"mechanical applicability result={certificate.result.value}"
                    ],
                )
            )
            state.last_observation = BoundedObservation(
                skill=SkillName.CHECK_RULE_APPLICABILITY,
                status="satisfied" if conclusive else "partial",
                target_obligation_id=target,
                references=[certificate_id],
            )
            return

        if isinstance(action, SubmitAnswerAction):
            if target_obligation.type is not ObligationType.FINAL_VERIFICATION:
                raise SkillError("submit_answer requires a final-verification target")
            if action.control.open_obligations or action.control.obligation_deltas:
                raise SkillError(
                    "submit_answer cannot mutate the obligation graph through model control"
                )
            certificate_id = (
                f"final-certificate-{state.next_final_certificate_sequence:04d}"
            )
            certificate = self.claim_verifier.verify(
                state=state,
                label=action.arguments.label,
                evidence_ids=action.arguments.evidence_ids,
                explanation=action.arguments.explanation,
                confidence=action.control.confidence,
                risk_flags=action.control.risk_flags,
                allow_fallback=(
                    state.forced_finalization
                    and state.phase is QuestionPhase.FINALIZATION
                ),
                certificate_id=certificate_id,
                target_obligation_id=target,
            )
            state.final_verification_certificate_ledger[
                certificate_id
            ] = certificate
            state.next_final_certificate_sequence += 1
            envelope = CertificateEnvelope(
                certificate_id=certificate_id,
                kind=CertificateKind.FINAL_VERIFICATION,
                payload_sha256=claim_verification_certificate_sha256(certificate),
                claim_sha256=state.resume_identity.statement_sha256,
                evidence_refs=certificate.document_evidence_refs,
                verified=(
                    certificate.result is ClaimVerificationResult.VERIFIED
                ),
                diagnostic=(
                    f"deterministic final result: {certificate.result.value}"
                ),
            )
            prediction = Prediction(
                example_id=state.example_id,
                label=action.arguments.label,
                status=PredictionStatus.COMPLETED,
                evidence_ids=action.arguments.evidence_ids,
                explanation=action.arguments.explanation,
            )

            if certificate.result is ClaimVerificationResult.FAILED:
                state.certificate_ledger[certificate_id] = envelope
                if state.phase is QuestionPhase.REVIEW and state.draft_prediction:
                    state.review_failure_reason = (
                        "verifier: "
                        + ",".join(code.value for code in certificate.failure_codes)
                    )[:160]
                else:
                    state.final_certificate_status = FinalCertificateStatus.FAILED
                state.last_observation = BoundedObservation(
                    skill=SkillName.SUBMIT_ANSWER,
                    status="invalid",
                    target_obligation_id=target,
                    references=[certificate_id],
                    diagnostics=[
                        f"final verifier failed: {code.value}"
                        for code in certificate.failure_codes[:8]
                    ],
                )
                return

            if certificate.result is ClaimVerificationResult.INCOMPLETE:
                state.apply_skill_result(
                    SkillResult(
                        status=SkillResultStatus.PARTIAL,
                        target_obligation_id=target,
                        partial_obligation_ids=[target],
                        evidence_refs=certificate.document_evidence_refs,
                        certificate=envelope,
                        diagnostics=["bounded low-confidence fallback submission"],
                    )
                )
                state.prediction = prediction
                state.prediction_certificate_ref = certificate_id
                state.unresolved_obligation_ids = [
                    obligation.obligation_id
                    for obligation in state.obligations
                    if obligation.status is not ObligationStatus.SATISFIED
                ]
                state.final_certificate_status = FinalCertificateStatus.INCOMPLETE
                state.termination_reason = "budget_exhausted_fallback"
                state.phase = QuestionPhase.CLOSED
                state.closed = True
                state.last_observation = BoundedObservation(
                    skill=SkillName.SUBMIT_ANSWER,
                    status="partial",
                    target_obligation_id=target,
                    references=[certificate_id],
                    diagnostics=["submission closed with unresolved obligations"],
                )
                return

            if state.phase is QuestionPhase.REVIEW:
                if state.draft_prediction is None or state.draft_certificate_ref is None:
                    raise SkillError("Review requires a verified draft and certificate")
                state.apply_skill_result(
                    SkillResult(
                        status=SkillResultStatus.SATISFIED,
                        target_obligation_id=target,
                        satisfied_obligation_ids=[target],
                        evidence_refs=certificate.document_evidence_refs,
                        certificate=envelope,
                        diagnostics=["certificate-focused Review verification passed"],
                    )
                )
                state.prediction = prediction
                state.prediction_certificate_ref = certificate_id
                state.review_changed_label = (
                    prediction.label != state.draft_prediction.label
                )
                state.review_changed_evidence = (
                    prediction.evidence_ids != state.draft_prediction.evidence_ids
                )
                state.review_changed_explanation = (
                    prediction.explanation != state.draft_prediction.explanation
                )
                state.final_certificate_status = FinalCertificateStatus.VERIFIED
                state.unresolved_obligation_ids = []
                state.termination_reason = "review_verified"
                state.phase = QuestionPhase.CLOSED
                state.closed = True
            else:
                review_reasons = self._review_trigger_reasons(
                    state, action, certificate
                )
                if review_reasons:
                    state.certificate_ledger[certificate_id] = envelope
                    state.draft_prediction = prediction
                    state.draft_certificate_ref = certificate_id
                    state.review_trigger_reasons = review_reasons
                    state.final_certificate_status = FinalCertificateStatus.PENDING
                    state.phase = QuestionPhase.REVIEW
                else:
                    state.apply_skill_result(
                        SkillResult(
                            status=SkillResultStatus.SATISFIED,
                            target_obligation_id=target,
                            satisfied_obligation_ids=[target],
                            evidence_refs=certificate.document_evidence_refs,
                            certificate=envelope,
                            diagnostics=[
                                "deterministic final claim verification passed"
                            ],
                        )
                    )
                    state.final_certificate_status = FinalCertificateStatus.VERIFIED
                    state.unresolved_obligation_ids = []
                    state.prediction = prediction
                    state.prediction_certificate_ref = certificate_id
                    state.termination_reason = "certificate_verified"
                    state.phase = QuestionPhase.CLOSED
                    state.closed = True
            state.last_observation = BoundedObservation(
                skill=SkillName.SUBMIT_ANSWER,
                status="satisfied",
                target_obligation_id=target,
                references=[certificate_id],
            )
            return

        raise SkillError(f"{action.action} is not implemented by this Runtime phase")

    def _review_trigger_reasons(
        self,
        state: FinOASISQuestionState,
        action: SubmitAnswerAction,
        certificate,
    ) -> list[str]:
        if (
            self.config.review_policy != "selective"
            or state.phase_attempts.review_limit <= state.phase_attempts.review_used
        ):
            return []
        reasons: list[str] = []
        if certificate.numeric_certificate_refs:
            reasons.append("numeric_certificate_consumed")
        if certificate.rule_certificate_refs:
            reasons.append("rule_applicability_certificate_consumed")
        if state.forced_finalization:
            reasons.append("forced_finalization")
        if action.control.confidence is not Confidence.HIGH:
            reasons.append("non_high_confidence")
        reasons.extend(
            f"risk:{flag.value}" for flag in action.control.risk_flags
        )
        if any(
            item.result is ClaimVerificationResult.FAILED
            for item in state.final_verification_certificate_ledger.values()
        ):
            reasons.append("prior_final_verifier_failure")
        return list(dict.fromkeys(reasons))[:8]

    @staticmethod
    def _bounded_unique(values, *, maximum: int) -> list[str]:
        bounded = [" ".join(str(value).split())[:160] for value in values]
        return list(dict.fromkeys(value for value in bounded if value))[:maximum]

    @staticmethod
    def _skill_failure_categories(skill: SkillName, message: str) -> list[str]:
        """Return aggregate-safe failure buckets without copying task material."""

        normalized = message.casefold()
        categories: list[str] = []
        if skill is SkillName.BIND_FINANCIAL_VALUE:
            categories.append("binding_failure")
        if skill is SkillName.EXECUTE_FINANCIAL_PROGRAM:
            categories.append("program_failure")
        if skill in {
            SkillName.BIND_FINANCIAL_VALUE,
            SkillName.EXECUTE_FINANCIAL_PROGRAM,
        }:
            if any(term in normalized for term in ("unit", "currency", "scale")):
                categories.append("unit_failure")
            if any(
                term in normalized
                for term in ("period", "quarter", "fiscal", "year")
            ):
                categories.append("period_failure")
            if any(
                term in normalized
                for term in (
                    "numeric type",
                    "type is",
                    "boolean",
                    "date",
                    "money",
                    "percentage",
                    "count",
                    "duration",
                    "scalar",
                )
            ):
                categories.append("type_failure")
            if any(term in normalized for term in ("relation", "claim")):
                categories.append("relation_failure")
        if skill in {
            SkillName.SEARCH_FINANCIAL_RULES,
            SkillName.READ_FINANCIAL_RULES,
            SkillName.CHECK_RULE_APPLICABILITY,
        } and any(
            term in normalized
            for term in (
                "hash",
                "provenance",
                "corpus",
                "manifest",
                "record",
                "source",
                "stale",
            )
        ):
            categories.append("rule_integrity_failure")
        return list(dict.fromkeys(categories))

    def _add_relevant_table_candidates(
        self,
        state: FinOASISQuestionState,
        *,
        session: ReportSession,
        table_reader: TableRegionReader,
        paragraph_ids: set[int],
    ) -> None:
        existing = {candidate.table_id for candidate in state.table_candidates}
        for table in session.tables:
            if table.paragraph_id not in paragraph_ids or table.table_id in existing:
                continue
            try:
                structure = table_reader.describe(table.table_id)
            except TableRegionError:
                continue
            title = self._table_title(table.raw_context, table.paragraph_id)
            state.table_candidates.append(
                TableCandidateRecord(
                    table_id=structure.table_id,
                    paragraph_id=structure.paragraph_id,
                    title=title,
                    row_count=structure.row_count,
                    column_count=structure.column_count,
                    ambiguity_flags=self._bounded_unique(
                        structure.ambiguity_flags, maximum=8
                    ),
                )
            )
            existing.add(table.table_id)

    @staticmethod
    def _table_title(raw_context: str, paragraph_id: int) -> str:
        lines = [" ".join(line.split()) for line in raw_context.splitlines()]
        title_lines = [line for line in lines if line and not line.startswith("|")]
        if not title_lines:
            return f"unknown table title at paragraph {paragraph_id}"
        return " — ".join(title_lines[-3:])[:500]

    @staticmethod
    def _value_ambiguity_flags(
        arguments: BindFinancialValueArguments,
        evidence: EvidenceLedgerEntry,
    ) -> tuple[ValueAmbiguityFlag, ...]:
        flags: set[ValueAmbiguityFlag] = set()
        evidence_flags = set(evidence.ambiguity_flags)
        if evidence.source == "table_cell" and evidence_flags & {
            "merged_cell",
            "column_header_unresolved",
            "row_header_ambiguous",
            "nested_table_structure",
        }:
            flags.add(ValueAmbiguityFlag.TABLE_HEADER_AMBIGUOUS)
        if evidence_flags & {
            "unit_ambiguous",
            "unit_unknown",
            "currency_symbol_ambiguous",
        }:
            flags.add(ValueAmbiguityFlag.UNIT_AMBIGUOUS)
        if evidence_flags & {"scale_ambiguous", "scale_unknown"}:
            flags.add(ValueAmbiguityFlag.SCALE_AMBIGUOUS)

        source_context = " ".join(
            [evidence.exact_text, *evidence.header_path]
        ).casefold()
        period = arguments.period.strip().casefold()
        years = set(re.findall(r"(?:19|20|21)\d{2}", period))
        source_years = set(re.findall(r"(?:19|20|21)\d{2}", source_context))
        period_supported = bool(period and period in source_context) or bool(
            years and years <= source_years
        )
        if period in {"unknown", "unspecified", "n/a"} or not period_supported:
            flags.add(ValueAmbiguityFlag.PERIOD_AMBIGUOUS)
        return tuple(flag for flag in ValueAmbiguityFlag if flag in flags)

    @staticmethod
    def _trusted_binding_arguments(
        arguments: BindFinancialValueArguments,
        evidence: EvidenceLedgerEntry,
    ) -> BindFinancialValueArguments:
        """Reconcile model metadata with deterministic table inference."""

        updates: dict[str, str] = {}
        trusted_unit = FinOASISAgent._canonical_metadata(
            evidence.inferred_unit, aliases=_UNIT_METADATA_ALIASES
        )
        if trusted_unit is not None:
            supplied_unit = FinOASISAgent._canonical_metadata(
                arguments.unit, aliases=_UNIT_METADATA_ALIASES
            )
            if supplied_unit is not None and supplied_unit != trusted_unit:
                raise SkillError(
                    "unit metadata conflicts with deterministic table inference"
                )
            updates["unit"] = trusted_unit
            if arguments.numeric_type == "money":
                supplied_currency = FinOASISAgent._canonical_metadata(
                    arguments.currency, aliases=_UNIT_METADATA_ALIASES
                )
                if (
                    supplied_currency is not None
                    and supplied_currency != trusted_unit
                ):
                    raise SkillError(
                        "currency metadata conflicts with deterministic table inference"
                    )
                updates["currency"] = trusted_unit

        trusted_scale = FinOASISAgent._canonical_metadata(
            evidence.inferred_scale, aliases=_SCALE_METADATA_ALIASES
        )
        if trusted_scale is not None:
            supplied_scale = FinOASISAgent._canonical_metadata(
                arguments.scale, aliases=_SCALE_METADATA_ALIASES
            )
            if supplied_scale is not None and supplied_scale != trusted_scale:
                raise SkillError(
                    "scale metadata conflicts with deterministic table inference"
                )
            updates["scale"] = trusted_scale

        return arguments.model_copy(update=updates) if updates else arguments

    @staticmethod
    def _canonical_metadata(
        value: str, *, aliases: dict[str, str]
    ) -> str | None:
        normalized = " ".join(value.strip().casefold().replace("_", " ").split())
        if normalized in _UNKNOWN_METADATA:
            return None
        return aliases.get(normalized, value.strip())

    @staticmethod
    def _apply_value_binding_result(
        state: FinOASISQuestionState,
        target: str,
        value_id: str,
    ) -> None:
        obligation = state.obligation(target)
        value_refs = [
            reference
            for reference in obligation.evidence_refs
            if reference in state.numeric_value_ledger
        ]
        value_refs.append(value_id)
        value_refs = list(dict.fromkeys(value_refs))
        satisfied: list[str] = []
        partial: list[str] = []

        if obligation.type is ObligationType.NUMERIC_OPERAND:
            matched = match_operand_slots(
                obligation.metadata.operand_slots,
                {
                    reference: state.numeric_value_ledger[reference]
                    for reference in value_refs
                },
            )
            if matched is not None:
                satisfied.append(target)
                unit_obligations = [
                    item
                    for item in state.obligations
                    if item.type is ObligationType.UNIT_PERIOD
                    and target in item.dependency_ids
                    and item.status is not ObligationStatus.SATISFIED
                ]
                metadata_ready = all(
                    not state.numeric_value_ledger[reference].ambiguity_flags
                    and state.numeric_value_ledger[reference].unit.casefold()
                    not in {"unknown", "unspecified", "n/a"}
                    and state.numeric_value_ledger[reference].period.casefold()
                    not in {"unknown", "unspecified", "n/a"}
                    for reference in matched.values()
                )
                for unit in unit_obligations:
                    (satisfied if metadata_ready else partial).append(
                        unit.obligation_id
                    )
            else:
                partial.append(target)
        elif obligation.type is ObligationType.UNIT_PERIOD:
            value = state.numeric_value_ledger[value_id]
            if not value.ambiguity_flags:
                satisfied.append(target)
            else:
                partial.append(target)
        else:
            raise SkillError("bind_financial_value target is not a numeric obligation")

        status = (
            SkillResultStatus.SATISFIED if satisfied else SkillResultStatus.PARTIAL
        )
        state.apply_skill_result(
            SkillResult(
                status=status,
                target_obligation_id=target,
                satisfied_obligation_ids=satisfied,
                partial_obligation_ids=partial,
                evidence_refs=[value_id],
                diagnostics=[
                    f"bound exact Decimal value {value_id}; "
                    f"matched_slots={len(matched or {})}/"
                    f"{len(obligation.metadata.operand_slots)}"
                ],
            )
        )

    @staticmethod
    def _validate_program_operand_refs(
        state: FinOASISQuestionState,
        operation: Obligation,
        program_value_refs: list[str],
    ) -> None:
        by_id = {
            obligation.obligation_id: obligation for obligation in state.obligations
        }
        operand_dependencies = [
            by_id[dependency_id]
            for dependency_id in operation.dependency_ids
            if by_id[dependency_id].type is ObligationType.NUMERIC_OPERAND
        ]
        if not operand_dependencies:
            raise SkillError("numeric operation has no typed operand dependency")
        allowed: set[str] = set()
        referenced = set(program_value_refs)
        for obligation in operand_dependencies:
            attached = {
                reference: state.numeric_value_ledger[reference]
                for reference in obligation.evidence_refs
                if reference in state.numeric_value_ledger
            }
            matched = match_operand_slots(
                obligation.metadata.operand_slots,
                {
                    reference: value
                    for reference, value in attached.items()
                    if reference in referenced
                },
            )
            if matched is None:
                raise SkillError(
                    "financial program does not consume every required operand slot"
                )
            allowed.update(attached)
        if referenced - allowed:
            raise SkillError(
                "financial program references a ValueRef outside its operand dependencies"
            )

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
            and state.draft_prediction is not None
            and state.draft_certificate_ref is not None
        ):
            state.phase = QuestionPhase.REVIEW
            self.state_store.save(state)
            trace.write(
                "phase_transition",
                {"phase": "review", "reason": "finalization_budget_exhausted"},
            )
            return True
        if (
            state.phase is QuestionPhase.REVIEW
            and state.draft_prediction is not None
            and state.draft_certificate_ref is not None
        ):
            self._close_with_review_fallback(
                state,
                trace,
                state.review_failure_reason or "review budget exhausted",
            )
            return True
        self._close_invalid(state, trace, f"{state.phase.value} budget exhausted")
        return True

    def _close_with_review_fallback(
        self,
        state: FinOASISQuestionState,
        trace: TraceWriter,
        reason: str,
    ) -> Prediction:
        if state.draft_prediction is None or state.draft_certificate_ref is None:
            raise ValueError("review fallback requires a verified draft")
        certificate = state.final_verification_certificate_ledger.get(
            state.draft_certificate_ref
        )
        if (
            certificate is None
            or certificate.result is not ClaimVerificationResult.VERIFIED
        ):
            raise ValueError("review fallback draft lacks a verified certificate")
        final_obligations = [
            obligation
            for obligation in state.obligations
            if obligation.type is ObligationType.FINAL_VERIFICATION
            and obligation.status is not ObligationStatus.SATISFIED
        ]
        if len(final_obligations) != 1:
            raise ValueError("review fallback requires one active final obligation")
        replayed = self.claim_verifier.verify(
            state=state,
            label=state.draft_prediction.label,
            evidence_ids=state.draft_prediction.evidence_ids,
            explanation=state.draft_prediction.explanation,
            confidence=Confidence.HIGH,
            risk_flags=(),
            allow_fallback=False,
            certificate_id=state.draft_certificate_ref,
            target_obligation_id=final_obligations[0].obligation_id,
        )
        if replayed != certificate:
            raise ValueError("review fallback draft failed deterministic revalidation")
        envelope = state.certificate_ledger[state.draft_certificate_ref]
        state.apply_skill_result(
            SkillResult(
                status=SkillResultStatus.SATISFIED,
                target_obligation_id=final_obligations[0].obligation_id,
                satisfied_obligation_ids=[final_obligations[0].obligation_id],
                evidence_refs=certificate.document_evidence_refs,
                certificate=envelope,
                diagnostics=["Review failed; retained certificate-verified draft"],
            )
        )
        state.prediction = state.draft_prediction.model_copy(deep=True)
        state.prediction_certificate_ref = state.draft_certificate_ref
        state.review_fallback_used = True
        state.review_failure_reason = " ".join(reason.split())[:160]
        state.final_certificate_status = FinalCertificateStatus.VERIFIED
        state.unresolved_obligation_ids = []
        state.termination_reason = "review_fallback"
        state.phase = QuestionPhase.CLOSED
        state.closed = True
        self.state_store.save(state)
        trace.write(
            "review_fallback",
            {
                "draft_certificate_ref": state.draft_certificate_ref,
                "reason": state.review_failure_reason,
            },
        )
        trace.write(
            "question_closed",
            {
                "status": "completed",
                "reason": "review_fallback",
                "review_failure_reason": state.review_failure_reason,
            },
        )
        return state.prediction

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
        state.final_certificate_status = FinalCertificateStatus.FAILED
        state.prediction = prediction
        state.prediction_certificate_ref = None
        state.termination_reason = reason[:160]
        state.phase = QuestionPhase.CLOSED
        state.closed = True
        self.state_store.save(state)
        trace.write("question_closed", {"status": "invalid", "reason": reason[:500]})
        return prediction


__all__ = ["FinOASISAgent"]
