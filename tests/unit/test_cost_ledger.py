"""Tests for the per-run spend ceiling.

The ledger's job is to refuse a call *before* it is made, so the tests that
matter are the refusal boundary and the guarantee that nothing is accidentally
free — an unpriced model must not slip past the ceiling.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.services.cost_ledger import (
    WEB_SEARCH_USD_PER_CALL,
    BudgetExceeded,
    CostLedger,
    LedgerCallback,
    current_ledger,
    estimate_tokens,
    ledger_config,
    price_for,
    record_anthropic_usage,
    use_ledger,
)


class TestPricing:
    def test_resolves_dated_model_id(self):
        assert price_for("claude-haiku-4-5-20251001") == (1.00, 5.00)

    def test_prefers_longest_matching_prefix(self):
        assert price_for("claude-sonnet-4-6") == (3.00, 15.00)
        assert price_for("claude-opus-4-7") == (5.00, 25.00)

    def test_unknown_model_is_not_free(self):
        """An unpriced id must charge the top rate, never zero."""
        assert price_for("some-unreleased-model") == (5.00, 25.00)

    def test_cost_math(self):
        # 1M input at $3 + 1M output at $15
        assert CostLedger.cost_of(
            "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000
        ) == pytest.approx(18.0)

    def test_cache_reads_are_discounted(self):
        full = CostLedger.cost_of("claude-sonnet-4-6", input_tokens=1_000_000)
        cached = CostLedger.cost_of("claude-sonnet-4-6", cache_read_tokens=1_000_000)
        assert cached == pytest.approx(full * 0.10)

    def test_cache_writes_are_surcharged(self):
        full = CostLedger.cost_of("claude-sonnet-4-6", input_tokens=1_000_000)
        written = CostLedger.cost_of("claude-sonnet-4-6", cache_write_tokens=1_000_000)
        assert written == pytest.approx(full * 1.25)

    def test_web_search_is_billed_per_call(self):
        assert CostLedger.cost_of("claude-haiku-4-5", web_searches=3) == pytest.approx(
            3 * WEB_SEARCH_USD_PER_CALL
        )

    def test_token_estimate_overestimates(self):
        """Pre-flight estimates must not undercount, or the ceiling leaks."""
        text = "word " * 1000  # 5000 chars, ~1250 real tokens
        assert estimate_tokens(text) > 1250


class TestEnforcement:
    def test_reserve_allows_a_call_that_fits(self):
        ledger = CostLedger(budget_usd=1.0)
        projected = ledger.reserve(
            phase="synthesis",
            model="claude-sonnet-4-6",
            input_tokens=90_000,
            max_output_tokens=10_000,
        )
        assert projected == pytest.approx(0.27 + 0.15)

    def test_reserve_refuses_a_call_that_does_not_fit(self):
        ledger = CostLedger(budget_usd=0.10)
        with pytest.raises(BudgetExceeded) as excinfo:
            ledger.reserve(
                phase="synthesis",
                model="claude-sonnet-4-6",
                input_tokens=90_000,
                max_output_tokens=10_000,
            )
        assert str(excinfo.value) == "budget_exceeded"
        assert excinfo.value.phase == "synthesis"
        assert "synthesis needs up to $0.42" in excinfo.value.detail

    def test_spend_reduces_what_the_next_phase_can_use(self):
        ledger = CostLedger(budget_usd=1.0)
        ledger.record(phase="research", model="claude-sonnet-4-6", input_tokens=200_000, output_tokens=8_000)
        assert ledger.spent_usd == pytest.approx(0.6 + 0.12)
        assert ledger.remaining_usd == pytest.approx(0.28)
        # A synthesis that would have fit a fresh budget no longer fits.
        assert not ledger.affords(
            model="claude-sonnet-4-6", input_tokens=90_000, max_output_tokens=10_000
        )

    def test_ceiling_is_never_exceeded_by_recorded_spend(self):
        """Every call is reserved first, so spend cannot pass the budget."""
        ledger = CostLedger(budget_usd=0.50)
        calls = 0
        while ledger.affords(model="claude-sonnet-4-6", input_tokens=10_000, max_output_tokens=2_000):
            ledger.record(
                phase="loop", model="claude-sonnet-4-6", input_tokens=10_000, output_tokens=2_000
            )
            calls += 1
            assert calls < 100, "guard against a non-terminating loop"
        assert ledger.spent_usd <= ledger.budget_usd

    def test_snapshot_reports_cost_per_phase(self):
        ledger = CostLedger(budget_usd=1.0)
        ledger.record(phase="research:deep", model="claude-sonnet-4-6", input_tokens=50_000, web_searches=2)
        ledger.record(phase="synthesis", model="claude-sonnet-4-6", input_tokens=80_000, output_tokens=9_000)
        snap = ledger.snapshot()
        assert snap["budget_usd"] == 1.0
        assert snap["cost_usd"] == pytest.approx(ledger.spent_usd, abs=1e-4)
        assert snap["web_searches"] == 2
        assert set(snap["cost_by_phase_usd"]) == {"research:deep", "synthesis"}
        assert snap["budget_remaining_usd"] == pytest.approx(1.0 - ledger.spent_usd, abs=1e-4)


class TestContextPlumbing:
    def test_no_ledger_outside_a_run(self):
        assert current_ledger() is None

    def test_ledger_is_visible_inside_and_cleared_after(self):
        ledger = CostLedger(budget_usd=1.0)
        with use_ledger(ledger):
            assert current_ledger() is ledger
        assert current_ledger() is None

    def test_record_usage_is_a_noop_without_a_ledger(self):
        """Callers that never opted in must be unaffected."""
        record_anthropic_usage(
            phase="research:deep",
            model="claude-sonnet-4-6",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=100),
        )  # must not raise

    def test_record_usage_charges_the_active_ledger(self):
        ledger = CostLedger(budget_usd=1.0)
        usage = SimpleNamespace(
            input_tokens=10_000,
            output_tokens=1_000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            server_tool_use=SimpleNamespace(web_search_requests=2),
        )
        with use_ledger(ledger):
            record_anthropic_usage(phase="research:deep", model="claude-sonnet-4-6", usage=usage)
        assert ledger.spent_usd == pytest.approx(0.03 + 0.015 + 2 * WEB_SEARCH_USD_PER_CALL)
        assert ledger.entries[0].web_searches == 2

    def test_record_usage_accepts_a_plain_dict(self):
        ledger = CostLedger(budget_usd=1.0)
        with use_ledger(ledger):
            record_anthropic_usage(
                phase="research:search",
                model="claude-haiku-4-5",
                usage={"input_tokens": 1_000_000, "output_tokens": 0},
            )
        assert ledger.spent_usd == pytest.approx(1.0)

    def test_ledger_config_is_empty_outside_a_run(self):
        assert ledger_config("synthesis") == {}

    def test_ledger_config_attaches_a_handler_inside_a_run(self):
        with use_ledger(CostLedger(budget_usd=1.0)):
            config = ledger_config("synthesis")
        assert isinstance(config["callbacks"][0], LedgerCallback)

    def test_ledger_reaches_tasks_spawned_inside_the_block(self):
        """gather() must charge the same ledger as the caller."""
        ledger = CostLedger(budget_usd=1.0)

        async def child():
            record_anthropic_usage(
                phase="child",
                model="claude-haiku-4-5",
                usage={"input_tokens": 1_000_000, "output_tokens": 0},
            )

        async def parent():
            with use_ledger(ledger):
                await asyncio.gather(child(), child())

        asyncio.run(parent())
        assert ledger.spent_usd == pytest.approx(2.0)


class TestLedgerCallback:
    def test_extracts_langchain_usage(self):
        ledger = CostLedger(budget_usd=1.0)
        message = SimpleNamespace(
            usage_metadata={
                "input_tokens": 80_000,
                "output_tokens": 9_000,
                "input_token_details": {"cache_read": 1_000, "cache_creation": 0},
            },
            response_metadata={"model_name": "claude-sonnet-4-6"},
        )
        response = SimpleNamespace(
            generations=[[SimpleNamespace(message=message)]], llm_output={}
        )
        asyncio.run(LedgerCallback(ledger, "synthesis").on_llm_end(response))
        entry = ledger.entries[0]
        assert entry.phase == "synthesis"
        assert entry.model == "claude-sonnet-4-6"
        assert entry.input_tokens == 80_000
        assert entry.cache_read_tokens == 1_000

    def test_survives_a_response_with_no_message(self):
        ledger = CostLedger(budget_usd=1.0)
        response = SimpleNamespace(generations=[], llm_output=None)
        asyncio.run(LedgerCallback(ledger, "synthesis").on_llm_end(response))
        assert ledger.entries == []
