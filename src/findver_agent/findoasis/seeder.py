"""Conservative, subset-free proof-obligation seeding for protocol v3.

The seeder inspects only the public claim text.  It deliberately under-seeds when
the lexical evidence is ambiguous: later model actions or validated Skill results
may open more obligations, while an unnecessary initial obligation would expose a
Skill family that an IE-only claim does not need.

Seed proposals are intended for a fresh obligation graph whose next Runtime
sequence is ``1``.  Proposals never contain their own IDs.  Dependencies refer only
to earlier proposals using the deterministic IDs that the Runtime will assign when
it opens the returned sequence in order.
"""

from __future__ import annotations

import re
import unicodedata

from .contracts import ObligationMetadata, ObligationProposal, ObligationType


# A whole calendar date is one period, not three numeric values.  Longer period
# forms must precede bare years so ``FY2024 Q1`` is counted once.
_PERIOD_TOKEN_RE = re.compile(
    r"(?:"
    r"\b(?:fy\s*)?(?:19|20|21)\d{2}\s*(?:q[1-4])\b"
    r"|\bq[1-4]\s*(?:fy\s*)?(?:19|20|21)\d{2}\b"
    r"|\b(?:19|20|21)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b"
    r"|\b(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+\d{1,2},\s*"
    r"(?:19|20|21)\d{2}\b"
    r"|(?:19|20|21)\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|(?:19|20|21)\d{2}\s*年"
    r"|\b(?:fy\s*)?(?:19|20|21)\d{2}\b"
    r"|(?:19|20|21)\d{2}\s*年度"
    r")",
    re.IGNORECASE,
)

# Filing form numbers are document identifiers, not claim operands.
_FILING_FORM_RE = re.compile(r"\b(?:10-[kq]|8-k|20-f|40-f|6-k)\b", re.IGNORECASE)

_VALUE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:[$¥€£]\s*)?"
    r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:\s*(?:%|bps?\b|basis\s+points?\b))?"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

_NUMERIC_RELATION_PATTERNS = (
    re.compile(
        r"\b(?:increase|increased|increases|increasing|decrease|decreased|"
        r"decreases|decreasing|change|changed|changes|changing|difference|"
        r"differed|rose|rise|rises|fell|fall|falls|grew|grow|grows|growth|"
        r"declined|decline|declines)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:percentage|percent|basis\s+points?|bps|ratio|margin|rate|"
        r"total|average|cagr|compound\s+annual\s+growth\s+rate|"
        r"per\s+share|share\s+of)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:compared\s+(?:with|to)|versus|vs\.?|greater\s+than|"
        r"less\s+than|higher\s+than|lower\s+than|equal(?:s|led)?\s+to|"
        r"approximately|approx\.)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:higher|lower|greater|less)\b.{0,48}\bthan\b", re.IGNORECASE
    ),
    re.compile(r"(?:^|\s)(?:=|[<>]=?|≈)(?:\s|$)"),
    re.compile(
        r"(?:增加|增长|上升|提高|减少|下降|降低|变动|变化|差额|差异|"
        r"百分点|百分比|百分率|基点|比率|比例|利润率|毛利率|利率|"
        r"合计|总计|平均|占比|相比|比较|高于|低于|等于|约为|大约|"
        r"近似|复合年增长率|每股)"
    ),
)

_RULE_SIGNAL_PATTERNS = (
    re.compile(
        r"\b(?:u\.?s\.?\s+)?gaap\b|\bifrs(?:\s+\d+)?\b|"
        r"\bgenerally\s+accepted\s+accounting\s+principles\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:accounting|regulatory|legal|statutory|compliance)\s+"
        r"(?:standard|standards|rule|rules|requirement|requirements|"
        r"treatment|classification|definition|threshold)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:tax\s+(?:law|laws|code|codes|rule|rules|regulation|"
        r"regulations|treatment)|securities\s+(?:law|laws|regulation|"
        r"regulations))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bregulations?\b|\bregulation\s+[a-z][a-z0-9.-]{0,15}\b|"
        r"\brule\s+\d+[a-z0-9-]*\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:pursuant\s+to|in\s+accordance\s+with|required\s+by|"
        r"mandated\s+by)\s+(?:an?\s+|the\s+)?(?:accounting\s+)?"
        r"(?:standard|standards|rule|rules|regulation|regulations|law|laws|"
        r"statute|statutes|tax\s+code)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:defined\s+as|qualifies\s+as|classified\s+as|"
        r"recognized\s+as)\s+(?:an?\s+)?(?:revenue|expense|asset|liability|"
        r"equity|lease|security|financial\s+instrument|cash\s+equivalent)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:revenue|expense|(?:current\s+|noncurrent\s+)?asset|"
        r"(?:current\s+|noncurrent\s+)?liability|equity|lease|security|"
        r"financial\s+instrument|cash\s+equivalent)\b.{0,24}"
        r"\b(?:is|are)\s+defined\s+as\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:会计准则|企业会计准则|国际财务报告准则|监管(?:规定|要求|规则)|"
        r"合规(?:规定|要求|规则)|税法|税务处理|法律(?:规定|要求)|法定要求)"
    ),
    re.compile(
        r"(?:根据|依据|按照).{0,32}(?:准则|法规|法律|税法|规定|规则)"
    ),
    re.compile(
        r"(?:规则|准则|法规|规定).{0,32}(?:生效|适用|定义|要求|应当|"
        r"确认|分类|门槛|阈值)"
    ),
    re.compile(
        r"(?:资产|负债|收入|费用|租赁|证券|金融工具|现金等价物).{0,16}"
        r"(?:定义为|是指)"
    ),
)


def _normalized_claim(claim_text: str) -> str:
    if not isinstance(claim_text, str):
        raise TypeError("claim_text must be a string")
    normalized = unicodedata.normalize("NFKC", claim_text).casefold().strip()
    if not normalized:
        raise ValueError("claim_text must not be empty")
    return normalized


def _numeric_signal(claim_text: str) -> bool:
    """Require both numeric-relation language and two comparable mentions.

    Two non-period numeric values are enough, as are two explicit periods.  One
    value plus its reporting date is intentionally not enough: that is a common
    IE statement shape and does not itself imply arithmetic.
    """

    period_matches = list(_PERIOD_TOKEN_RE.finditer(claim_text))
    without_periods = list(claim_text)
    for match in period_matches:
        without_periods[match.start() : match.end()] = " " * (
            match.end() - match.start()
        )
    value_text = _FILING_FORM_RE.sub(" ", "".join(without_periods))
    value_count = sum(1 for _ in _VALUE_TOKEN_RE.finditer(value_text))
    has_two_quantities = value_count >= 2 or len(period_matches) >= 2
    return has_two_quantities and any(
        pattern.search(claim_text) for pattern in _NUMERIC_RELATION_PATTERNS
    )


def _rule_signal(claim_text: str) -> bool:
    return any(pattern.search(claim_text) for pattern in _RULE_SIGNAL_PATTERNS)


def _runtime_id(sequence: int) -> str:
    return f"obl-{sequence:04d}"


def _rule_scope_metadata(claim_text: str) -> ObligationMetadata:
    if re.search(r"\b(?:u\.?s\.?\s+)?gaap\b|\bsec\b", claim_text, re.I):
        jurisdiction = "US"
    elif re.search(r"\bifrs\b", claim_text, re.I):
        jurisdiction = "international"
    else:
        jurisdiction = "unknown"

    exact_date = re.search(r"\b((?:19|20|21)\d{2}-\d{2}-\d{2})\b", claim_text)
    if exact_date:
        effective_date = exact_date.group(1)
    else:
        year = re.search(r"\b((?:19|20|21)\d{2})\b", claim_text)
        effective_date = f"{year.group(1)}-12-31" if year else "unknown"

    if re.search(r"\bpublic issuer\b", claim_text, re.I):
        entity_scope = "public issuer"
    elif re.search(r"\bbank\b", claim_text, re.I):
        entity_scope = "bank"
    elif re.search(r"\binsurer\b|\binsurance compan", claim_text, re.I):
        entity_scope = "insurer"
    else:
        entity_scope = "unknown"
    return ObligationMetadata(
        jurisdiction=jurisdiction,
        effective_date=effective_date,
        entity_scope=entity_scope,
    )


def seed_obligations(claim_text: str) -> tuple[ObligationProposal, ...]:
    """Return deterministic seed proposals derived only from ``claim_text``.

    The caller must open the proposals, in order, into a fresh Runtime graph with
    ``next_obligation_sequence == 1``.  This function never predicts or consumes a
    label and has no task, subset, report, Gold, or scorer input.
    """

    normalized = _normalized_claim(claim_text)
    needs_numeric = _numeric_signal(normalized)
    needs_rule = _rule_signal(normalized)

    proposals: list[ObligationProposal] = []

    def append(
        obligation_type: ObligationType,
        description: str,
        dependency_sequences: tuple[int, ...] = (),
        metadata: ObligationMetadata | None = None,
    ) -> int:
        proposals.append(
            ObligationProposal(
                type=obligation_type,
                description=description,
                mandatory=True,
                dependency_ids=[
                    _runtime_id(sequence) for sequence in dependency_sequences
                ],
                metadata=metadata or ObligationMetadata(),
            )
        )
        return len(proposals)

    document_sequence = append(
        ObligationType.DOCUMENT_FACT,
        "Establish the report facts needed to verify the claim.",
    )

    numeric_operation_sequence: int | None = None
    if needs_numeric:
        numeric_operand_sequence = append(
            ObligationType.NUMERIC_OPERAND,
            "Bind each report value required by the claim to exact report evidence.",
            (document_sequence,),
        )
        unit_period_sequence = append(
            ObligationType.UNIT_PERIOD,
            "Verify the units, scales, currencies, entities, and periods of the "
            "bound values.",
            (numeric_operand_sequence,),
        )
        numeric_operation_sequence = append(
            ObligationType.NUMERIC_OPERATION,
            "Execute and verify the claim's numeric relation using only bound values.",
            (numeric_operand_sequence, unit_period_sequence),
        )

    rule_applicability_sequence: int | None = None
    if needs_rule:
        rule_metadata = _rule_scope_metadata(normalized)
        domain_rule_sequence = append(
            ObligationType.DOMAIN_RULE,
            "Locate the financial rule explicitly implicated by the claim.",
            metadata=rule_metadata,
        )
        rule_applicability_sequence = append(
            ObligationType.RULE_APPLICABILITY,
            "Verify the rule's applicability using its scope and relevant report facts.",
            (document_sequence, domain_rule_sequence),
            metadata=rule_metadata,
        )

    final_dependencies = [document_sequence]
    if numeric_operation_sequence is not None:
        final_dependencies.append(numeric_operation_sequence)
    if rule_applicability_sequence is not None:
        final_dependencies.append(rule_applicability_sequence)
    append(
        ObligationType.FINAL_VERIFICATION,
        "Verify that the evidence and required certificates justify the final answer.",
        tuple(final_dependencies),
    )

    return tuple(proposals)


class ConservativeObligationSeeder:
    """Stateless object interface for Runtime dependency injection."""

    def seed(self, claim_text: str) -> tuple[ObligationProposal, ...]:
        return seed_obligations(claim_text)


__all__ = ["ConservativeObligationSeeder", "seed_obligations"]
