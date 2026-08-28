import json
from dataclasses import FrozenInstanceError

import pytest

from findver_agent.report_store import (
    MAX_TABLE_HTML_CHARACTERS,
    MAX_TABLE_ROOTS,
    ReportError,
    ReportStore,
)


def write_report(tmp_path, payload):
    (tmp_path / "report.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return ReportStore(tmp_path).open_session("report.json")


def table_context(text, *, context_id=1):
    return {"id": context_id, "type": "table", "context": text}


def test_parallel_table_index_preserves_legacy_paragraph_ids_and_exact_text(tmp_path):
    table_text = "Statement title\n| Metric | 2024 |\n| Revenue | 120 |"
    first = '<table data-name="first"><tr><td>Revenue</td><td>120</td></tr></table>'
    second = "<table><tr><td>Expense</td><td>80</td></tr></table>"
    bundle = f"prefix\n{first}\nnoise\n{second}\nsuffix"
    session = write_report(
        tmp_path,
        {
            "context": [
                {"id": 0, "type": "paragraph", "context": "Exact paragraph."},
                table_context(table_text),
                {"id": 2, "type": "paragraph", "context": "Last paragraph."},
            ],
            "html_tables": [bundle],
        },
    )

    assert [(item.paragraph_id, item.text) for item in session.paragraphs] == [
        (0, "Exact paragraph."),
        (1, table_text),
        (2, "Last paragraph."),
    ]
    assert session.read(1).text == table_text
    assert session.table_alignment_valid is True
    assert [table.table_id for table in session.tables] == ["table:0001"]
    table = session.tables[0]
    assert table.raw_html == bundle
    assert table.paragraph_id == 1
    assert table.source_html_bundle_index == 0
    assert table.source_root_spans == (
        (bundle.index(first), bundle.index(first) + len(first)),
        (bundle.index(second), bundle.index(second) + len(second)),
    )
    assert bundle[table.source_html_start : table.source_html_end] == table.raw_html
    assert table.ambiguity_flags == ("multi_root_table_bundle",)


def test_catalog_is_bounded_text_free_metadata_and_tables_are_immutable(tmp_path):
    session = write_report(
        tmp_path,
        {
            "context": [table_context("| Metric | Value |", context_id=0)],
            "html_tables": ["<table><tr><td>Metric</td><td>Value</td></tr></table>"],
        },
    )

    catalog = session.table_catalog(limit=1)
    assert len(catalog) == 1
    assert catalog[0].table_id == "table:0000"
    assert catalog[0].paragraph_id == 0
    assert not hasattr(catalog[0], "raw_html")
    assert not hasattr(catalog[0], "raw_context")
    with pytest.raises(FrozenInstanceError):
        session.tables[0].table_id = "changed"
    with pytest.raises(ReportError, match="between 1 and 64"):
        session.table_catalog(limit=65)


@pytest.mark.parametrize(
    ("html_tables", "error"),
    [
        ([], "do not align"),
        ("<table></table>", "must be a list"),
        ([42], "non-empty string"),
        (["not a table"], "no top-level table"),
        (["<table><tr><td>open"], "unclosed table"),
    ],
)
def test_unreliable_alignment_fails_closed_without_breaking_paragraphs(
    tmp_path, html_tables, error
):
    exact = "| Metric | 2024 |\n| Revenue | 120 |"
    session = write_report(
        tmp_path,
        {
            "context": [table_context(exact, context_id=0)],
            "html_tables": html_tables,
        },
    )

    assert session.read(0).text == exact
    assert session.tables == ()
    assert session.table_alignment_valid is False
    assert error in session.table_alignment_error
    with pytest.raises(ReportError, match=error):
        session.table("table:0000")


def test_missing_html_is_valid_only_when_no_table_context_exists(tmp_path):
    plain = write_report(
        tmp_path,
        {
            "context": [
                {"id": 0, "type": "paragraph", "context": "Plain text."}
            ]
        },
    )
    assert plain.table_alignment_valid is True
    assert plain.tables == ()

    table_only = write_report(
        tmp_path,
        {"context": [table_context("| A | B |", context_id=0)]},
    )
    assert table_only.read(0).text == "| A | B |"
    assert table_only.table_alignment_valid is False
    assert table_only.tables == ()


def test_context_id_drift_disables_only_the_new_table_view(tmp_path):
    session = write_report(
        tmp_path,
        {
            "context": [table_context("| A | B |", context_id=99)],
            "html_tables": ["<table><tr><td>A</td><td>B</td></tr></table>"],
        },
    )

    assert session.paragraphs[0].paragraph_id == 0
    assert session.table_alignment_valid is False
    assert "immutable context index" in session.table_alignment_error


def test_nested_table_is_catalogued_as_ambiguous_for_reader_fail_closed(tmp_path):
    html = (
        "<table><tr><td>outer<table><tr><td>inner</td></tr></table>"
        "</td></tr></table>"
    )
    session = write_report(
        tmp_path,
        {
            "context": [table_context("| outer |", context_id=0)],
            "html_tables": [html],
        },
    )

    assert session.table_alignment_valid is True
    assert session.tables[0].raw_html == html
    assert session.tables[0].ambiguity_flags == ("nested_table_structure",)


@pytest.mark.parametrize(
    ("html", "message"),
    [
        (
            "<table><tr><td>" + "x" * MAX_TABLE_HTML_CHARACTERS + "</td></tr></table>",
            "size bound",
        ),
        ("".join("<table><tr><td>x</td></tr></table>" for _ in range(MAX_TABLE_ROOTS + 1)), "root-table bound"),
    ],
)
def test_malicious_table_bundle_bounds_disable_only_table_view(tmp_path, html, message):
    session = write_report(
        tmp_path,
        {
            "context": [table_context("| Metric | Value |", context_id=0)],
            "html_tables": [html],
        },
    )

    assert session.read(0).text == "| Metric | Value |"
    assert session.tables == ()
    assert session.table_alignment_valid is False
    assert message in session.table_alignment_error
