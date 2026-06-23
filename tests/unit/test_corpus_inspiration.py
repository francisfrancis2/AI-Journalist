"""Unit tests for the DB-backed corpus approach-exemplar sampler."""

import pytest

from backend.models.benchmark import BIReferenceDocORM
from backend.services.corpus_inspiration import (
    CorpusExemplar,
    format_corpus_approach_exemplars,
    load_corpus_approach_exemplars,
)


def _seed(db_session, count: int) -> None:
    for i in range(count):
        db_session.add(
            BIReferenceDocORM(
                library_key="bi",
                youtube_id=f"vid-{i}",
                title=f"How Thing {i} Became A Giant | Big Business | Business Insider",
                description=(
                    f"Inside the surprising economics of thing {i}. "
                    "Subscribe for more business documentaries! https://example.com #money"
                ),
                view_count=1_000 + i,
                like_count=10 + i,
                duration_seconds=600,
                transcript="t",
                extracted_structure={
                    "hook_text": f"It takes {i * 40} gallons of sap to make one jug.",
                    "hook_type": "stat",
                    "title_formula": "how_x_became_y",
                },
            )
        )


@pytest.mark.asyncio
async def test_load_exemplars_returns_neutralized_clean_fields(db_session):
    _seed(db_session, 3)
    await db_session.commit()

    exemplars = await load_corpus_approach_exemplars(db_session, sample_size=3)

    assert len(exemplars) == 3
    for ex in exemplars:
        # Channel branding and the trailing " | Series | Channel" tail are stripped.
        assert "Business Insider" not in ex.title
        assert "|" not in ex.title
        assert ex.title.startswith("How Thing")
        # Description keeps the lead sentence but drops marketing boilerplate.
        assert "Subscribe" not in ex.description
        assert "https://" not in ex.description
        assert "Inside the surprising economics" in ex.description
        # Opening hook and structural tags come from extracted_structure.
        assert "gallons of sap" in ex.opening_hook
        assert ex.hook_type == "stat"
        assert ex.title_formula == "how_x_became_y"


@pytest.mark.asyncio
async def test_load_exemplars_respects_sample_size_and_empty_corpus(db_session):
    # Empty corpus → empty list, no error.
    assert await load_corpus_approach_exemplars(db_session, sample_size=5) == []

    _seed(db_session, 10)
    await db_session.commit()

    exemplars = await load_corpus_approach_exemplars(db_session, sample_size=4)
    assert len(exemplars) == 4


@pytest.mark.asyncio
async def test_load_exemplars_clips_long_description(db_session):
    db_session.add(
        BIReferenceDocORM(
            library_key="bi",
            youtube_id="long",
            title="A Plain Title",
            description="word " * 200,
            view_count=1,
            duration_seconds=600,
            extracted_structure={"hook_text": "h", "hook_type": "stat"},
        )
    )
    await db_session.commit()

    [ex] = await load_corpus_approach_exemplars(db_session, sample_size=1, max_desc_chars=80)
    assert len(ex.description) <= 81  # clip budget + ellipsis
    assert ex.description.endswith("…")


def test_format_exemplars_renders_block_and_warns_against_copying():
    block = format_corpus_approach_exemplars(
        [
            CorpusExemplar(
                title="How Salt Became Money",
                description="The economics of salt.",
                opening_hook="Salt was once worth more than gold.",
                hook_type="claim",
                title_formula="how_x_became_y",
            )
        ]
    )
    assert "CORPUS APPROACH EXEMPLARS" in block
    assert "not facts" in block.lower() or "never a factual" in block.lower() or "not a factual" in block.lower()
    assert "How Salt Became Money" in block
    assert "Salt was once worth more than gold" in block
    assert "[claim]" in block


def test_format_exemplars_empty_returns_empty_string():
    assert format_corpus_approach_exemplars([]) == ""
