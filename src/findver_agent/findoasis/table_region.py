"""Bounded, fail-closed reads from immutable report table bundles."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from findver_agent.report_store import ReportError, ReportSession, ReportTable


MAX_ROWS_PER_REGION = 20
MAX_COLUMNS_PER_REGION = 12
MAX_CELLS_PER_REGION = MAX_ROWS_PER_REGION * MAX_COLUMNS_PER_REGION
MAX_SOURCE_ROWS = 1_024
MAX_SOURCE_COLUMNS = 256
MAX_TABLE_HTML_CHARACTERS = 4 * 1024 * 1024
MAX_CELL_RAW_TEXT_CHARACTERS = 2_000
MAX_REGION_BYTES = 32 * 1024
MAX_HTML_NODES = 100_000


class TableRegionError(ValueError):
    """The requested table region is invalid, ambiguous, or exceeds a bound."""


@dataclass(frozen=True, slots=True)
class TableCell:
    table_id: str
    paragraph_id: int
    row_index: int
    column_index: int
    row_span: int
    column_span: int
    selected_coordinates: tuple[tuple[int, int], ...]
    raw_text: str
    text: str
    source_html_start: int
    source_html_end: int
    header_path: tuple[str, ...]
    row_header_path: tuple[str, ...]
    column_header_path: tuple[str, ...]
    unit: str
    scale: str
    ambiguity_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "table_id": self.table_id,
            "paragraph_id": self.paragraph_id,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "row_span": self.row_span,
            "column_span": self.column_span,
            "selected_coordinates": [list(item) for item in self.selected_coordinates],
            "raw_text": self.raw_text,
            "text": self.text,
            "source_html_start": self.source_html_start,
            "source_html_end": self.source_html_end,
            "header_path": list(self.header_path),
            "row_header_path": list(self.row_header_path),
            "column_header_path": list(self.column_header_path),
            "unit": self.unit,
            "scale": self.scale,
            "ambiguity_flags": list(self.ambiguity_flags),
        }


@dataclass(frozen=True, slots=True)
class TableRegion:
    table_id: str
    paragraph_id: int
    source_context_index: int
    source_html_bundle_index: int
    row_count: int
    column_count: int
    selected_row_indices: tuple[int, ...]
    selected_column_indices: tuple[int, ...]
    cells: tuple[TableCell, ...]
    ambiguity_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "table_id": self.table_id,
            "paragraph_id": self.paragraph_id,
            "source_context_index": self.source_context_index,
            "source_html_bundle_index": self.source_html_bundle_index,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "selected_row_indices": list(self.selected_row_indices),
            "selected_column_indices": list(self.selected_column_indices),
            "cells": [cell.to_dict() for cell in self.cells],
            "ambiguity_flags": list(self.ambiguity_flags),
        }


@dataclass(frozen=True, slots=True)
class TableStructure:
    table_id: str
    paragraph_id: int
    row_count: int
    column_count: int
    ambiguity_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "table_id": self.table_id,
            "paragraph_id": self.paragraph_id,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "ambiguity_flags": list(self.ambiguity_flags),
        }


@dataclass(frozen=True, slots=True)
class _ParsedCell:
    source_root_index: int
    source_row_index: int
    row_index: int
    column_index: int
    row_span: int
    column_span: int
    is_header: bool
    raw_text: str
    text: str
    source_html_start: int
    source_html_end: int


@dataclass(frozen=True, slots=True)
class _ParsedRow:
    source_root_index: int
    source_row_index: int
    row_index: int
    cells: tuple[_ParsedCell, ...]


@dataclass(frozen=True, slots=True)
class _ParsedTable:
    rows: tuple[_ParsedRow, ...]
    grid: tuple[tuple[_ParsedCell, ...], ...]
    column_count: int
    header_row_indices: tuple[int, ...]
    ambiguity_flags: tuple[str, ...]
    scope_text: str


@dataclass(slots=True)
class _CellBuilder:
    tag: str
    source_root_index: int
    source_row_index: int
    row_span: int
    column_span: int
    is_header: bool
    hidden: bool
    source_html_start: int
    raw_chunks: list[str]


@dataclass(slots=True)
class _RowBuilder:
    source_root_index: int
    source_row_index: int
    hidden: bool
    cells: list[tuple[_CellBuilder, int]]


def _style_is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
    values = {key.casefold(): value or "" for key, value in attrs}
    style = re.sub(r"\s+", "", values.get("style", "").casefold())
    return "display:none" in style or "hidden" in values


def _positive_span(attrs: list[tuple[str, str | None]], name: str) -> int:
    values = {key.casefold(): value for key, value in attrs}
    raw = values.get(name)
    if raw is None:
        return 1
    if not re.fullmatch(r"[1-9][0-9]{0,2}", raw.strip()):
        raise TableRegionError(f"invalid {name} in table source")
    value = int(raw)
    if value > MAX_SOURCE_COLUMNS:
        raise TableRegionError(f"{name} exceeds the table-source bound")
    return value


class _RootTableParser(HTMLParser):
    _CLOSING_CELL_RE = {
        "td": re.compile(r"</\s*td\s*>", re.IGNORECASE),
        "th": re.compile(r"</\s*th\s*>", re.IGNORECASE),
    }

    def __init__(self, source: str, *, base_offset: int, root_index: int) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.base_offset = base_offset
        self.root_index = root_index
        self.line_offsets = [0]
        for match in re.finditer("\n", source):
            self.line_offsets.append(match.end())
        self.table_depth = 0
        self.current_row: _RowBuilder | None = None
        self.current_cell: _CellBuilder | None = None
        self.rows: list[list[tuple[_CellBuilder, int]]] = []
        self.error: str | None = None
        self.source_row_sequence = 0
        self.node_count = 0

    def _local_offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def _global_offset(self) -> int:
        return self.base_offset + self._local_offset()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if self.error is not None:
            return
        self.node_count += 1
        if self.node_count > MAX_HTML_NODES:
            self.error = "table HTML exceeds the parser node bound"
            return
        if tag == "table":
            self.table_depth += 1
            if self.table_depth > 1:
                self.error = "nested table structure cannot be read reliably"
            return
        if self.table_depth != 1:
            return
        if tag == "tr":
            if self.current_row is not None or self.current_cell is not None:
                self.error = "nested or unclosed table row"
                return
            self.current_row = _RowBuilder(
                source_root_index=self.root_index,
                source_row_index=self.source_row_sequence,
                hidden=_style_is_hidden(attrs),
                cells=[],
            )
            self.source_row_sequence += 1
            return
        if tag in {"td", "th"}:
            if self.current_row is None or self.current_cell is not None:
                self.error = "table cell is outside a unique row"
                return
            try:
                row_span = _positive_span(attrs, "rowspan")
                column_span = _positive_span(attrs, "colspan")
            except TableRegionError as error:
                self.error = str(error)
                return
            self.current_cell = _CellBuilder(
                tag=tag,
                source_root_index=self.root_index,
                source_row_index=self.current_row.source_row_index,
                row_span=row_span,
                column_span=column_span,
                is_header=tag == "th",
                hidden=self.current_row.hidden or _style_is_hidden(attrs),
                source_html_start=self._global_offset(),
                raw_chunks=[],
            )

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() in {"table", "tr", "td", "th"}:
            self.error = "self-closing table structure is not supported"

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None and not self.current_cell.hidden:
            self.current_cell.raw_chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if self.current_cell is not None and not self.current_cell.hidden:
            self.current_cell.raw_chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.current_cell is not None and not self.current_cell.hidden:
            self.current_cell.raw_chunks.append(f"&#{name};")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self.error is not None:
            return
        if tag in {"td", "th"} and self.table_depth == 1:
            if self.current_cell is None or self.current_cell.tag != tag:
                self.error = "table cell closing tag is unmatched"
                return
            closing = self._CLOSING_CELL_RE[tag].match(
                self.source, self._local_offset()
            )
            if closing is None:
                self.error = "table cell source boundary could not be located"
                return
            if not self.current_cell.hidden:
                self.current_row.cells.append(
                    (self.current_cell, self.base_offset + closing.end())
                )
            self.current_cell = None
            return
        if tag == "tr" and self.table_depth == 1:
            if self.current_row is None or self.current_cell is not None:
                self.error = "table row closing tag is unmatched"
                return
            if not self.current_row.hidden and self.current_row.cells:
                self.rows.append(self.current_row.cells)
            self.current_row = None
            return
        if tag == "table":
            if self.table_depth == 0:
                self.error = "table closing tag is unmatched"
                return
            if self.current_row is not None or self.current_cell is not None:
                self.error = "table closed before its row or cell"
                return
            self.table_depth -= 1

    def parse(self) -> list[list[tuple[_CellBuilder, int]]]:
        try:
            self.feed(self.source)
            self.close()
        except (AssertionError, ValueError) as error:
            raise TableRegionError("malformed table HTML") from error
        if self.error is not None:
            raise TableRegionError(self.error)
        if self.table_depth != 0 or self.current_row is not None:
            raise TableRegionError("unclosed table structure")
        return self.rows


def _normalized_text(raw_text: str) -> str:
    return " ".join(html.unescape(raw_text).replace("\xa0", " ").split())


def _place_root_rows(
    source_rows: list[list[tuple[_CellBuilder, int]]],
    *,
    first_global_row: int,
) -> tuple[list[_ParsedRow], list[list[_ParsedCell]], int, bool]:
    parsed_rows: list[_ParsedRow] = []
    grids: list[list[_ParsedCell]] = []
    active: dict[int, tuple[_ParsedCell, int]] = {}
    expected_width: int | None = None
    skipped_empty_row = False

    for source_cells in source_rows:
        if not active and not any(
            _normalized_text("".join(builder.raw_chunks))
            for builder, _ in source_cells
        ):
            skipped_empty_row = True
            continue
        occupied: dict[int, _ParsedCell] = {
            column: cell for column, (cell, _) in active.items()
        }
        cursor = 0
        parsed_cells: list[_ParsedCell] = []
        global_row_index = first_global_row + len(parsed_rows)
        for builder, source_end in source_cells:
            while cursor in occupied:
                cursor += 1
            while any(
                column in occupied
                for column in range(cursor, cursor + builder.column_span)
            ):
                cursor += 1
                while cursor in occupied:
                    cursor += 1
            raw_text = "".join(builder.raw_chunks)
            if len(raw_text) > MAX_CELL_RAW_TEXT_CHARACTERS:
                raise TableRegionError("table cell exceeds the raw-text bound")
            cell = _ParsedCell(
                source_root_index=builder.source_root_index,
                source_row_index=builder.source_row_index,
                row_index=global_row_index,
                column_index=cursor,
                row_span=builder.row_span,
                column_span=builder.column_span,
                is_header=builder.is_header,
                raw_text=raw_text,
                text=_normalized_text(raw_text),
                source_html_start=builder.source_html_start,
                source_html_end=source_end,
            )
            parsed_cells.append(cell)
            for column in range(cursor, cursor + builder.column_span):
                occupied[column] = cell
            cursor += builder.column_span

        if not occupied:
            continue
        width = max(occupied) + 1
        if width > MAX_SOURCE_COLUMNS:
            raise TableRegionError("table exceeds the source-column bound")
        if set(occupied) != set(range(width)):
            raise TableRegionError("table row contains an unresolved structural gap")
        if expected_width is None:
            expected_width = width
        elif expected_width != width:
            raise TableRegionError("table rows have incompatible expanded widths")

        parsed_row = _ParsedRow(
            source_root_index=(
                parsed_cells[0].source_root_index
                if parsed_cells
                else next(iter(occupied.values())).source_root_index
            ),
            source_row_index=(
                parsed_cells[0].source_row_index
                if parsed_cells
                else next(iter(occupied.values())).source_row_index
            ),
            row_index=global_row_index,
            cells=tuple(parsed_cells),
        )
        parsed_rows.append(parsed_row)
        grids.append([occupied[column] for column in range(width)])

        next_active: dict[int, tuple[_ParsedCell, int]] = {}
        for column, (cell, remaining) in active.items():
            if remaining > 1:
                next_active[column] = (cell, remaining - 1)
        for cell in parsed_cells:
            if cell.row_span > 1:
                for column in range(
                    cell.column_index, cell.column_index + cell.column_span
                ):
                    next_active[column] = (cell, cell.row_span - 1)
        active = next_active

    if active:
        raise TableRegionError("rowspan extends beyond the table source")
    return parsed_rows, grids, expected_width or 0, skipped_empty_row


_NUMERIC_VALUE_RE = re.compile(
    r"^\(?\s*[-+]?\s*(?:[$¥€£]\s*)?"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%?\s*\)?$"
)


def _looks_like_data_value(text: str) -> bool:
    if not _NUMERIC_VALUE_RE.fullmatch(text.strip()):
        return False
    digits = re.sub(r"\D", "", text)
    if len(digits) == 4 and 1800 <= int(digits) <= 2199:
        return False
    return True


def _header_rows(rows: list[_ParsedRow], grids: list[list[_ParsedCell]]) -> tuple[int, ...]:
    explicit = {
        row.row_index for row in rows if any(cell.is_header for cell in row.cells)
    }
    if explicit:
        return tuple(sorted(explicit))
    inferred: list[int] = []
    for row, grid in zip(rows, grids, strict=True):
        nonblank = [cell for cell in row.cells if cell.text]
        is_data = len(nonblank) >= 2 and any(
            _looks_like_data_value(cell.text) for cell in nonblank[1:]
        )
        if is_data:
            break
        inferred.append(row.row_index)
    return tuple(inferred)


def _parse_table(table: ReportTable) -> _ParsedTable:
    if "nested_table_structure" in table.ambiguity_flags:
        raise TableRegionError("nested table structure cannot be read reliably")
    if len(table.raw_html) > MAX_TABLE_HTML_CHARACTERS:
        raise TableRegionError("table HTML exceeds the parser bound")

    retained_roots: list[
        tuple[list[_ParsedRow], list[list[_ParsedCell]], int]
    ] = []
    ambiguity_flags = list(table.ambiguity_flags)
    next_row = 0
    for root_index, (start, end) in enumerate(table.source_root_spans):
        fragment = table.raw_html[start:end]
        source_rows = _RootTableParser(
            fragment, base_offset=start, root_index=root_index
        ).parse()
        has_text = any(
            _normalized_text("".join(builder.raw_chunks))
            for row in source_rows
            for builder, _ in row
        )
        if not has_text:
            if "empty_layout_root_skipped" not in ambiguity_flags:
                ambiguity_flags.append("empty_layout_root_skipped")
            continue
        rows, grids, width, skipped_empty_row = _place_root_rows(
            source_rows, first_global_row=next_row
        )
        if skipped_empty_row and "empty_layout_row_skipped" not in ambiguity_flags:
            ambiguity_flags.append("empty_layout_row_skipped")
        if not rows or width == 0:
            raise TableRegionError("table root has no readable rows")
        retained_roots.append((rows, grids, width))
        next_row += len(rows)

    if not retained_roots:
        raise TableRegionError("table bundle has no non-empty logical root")
    widths = {width for _, _, width in retained_roots}
    if len(widths) != 1:
        raise TableRegionError("table roots have incompatible expanded widths")
    if len(retained_roots) > 1:
        ambiguity_flags.append("multi_root_compatible_merge")

    rows = [row for root_rows, _, _ in retained_roots for row in root_rows]
    grids = [grid for _, root_grids, _ in retained_roots for grid in root_grids]
    if len(rows) > MAX_SOURCE_ROWS:
        raise TableRegionError("table exceeds the source-row bound")
    scope_parts = [cell.text for row in rows for cell in row.cells if cell.text]
    scope_parts.append(table.raw_context)
    return _ParsedTable(
        rows=tuple(rows),
        grid=tuple(tuple(grid) for grid in grids),
        column_count=widths.pop(),
        header_row_indices=_header_rows(rows, grids),
        ambiguity_flags=tuple(dict.fromkeys(ambiguity_flags)),
        scope_text=" ".join(scope_parts),
    )


def _unique_text(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _header_paths(
    parsed: _ParsedTable, cell: _ParsedCell
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    column_headers: list[str] = []
    for row_index in parsed.header_row_indices:
        if row_index >= cell.row_index:
            continue
        header = parsed.grid[row_index][cell.column_index]
        if header.text:
            column_headers.append(header.text)
    source_row = parsed.rows[cell.row_index]
    row_headers = [
        candidate.text
        for candidate in source_row.cells
        if candidate.column_index < cell.column_index and candidate.text
    ][:1]
    column_path = _unique_text(column_headers)
    row_path = _unique_text(row_headers)
    return _unique_text([*column_path, *row_path]), row_path, column_path


_SCALE_PATTERNS = (
    ("thousand", re.compile(r"\bin\s+thousands?\b|\bthousands?\s+of\b", re.I)),
    ("million", re.compile(r"\bin\s+millions?\b|\bmillions?\s+of\b", re.I)),
    ("billion", re.compile(r"\bin\s+billions?\b|\bbillions?\s+of\b", re.I)),
    ("thousand", re.compile(r"单位\s*[:：]?\s*千(?:元|股)?")),
    ("million", re.compile(r"单位\s*[:：]?\s*百万元?")),
    ("hundred_million", re.compile(r"单位\s*[:：]?\s*亿元?")),
)


def _unit_and_scale(
    parsed: _ParsedTable,
    cell: _ParsedCell,
    row_header_path: tuple[str, ...],
) -> tuple[str, str, list[str]]:
    flags: list[str] = []
    text = cell.text
    row_context = " ".join(row_header_path)
    numeric = _looks_like_data_value(text)

    if "%" in text:
        return "percentage", "ones", flags
    if "per share" in row_context.casefold():
        return "per_share", "ones", flags

    row = parsed.rows[cell.row_index]
    preceding = [
        candidate.text
        for candidate in row.cells
        if candidate.column_index < cell.column_index and candidate.text
    ]
    local = " ".join([*preceding[-2:], text])
    unit_candidates: list[str] = []
    for marker, unit in (
        ("$", "USD"),
        ("€", "EUR"),
        ("£", "GBP"),
    ):
        if marker in local:
            unit_candidates.append(unit)
    lowered_scope = parsed.scope_text.casefold()
    for pattern, unit in (
        (r"\b(?:usd|u\.s\.\s+dollars?|dollars?)\b", "USD"),
        (r"\b(?:eur|euros?)\b", "EUR"),
        (r"\b(?:gbp|pounds?)\b", "GBP"),
        (r"\b(?:cny|rmb)\b|人民币", "CNY"),
        (r"\b(?:jpy|yen)\b|日元", "JPY"),
    ):
        if re.search(pattern, lowered_scope, re.I):
            unit_candidates.append(unit)
    if "¥" in local and not {"CNY", "JPY"} & set(unit_candidates):
        flags.append("currency_symbol_ambiguous")
    units = set(unit_candidates)
    if len(units) == 1:
        unit = units.pop()
    elif len(units) > 1:
        unit = "unknown"
        flags.append("unit_ambiguous")
    elif "share" in row_context.casefold():
        unit = "shares"
    else:
        unit = "unknown"
        if numeric:
            flags.append("unit_unknown")

    scales = {
        scale
        for scale, pattern in _SCALE_PATTERNS
        if pattern.search(parsed.scope_text)
    }
    if len(scales) == 1:
        scale = scales.pop()
    elif len(scales) > 1:
        scale = "unknown"
        flags.append("scale_ambiguous")
    else:
        scale = "unknown"
        if numeric:
            flags.append("scale_unknown")
    return unit, scale, flags


def _validate_indices(
    value: list[int], *, name: str, maximum: int
) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise TableRegionError(f"{name} must be a non-empty list")
    if len(value) > maximum:
        raise TableRegionError(f"{name} exceeds the {maximum}-item bound")
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in value
    ):
        raise TableRegionError(f"{name} must contain non-negative integers")
    if len(value) != len(set(value)):
        raise TableRegionError(f"{name} must contain unique indices")
    return tuple(value)


class TableRegionReader:
    """Read exact source cells from one table using the v3 action coordinates."""

    def __init__(self, session: ReportSession) -> None:
        self._session = session

    def describe(self, table_id: str) -> TableStructure:
        table = self._table(table_id)
        parsed = _parse_table(table)
        return TableStructure(
            table_id=table.table_id,
            paragraph_id=table.paragraph_id,
            row_count=len(parsed.rows),
            column_count=parsed.column_count,
            ambiguity_flags=parsed.ambiguity_flags,
        )

    def read(
        self,
        *,
        table_id: str,
        row_indices: list[int],
        column_indices: list[int],
    ) -> TableRegion:
        rows = _validate_indices(
            row_indices, name="row_indices", maximum=MAX_ROWS_PER_REGION
        )
        columns = _validate_indices(
            column_indices,
            name="column_indices",
            maximum=MAX_COLUMNS_PER_REGION,
        )
        if len(rows) * len(columns) > MAX_CELLS_PER_REGION:
            raise TableRegionError("requested table region exceeds the cell bound")
        table = self._table(table_id)
        parsed = _parse_table(table)
        if any(row >= len(parsed.rows) for row in rows):
            raise TableRegionError("requested table row is out of range")
        if any(column >= parsed.column_count for column in columns):
            raise TableRegionError("requested table column is out of range")

        selected: dict[tuple[int, int], list[tuple[int, int]]] = {}
        cells_by_source: dict[tuple[int, int], _ParsedCell] = {}
        for row in rows:
            for column in columns:
                cell = parsed.grid[row][column]
                key = (cell.source_html_start, cell.source_html_end)
                selected.setdefault(key, []).append((row, column))
                cells_by_source[key] = cell

        output_cells: list[TableCell] = []
        for key, coordinates in selected.items():
            cell = cells_by_source[key]
            header_path, row_path, column_path = _header_paths(parsed, cell)
            unit, scale, unit_flags = _unit_and_scale(parsed, cell, row_path)
            flags = list(parsed.ambiguity_flags)
            flags.extend(unit_flags)
            if row_path:
                row_label = row_path[0].casefold()
                matching_rows = sum(
                    any(
                        candidate.column_index == 0
                        and candidate.text.casefold() == row_label
                        for candidate in row.cells
                    )
                    for row in parsed.rows
                )
                if matching_rows > 1:
                    flags.append("row_header_ambiguous")
            if not cell.text:
                flags.append("blank_cell")
            if cell.row_span > 1 or cell.column_span > 1:
                flags.append("merged_cell")
            if not column_path and cell.column_index > 0:
                flags.append("column_header_unresolved")
            output_cells.append(
                TableCell(
                    table_id=table.table_id,
                    paragraph_id=table.paragraph_id,
                    row_index=cell.row_index,
                    column_index=cell.column_index,
                    row_span=cell.row_span,
                    column_span=cell.column_span,
                    selected_coordinates=tuple(coordinates),
                    raw_text=cell.raw_text,
                    text=cell.text,
                    source_html_start=cell.source_html_start,
                    source_html_end=cell.source_html_end,
                    header_path=header_path,
                    row_header_path=row_path,
                    column_header_path=column_path,
                    unit=unit,
                    scale=scale,
                    ambiguity_flags=tuple(dict.fromkeys(flags)),
                )
            )

        region = TableRegion(
            table_id=table.table_id,
            paragraph_id=table.paragraph_id,
            source_context_index=table.source_context_index,
            source_html_bundle_index=table.source_html_bundle_index,
            row_count=len(parsed.rows),
            column_count=parsed.column_count,
            selected_row_indices=rows,
            selected_column_indices=columns,
            cells=tuple(output_cells),
            ambiguity_flags=parsed.ambiguity_flags,
        )
        if len(
            json.dumps(
                region.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ) > MAX_REGION_BYTES:
            raise TableRegionError("table region exceeds the serialized size bound")
        return region

    def execute(
        self,
        *,
        table_id: str,
        row_indices: list[int],
        column_indices: list[int],
    ) -> dict[str, object]:
        return self.read(
            table_id=table_id,
            row_indices=row_indices,
            column_indices=column_indices,
        ).to_dict()

    def _table(self, table_id: str) -> ReportTable:
        try:
            return self._session.table(table_id)
        except ReportError as error:
            raise TableRegionError(str(error)) from error


def read_table_region(
    session: ReportSession,
    *,
    table_id: str,
    row_indices: list[int],
    column_indices: list[int],
) -> TableRegion:
    return TableRegionReader(session).read(
        table_id=table_id,
        row_indices=row_indices,
        column_indices=column_indices,
    )


__all__ = [
    "MAX_COLUMNS_PER_REGION",
    "MAX_REGION_BYTES",
    "MAX_ROWS_PER_REGION",
    "TableCell",
    "TableRegion",
    "TableRegionError",
    "TableRegionReader",
    "TableStructure",
    "read_table_region",
]
