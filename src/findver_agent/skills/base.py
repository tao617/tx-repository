"""Skill errors exposed to the bounded agent loop."""


class SkillError(ValueError):
    """A local skill rejected invalid input or exceeded a safety bound."""

