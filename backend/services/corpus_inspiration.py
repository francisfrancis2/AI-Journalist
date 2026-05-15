"""
Shared loader for benchmark corpus inspiration.

The YouTube benchmark pattern caches (backend/data/{bi,cnbc,vox,jh}_patterns.json)
contain `sample_titles`, `sample_hooks`, and `title_formula_distribution` from
real published documentaries. Agents inject this material into their prompts
as on-style exemplars — titles for the angle / framing layer, hooks for the
fact-density and specificity layer.

Sampling is randomised per call so successive runs see different exemplars,
which keeps regenerated outputs from converging on the same patterns.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

import structlog

from backend.config import settings

log = structlog.get_logger(__name__)


_LIBRARY_LABELS: dict[str, str] = {
    "bi":   "Business Insider",
    "cnbc": "CNBC Make It",
    "vox":  "Vox",
    "jh":   "Johnny Harris",
}


def _load_pattern(key: str) -> Optional[dict]:
    path = Path(settings.get_pattern_cache_path(key))
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("corpus_inspiration.load_failed", key=key, error=str(exc))
        return None


def load_titles_inspiration(
    *,
    per_library_titles: int = 5,
    per_library_formulas: int = 2,
) -> str:
    """
    Per-library: top title formulas + a random sample of real titles. Used by
    the angle-generation layer (or whichever agent decides the framing).
    """
    parts: list[str] = []
    for key, label in _LIBRARY_LABELS.items():
        data = _load_pattern(key)
        if not data:
            continue
        titles: list[str] = data.get("sample_titles") or []
        formula_dist: dict[str, float] = data.get("title_formula_distribution") or {}
        if not titles and not formula_dist:
            continue

        sampled = (
            random.sample(titles, min(per_library_titles, len(titles))) if titles else []
        )
        top_formulas = sorted(
            formula_dist.items(), key=lambda kv: kv[1], reverse=True
        )[:per_library_formulas]

        block: list[str] = [f"-- {label} ({data.get('doc_count', '?')} docs) --"]
        if top_formulas:
            block.append("Title formulas: " + " | ".join(n for n, _ in top_formulas))
        if sampled:
            block.append("Example titles:")
            block.extend(f"  • {t}" for t in sampled)
        parts.append("\n".join(block))

    return "\n\n".join(parts)


def load_hooks_inspiration(*, per_library_hooks: int = 3, max_chars: int = 280) -> str:
    """
    Per-library: a random sample of real opening hooks. Used by the analyst
    to anchor fact-density expectations — real published documentaries open
    with a specific number, a named place, or a counterintuitive claim,
    rarely with abstract framing.
    """
    parts: list[str] = []
    for key, label in _LIBRARY_LABELS.items():
        data = _load_pattern(key)
        if not data:
            continue
        hooks: list[str] = data.get("sample_hooks") or []
        if not hooks:
            continue

        sampled = random.sample(hooks, min(per_library_hooks, len(hooks)))
        block: list[str] = [f"-- {label} ({data.get('doc_count', '?')} docs) --"]
        for hook in sampled:
            snippet = hook.strip().replace("\n", " ")
            if len(snippet) > max_chars:
                snippet = snippet[:max_chars].rsplit(" ", 1)[0] + "…"
            block.append(f"  • {snippet}")
        parts.append("\n".join(block))

    return "\n\n".join(parts)
