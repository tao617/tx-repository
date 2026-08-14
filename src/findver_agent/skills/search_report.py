"""Small deterministic BM25 implementation scoped to one report session."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from findver_agent.report_store import ReportSession
from findver_agent.skills.base import SkillError


TOKEN_PATTERN = re.compile(r"[a-z]+|\d+(?:,\d{3})*(?:\.\d+)?%?", re.IGNORECASE)


def tokenise(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_PATTERN.findall(text.lower()):
        token = raw.replace(",", "")
        if token.isalpha():
            if token.endswith("ies") and len(token) > 4:
                token = f"{token[:-3]}y"
            elif token.endswith("ing") and len(token) > 5:
                token = token[:-3]
            elif token.endswith("ed") and len(token) > 4:
                token = token[:-2]
            elif token.endswith("s") and len(token) > 3:
                token = token[:-1]
        tokens.append(token)
    return tokens


@dataclass(frozen=True, slots=True)
class SearchHit:
    paragraph_id: int
    score: float
    snippet: str

    def as_dict(self) -> dict[str, object]:
        return {
            "paragraph_id": self.paragraph_id,
            "score": round(self.score, 6),
            "snippet": self.snippet,
        }


class SearchReportSkill:
    name = "search_report"

    def __init__(self, session: ReportSession, *, snippet_chars: int = 500) -> None:
        self._session = session
        self._snippet_chars = snippet_chars
        self._documents = [tokenise(paragraph.text) for paragraph in session.paragraphs]
        self._frequencies = [Counter(document) for document in self._documents]
        self._lengths = [len(document) for document in self._documents]
        self._average_length = sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        self._document_frequency: Counter[str] = Counter()
        for document in self._documents:
            self._document_frequency.update(set(document))

    def execute(self, *, query: str, top_k: int) -> dict[str, object]:
        if not isinstance(query, str) or not query.strip():
            raise SkillError("query must be a non-empty string")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
            raise SkillError("top_k must be between 1 and 10")
        query_tokens = tokenise(query)
        if not query_tokens:
            raise SkillError("query contains no searchable tokens")
        count = len(self._documents)
        scored: list[SearchHit] = []
        for paragraph_id, frequencies in enumerate(self._frequencies):
            score = 0.0
            document_length = self._lengths[paragraph_id]
            for term in query_tokens:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency[term]
                inverse_frequency = math.log(1 + (count - document_frequency + 0.5) / (document_frequency + 0.5))
                normaliser = frequency + 1.5 * (
                    1 - 0.75 + 0.75 * document_length / (self._average_length or 1)
                )
                score += inverse_frequency * frequency * 2.5 / normaliser
            if score > 0:
                text = self._session.paragraphs[paragraph_id].text
                snippet = text if len(text) <= self._snippet_chars else f"{text[: self._snippet_chars]}…"
                scored.append(SearchHit(paragraph_id, score, snippet))
        scored.sort(key=lambda item: (-item.score, item.paragraph_id))
        hits = [item.as_dict() for item in scored[:top_k]]
        return {"query": query, "hits": hits}

