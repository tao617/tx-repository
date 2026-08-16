import json

import pytest

from findver_agent.fixed_retrieval import FixedRetrievalError, FixedRetrievalIndex


def write_wrapped(tmp_path, *, report="report.json", ids=None, top_k=3):
    if ids is None:
        ids = [0]
    path = tmp_path / "retrieval.json"
    path.write_text(
        json.dumps(
            {
                "metadata": {"retriever": "bm25", "top_k": top_k},
                "items": {
                    "example": {
                        "report": report,
                        "retrieved_context": ids,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("ids", [[0, 0], [-1], [True], [0, 1, 2, 3]])
def test_invalid_or_over_cutoff_paragraph_ids_are_rejected(tmp_path, ids):
    path = write_wrapped(tmp_path, ids=ids)

    with pytest.raises(FixedRetrievalError, match="invalid paragraph ids"):
        FixedRetrievalIndex(path)


@pytest.mark.parametrize(
    "report",
    ["", ".", "../report.json", "folder/report.json", "report.txt"],
)
def test_unsafe_report_name_is_rejected(tmp_path, report):
    path = write_wrapped(tmp_path, report=report)

    with pytest.raises(FixedRetrievalError, match="invalid report name"):
        FixedRetrievalIndex(path)


def test_retriever_metadata_mismatch_is_rejected(tmp_path):
    path = write_wrapped(tmp_path)

    with pytest.raises(FixedRetrievalError, match="retriever does not match"):
        FixedRetrievalIndex(path, retriever="contriever-msmarco", top_k=3)
