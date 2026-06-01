"""Skill prompt loader — reads .md templates from skills/ directory and fills {{variable}} placeholders."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_placeholder_re = re.compile(r"\{\{(\w+)\}\}")


class SkillPromptLoader:
    """Load and fill prompt templates from the skills/ directory."""

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self._cache: dict[str, str] = {}

    def load(self, skill_name: str, prompt_name: str) -> str:
        """Load a prompt template from skills/{skill_name}/prompts/{prompt_name}.md.

        Results are cached — subsequent calls return the same string.
        """
        cache_key = f"{skill_name}/{prompt_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        path = self.skills_dir / skill_name / "prompts" / f"{prompt_name}.md"
        if not path.exists():
            logger.warning("Prompt file not found: %s", path)
            return ""

        text = path.read_text(encoding="utf-8")
        self._cache[cache_key] = text
        return text

    def fill(self, template: str, variables: dict[str, str]) -> str:
        """Fill {{variable}} placeholders in a prompt template.

        Unfilled variables are kept as-is — LLMs can understand {{xxx}} semantics.
        """
        def _replace(match: re.Match) -> str:
            key = match.group(1)
            if key in variables:
                return str(variables[key])
            return match.group(0)  # keep placeholder if not provided

        return _placeholder_re.sub(_replace, template)

    def load_and_fill(self, skill_name: str, prompt_name: str, variables: dict[str, str]) -> str:
        """Load a prompt and fill variables in one call."""
        template = self.load(skill_name, prompt_name)
        return self.fill(template, variables)