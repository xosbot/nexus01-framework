"""IVA Skill System — modular capability definitions loaded on-demand from SKILL.md files."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    category: str
    tags: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    version: str = "1.0"
    content: str = ""
    path: str = ""

    def matches(self, query: str) -> float:
        query_lower = query.lower()
        score = 0.0

        for trigger in self.triggers:
            if trigger in query_lower:
                score += 0.3

        for tag in self.tags:
            if tag in query_lower:
                score += 0.2

        if self.name.replace("-", " ") in query_lower:
            score += 0.5

        name_words = self.name.replace("-", " ").split()
        for word in name_words:
            if len(word) > 3 and word in query_lower:
                score += 0.1

        return min(score, 1.0)


class SkillRegistry:
    def __init__(self, skills_dir: str = "skills") -> None:
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}
        self._load_skills()

    def _load_skills(self) -> None:
        if not self.skills_dir.exists():
            logger.warning("[skills] Skills directory not found: %s", self.skills_dir)
            return

        for skill_md in self.skills_dir.rglob("SKILL.md"):
            skill = self._parse_skill_md(skill_md)
            if skill:
                self.skills[skill.name] = skill
                logger.info("[skills] Loaded skill: %s (v%s)", skill.name, skill.version)

        logger.info("[skills] %d skill(s) loaded from %s", len(self.skills), self.skills_dir)

    def _parse_skill_md(self, path: Path) -> Skill | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("[skills] Failed to read %s: %s", path, exc)
            return None

        frontmatter, body = self._split_frontmatter(text, path)
        if frontmatter is None:
            return None

        name = frontmatter.get("name", "")
        if not name:
            logger.warning("[skills] Missing 'name' in frontmatter: %s", path)
            return None

        return Skill(
            name=name,
            category=frontmatter.get("category", "general"),
            tags=self._parse_list(frontmatter.get("tags", "")),
            triggers=self._parse_list(frontmatter.get("triggers", "")),
            version=frontmatter.get("version", "1.0"),
            content=body,
            path=str(path),
        )

    def _split_frontmatter(self, text: str, path: Path) -> tuple[dict[str, str] | None, str]:
        parts = text.split("---", 2)
        if len(parts) < 3:
            logger.warning("[skills] No valid frontmatter found: %s", path)
            return None, text

        fm_text = parts[1].strip()
        body = parts[2].strip()
        metadata: dict[str, str] = {}

        for line in fm_text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip()

        return metadata, body

    def _parse_list(self, raw: str) -> list[str]:
        if not raw:
            return []
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        return [item.strip().strip("'\"") for item in raw.split(",") if item.strip()]

    def find_skills(self, query: str, top_k: int = 3) -> list[Skill]:
        scored = [(skill, skill.matches(query)) for skill in self.skills.values()]
        scored = [(s, sc) for s, sc in scored if sc > 0.0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored[:top_k]]

    def get_skill(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def get_skill_context(self, query: str, max_tokens: int = 2000) -> str:
        matched = self.find_skills(query)
        if not matched:
            return ""

        sections: list[str] = []
        total_chars = 0
        char_budget = max_tokens * 4

        for skill in matched:
            header = f"## Skill: {skill.name} ({skill.category})"
            block = f"{header}\n\n{skill.content}"
            if total_chars + len(block) > char_budget:
                remaining = char_budget - total_chars
                if remaining > 100:
                    sections.append(block[:remaining] + "\n... [truncated]")
                break
            sections.append(block)
            total_chars += len(block)

        return "\n\n---\n\n".join(sections)

    def list_skills(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "category": s.category,
                "tags": s.tags,
                "triggers": s.triggers,
                "version": s.version,
                "path": s.path,
            }
            for s in self.skills.values()
        ]

    def install_skill(self, name: str, content: str) -> Skill:
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(content, encoding="utf-8")

        skill = self._parse_skill_md(skill_path)
        if skill is None:
            skill = Skill(name=name, category="custom", content=content, path=str(skill_path))

        self.skills[skill.name] = skill
        logger.info("[skills] Installed skill: %s", skill.name)
        return skill
