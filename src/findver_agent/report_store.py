"""Safe access to the report bound to one question."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


MAX_LOGICAL_TABLES = 512
MAX_TABLE_CATALOG_ENTRIES = 64
MAX_TABLE_HTML_CHARACTERS = 4 * 1024 * 1024
MAX_TABLE_ROOTS = 128


class ReportError(ValueError):
    """A report is missing, malformed, or outside the report root."""


@dataclass(frozen=True, slots=True)
class Paragraph:
    paragraph_id: int
    text: str


@dataclass(frozen=True, slots=True)
class ReportTable:
    """One table context and its exactly aligned HTML bundle."""

    table_id: str
    paragraph_id: int
    source_context_index: int
    source_html_bundle_index: int
    source_html_start: int
    source_html_end: int
    source_root_spans: tuple[tuple[int, int], ...]
    raw_context: str
    raw_html: str
    ambiguity_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TableCatalogEntry:
    """Bounded, text-free table metadata safe to expose to routing code."""

    table_id: str
    paragraph_id: int
    source_context_index: int
    source_html_bundle_index: int
    source_html_start: int
    source_html_end: int
    source_root_count: int
    context_character_count: int
    html_character_count: int
    ambiguity_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportSession:
    report_name: str
    paragraphs: tuple[Paragraph, ...]
    tables: tuple[ReportTable, ...] = ()
    table_alignment_valid: bool = True
    table_alignment_error: str | None = None

    def read(self, paragraph_id: int) -> Paragraph:
        if isinstance(paragraph_id, bool) or paragraph_id < 0 or paragraph_id >= len(self.paragraphs):
            raise ReportError(f"paragraph id out of range: {paragraph_id}")
        return self.paragraphs[paragraph_id]

    def table(self, table_id: str) -> ReportTable:
        if not self.table_alignment_valid:
            raise ReportError(
                self.table_alignment_error or "report table alignment is unavailable"
            )
        if not isinstance(table_id, str):
            raise ReportError("table id must be a string")
        for table in self.tables:
            if table.table_id == table_id:
                return table
        raise ReportError(f"unknown table id: {table_id}")

    def table_catalog(
        self, *, offset: int = 0, limit: int = MAX_TABLE_CATALOG_ENTRIES
    ) -> tuple[TableCatalogEntry, ...]:
        if not self.table_alignment_valid:
            raise ReportError(
                self.table_alignment_error or "report table alignment is unavailable"
            )
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ReportError("table catalog offset must be a non-negative integer")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > MAX_TABLE_CATALOG_ENTRIES
        ):
            raise ReportError(
                f"table catalog limit must be between 1 and {MAX_TABLE_CATALOG_ENTRIES}"
            )
        return tuple(
            TableCatalogEntry(
                table_id=table.table_id,
                paragraph_id=table.paragraph_id,
                source_context_index=table.source_context_index,
                source_html_bundle_index=table.source_html_bundle_index,
                source_html_start=table.source_html_start,
                source_html_end=table.source_html_end,
                source_root_count=len(table.source_root_spans),
                context_character_count=len(table.raw_context),
                html_character_count=len(table.raw_html),
                ambiguity_flags=table.ambiguity_flags,
            )
            for table in self.tables[offset : offset + limit]
        )


class _TopLevelTableSplitter(HTMLParser):
    """Locate balanced top-level table spans without normalizing source HTML."""

    _CLOSING_TABLE_RE = re.compile(r"</\s*table\s*>", re.IGNORECASE)

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets = [0]
        for match in re.finditer("\n", source):
            self.line_offsets.append(match.end())
        self.depth = 0
        self.current_start: int | None = None
        self.current_nested = False
        self.spans: list[tuple[int, int, bool]] = []
        self.error: str | None = None

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "table" or self.error is not None:
            return
        start = self._offset()
        if self.depth == 0:
            self.current_start = start
            self.current_nested = False
        else:
            self.current_nested = True
        self.depth += 1

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag.casefold() == "table":
            self.error = "self-closing table tags are not supported"

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "table" or self.error is not None:
            return
        if self.depth == 0:
            self.error = "table bundle contains an unmatched closing table tag"
            return
        start = self._offset()
        closing = self._CLOSING_TABLE_RE.match(self.source, start)
        if closing is None:
            self.error = "table bundle closing tag could not be located exactly"
            return
        self.depth -= 1
        if self.depth == 0:
            if self.current_start is None:
                self.error = "table bundle lost its opening table boundary"
                return
            self.spans.append(
                (self.current_start, closing.end(), self.current_nested)
            )
            self.current_start = None
            self.current_nested = False

    def split(self) -> tuple[tuple[int, int, bool], ...]:
        try:
            self.feed(self.source)
            self.close()
        except (AssertionError, ValueError) as error:
            raise ReportError("table bundle contains malformed HTML") from error
        if self.error is not None:
            raise ReportError(self.error)
        if self.depth != 0 or self.current_start is not None:
            raise ReportError("table bundle contains an unclosed table tag")
        if not self.spans:
            raise ReportError("table bundle contains no top-level table")
        return tuple(self.spans)


def _load_report_tables(
    value: dict[str, object], context: list[object]
) -> tuple[tuple[ReportTable, ...], bool, str | None]:
    table_contexts = [
        (index, item)
        for index, item in enumerate(context)
        if isinstance(item, dict) and item.get("type") == "table"
    ]
    html_bundles = value.get("html_tables")
    if html_bundles is None and not table_contexts:
        return (), True, None
    if not isinstance(html_bundles, list):
        return (), False, "report html_tables must be a list when table contexts exist"
    if len(html_bundles) != len(table_contexts):
        return (), False, "report table contexts do not align with html_tables count"

    tables: list[ReportTable] = []
    try:
        for bundle_index, ((context_index, item), bundle) in enumerate(
            zip(table_contexts, html_bundles, strict=True)
        ):
            if item.get("id") != context_index:
                raise ReportError(
                    "table context id does not match its immutable context index"
                )
            if not isinstance(bundle, str) or not bundle.strip():
                raise ReportError("html table bundle must be a non-empty string")
            if len(bundle) > MAX_TABLE_HTML_CHARACTERS:
                raise ReportError("html table bundle exceeds the parser size bound")
            split_spans = _TopLevelTableSplitter(bundle).split()
            if len(split_spans) > MAX_TABLE_ROOTS:
                raise ReportError("html table bundle exceeds the root-table bound")
            ambiguity_flags: tuple[str, ...] = ()
            if len(split_spans) > 1:
                ambiguity_flags += ("multi_root_table_bundle",)
            if any(nested for _, _, nested in split_spans):
                ambiguity_flags += ("nested_table_structure",)
            tables.append(
                ReportTable(
                    table_id=f"table:{context_index:04d}",
                    paragraph_id=context_index,
                    source_context_index=context_index,
                    source_html_bundle_index=bundle_index,
                    source_html_start=0,
                    source_html_end=len(bundle),
                    source_root_spans=tuple(
                        (start, end) for start, end, _ in split_spans
                    ),
                    raw_context=item["context"],
                    raw_html=bundle,
                    ambiguity_flags=ambiguity_flags,
                )
            )
            if len(tables) > MAX_LOGICAL_TABLES:
                raise ReportError(
                    f"report exceeds the {MAX_LOGICAL_TABLES} logical-table limit"
                )
    except ReportError as error:
        return (), False, str(error)
    return tuple(tables), True, None


class ReportStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ReportError("report root must be a directory")

    def open_session(self, report_name: str) -> ReportSession:
        if not isinstance(report_name, str) or Path(report_name).name != report_name:
            raise ReportError("report must be a bare filename")
        if not report_name.lower().endswith(".json"):
            raise ReportError("report must use the .json extension")
        candidate = (self.root / report_name).resolve(strict=True)
        if candidate.parent != self.root or not candidate.is_file():
            raise ReportError("report is outside the configured report root")
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
            context = value["context"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ReportError(f"invalid report: {report_name}") from error
        if not isinstance(context, list):
            raise ReportError("report context must be a list")
        paragraphs: list[Paragraph] = []
        for index, item in enumerate(context):
            if not isinstance(item, dict) or not isinstance(item.get("context"), str):
                raise ReportError(f"invalid paragraph at index {index}")
            paragraphs.append(Paragraph(paragraph_id=index, text=item["context"]))
        tables, table_alignment_valid, table_alignment_error = _load_report_tables(
            value, context
        )
        return ReportSession(
            report_name=report_name,
            paragraphs=tuple(paragraphs),
            tables=tables,
            table_alignment_valid=table_alignment_valid,
            table_alignment_error=table_alignment_error,
        )
