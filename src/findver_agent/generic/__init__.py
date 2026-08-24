"""Additive generic evaluation Agent built on the FinDVer Runtime principles."""

from findver_agent.generic.config import GenericAgentConfig, GenericAppConfig
from findver_agent.generic.engine import GenericAgent
from findver_agent.generic.models import (
    AnswerContract,
    ContextUnit,
    GenericPrediction,
    GenericTask,
    GenericTaskProfile,
)
from findver_agent.generic.skills import SkillCatalog, default_skill_catalog

__all__ = [
    "AnswerContract",
    "ContextUnit",
    "GenericAgent",
    "GenericAgentConfig",
    "GenericAppConfig",
    "GenericPrediction",
    "GenericTask",
    "GenericTaskProfile",
    "SkillCatalog",
    "default_skill_catalog",
]
