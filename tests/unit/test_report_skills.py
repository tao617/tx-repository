import json

import pytest

from findver_agent.report_store import ReportError, ReportStore
from findver_agent.skills.base import SkillError
from findver_agent.skills.read_paragraphs import ReadParagraphsSkill
from findver_agent.skills.search_report import SearchReportSkill


def make_report(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "context": [
                    {"id": 0, "type": "text", "context": "General corporate information."},
                    {"id": 1, "type": "table", "context": "Operating income was $128.4 million in 2022."},
                    {"id": 2, "type": "table", "context": "Operating income was $114.7 million in 2021."},
                ]
            }
        ),
        encoding="utf-8",
    )
    return ReportStore(tmp_path).open_session("report.json")


def test_bm25_search_is_local_and_deterministic(tmp_path):
    session = make_report(tmp_path)
    skill = SearchReportSkill(session)

    first = skill.execute(query="operating income 2022", top_k=2)
    second = skill.execute(query="operating income 2022", top_k=2)

    assert first == second
    assert first["hits"][0]["paragraph_id"] == 1


def test_read_paragraphs_returns_exact_text(tmp_path):
    session = make_report(tmp_path)
    result = ReadParagraphsSkill(session).execute(paragraph_ids=[2, 1])
    assert result["paragraphs"][0] == {
        "paragraph_id": 2,
        "text": "Operating income was $114.7 million in 2021.",
    }


def test_report_store_rejects_path_traversal(tmp_path):
    make_report(tmp_path)
    with pytest.raises(ReportError, match="bare filename"):
        ReportStore(tmp_path).open_session("../private/gold.jsonl")


def test_read_rejects_unknown_and_duplicate_ids(tmp_path):
    skill = ReadParagraphsSkill(make_report(tmp_path))
    with pytest.raises(SkillError):
        skill.execute(paragraph_ids=[1, 1])
    with pytest.raises(SkillError):
        skill.execute(paragraph_ids=[99])

