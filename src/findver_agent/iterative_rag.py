"""Fixed-loop, non-agent iterative RAG baseline."""

from __future__ import annotations

from pathlib import Path

from findver_agent.actions import ActionParseError, SearchAction, SubmitAction, parse_action
from findver_agent.baseline import format_paragraphs
from findver_agent.config import IterativeRAGConfig
from findver_agent.fixed_retrieval import FixedRetrievalIndex
from findver_agent.model_backends.base import (
    GenerationConfig,
    ModelBackend,
    ModelResponse,
    context_window_metadata,
)
from findver_agent.report_store import ReportSession, ReportStore
from findver_agent.schemas import Prediction, PredictionStatus, PublicTask
from findver_agent.skills import ReadParagraphsSkill, SearchReportSkill, SubmitAnswerSkill
from findver_agent.skills.base import SkillError
from findver_agent.trace_writer import TraceWriter


QUERY_SYSTEM = """You generate one targeted query for a fixed-round financial-report retrieval baseline.
Return exactly one JSON object and no other text:
{"action":"search_report","arguments":{"query":"specific missing financial fact","top_k":5}}
Do not submit an answer. Do not output chain-of-thought."""

FINAL_SYSTEM = """You are finalizing a financial fact-verification baseline from already retrieved evidence.
Return exactly one JSON object and no other text:
{"action":"submit_answer","arguments":{"label":"entailed or refuted","evidence_ids":[0],"explanation":"concise evidence-based explanation"}}
No other action is allowed. Do not output chain-of-thought."""


class IterativeRAGRunner:
    """Run a configured number of retrieval calls before strict finalization."""

    def __init__(
        self,
        *,
        backend: ModelBackend,
        generation: GenerationConfig,
        iterative_config: IterativeRAGConfig,
        report_store: ReportStore,
        run_dir: Path,
    ) -> None:
        self.backend = backend
        self.generation = generation
        self.config = iterative_config
        self.report_store = report_store
        self.trace_root = run_dir / "traces"
        self.fixed_retrieval = FixedRetrievalIndex(
            iterative_config.retrieval_file,
            retriever=iterative_config.retriever,
            top_k=iterative_config.top_k,
        )

    async def run_question(self, task: PublicTask) -> Prediction:
        session = self.report_store.open_session(task.report)
        trace = TraceWriter(self.trace_root, task.example_id)
        seed_ids = self.fixed_retrieval.paragraph_ids(task, session)
        if len(seed_ids) > self.config.max_total_unique_paragraphs:
            raise ValueError("iterative RAG seed exceeds maximum unique paragraphs")
        evidence_ids = list(seed_ids)
        trace.write(
            "retrieval_seed_loaded",
            {
                "retriever": self.fixed_retrieval.retriever,
                "top_k": self.fixed_retrieval.top_k,
                "retrieval_file_sha256": self.fixed_retrieval.file_sha256,
                "paragraph_ids": seed_ids,
                "preload_as_evidence": True,
            },
        )
        trace.write(
            "iterative_budget",
            {
                "retrieval_rounds": self.config.retrieval_rounds,
                "finalization_steps": self.config.finalization_steps,
                "maximum_model_calls": (
                    self.config.retrieval_rounds + self.config.finalization_steps
                ),
                "results_per_round": self.config.results_per_round,
                "auto_read_per_round": self.config.auto_read_per_round,
            },
        )
        search = SearchReportSkill(session)
        read = ReadParagraphsSkill(
            session,
            max_paragraphs=self.config.auto_read_per_round,
        )

        for round_number in range(1, self.config.retrieval_rounds + 1):
            messages = self._query_messages(task, session, evidence_ids, round_number)
            response = await self._generate(
                trace,
                messages,
                phase="iterative_retrieval",
                attempt=round_number,
            )
            if response is None:
                continue
            try:
                action = parse_action(response.content)
            except ActionParseError as error:
                self._trace_error(
                    trace,
                    phase="iterative_retrieval",
                    attempt=round_number,
                    kind="parse",
                    message=str(error),
                )
                continue
            trace.write(
                "action",
                {
                    "phase": "iterative_retrieval",
                    "round": round_number,
                    **action.model_dump(mode="json", exclude_none=True),
                },
            )
            if not isinstance(action, SearchAction):
                self._trace_error(
                    trace,
                    phase="iterative_retrieval",
                    attempt=round_number,
                    kind="protocol",
                    message="iterative retrieval round requires search_report",
                )
                continue
            try:
                search_result = search.execute(
                    query=action.arguments.query,
                    top_k=self.config.results_per_round,
                )
                trace.write(
                    "tool_result",
                    {
                        "phase": "iterative_retrieval",
                        "skill": "search_report",
                        "round": round_number,
                        "query": action.arguments.query,
                        "result_ids": [
                            int(hit["paragraph_id"]) for hit in search_result["hits"]
                        ],
                    },
                )
                known = set(evidence_ids)
                available = self.config.max_total_unique_paragraphs - len(known)
                new_ids = [
                    int(hit["paragraph_id"])
                    for hit in search_result["hits"]
                    if int(hit["paragraph_id"]) not in known
                ][: min(self.config.auto_read_per_round, available)]
                if new_ids:
                    read_result = read.execute(paragraph_ids=new_ids)
                    evidence_ids.extend(new_ids)
                    trace.write(
                        "tool_result",
                        {
                            "phase": "iterative_retrieval",
                            "skill": "read_paragraphs",
                            "round": round_number,
                            "paragraph_ids": new_ids,
                            "paragraph_count": len(read_result["paragraphs"]),
                        },
                    )
                    trace.write(
                        "dynamic_evidence_loaded",
                        {"round": round_number, "paragraph_ids": new_ids},
                    )
            except (SkillError, ValueError, TypeError) as error:
                self._trace_error(
                    trace,
                    phase="iterative_retrieval",
                    attempt=round_number,
                    kind="skill",
                    message=str(error),
                )

        submit = SubmitAnswerSkill(session, task.example_id)
        for attempt in range(1, self.config.finalization_steps + 1):
            messages = self._finalization_messages(task, session, evidence_ids, attempt)
            response = await self._generate(
                trace,
                messages,
                phase="finalization",
                attempt=attempt,
            )
            if response is None:
                continue
            try:
                action = parse_action(response.content)
            except ActionParseError as error:
                self._trace_error(
                    trace,
                    phase="finalization",
                    attempt=attempt,
                    kind="parse",
                    message=str(error),
                )
                continue
            trace.write(
                "action",
                {
                    "phase": "finalization",
                    "phase_attempt": attempt,
                    **action.model_dump(mode="json", exclude_none=True),
                },
            )
            if not isinstance(action, SubmitAction):
                self._trace_error(
                    trace,
                    phase="finalization",
                    attempt=attempt,
                    kind="protocol",
                    message="iterative RAG finalization requires submit_answer",
                )
                continue
            try:
                if not action.arguments.explanation.strip():
                    raise SkillError("submit explanation must be non-empty")
                unknown = sorted(set(action.arguments.evidence_ids) - set(evidence_ids))
                if unknown:
                    raise SkillError("submit evidence_ids must be in retrieved evidence")
                prediction = submit.execute(**action.arguments.model_dump())
            except (SkillError, ValueError, TypeError) as error:
                self._trace_error(
                    trace,
                    phase="finalization",
                    attempt=attempt,
                    kind="skill",
                    message=str(error),
                )
                continue
            trace.write(
                "question_closed",
                {
                    "status": "completed",
                    "reason": "iterative_rag_finalized",
                    "retrieval_rounds": self.config.retrieval_rounds,
                },
            )
            return prediction

        prediction = Prediction(
            example_id=task.example_id,
            label=None,
            status=PredictionStatus.INVALID,
            evidence_ids=[],
            explanation="iterative RAG finalization budget exhausted",
        )
        trace.write(
            "question_closed",
            {
                "status": "invalid",
                "reason": "finalization_budget_exhausted",
                "retrieval_rounds": self.config.retrieval_rounds,
            },
        )
        return prediction

    def _query_messages(
        self,
        task: PublicTask,
        session: ReportSession,
        evidence_ids: list[int],
        round_number: int,
    ) -> list[dict[str, str]]:
        evidence = format_paragraphs(session, evidence_ids)
        user = f"""Statement:
{task.statement}

Evidence retrieved before fixed round {round_number} of {self.config.retrieval_rounds}:
{evidence}

Generate the next targeted query. Every configured round runs; do not submit an answer."""
        return [
            {"role": "system", "content": QUERY_SYSTEM},
            {"role": "user", "content": user},
        ]

    def _finalization_messages(
        self,
        task: PublicTask,
        session: ReportSession,
        evidence_ids: list[int],
        attempt: int,
    ) -> list[dict[str, str]]:
        evidence = format_paragraphs(session, evidence_ids)
        if self.config.prompt_type == "findver_cot_json":
            guidance = (
                "Check the label, evidence IDs, values, units, and arithmetic internally, "
                "then submit without exposing long-form reasoning."
            )
        else:
            guidance = "Make the evidence-based judgment directly, then submit."
        user = f"""Statement:
{task.statement}

Evidence after exactly {self.config.retrieval_rounds} retrieval rounds:
{evidence}

Finalization attempt {attempt} of {self.config.finalization_steps}. {guidance}"""
        return [
            {"role": "system", "content": FINAL_SYSTEM},
            {"role": "user", "content": user},
        ]

    async def _generate(
        self,
        trace: TraceWriter,
        messages: list[dict[str, str]],
        *,
        phase: str,
        attempt: int,
    ) -> ModelResponse | None:
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
                "phase": phase,
                "phase_attempt": attempt,
                "messages": messages,
                "prompt_budget_tokens": self.generation.prompt_budget_tokens,
                **context_metadata,
            },
        )
        try:
            response = await self.backend.generate(messages, self.generation)
        except Exception as error:
            self._trace_error(
                trace,
                phase=phase,
                attempt=attempt,
                kind="model",
                message=f"{type(error).__name__}: {error}",
            )
            return None
        trace.write(
            "model_response",
            {
                "phase": phase,
                "phase_attempt": attempt,
                "content": response.content,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "actual_provider_input_tokens": response.input_tokens,
                "latency_ms": response.latency_ms,
                "response_id": response.response_id,
            },
        )
        return response

    @staticmethod
    def _trace_error(
        trace: TraceWriter,
        *,
        phase: str,
        attempt: int,
        kind: str,
        message: str,
    ) -> None:
        trace.write(
            "recoverable_error",
            {
                "phase": phase,
                "phase_attempt": attempt,
                "error_type": kind,
                "error": message[:1000],
            },
        )
