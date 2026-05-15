"""Load editable Markdown prompts used by the agent pipeline."""

from __future__ import annotations

import re
from pathlib import Path


_PROMPT_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt from ``backend/prompts/{name}.md``.

    Prompt files are read on every call so local edits are picked up by the
    next agent invocation without changing Python code.
    """
    if not _PROMPT_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid prompt name: {name!r}")

    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    return path.read_text(encoding="utf-8").strip()


def format_prompt(name: str, **values: object) -> str:
    """Load a prompt and apply ``str.format`` values."""
    return load_prompt(name).format(**values)
