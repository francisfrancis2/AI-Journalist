"""Role-specific retrieval from the script/reference library.

This service is the prompt-facing contract for library knowledge. It currently
derives compact guidance cards from the benchmark pattern caches, and it mirrors
the DB-backed ``library_knowledge_cards`` shape so richer extracted cards or
embeddings can be added without changing agent code.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import structlog

from backend.config import settings
from backend.models.benchmark import (
    BIPatternLibrary,
    LibraryReferenceCard,
    LibraryReferencePack,
)

log = structlog.get_logger(__name__)

_LIBRARY_KEYS = ("bi", "cnbc", "vox", "jh")
_SOURCE_NAME_RE = re.compile(
    r"\b(Business Insider|Insider Business|CNBC Make It|CNBC|Vox|Johnny Harris|BI)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9$%-]+", re.IGNORECASE)
_STOPWORDS = {
    "about", "after", "again", "against", "also", "because", "before", "behind",
    "being", "between", "could", "documentary", "from", "have", "into", "more",
    "most", "that", "their", "there", "these", "this", "through", "what", "when",
    "where", "which", "while", "with", "world", "would", "your",
}


def _neutralize(value: str) -> str:
    return _SOURCE_NAME_RE.sub("reference corpus", value or "").strip()


def _clip(value: str, limit: int = 240) -> str:
    text = " ".join(_neutralize(value).split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(value or "")
        if len(token) > 2 and token.lower() not in _STOPWORDS
    }


def _top_distribution_names(distribution: dict[str, float], limit: int = 3) -> list[str]:
    return [
        _clip(name, 90)
        for name, _ in sorted(distribution.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _load_cached_library(library_key: str) -> BIPatternLibrary | None:
    path = Path(settings.get_pattern_cache_path(library_key))
    if not path.is_file():
        return None
    try:
        return BIPatternLibrary.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("library_knowledge.cache_load_failed", library_key=library_key, error=str(exc))
        return None


def _loaded_libraries() -> list[tuple[str, BIPatternLibrary]]:
    loaded: list[tuple[str, BIPatternLibrary]] = []
    for key in _LIBRARY_KEYS:
        library = _load_cached_library(key)
        if library and library.doc_count > 0:
            loaded.append((key, library))
    return loaded


def _infer_topic_tags(library: BIPatternLibrary) -> list[str]:
    counts: dict[str, int] = {}
    text = " ".join([*library.sample_titles[:30], *library.sample_hooks[:8]])
    for token in _tokens(text):
        counts[token] = counts.get(token, 0) + 1
    return [
        token
        for token, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]
    ]


def _card(
    *,
    role: str,
    artifact_type: str,
    pattern: str,
    example_shape: str,
    do: list[str],
    dont: list[str],
    library_key: str,
    topic_tags: list[str],
    quality_score: float = 0.65,
) -> LibraryReferenceCard:
    return LibraryReferenceCard(
        role=role,
        artifact_type=artifact_type,
        pattern=_clip(pattern, 320),
        example_shape=_clip(example_shape, 320),
        do=[_clip(item, 150) for item in do],
        dont=[_clip(item, 150) for item in dont],
        library_key=library_key,
        topic_tags=topic_tags,
        relevance_score=quality_score,
    )


def _cards_for_role(role: str, library_key: str, library: BIPatternLibrary) -> list[LibraryReferenceCard]:
    hook_types = _top_distribution_names(library.hook_type_distribution)
    title_formulas = _top_distribution_names(library.title_formula_distribution)
    closing_devices = _top_distribution_names(library.closing_device_distribution, limit=2)
    sample_hook = library.sample_hooks[0] if library.sample_hooks else ""
    sample_title = library.sample_titles[0] if library.sample_titles else ""
    tags = _infer_topic_tags(library)

    shared_donts = [
        "Do not copy reference wording.",
        "Do not use reference-library facts as facts for this story.",
        "Do not name the source channels or reference titles in user-facing output.",
    ]

    if role == "researcher":
        return [
            _card(
                role=role,
                artifact_type="research_lane",
                pattern=(
                    "Successful library pieces collect evidence that can support "
                    f"{', '.join(hook_types) or 'specific hook'} openings and "
                    f"{', '.join(title_formulas) or 'clear explanatory'} frames."
                ),
                example_shape=(
                    "Queries should look for costs, process steps, named people, origin dates, "
                    "counterintuitive claims, and filmable places tied to the topic."
                ),
                do=[
                    "Plan at least one search for a number with units.",
                    "Plan at least one search for a named protagonist or operator.",
                    "Plan at least one search for a visual process or place.",
                ],
                dont=shared_donts + ["Do not search only broad background explainers."],
                library_key=library_key,
                topic_tags=tags,
            )
        ]

    if role == "analyst":
        return [
            _card(
                role=role,
                artifact_type="opening_hook",
                pattern=f"Strong openings usually use {', '.join(hook_types) or 'a concrete surprise'}.",
                example_shape=sample_hook,
                do=[
                    "Promote findings with numbers, named places, or contradictions.",
                    "Turn abstract trends into a specific viewer question.",
                    "Flag which findings could become the first 30 seconds.",
                ],
                dont=shared_donts + ["Do not propose angles unsupported by the research package."],
                library_key=library_key,
                topic_tags=tags,
            ),
            _card(
                role=role,
                artifact_type="angle_frame",
                pattern=f"Common library framing formulas: {', '.join(title_formulas) or 'why/how/inside frames'}.",
                example_shape=sample_title,
                do=[
                    "Produce angles that differ by frame, not just wording.",
                    "Anchor each selectable angle in a numeric, human, process, or contrarian finding.",
                    "Keep each angle short enough for a producer to choose quickly.",
                ],
                dont=shared_donts + ["Do not return vague verbs like explores or examines."],
                library_key=library_key,
                topic_tags=tags,
            ),
        ]

    if role == "storyline_creator":
        return [
            _card(
                role=role,
                artifact_type="act_architecture",
                pattern=(
                    f"Reference stories average {library.avg_act_count:.1f} acts at about "
                    f"{library.avg_act_duration_seconds:.0f}s per act, with a clear escalation."
                ),
                example_shape="Hook and stakes -> context -> evidence/process -> human consequence -> forward-looking payoff.",
                do=[
                    "Give each act a distinct job in the viewer's understanding.",
                    "Use act transitions to raise or answer a question.",
                    "Keep the human element near the corpus norm when the research supports it.",
                ],
                dont=shared_donts + ["Do not create acts that are only topic buckets."],
                library_key=library_key,
                topic_tags=tags,
            ),
            _card(
                role=role,
                artifact_type="closing_device",
                pattern=f"Common closing moves: {', '.join(closing_devices) or 'forward look and callback'}.",
                example_shape="Resolve the core question, then point to what changes next.",
                do=[
                    "Make the closing pay off the opening question.",
                    "Name the remaining consequence or decision ahead.",
                ],
                dont=shared_donts + ["Do not end with a flat summary of the topic."],
                library_key=library_key,
                topic_tags=tags,
            ),
        ]

    if role == "evaluator":
        return [
            _card(
                role=role,
                artifact_type="evaluation_rubric",
                pattern=(
                    "Score against library norms for hook potency, title/frame fit, act architecture, "
                    f"data density around {library.avg_stat_count:.1f} concrete data points, "
                    "human placement, tension/release, and closing payoff."
                ),
                example_shape="A strong proposal has a concrete hook, sourced numbers, filmable scenes, and a reason to keep watching.",
                do=[
                    "Identify whether the weakness is research, structure, or writing.",
                    "Turn every low score into an executable repair.",
                    "Require enough concrete evidence to sustain the selected angle.",
                ],
                dont=shared_donts + ["Do not approve a generic outline just because it is coherent."],
                library_key=library_key,
                topic_tags=tags,
            )
        ]

    if role in {"scriptwriter", "script_evaluator", "script_rewriter"}:
        return [
            _card(
                role=role,
                artifact_type="narration_hook",
                pattern=f"Opening narration should embody {', '.join(hook_types) or 'specific stakes'} immediately.",
                example_shape=sample_hook,
                do=[
                    "Start with the sharpest sourced image, number, named person, or contradiction.",
                    "Write for the ear with short active sentences.",
                    "Use the reference pattern as cadence, not content.",
                ],
                dont=shared_donts + ["Do not open with throat-clearing context."],
                library_key=library_key,
                topic_tags=tags,
            ),
            _card(
                role=role,
                artifact_type="specificity_and_flow",
                pattern=(
                    "The library style keeps viewers oriented by alternating specific evidence, "
                    "plain-language explanation, and a new question or consequence."
                ),
                example_shape="Concrete fact -> why it matters -> what it changes -> next question.",
                do=[
                    "Tie every major claim to a provided source ID.",
                    "Translate numbers into human or operational consequences.",
                    "End sections with a bridge into the next act or payoff.",
                ],
                dont=shared_donts + ["Do not add unsourced numbers, dates, quotes, or names."],
                library_key=library_key,
                topic_tags=tags,
            ),
        ]

    return []


def _context_text(topic: str, state: dict[str, Any] | None) -> str:
    parts = [topic]
    if not state:
        return topic

    selected_angle = state.get("selected_angle")
    if selected_angle:
        parts.append(str(selected_angle))

    analysis = state.get("analysis_result")
    if analysis:
        parts.append(getattr(analysis, "executive_summary", ""))
        parts.extend(getattr(analysis, "narrative_angles", [])[:6])
        parts.extend(getattr(finding, "claim", "") for finding in getattr(analysis, "key_findings", [])[:12])

    storyline = state.get("selected_storyline")
    if storyline:
        parts.extend([
            getattr(storyline, "title", ""),
            getattr(storyline, "logline", ""),
            getattr(storyline, "opening_hook", ""),
            getattr(storyline, "unique_angle", ""),
        ])

    act_plan = state.get("act_plan")
    if isinstance(act_plan, dict):
        parts.extend(str(act_plan.get(key, "")) for key in ("act_title", "purpose"))
        parts.extend(str(item) for item in act_plan.get("key_points", [])[:5])

    return "\n".join(part for part in parts if part)


def _rank(card: LibraryReferenceCard, context_tokens: set[str]) -> float:
    haystack = " ".join([
        card.pattern,
        card.example_shape,
        " ".join(card.do),
        " ".join(card.topic_tags),
    ])
    overlap = len(_tokens(haystack).intersection(context_tokens))
    return card.relevance_score + overlap * 0.08


def _fit_budget(cards: Iterable[LibraryReferenceCard], token_budget: int) -> list[LibraryReferenceCard]:
    budget_chars = max(token_budget, 200) * 4
    selected: list[LibraryReferenceCard] = []
    used = 0
    for card in cards:
        card_chars = (
            len(card.pattern)
            + len(card.example_shape)
            + sum(len(item) for item in card.do)
            + sum(len(item) for item in card.dont)
        )
        if selected and used + card_chars > budget_chars:
            continue
        selected.append(card)
        used += card_chars
    return selected


def get_reference_pack(
    *,
    role: str,
    topic: str,
    state: dict[str, Any] | None = None,
    max_cards: int = 6,
    token_budget: int = 1600,
) -> LibraryReferencePack:
    """Return compact, source-neutral library guidance for one agent role."""

    normalized_role = role.strip().lower()
    context_tokens = _tokens(_context_text(topic, state))
    candidates: list[LibraryReferenceCard] = []
    corpus_doc_count = 0

    for library_key, library in _loaded_libraries():
        corpus_doc_count += library.doc_count
        candidates.extend(_cards_for_role(normalized_role, library_key, library))

    if not candidates:
        return LibraryReferencePack(
            role=normalized_role,
            topic=topic,
            cards=[],
            corpus_doc_count=corpus_doc_count,
            notes=["No reference-library cache was available for this role."],
        )

    ranked = sorted(
        (
            card.model_copy(update={"relevance_score": round(_rank(card, context_tokens), 3)})
            for card in candidates
        ),
        key=lambda card: card.relevance_score,
        reverse=True,
    )
    cards = _fit_budget(ranked[: max(max_cards * 2, max_cards)], token_budget)[:max_cards]
    return LibraryReferencePack(
        role=normalized_role,
        topic=topic,
        cards=cards,
        corpus_doc_count=corpus_doc_count,
    )


def format_reference_pack(pack: LibraryReferencePack) -> str:
    """Format a reference pack for inclusion in an LLM prompt."""

    if not pack.cards:
        return ""

    lines = [
        "=== ROLE-SPECIFIC LIBRARY REFERENCE PACK ===",
        (
            "Use this as craft guidance from the reference library. "
            "It is not a factual source. Copy no wording; use only the provided research "
            "package for facts, numbers, names, dates, and quotes."
        ),
    ]
    for index, card in enumerate(pack.cards, 1):
        lines.append(f"{index}. {card.artifact_type}: {card.pattern}")
        if card.example_shape:
            lines.append(f"   Example shape: {card.example_shape}")
        if card.do:
            lines.append("   Do: " + "; ".join(card.do[:3]))
        if card.dont:
            lines.append("   Don't: " + "; ".join(card.dont[:3]))
    return "\n".join(lines)


def merge_reference_pack(state: dict[str, Any], pack: LibraryReferencePack) -> dict[str, Any]:
    """Return state-compatible reference pack cache with the current role updated."""

    existing = dict(state.get("reference_packs") or {})
    existing[pack.role] = pack.model_dump()
    return existing
