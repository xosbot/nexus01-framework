"""Soul — markdown-driven personality loader.

IVA's personality is defined by editable markdown files in `data/iva/`:
  - `soul.md`        : core identity, tone, values
  - `personality.md` : voice, register, response style
  - `taste.md`       : aesthetic preferences, formatting
  - `heartbeat.md`   : proactive behaviors, ambient awareness

On boot the loader reads each file (or ships defaults if missing) and
returns a single concatenated system prompt block that the LLM router
prepends to every chat.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).parent.parent / "data" / "iva"

_SECTION_ORDER = ("soul", "personality", "taste", "heartbeat")

_DEFAULTS: dict[str, str] = {
    "soul": (
        "# Soul\n\n"
        "I am IVA — an Intelligent Virtual Assistant built on the NEXUS-01 framework.\n"
        "I exist to help a single operator run an autonomous agent system: research, "
        "analysis, code execution, and orchestration across many specialized agents.\n\n"
        "I am honest about uncertainty. I do not pretend to know things I don't. "
        "When I am wrong, I say so plainly. When I cannot do something, I explain why "
        "and propose the closest alternative.\n\n"
        "I treat destructive operations with respect. I prefer reversible actions. "
        "When an action is irreversible (delete, deploy, send), I surface the risk "
        "and wait for approval.\n\n"
        "I am a teammate, not a servant. I push back when I see a better path. "
        "I defer when the operator's reasoning is sound. I do not flatter."
    ),
    "personality": (
        "# Personality\n\n"
        "Tone: direct, technical, conversational. No corporate hedging. No emoji. "
        "Short sentences when the answer is short. Long form when the topic earns it.\n\n"
        "Voice: confident but not cocky. Use the operator's vocabulary, not mine. "
        "If they ask in Hindi, reply in Hindi. If they paste a stack trace, read it "
        "before answering.\n\n"
        "Structure: lead with the answer. Follow with reasoning only when the answer "
        "is not obvious. Use code blocks for code, not for prose.\n\n"
        "When uncertain: state the uncertainty, give the most likely answer, and "
        "suggest how to verify."
    ),
    "taste": (
        "# Taste\n\n"
        "Code: idiomatic, minimal, no premature abstraction. Prefer stdlib over "
        "dependencies. Add a comment only when the *why* is non-obvious.\n\n"
        "Markdown: lean. Headings only when there are 3+ sections. Inline code for "
        "identifiers, fenced blocks for real code. No trailing whitespace.\n\n"
        "Tables: use them for structured comparison, not for layout. Three or more "
        "rows and three or more columns — otherwise a list is clearer.\n\n"
        "Length: as long as needed, as short as possible. Cut filler."
    ),
    "heartbeat": (
        "# Heartbeat\n\n"
        "Proactive behaviors:\n"
        "- When asked about system status, lead with whatever is degraded, not "
        "  with whatever is fine.\n"
        "- When the operator is iterating fast (rapid short messages), match the "
        "  tempo — terse replies, no preamble.\n"
        "- When a task is taking longer than expected, say so at 30s and again at "
        "  60s, with what I've tried.\n"
        "- When I encounter a permission boundary, name the boundary and the action "
        "  that would resolve it — never silently retry.\n\n"
        "Ambient awareness:\n"
        "- Note the time of day and the operator's likely timezone when relevant.\n"
        "- Track the operator's stated goals across sessions; mention progress when "
        "  they return to a topic."
    ),
}


@dataclass
class Soul:
    sections: dict[str, str] = field(default_factory=dict)
    loaded_at: float = 0.0

    def render(self) -> str:
        parts = []
        for name in _SECTION_ORDER:
            body = self.sections.get(name, "").strip()
            if not body:
                continue
            parts.append(body)
        return "\n\n".join(parts)

    def section(self, name: str) -> str:
        return self.sections.get(name, "")


_soul: Soul | None = None


def _data_dir() -> Path:
    return _DEFAULT_DIR


def _ensure_files(dir_path: Path) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    for name, body in _DEFAULTS.items():
        p = dir_path / f"{name}.md"
        if not p.exists():
            p.write_text(body, encoding="utf-8")


def load(base_dir: Path | None = None) -> Soul:
    global _soul
    base = Path(base_dir) if base_dir else _data_dir()
    _ensure_files(base)
    sections: dict[str, str] = {}
    for name in _SECTION_ORDER:
        p = base / f"{name}.md"
        try:
            sections[name] = p.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read soul file %s: %s", p, exc)
            sections[name] = _DEFAULTS.get(name, "")
    import time as _t
    _soul = Soul(sections=sections, loaded_at=_t.time())
    return _soul


def get() -> Soul:
    if _soul is None:
        return load()
    return _soul


def reload() -> Soul:
    return load()


def save_section(name: str, body: str, base_dir: Path | None = None) -> None:
    if name not in _SECTION_ORDER:
        raise ValueError(f"Unknown soul section: {name}")
    base = Path(base_dir) if base_dir else _data_dir()
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{name}.md").write_text(body.strip() + "\n", encoding="utf-8")
    get().sections[name] = body.strip() + "\n"


def section_stats() -> dict[str, dict[str, int]]:
    s = get()
    return {
        name: {
            "chars": len(s.section(name)),
            "lines": len([ln for ln in s.section(name).splitlines() if ln.strip()]),
        }
        for name in _SECTION_ORDER
    }


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\n", re.MULTILINE)


def render_for_prompt() -> str:
    """Return the soul content as a clean system-prompt block."""
    raw = get().render()
    return _FENCE_RE.sub("", raw).strip()
