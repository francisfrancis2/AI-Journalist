"""Tests for role-specific library reference packs."""

from backend.services.library_knowledge import format_reference_pack, get_reference_pack


def test_reference_pack_returns_role_specific_cards(sample_topic):
    pack = get_reference_pack(role="analyst", topic=sample_topic, max_cards=3)

    assert pack.role == "analyst"
    assert pack.corpus_doc_count > 0
    assert 1 <= len(pack.cards) <= 3
    assert all(card.role == "analyst" for card in pack.cards)
    assert {card.artifact_type for card in pack.cards}.intersection(
        {"opening_hook", "angle_frame"}
    )


def test_reference_pack_format_is_source_neutral(sample_topic):
    pack = get_reference_pack(role="scriptwriter", topic=sample_topic, max_cards=2)
    formatted = format_reference_pack(pack)

    assert "ROLE-SPECIFIC LIBRARY REFERENCE PACK" in formatted
    assert "Business Insider" not in formatted
    assert "CNBC" not in formatted
    assert "Vox" not in formatted
    assert "Johnny Harris" not in formatted
    assert "not a factual source" in formatted
