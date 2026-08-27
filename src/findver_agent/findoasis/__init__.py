"""FinOASIS experimental protocol-v3 contracts.

Importing this package has no effect on the legacy v1/v2 runtime.  Protocol v3
is dispatched explicitly by experimental configuration.
"""

from .actions import Action, ActionControl, ActionParseError, parse_action, parse_action_v3
from .contracts import (
    CertificateEnvelope,
    CertificateKind,
    FinalCertificateStatus,
    Obligation,
    ObligationDelta,
    ObligationMetadata,
    ObligationProposal,
    ObligationStatus,
    ObligationType,
    QuestionPhase,
    SkillContract,
    SkillName,
    SkillResult,
    SkillResultStatus,
)
from .state import (
    FinOASISQuestionState,
    FinOASISStateStore,
    QuestionStateV3,
    ResumeIdentity,
    V3StateStore,
)

__all__ = [
    "Action",
    "ActionControl",
    "ActionParseError",
    "CertificateEnvelope",
    "CertificateKind",
    "FinalCertificateStatus",
    "FinOASISQuestionState",
    "FinOASISStateStore",
    "Obligation",
    "ObligationDelta",
    "ObligationMetadata",
    "ObligationProposal",
    "ObligationStatus",
    "ObligationType",
    "QuestionPhase",
    "QuestionStateV3",
    "ResumeIdentity",
    "SkillContract",
    "SkillName",
    "SkillResult",
    "SkillResultStatus",
    "V3StateStore",
    "parse_action",
    "parse_action_v3",
]
