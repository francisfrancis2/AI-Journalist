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
import re
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.benchmark import BIReferenceDocORM

log = structlog.get_logger(__name__)


_LIBRARY_LABELS: dict[str, str] = {
    "bi":   "Business Insider",
    "cnbc": "CNBC Make It",
    "vox":  "Vox",
    "jh":   "Johnny Harris",
}

# Source-channel names are stripped from corpus exemplars so user-facing craft
# guidance stays brand-neutral (mirrors library_knowledge._neutralize).
_SOURCE_NAME_RE = re.compile(
    r"\b(Business Insider|Insider Business|CNBC Make It|CNBC Making It|CNBC|Vox|"
    r"Johnny Harris|BI)\b",
    re.IGNORECASE,
)
# Marketing boilerplate that frequently trails YouTube documentary descriptions.
_DESC_BOILERPLATE_RE = re.compile(
    r"(subscribe|follow us|watch more|read more|#\w+|https?://|www\.)",
    re.IGNORECASE,
)


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
    Per-library: a random sample of real opening hooks. Used by Angles & Hooks
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


# ── DB-backed corpus approach exemplars ───────────────────────────────────────
#
# The pattern-cache helpers above read static JSON snapshots. The functions
# below read the live benchmark corpus (bi_reference_docs, 500+ docs) so the
# Angles & Hooks synthesis skill can show the model a *variety* of real
# documentary approaches — each a (title, description, opening hook) triple that
# demonstrates a different way of turning data into a story. The model uses the
# spread of approaches to make each generated angle structurally distinct; it is
# never a factual source for the story being produced.


class CorpusExemplar(BaseModel):
    """One real benchmark documentary, distilled into approach-shaping signal."""

    title: str
    description: str = ""
    opening_hook: str = ""
    hook_type: str = ""
    title_formula: str = ""


def _neutralize(value: str) -> str:
    return _SOURCE_NAME_RE.sub("reference corpus", value or "").strip()


def _clip(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"


def _clean_title(raw: str) -> str:
    # Corpus titles often carry a trailing " | Series | Channel" suffix; drop the
    # channel-y tail so the model sees the editorial framing, not the branding.
    head = raw.split("|", 1)[0] if "|" in raw else raw
    return _clip(_neutralize(head), 110)


def _clean_description(raw: Optional[str], limit: int) -> str:
    if not raw:
        return ""
    # Keep only the lead sentences before marketing boilerplate kicks in.
    text = _neutralize(raw)
    cut = _DESC_BOILERPLATE_RE.search(text)
    if cut and cut.start() > 40:
        text = text[: cut.start()]
    return _clip(text, limit)


async def load_corpus_approach_exemplars(
    session: AsyncSession,
    *,
    sample_size: int = 6,
    max_desc_chars: int = 220,
    max_hook_chars: int = 220,
) -> list[CorpusExemplar]:
    """Sample random corpus docs and distil each into a (title, description, hook).

    Randomised per call so successive generations see different approaches.
    Returns an empty list when the corpus is unavailable or empty.
    """
    query = (
        select(
            BIReferenceDocORM.title,
            BIReferenceDocORM.description,
            BIReferenceDocORM.extracted_structure,
        )
        .where(BIReferenceDocORM.title.isnot(None))
        .order_by(func.random())
        .limit(max(1, sample_size))
    )
    result = await session.execute(query)

    exemplars: list[CorpusExemplar] = []
    for title, description, structure in result.all():
        clean_title = _clean_title(title or "")
        if not clean_title:
            continue
        structure = structure if isinstance(structure, dict) else {}
        exemplars.append(
            CorpusExemplar(
                title=clean_title,
                description=_clean_description(description, max_desc_chars),
                opening_hook=_clip(_neutralize(str(structure.get("hook_text", ""))), max_hook_chars),
                hook_type=_clip(str(structure.get("hook_type", "")), 40),
                title_formula=_clip(str(structure.get("title_formula", "")), 40),
            )
        )
    return exemplars


def format_corpus_approach_exemplars(exemplars: list[CorpusExemplar]) -> str:
    """Render exemplars as a prompt section. Returns '' when there are none."""
    if not exemplars:
        return ""

    lines = [
        "=== CORPUS APPROACH EXEMPLARS (craft guidance, not facts) ===",
        (
            "Each item below is a real benchmark documentary shown as its title, "
            "description, and opening hook. They illustrate DIFFERENT approaches to "
            "turning data into a story — a numeric cold-open, a named protagonist, a "
            "counterintuitive claim, a process walk-through, a place-led scene. Use the "
            "SPREAD of approaches to make your selectable angles structurally distinct "
            "from one another. Do NOT copy their wording, topics, or facts, and never "
            "name a source channel."
        ),
    ]
    for i, ex in enumerate(exemplars, 1):
        lines.append(f"{i}. Title: {ex.title}")
        if ex.title_formula:
            lines.append(f"   Title formula: {ex.title_formula}")
        if ex.description:
            lines.append(f"   Description: {ex.description}")
        if ex.opening_hook:
            hook_tag = f" [{ex.hook_type}]" if ex.hook_type else ""
            lines.append(f"   Opening hook{hook_tag}: {ex.opening_hook}")
    return "\n".join(lines)


async def get_corpus_approach_inspiration(*, sample_size: int = 6) -> str:
    """Open a session, sample corpus exemplars, and return a formatted prompt block.

    Defensive: any error (no DB, empty corpus, bad row) degrades to ''. The
    caller treats the corpus section as optional craft guidance.
    """
    from backend.db.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            exemplars = await load_corpus_approach_exemplars(
                session, sample_size=sample_size
            )
        formatted = format_corpus_approach_exemplars(exemplars)
        if formatted:
            log.info("corpus_inspiration.approach_exemplars", count=len(exemplars))
        return formatted
    except Exception as exc:  # noqa: BLE001 — craft guidance is best-effort
        log.warning("corpus_inspiration.approach_exemplars_failed", error=str(exc))
        return ""
