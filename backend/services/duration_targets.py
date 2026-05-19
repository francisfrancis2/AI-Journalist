"""Duration profiles used to shape the full story pipeline.

The numbers in this module are calibrated against the benchmark corpus. The
cross-library median WPM is 148, and act counts by duration bucket are:
under 6 min -> 3.6 acts, 6-12 min -> 4.1 acts, 12-20 min -> 4.5 acts,
over 20 min -> 4.8 acts. The targets below mirror those medians so a 5/10/15
minute pick produces a script with realistic length and structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


# Cross-library median WPM across the benchmark corpus. Per-library values
# (BI=134, CNBC=153, Vox=144, JH=164) are available via `wpm_for(library_key)`
# for future per-target-style word budgeting.
WORDS_PER_MINUTE = 148
_CORPUS_WPM_BY_LIBRARY: dict[str, int] = {
    "bi":   134,
    "cnbc": 153,
    "vox":  144,
    "jh":   164,
}
DEFAULT_DURATION_MINUTES = 10
SUPPORTED_DURATION_MINUTES = (5, 10, 15)


def wpm_for(library_key: Optional[str] = None) -> int:
    """Return the corpus-derived narration WPM for a library, or the median."""
    if not library_key:
        return WORDS_PER_MINUTE
    return _CORPUS_WPM_BY_LIBRARY.get(library_key.lower(), WORDS_PER_MINUTE)


@dataclass(frozen=True)
class DurationTarget:
    """Concrete production targets derived from the requested episode length."""

    minutes: int
    seconds: int
    target_word_count: int
    label: str
    act_count_min: int
    act_count_max: int
    recommended_act_count: int
    analysis_findings_min: int
    analysis_findings_max: int
    selectable_angle_count: int
    web_query_cap: int
    human_story_query_cap: int
    news_query_cap: int
    rss_entries_per_feed: int
    scrape_url_cap: int
    guidance: str

    @property
    def act_count_label(self) -> str:
        if self.act_count_min == self.act_count_max:
            return f"{self.act_count_min}"
        return f"{self.act_count_min}-{self.act_count_max}"


def duration_target_for(minutes: int | None) -> DurationTarget:
    """Return a duration-aware production profile.

    The UI currently offers 5, 10, and 15 minutes. Older persisted stories may
    still carry intermediate values, so profile selection is bucketed while the
    exact seconds and word target continue to respect the stored minute value.
    """
    requested = int(minutes or DEFAULT_DURATION_MINUTES)
    bounded = max(5, min(15, requested))
    seconds = bounded * 60
    target_word_count = bounded * WORDS_PER_MINUTE

    if bounded <= 7:
        return DurationTarget(
            minutes=bounded,
            seconds=seconds,
            target_word_count=target_word_count,
            label="short-form",
            act_count_min=3,
            act_count_max=3,
            recommended_act_count=3,
            analysis_findings_min=7,
            analysis_findings_max=9,
            selectable_angle_count=3,
            web_query_cap=6,
            human_story_query_cap=1,
            news_query_cap=1,
            rss_entries_per_feed=5,
            scrape_url_cap=2,
            guidance=(
                "Short-form episode: one sharp hook, one compact evidence build, "
                "one payoff. Prioritize only the strongest facts and avoid broad detours."
            ),
        )

    if bounded <= 12:
        return DurationTarget(
            minutes=bounded,
            seconds=seconds,
            target_word_count=target_word_count,
            label="standard",
            act_count_min=4,
            act_count_max=5,
            recommended_act_count=4,
            analysis_findings_min=10,
            analysis_findings_max=13,
            selectable_angle_count=4,
            web_query_cap=8,
            human_story_query_cap=2,
            news_query_cap=2,
            rss_entries_per_feed=8,
            scrape_url_cap=3,
            guidance=(
                "Standard episode: hook, context, evidence escalation, human or "
                "consequence turn, and payoff. Balance breadth with forward momentum."
            ),
        )

    return DurationTarget(
        minutes=bounded,
        seconds=seconds,
        target_word_count=target_word_count,
        label="long-form",
        act_count_min=4,
        act_count_max=5,
        recommended_act_count=5,
        analysis_findings_min=14,
        analysis_findings_max=18,
        selectable_angle_count=5,
        web_query_cap=12,
        human_story_query_cap=3,
        news_query_cap=3,
        rss_entries_per_feed=12,
        scrape_url_cap=5,
        guidance=(
            "Long-form episode: allow deeper context, more evidence turns, a fuller "
            "human section, and a more deliberate resolution."
        ),
    )


def _distribute_total(total: int, ratios: Sequence[float]) -> list[int]:
    raw = [total * ratio for ratio in ratios]
    rounded = [max(30, round(value)) for value in raw]
    delta = total - sum(rounded)
    rounded[-1] += delta
    if rounded[-1] < 30:
        rounded[-1] = 30
        rounded[0] += total - sum(rounded)
    return rounded


def act_timings_for_count(target: DurationTarget, act_count: int | None = None) -> list[int]:
    """Return act durations in seconds that sum to the requested episode length."""
    count = max(1, int(act_count or target.recommended_act_count))
    ratio_map: dict[int, tuple[float, ...]] = {
        1: (1.0,),
        2: (0.4, 0.6),
        3: (0.2, 0.58, 0.22),
        4: (0.16, 0.26, 0.34, 0.24),
        5: (0.15, 0.24, 0.30, 0.20, 0.11),
        6: (0.12, 0.17, 0.22, 0.20, 0.18, 0.11),
    }
    ratios = ratio_map.get(count)
    if ratios is None:
        ratios = tuple(1 / count for _ in range(count))
    return _distribute_total(target.seconds, ratios)


def duration_prompt_block(target: DurationTarget, *, role: str) -> str:
    """Format a concise duration contract for an agent prompt."""
    # Give the LLM a +/- 10% acceptable range rather than a single target,
    # so it has room to write naturally without drifting from the requested length.
    word_floor = int(target.target_word_count * 0.90)
    word_ceil = int(target.target_word_count * 1.10)
    return (
        "=== EPISODE DURATION CONTRACT ===\n"
        f"Requested duration: {target.minutes} minutes ({target.seconds} seconds).\n"
        f"Narration length: target ~{target.target_word_count} words "
        f"(stay within {word_floor}-{word_ceil}). This is grounded in the benchmark "
        f"corpus median of {WORDS_PER_MINUTE} words per minute across the "
        f"reference documentaries.\n"
        f"Episode profile: {target.label}. Expected act count: "
        f"{target.act_count_label} (recommended: {target.recommended_act_count}). "
        f"These match the corpus median for this duration bucket.\n"
        f"Role-specific implication for {role}: {target.guidance}\n"
    )
