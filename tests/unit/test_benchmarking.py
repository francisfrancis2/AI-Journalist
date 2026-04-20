"""
Unit tests for benchmark corpus readiness helpers.
"""

from datetime import datetime, timezone

from backend.models.benchmark import BIPatternLibrary
from backend.services.benchmarking import _status_from_library


def _library(doc_count: int) -> BIPatternLibrary:
    return BIPatternLibrary(
        version=1,
        doc_count=doc_count,
        avg_act_count=5.0,
        avg_act_duration_seconds=120.0,
        hook_type_distribution={"stat": 1.0},
        title_formula_distribution={"how_x_became_y": 1.0},
        closing_device_distribution={"forward_look": 1.0},
        avg_stat_count=8.0,
        avg_rhetorical_questions=2.0,
        human_story_act_avg=4.0,
        sample_hooks=["A sharp opening hook."],
        sample_titles=["Reference documentary"],
    )


def test_small_benchmark_library_is_not_ready_for_scoring():
    status = _status_from_library(
        _library(doc_count=1),
        library_key="bi",
        built_at=datetime.now(timezone.utc),
        cache_exists=True,
        cache_mtime=datetime.now(timezone.utc),
        notes=[],
    )

    assert status.available is True
    assert status.ready_for_scoring is False
    assert status.stale is True
    assert "below the recommended minimum" in " ".join(status.notes)


def test_sufficient_benchmark_library_is_ready_for_scoring():
    status = _status_from_library(
        _library(doc_count=25),
        library_key="bi",
        built_at=datetime.now(timezone.utc),
        cache_exists=True,
        cache_mtime=datetime.now(timezone.utc),
        notes=[],
    )

    assert status.available is True
    assert status.ready_for_scoring is True
