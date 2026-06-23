"""Tests for the Skill System."""

import pytest
import tempfile
import shutil
from pathlib import Path

from core.skills import Skill, SkillRegistry


@pytest.fixture
def temp_skills_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


@pytest.fixture
def registry(temp_skills_dir):
    return SkillRegistry(skills_dir=str(temp_skills_dir))


class TestSkillMatching:
    def test_name_word_match(self):
        skill = Skill(name="karpathy-guidelines", category="coding", tags=[], triggers=[])
        score = skill.matches("karpathy guidelines")
        assert score > 0

    def test_partial_name_match(self):
        skill = Skill(name="karpathy-guidelines", category="coding", tags=[], triggers=[])
        assert skill.matches("karpathy") > 0

    def test_trigger_match(self):
        skill = Skill(
            name="test-skill", category="general",
            triggers=["refactor", "optimize"],
            tags=["python"],
        )
        score = skill.matches("can you refactor this code")
        assert score >= 0.3

    def test_tag_match(self):
        skill = Skill(name="test", category="coding", tags=["python"], triggers=[])
        assert skill.matches("python script") > 0

    def test_no_match(self):
        skill = Skill(name="test", category="general", tags=[], triggers=[])
        assert skill.matches("unrelated query xyz123") == 0.0

    def test_score_cap(self):
        skill = Skill(
            name="test skill",
            category="general",
            tags=["test", "skill"],
            triggers=["test"],
        )
        assert skill.matches("test skill") <= 1.0


class TestSkillRegistry:
    def test_empty_registry(self, registry):
        assert len(registry.skills) == 0
        assert registry.list_skills() == []

    def test_find_no_skills(self, registry):
        assert registry.find_skills("anything") == []

    def test_install_and_retrieve(self, registry):
        content = """---
name: test-skill
category: test
tags: [testing]
triggers: [test]
version: "1.0"
---

Test skill content."""
        skill = registry.install_skill("test-skill", content)
        assert skill.name == "test-skill"
        assert registry.get_skill("test-skill") is not None
        assert len(registry.skills) == 1

    def test_find_skills_by_trigger(self, temp_skills_dir):
        skill_md = temp_skills_dir / "test-skill" / "SKILL.md"
        skill_md.parent.mkdir()
        skill_md.write_text("""---
name: my-skill
category: test
tags: [test]
triggers: [refactor, optimize]
version: "1.0"
---

Content here.""")
        registry = SkillRegistry(skills_dir=str(temp_skills_dir))
        found = registry.find_skills("please refactor my code")
        assert len(found) >= 1
        assert any(s.name == "my-skill" for s in found)

    def test_get_skill_context(self, registry):
        content = """---
name: context-skill
category: test
version: "1.0"
tags: []
triggers: [test]
---

Some skill content here."""
        registry.install_skill("context-skill", content)
        ctx = registry.get_skill_context("run test")
        assert "context-skill" in ctx
        assert "Some skill content" in ctx

    def test_parse_list_variations(self, registry):
        assert registry._parse_list("") == []
        assert registry._parse_list("[a, b, c]") == ["a", "b", "c"]
        assert registry._parse_list("single") == ["single"]


class TestMarketResearchSkill:
    def test_market_research_intent_classification(self):
        from agents.orchestrator import INTENT_PATTERNS
        import re

        patterns = INTENT_PATTERNS.get("market_research", [])
        assert len(patterns) > 0

        test_queries = [
            "research competitor activity for AI startups",
            "market trends in cloud computing",
            "competitor analysis for SaaS companies",
            "industry analysis of cybersecurity market",
            "what's the market size for IoT devices",
        ]

        for query in test_queries:
            matched = any(re.search(p, query, re.I) for p in patterns)
            assert matched, f"Query '{query}' should match market_research intent"

    def test_market_research_routes_to_analyst(self):
        from agents.orchestrator import INTENT_PATTERNS
        import re

        patterns = INTENT_PATTERNS.get("market_research", [])
        test_query = "analyze competitor landscape for fintech startups"

        matched = any(re.search(p, test_query, re.I) for p in patterns)
        assert matched, "Market research query should match"

    def test_market_research_skill_exists(self):
        from pathlib import Path
        skill_path = Path(__file__).parent.parent / "skills" / "market-research" / "SKILL.md"
        assert skill_path.exists(), "market-research SKILL.md should exist"

        content = skill_path.read_text()
        assert "market_research" in content.lower() or "market research" in content.lower()
        assert "competitor" in content.lower()
        assert "trend" in content.lower()