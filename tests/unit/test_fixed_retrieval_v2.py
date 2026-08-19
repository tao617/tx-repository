import hashlib
import json

import pytest

from scripts.prepare_fixed_retrieval import build as build_fixed_retrieval
from findver_agent.baseline import BaselineRunner
from findver_agent.config import BaselineConfig
from findver_agent.fixed_retrieval import FixedRetrievalError, FixedRetrievalIndex
from findver_agent.model_backends.base import GenerationConfig
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PublicTask


class UnusedBackend:
    model_name = "unused"


def report_store(tmp_path, paragraphs=("zero", "one", "two", "three")):
    root = tmp_path / "reports"
    root.mkdir()
    (root / "report.json").write_text(
        json.dumps({"context": [{"context": text} for text in paragraphs]}),
        encoding="utf-8",
    )
    return ReportStore(root)


def wrapped(path, *, retriever="text-embedding-3-large", top_k=10, ids=(0,)):
    path.write_text(
        json.dumps(
            {
                "metadata": {"retriever": retriever, "top_k": top_k},
                "items": {
                    "example": {
                        "report": "report.json",
                        "retrieved_context": list(ids),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_original_findver_list_requires_and_uses_explicit_metadata(tmp_path):
    path = tmp_path / "list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "example_id": "example",
                    "report": "report.json",
                    "retrieved_context": [2, 0],
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(FixedRetrievalError, match="requires configured"):
        FixedRetrievalIndex(path)

    index = FixedRetrievalIndex(path, retriever="bm25", top_k=3)

    assert index.retriever == "bm25"
    assert index.top_k == 3
    assert index.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("retriever", "top_k"),
    [
        ("bm25", 3),
        ("contriever-msmarco", 5),
        ("text-embedding-3-large", 10),
        ("hybrid-rrf", 10),
    ],
)
def test_wrapped_top_k_and_retriever_variants_load(tmp_path, retriever, top_k):
    path = wrapped(
        tmp_path / f"{retriever}-{top_k}.json",
        retriever=retriever,
        top_k=top_k,
        ids=tuple(range(min(top_k, 4))),
    )

    index = FixedRetrievalIndex(path, retriever=retriever, top_k=top_k)

    assert (index.retriever, index.top_k) == (retriever, top_k)


def test_top_10_artifact_is_not_accepted_as_top_3(tmp_path):
    path = wrapped(tmp_path / "top10.json", top_k=10, ids=(0, 1, 2))

    with pytest.raises(FixedRetrievalError, match="top_k does not match"):
        FixedRetrievalIndex(
            path,
            retriever="text-embedding-3-large",
            top_k=3,
        )


def test_recursive_forbidden_field_is_rejected(tmp_path):
    path = wrapped(tmp_path / "forbidden.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["metadata"]["nested"] = [{"subset": "dev"}]
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(FixedRetrievalError, match="forbidden fields"):
        FixedRetrievalIndex(path)


def test_duplicate_list_example_id_is_rejected(tmp_path):
    record = {
        "example_id": "same",
        "report": "report.json",
        "retrieved_context": [0],
    }
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps([record, record]), encoding="utf-8")

    with pytest.raises(FixedRetrievalError, match="duplicate example_id"):
        FixedRetrievalIndex(path, retriever="bm25", top_k=3)


def test_duplicate_json_key_is_rejected(tmp_path):
    path = tmp_path / "duplicate-key.json"
    path.write_text(
        '{"metadata":{"retriever":"bm25","retriever":"bm25","top_k":3},"items":{}}',
        encoding="utf-8",
    )

    with pytest.raises(FixedRetrievalError, match="duplicate JSON key"):
        FixedRetrievalIndex(path)


def test_report_mismatch_and_paragraph_bounds_are_checked_at_lookup(tmp_path):
    reports = report_store(tmp_path)
    session = reports.open_session("report.json")
    mismatched = wrapped(tmp_path / "mismatch.json")
    value = json.loads(mismatched.read_text(encoding="utf-8"))
    value["items"]["example"]["report"] = "other.json"
    mismatched.write_text(json.dumps(value), encoding="utf-8")
    task = PublicTask(
        example_id="example", statement="claim", report="report.json"
    )

    with pytest.raises(FixedRetrievalError, match="report mismatch"):
        FixedRetrievalIndex(mismatched).paragraph_ids(task, session)

    out_of_range = wrapped(tmp_path / "range.json", ids=(8,))
    with pytest.raises(FixedRetrievalError, match="out of range"):
        FixedRetrievalIndex(out_of_range).paragraph_ids(task, session)


def test_fixed_retrieval_baseline_accepts_original_list_format(tmp_path):
    reports = report_store(tmp_path)
    path = tmp_path / "list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "example_id": "example",
                    "report": "report.json",
                    "retrieved_context": [2, 0],
                }
            ]
        ),
        encoding="utf-8",
    )
    runner = BaselineRunner(
        backend=UnusedBackend(),
        generation=GenerationConfig(max_context_tokens=1024),
        baseline_config=BaselineConfig(
            retrieval="fixed_retrieval",
            retrieval_file=path,
            retriever="bm25",
            top_k=3,
        ),
        report_store=reports,
        run_dir=tmp_path / "run",
    )
    task = PublicTask(
        example_id="example", statement="claim", report="report.json"
    )

    assert runner._context(task, reports.open_session("report.json")) == (
        "[paragraph id = 2] two\n[paragraph id = 0] zero\n"
    )


def test_prepare_fixed_retrieval_accepts_original_report_path(tmp_path):
    reports = report_store(tmp_path)
    tasks_path = tmp_path / "tasks.jsonl"
    tasks_path.write_text(
        json.dumps(
            {
                "example_id": "example",
                "statement": "claim",
                "report": "report.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    official_path = tmp_path / "official.json"
    official_path.write_text(
        json.dumps(
            [
                {
                    "example_id": "example",
                    "report": "reports/processed_reports/report.json",
                    "retrieved_context": [2, 0],
                }
            ]
        ),
        encoding="utf-8",
    )

    value = build_fixed_retrieval(
        tasks_path=tasks_path,
        reports_path=reports.root,
        official_paths=[official_path],
        source_commit="frozen-commit",
        retriever="text-embedding-3-large",
        top_k=3,
    )

    assert value["metadata"]["top_k"] == 3
    assert value["items"]["example"] == {
        "report": "report.json",
        "retrieved_context": [2, 0],
    }
