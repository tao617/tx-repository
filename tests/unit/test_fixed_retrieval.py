import json
from pathlib import Path

import pytest

from findver_agent.baseline import BaselineRunner, format_paragraphs
from findver_agent.config import BaselineConfig
from findver_agent.fixed_retrieval import FixedEmbeddingIndex, FixedRetrievalError
from findver_agent.model_backends.base import GenerationConfig
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PublicTask


class UnusedBackend:
    model_name = "unused"


def write_report(root: Path, paragraphs: list[str]) -> ReportStore:
    root.mkdir()
    (root / "report.json").write_text(
        json.dumps({"context": [{"context": text} for text in paragraphs]}),
        encoding="utf-8",
    )
    return ReportStore(root)


def write_index(path: Path, items: dict) -> Path:
    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "source_repo": "yilunzhao/FinDVer",
                    "source_commit": "commit",
                    "retriever": "text-embedding-3-large",
                    "top_k": 10,
                },
                "items": items,
            }
        ),
        encoding="utf-8",
    )
    return path


def runner(tmp_path: Path, reports: ReportStore, config: BaselineConfig) -> BaselineRunner:
    return BaselineRunner(
        backend=UnusedBackend(),
        generation=GenerationConfig(max_context_tokens=1024),
        baseline_config=config,
        report_store=reports,
        run_dir=tmp_path / "run",
    )


def test_fixed_embedding_reads_selected_top_10(tmp_path):
    reports = write_report(tmp_path / "reports", ["zero", "one claim", "two claim"])
    index = write_index(
        tmp_path / "retrieval.json",
        {"example": {"report": "report.json", "retrieved_context": [1, 2]}},
    )
    task = PublicTask(example_id="example", statement="claim", report="report.json")
    engine = runner(
        tmp_path,
        reports,
        BaselineConfig(
            prompt_type="cot",
            retrieval="fixed_embedding",
            retrieval_file=index,
            top_k=10,
        ),
    )

    context = engine._context(task, reports.open_session("report.json"))

    assert context == (
        "[paragraph id = 1] one claim\n"
        "[paragraph id = 2] two claim\n"
    )


def test_fixed_embedding_missing_example_fails(tmp_path):
    reports = write_report(tmp_path / "reports", ["claim"])
    index = write_index(tmp_path / "retrieval.json", {})
    task = PublicTask(example_id="missing", statement="claim", report="report.json")
    engine = runner(
        tmp_path,
        reports,
        BaselineConfig(retrieval="fixed_embedding", retrieval_file=index),
    )

    with pytest.raises(FixedRetrievalError, match="missing example_id"):
        engine._context(task, reports.open_session("report.json"))


def test_fixed_embedding_out_of_range_fails(tmp_path):
    reports = write_report(tmp_path / "reports", ["claim"])
    index = write_index(
        tmp_path / "retrieval.json",
        {"example": {"report": "report.json", "retrieved_context": [3]}},
    )
    task = PublicTask(example_id="example", statement="claim", report="report.json")
    engine = runner(
        tmp_path,
        reports,
        BaselineConfig(retrieval="fixed_embedding", retrieval_file=index),
    )

    with pytest.raises(FixedRetrievalError, match="out of range"):
        engine._context(task, reports.open_session("report.json"))


def test_bm25_and_embedding_share_paragraph_format_and_order(tmp_path):
    reports = write_report(
        tmp_path / "reports",
        ["claim alpha", "irrelevant", "claim beta"],
    )
    index = write_index(
        tmp_path / "retrieval.json",
        {"example": {"report": "report.json", "retrieved_context": [0, 2]}},
    )
    task = PublicTask(example_id="example", statement="claim", report="report.json")
    session = reports.open_session("report.json")
    b2 = runner(
        tmp_path / "b2",
        reports,
        BaselineConfig(prompt_type="cot", retrieval="fixed_bm25", top_k=10),
    )
    b3 = runner(
        tmp_path / "b3",
        reports,
        BaselineConfig(
            prompt_type="cot",
            retrieval="fixed_embedding",
            retrieval_file=index,
            top_k=10,
        ),
    )

    assert b2._context(task, session) == b3._context(task, session)
    assert b2._context(task, session) == format_paragraphs(session, [0, 2])


def test_full_report_is_not_silently_character_truncated(tmp_path):
    reports = write_report(
        tmp_path / "reports",
        ["a" * 3000, "b" * 3000 + "TAIL"],
    )
    task = PublicTask(example_id="example", statement="claim", report="report.json")
    engine = runner(tmp_path, reports, BaselineConfig(retrieval="none"))

    context = engine._context(task, reports.open_session("report.json"))

    assert len(context) > 6000
    assert "TAIL" in context
    assert "[paragraph id = 1]" in context


def test_runtime_retrieval_file_is_gold_free_and_complete():
    root = Path(__file__).parents[2]
    path = root / "runtime_data" / "retrieval" / "findver_embedding3large_top10.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    rendered = json.dumps(value).lower()

    assert value["metadata"]["examples"] == 700
    assert len(value["items"]) == 700
    assert not {
        "entailment_label",
        "explanation",
        "relevant_context",
        "gold",
        "correct",
        "feedback",
    } & set(rendered.replace('"', "").replace("{", " ").replace("}", " ").split())
    FixedEmbeddingIndex(path)
