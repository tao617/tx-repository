"""Stable paragraph serialization shared by Baseline and Agent prompts."""

from __future__ import annotations

from findver_agent.report_store import ReportSession


def format_paragraphs(session: ReportSession, paragraph_ids: list[int]) -> str:
    return "".join(
        f"[paragraph id = {paragraph_id}] {session.read(paragraph_id).text}\n"
        for paragraph_id in paragraph_ids
    )


def format_full_report(session: ReportSession) -> str:
    return format_paragraphs(session, list(range(len(session.paragraphs))))
