import json

import pytest

from findver_agent.findoasis.table_region import (
    MAX_REGION_BYTES,
    TableRegionError,
    TableRegionReader,
    read_table_region,
)
from findver_agent.report_store import ReportStore


def make_session(tmp_path, html_bundle, *, context=None):
    table_context = context or (
        "CONSOLIDATED RESULTS\n(in millions)\n"
        "| Metric | 2024 | 2023 |\n| Revenue | $ 1,200 | $ 1,000 |"
    )
    (tmp_path / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {"id": 0, "type": "table", "context": table_context}
                ],
                "html_tables": [html_bundle],
            }
        ),
        encoding="utf-8",
    )
    return ReportStore(tmp_path).open_session("report.json")


def simple_table():
    return (
        "<table><tr><th>Metric</th><th>2024</th><th>2023</th></tr>"
        "<tr><td>Revenue</td><td>$ 1,200</td><td>$ 1,000</td></tr>"
        "<tr><td>Expense</td><td>$ 800</td><td>$ 750</td></tr></table>"
    )


def test_bounded_region_keeps_exact_text_offsets_headers_unit_and_scale(tmp_path):
    session = make_session(tmp_path, simple_table())
    reader = TableRegionReader(session)

    structure = reader.describe("table:0000")
    region = reader.read(
        table_id="table:0000", row_indices=[1], column_indices=[1, 2]
    )

    assert structure.row_count == 3
    assert structure.column_count == 3
    assert region.row_count == 3
    assert region.column_count == 3
    assert [cell.text for cell in region.cells] == ["$ 1,200", "$ 1,000"]
    assert [cell.raw_text for cell in region.cells] == ["$ 1,200", "$ 1,000"]
    assert region.cells[0].column_header_path == ("2024",)
    assert region.cells[0].row_header_path == ("Revenue",)
    assert region.cells[0].header_path == ("2024", "Revenue")
    assert region.cells[0].unit == "USD"
    assert region.cells[0].scale == "million"
    source = session.tables[0].raw_html
    for cell in region.cells:
        exact_source = source[cell.source_html_start : cell.source_html_end]
        assert exact_source.startswith("<td>")
        assert cell.raw_text in exact_source


def test_execute_is_deterministic_bounded_and_does_not_expose_raw_html(tmp_path):
    reader = TableRegionReader(make_session(tmp_path, simple_table()))
    first = reader.execute(
        table_id="table:0000", row_indices=[2, 1], column_indices=[2]
    )
    second = reader.execute(
        table_id="table:0000", row_indices=[2, 1], column_indices=[2]
    )

    assert first == second
    encoded = json.dumps(first, ensure_ascii=False).encode("utf-8")
    assert len(encoded) < MAX_REGION_BYTES
    assert "raw_html" not in first
    assert "raw_html" not in encoded.decode("utf-8")
    assert [cell["row_index"] for cell in first["cells"]] == [2, 1]


def test_raw_entity_text_is_preserved_while_normalized_text_is_decoded(tmp_path):
    html = (
        "<table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>R&amp;D</td><td>120</td></tr></table>"
    )
    region = read_table_region(
        make_session(tmp_path, html),
        table_id="table:0000",
        row_indices=[1],
        column_indices=[0],
    )

    assert region.cells[0].raw_text == "R&amp;D"
    assert region.cells[0].text == "R&D"


def test_merged_cell_is_not_fabricated_for_each_expanded_column(tmp_path):
    html = (
        "<table><tr><th>Metric</th><th colspan=\"2\">Years</th></tr>"
        "<tr><td>Revenue</td><td>120</td><td>100</td></tr></table>"
    )
    region = TableRegionReader(make_session(tmp_path, html)).read(
        table_id="table:0000", row_indices=[0], column_indices=[1, 2]
    )

    assert len(region.cells) == 1
    assert region.cells[0].text == "Years"
    assert region.cells[0].column_index == 1
    assert region.cells[0].column_span == 2
    assert region.cells[0].selected_coordinates == ((0, 1), (0, 2))
    assert "merged_cell" in region.cells[0].ambiguity_flags


def test_hidden_layout_cells_do_not_shift_visible_expanded_columns(tmp_path):
    html = (
        "<table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>Revenue</td><td style=\"display: none\">ignore</td>"
        "<td>120</td></tr></table>"
    )
    region = TableRegionReader(make_session(tmp_path, html)).read(
        table_id="table:0000", row_indices=[1], column_indices=[1]
    )

    assert region.cells[0].text == "120"
    assert region.cells[0].column_index == 1


def test_compatible_multi_root_row_fragments_merge_with_global_offsets(tmp_path):
    first = (
        "<table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>Revenue</td><td>120</td></tr></table>"
    )
    empty = "<table><tr><td>&nbsp;</td><td> </td></tr></table>"
    second = "<table><tr><td>Expense</td><td>80</td></tr></table>"
    bundle = f"before{first}between{empty}more{second}after"
    session = make_session(tmp_path, bundle)
    reader = TableRegionReader(session)

    structure = reader.describe("table:0000")
    region = reader.read(
        table_id="table:0000", row_indices=[2], column_indices=[0, 1]
    )

    assert structure.row_count == 3
    assert structure.column_count == 2
    assert "multi_root_compatible_merge" in structure.ambiguity_flags
    assert "empty_layout_root_skipped" in structure.ambiguity_flags
    assert [cell.text for cell in region.cells] == ["Expense", "80"]
    assert region.cells[0].source_html_start == bundle.index("<td>Expense")


def test_incompatible_multi_root_structures_fail_closed(tmp_path):
    bundle = (
        "<table><tr><td>A</td><td>B</td></tr></table>"
        "<table><tr><td>C</td><td>D</td><td>E</td></tr></table>"
    )
    reader = TableRegionReader(make_session(tmp_path, bundle))

    with pytest.raises(TableRegionError, match="incompatible expanded widths"):
        reader.describe("table:0000")


def test_ragged_rows_fail_closed_instead_of_inventing_missing_cells(tmp_path):
    html = (
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td>C</td><td>D</td><td>E</td></tr></table>"
    )
    reader = TableRegionReader(make_session(tmp_path, html))

    with pytest.raises(TableRegionError, match="incompatible expanded widths"):
        reader.read(
            table_id="table:0000", row_indices=[0], column_indices=[0]
        )


def test_nested_table_catalog_ambiguity_is_rejected_by_reader(tmp_path):
    html = (
        "<table><tr><td>outer<table><tr><td>inner</td></tr></table>"
        "</td></tr></table>"
    )
    reader = TableRegionReader(make_session(tmp_path, html))

    with pytest.raises(TableRegionError, match="nested table structure"):
        reader.describe("table:0000")


@pytest.mark.parametrize(
    ("rows", "columns", "message"),
    [
        ([], [0], "non-empty"),
        ([0, 0], [0], "unique"),
        ([True], [0], "non-negative integers"),
        ([99], [0], "row is out of range"),
        ([0], [99], "column is out of range"),
        (list(range(21)), [0], "20-item bound"),
        ([0], list(range(13)), "12-item bound"),
    ],
)
def test_region_request_bounds_fail_closed(tmp_path, rows, columns, message):
    reader = TableRegionReader(make_session(tmp_path, simple_table()))

    with pytest.raises(TableRegionError, match=message):
        reader.read(
            table_id="table:0000", row_indices=rows, column_indices=columns
        )


def test_unknown_table_and_invalid_alignment_are_rejected(tmp_path):
    reader = TableRegionReader(make_session(tmp_path, simple_table()))
    with pytest.raises(TableRegionError, match="unknown table id"):
        reader.describe("table:9999")

    (tmp_path / "report.json").write_text(
        json.dumps(
            {
                "context": [{"id": 0, "type": "table", "context": "| A |"}],
                "html_tables": [],
            }
        ),
        encoding="utf-8",
    )
    invalid_reader = TableRegionReader(
        ReportStore(tmp_path).open_session("report.json")
    )
    with pytest.raises(TableRegionError, match="do not align"):
        invalid_reader.describe("table:0000")


def test_oversized_cell_fails_before_any_unbounded_output(tmp_path):
    html = f"<table><tr><td>{'x' * 2001}</td></tr></table>"
    reader = TableRegionReader(make_session(tmp_path, html))

    with pytest.raises(TableRegionError, match="raw-text bound"):
        reader.describe("table:0000")


def test_financial_display_forms_are_preserved_and_dash_is_not_fabricated(tmp_path):
    html = (
        "<table><tr><th>Metric</th><th>2024</th></tr>"
        "<tr><td>Loss</td><td>(1,234.50)</td></tr>"
        "<tr><td>Margin</td><td>12.5%</td></tr>"
        "<tr><td>Missing</td><td>—</td></tr></table>"
    )
    region = TableRegionReader(make_session(tmp_path, html)).read(
        table_id="table:0000",
        row_indices=[1, 2, 3],
        column_indices=[1],
    )

    assert [cell.text for cell in region.cells] == ["(1,234.50)", "12.5%", "—"]
    assert region.cells[1].unit == "percentage"
    assert region.cells[2].text != "0"


def test_duplicate_row_label_is_reported_as_ambiguous(tmp_path):
    html = (
        "<table><tr><th>Metric</th><th>2024</th></tr>"
        "<tr><td>Revenue</td><td>120</td></tr>"
        "<tr><td>Revenue</td><td>100</td></tr></table>"
    )
    region = TableRegionReader(make_session(tmp_path, html)).read(
        table_id="table:0000", row_indices=[1], column_indices=[1]
    )

    assert "row_header_ambiguous" in region.cells[0].ambiguity_flags
