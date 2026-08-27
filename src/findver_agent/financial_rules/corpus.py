"""Strict loader and deterministic local search for a frozen rule corpus."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from findver_agent.config import FinOasisRuleCorpusConfig

from .models import RuleCorpusManifest, RuleRecord, RuleRecordsFile, RuleSearchHit


MAX_CORPUS_FILE_BYTES = 4 * 1024 * 1024
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class RuleCorpusError(ValueError):
    """The configured corpus cannot be trusted or safely read."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def rule_record_sha256(record: RuleRecord) -> str:
    return _sha256_bytes(_canonical_json(record.model_dump(mode="json")))


def _tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(value)]


@dataclass(frozen=True, slots=True)
class FrozenRuleCorpus:
    root: Path
    manifest_path: Path
    records_path: Path
    manifest_sha256: str
    records_sha256: str
    manifest: RuleCorpusManifest
    records: tuple[RuleRecord, ...]

    @classmethod
    def load(cls, config: FinOasisRuleCorpusConfig) -> "FrozenRuleCorpus":
        if not config.enabled:
            raise RuleCorpusError("cannot load a disabled rule corpus")
        assert config.rule_root is not None
        assert config.manifest_path is not None
        assert config.records_path is not None
        assert config.corpus_id is not None
        assert config.manifest_sha256 is not None
        assert config.records_sha256 is not None

        try:
            root = config.rule_root.resolve(strict=True)
        except OSError as error:
            raise RuleCorpusError("configured rule root does not exist") from error
        if not root.is_dir():
            raise RuleCorpusError("configured rule root is not a directory")

        manifest_path = cls._member(root, config.manifest_path, "manifest")
        records_path = cls._member(root, config.records_path, "records")
        manifest_bytes = cls._read_bounded(manifest_path, "manifest")
        records_bytes = cls._read_bounded(records_path, "records")
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        records_sha256 = _sha256_bytes(records_bytes)
        if manifest_sha256 != config.manifest_sha256:
            raise RuleCorpusError("rule manifest hash does not match configuration")
        if records_sha256 != config.records_sha256:
            raise RuleCorpusError("rule records hash does not match configuration")

        try:
            manifest_value = json.loads(manifest_bytes)
            records_value = json.loads(records_bytes)
            manifest = RuleCorpusManifest.model_validate(manifest_value)
            records_file = RuleRecordsFile.model_validate(records_value)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RuleCorpusError("rule corpus JSON or schema is invalid") from error
        if manifest.corpus_id != config.corpus_id:
            raise RuleCorpusError("manifest corpus_id does not match configuration")
        if manifest.records_sha256 != records_sha256:
            raise RuleCorpusError("manifest does not bind the configured records bytes")

        identifiers = [record.rule_id for record in records_file.records]
        if len(identifiers) != len(set(identifiers)):
            raise RuleCorpusError("rule corpus contains duplicate rule IDs")
        known = set(identifiers)
        for record in records_file.records:
            if _sha256_bytes(record.text.encode("utf-8")) != record.source_sha256:
                raise RuleCorpusError(
                    f"rule {record.rule_id} source hash does not match its text"
                )
            if set(record.conflicts_with) - known:
                raise RuleCorpusError(
                    f"rule {record.rule_id} references an unknown conflict rule"
                )
        return cls(
            root=root,
            manifest_path=manifest_path,
            records_path=records_path,
            manifest_sha256=manifest_sha256,
            records_sha256=records_sha256,
            manifest=manifest,
            records=tuple(records_file.records),
        )

    @staticmethod
    def _member(root: Path, relative: Path, name: str) -> Path:
        try:
            path = (root / relative).resolve(strict=True)
            path.relative_to(root)
        except (OSError, ValueError) as error:
            raise RuleCorpusError(
                f"configured rule {name} path escapes or is missing"
            ) from error
        if not path.is_file():
            raise RuleCorpusError(f"configured rule {name} is not a regular file")
        return path

    @staticmethod
    def _read_bounded(path: Path, name: str) -> bytes:
        try:
            size = path.stat().st_size
            if size < 1 or size > MAX_CORPUS_FILE_BYTES:
                raise RuleCorpusError(
                    f"rule {name} size must be within the bounded corpus limit"
                )
            return path.read_bytes()
        except OSError as error:
            raise RuleCorpusError(f"rule {name} could not be read") from error

    @property
    def corpus_id(self) -> str:
        return self.manifest.corpus_id

    def record(self, rule_id: str) -> RuleRecord:
        for record in self.records:
            if record.rule_id == rule_id:
                return record
        raise RuleCorpusError(f"unknown rule ID: {rule_id}")

    def search(
        self,
        *,
        query: str,
        jurisdiction: str,
        as_of_date: str,
        top_k: int,
    ) -> tuple[RuleSearchHit, ...]:
        if not query.strip():
            raise RuleCorpusError("rule search query must not be empty")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
            raise RuleCorpusError("rule search top_k must be between 1 and 10")
        try:
            effective = date.fromisoformat(as_of_date)
        except ValueError as error:
            raise RuleCorpusError("rule search as_of_date must be ISO YYYY-MM-DD") from error
        query_tokens = list(dict.fromkeys(_tokens(query)))
        if not query_tokens:
            raise RuleCorpusError("rule search query has no searchable tokens")
        jurisdiction_key = jurisdiction.strip().casefold()
        scored: list[tuple[int, str, RuleRecord]] = []
        for record in self.records:
            if record.jurisdiction.casefold() not in {jurisdiction_key, "all"}:
                continue
            if effective < record.effective_from or (
                record.effective_to is not None and effective > record.effective_to
            ):
                continue
            title = _tokens(record.title)
            aliases = _tokens(" ".join(record.aliases))
            topic = _tokens(record.topic)
            body = _tokens(record.text)
            score = sum(
                8 * title.count(token)
                + 6 * aliases.count(token)
                + 4 * topic.count(token)
                + body.count(token)
                for token in query_tokens
            )
            if score > 0:
                scored.append((score, record.rule_id, record))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            RuleSearchHit(
                rule_id=record.rule_id,
                score=score,
                snippet=" ".join(record.text.split())[:240],
            )
            for score, _, record in scored[:top_k]
        )


__all__ = [
    "FrozenRuleCorpus",
    "RuleCorpusError",
    "rule_record_sha256",
]
