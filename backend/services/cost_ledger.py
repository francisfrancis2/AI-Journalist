"""Measured dollar accounting and a hard per-run spend ceiling.

Two gaps this closes. Nothing in the backend recorded token usage, so the cost
of a run could only ever be reconstructed afterwards from price tables and
guesswork. And nothing capped it: a run spent whatever its prompts happened to
cost, however the payload grew.

The ledger is published through a context variable so tools nested inside a run
— deep research, agentic search — can record what they spent without threading
a parameter through every intermediate signature. Outside a run no ledger is
set and every ``record_*`` call is a no-op, so callers that have not opted in
behave exactly as before.

Enforcement is deliberately *pre-flight*: :meth:`CostLedger.reserve` refuses a
call whose worst case would not fit the remaining budget. Refusing before the
spend is the only way a ceiling can actually be honoured — checking afterwards
merely reports the overspend.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import structlog
from langchain_core.callbacks import AsyncCallbackHandler

log = structlog.get_logger(__name__)


# USD per million tokens, (input, output). Keep in step with published Anthropic
# pricing; this table is the single place the rates are stated. Matching is by
# longest prefix, so dated ids such as "claude-haiku-4-5-20251001" resolve.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-fable-5": (1.00, 5.00),
    "claude-haiku-4": (1.00, 5.00),
    "claude-haiku-3": (0.80, 4.00),
}

# Unknown model: charge the most expensive known rate rather than zero, so a
# model id we have not priced cannot slip past the ceiling for free.
_FALLBACK_PRICE = (5.00, 25.00)

# Server-side web search is billed per request, independent of tokens.
WEB_SEARCH_USD_PER_CALL = 0.01

# Cache reads bill at a tenth of base input; 5-minute cache writes at 1.25x.
CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25

# Characters per token for pre-flight estimates. English averages ~4; we use a
# smaller divisor so an estimate errs toward *over*-charging. A ceiling that
# under-estimates is not a ceiling.
_CHARS_PER_TOKEN = 3.4


class BudgetExceeded(RuntimeError):
    """Raised when a call's worst case will not fit the remaining budget.

    ``str(exc)`` is the stable code ``budget_exceeded`` so callers can match on
    it the same way they match the pipeline's timeout codes; the human-readable
    numbers live on the attributes.
    """

    def __init__(self, *, phase: str, projected_usd: float, remaining_usd: float, spent_usd: float) -> None:
        super().__init__("budget_exceeded")
        self.phase = phase
        self.projected_usd = projected_usd
        self.remaining_usd = remaining_usd
        self.spent_usd = spent_usd

    @property
    def detail(self) -> str:
        return (
            f"{self.phase} needs up to ${self.projected_usd:.2f} but only "
            f"${self.remaining_usd:.2f} of the run budget is left "
            f"(${self.spent_usd:.2f} already spent)."
        )


def price_for(model: str) -> tuple[float, float]:
    """Resolve (input, output) USD per million tokens for a model id."""
    name = (model or "").strip().lower()
    best: Optional[str] = None
    for prefix in PRICES_USD_PER_MTOK:
        if name.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    if best is None:
        log.warning("cost_ledger.unpriced_model", model=model)
        return _FALLBACK_PRICE
    return PRICES_USD_PER_MTOK[best]


def estimate_tokens(text: str) -> int:
    """Conservative token estimate for pre-flight reservations."""
    return int(len(text or "") / _CHARS_PER_TOKEN) + 1


@dataclass
class CostEntry:
    phase: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0
    usd: float = 0.0
    estimated: bool = False


class CostLedger:
    """Accumulates measured spend for one run and enforces its ceiling."""

    def __init__(self, budget_usd: float) -> None:
        self.budget_usd = float(budget_usd)
        self.entries: list[CostEntry] = []

    # -- pricing ---------------------------------------------------------
    @staticmethod
    def cost_of(
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        web_searches: int = 0,
    ) -> float:
        rate_in, rate_out = price_for(model)
        billable_input = (
            input_tokens
            + cache_read_tokens * CACHE_READ_MULTIPLIER
            + cache_write_tokens * CACHE_WRITE_MULTIPLIER
        )
        return (
            billable_input / 1_000_000 * rate_in
            + output_tokens / 1_000_000 * rate_out
            + web_searches * WEB_SEARCH_USD_PER_CALL
        )

    # -- accounting ------------------------------------------------------
    def record(
        self,
        *,
        phase: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        web_searches: int = 0,
        estimated: bool = False,
    ) -> float:
        usd = self.cost_of(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            web_searches=web_searches,
        )
        self.entries.append(
            CostEntry(
                phase=phase,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                web_searches=web_searches,
                usd=usd,
                estimated=estimated,
            )
        )
        log.info(
            "cost_ledger.recorded",
            phase=phase,
            model=model,
            usd=round(usd, 4),
            spent_usd=round(self.spent_usd, 4),
            budget_usd=self.budget_usd,
        )
        return usd

    @property
    def spent_usd(self) -> float:
        return sum(entry.usd for entry in self.entries)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd)

    # -- enforcement -----------------------------------------------------
    def project(
        self,
        *,
        model: str,
        input_tokens: int,
        max_output_tokens: int,
        web_searches: int = 0,
    ) -> float:
        """Worst-case cost of a call that has not run yet."""
        return self.cost_of(
            model,
            input_tokens=input_tokens,
            output_tokens=max_output_tokens,
            web_searches=web_searches,
        )

    def affords(
        self,
        *,
        model: str,
        input_tokens: int,
        max_output_tokens: int,
        web_searches: int = 0,
    ) -> bool:
        projected = self.project(
            model=model,
            input_tokens=input_tokens,
            max_output_tokens=max_output_tokens,
            web_searches=web_searches,
        )
        return projected <= self.remaining_usd

    def reserve(
        self,
        *,
        phase: str,
        model: str,
        input_tokens: int,
        max_output_tokens: int,
        web_searches: int = 0,
    ) -> float:
        """Refuse a call whose worst case exceeds the remaining budget."""
        projected = self.project(
            model=model,
            input_tokens=input_tokens,
            max_output_tokens=max_output_tokens,
            web_searches=web_searches,
        )
        if projected > self.remaining_usd:
            log.warning(
                "cost_ledger.refused",
                phase=phase,
                projected_usd=round(projected, 4),
                remaining_usd=round(self.remaining_usd, 4),
            )
            raise BudgetExceeded(
                phase=phase,
                projected_usd=projected,
                remaining_usd=self.remaining_usd,
                spent_usd=self.spent_usd,
            )
        return projected

    # -- reporting -------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        by_phase: dict[str, float] = {}
        for entry in self.entries:
            by_phase[entry.phase] = round(by_phase.get(entry.phase, 0.0) + entry.usd, 4)
        return {
            "cost_usd": round(self.spent_usd, 4),
            "budget_usd": round(self.budget_usd, 4),
            "budget_remaining_usd": round(self.remaining_usd, 4),
            "input_tokens": sum(e.input_tokens for e in self.entries),
            "output_tokens": sum(e.output_tokens for e in self.entries),
            "cache_read_tokens": sum(e.cache_read_tokens for e in self.entries),
            "web_searches": sum(e.web_searches for e in self.entries),
            "cost_by_phase_usd": by_phase,
            "cost_is_partly_estimated": any(e.estimated for e in self.entries),
        }


# -- context plumbing ----------------------------------------------------
_CURRENT: contextvars.ContextVar[Optional[CostLedger]] = contextvars.ContextVar(
    "cost_ledger_current", default=None
)


def current_ledger() -> Optional[CostLedger]:
    """The ledger for the run on this context, or None outside a budgeted run."""
    return _CURRENT.get()


@contextmanager
def use_ledger(ledger: CostLedger) -> Iterator[CostLedger]:
    """Publish ``ledger`` to everything called inside the block.

    contextvars propagate into tasks created within the block, so tools running
    under ``asyncio.gather`` record into the same ledger.
    """
    token = _CURRENT.set(ledger)
    try:
        yield ledger
    finally:
        _CURRENT.reset(token)


def _usage_int(usage: Any, *names: str) -> int:
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def record_anthropic_usage(
    *,
    phase: str,
    model: str,
    usage: Any,
    web_searches: Optional[int] = None,
) -> None:
    """Record a raw Anthropic SDK ``response.usage`` into the current ledger.

    Tolerant of both the SDK objects and plain dicts, and a no-op when no
    ledger is active, so tools can call it unconditionally. ``web_searches``
    defaults to the server-tool count on the usage object itself.
    """
    ledger = current_ledger()
    if ledger is None or usage is None:
        return
    if web_searches is None:
        server_tool_use = (
            usage.get("server_tool_use") if isinstance(usage, dict) else getattr(usage, "server_tool_use", None)
        )
        web_searches = _usage_int(server_tool_use, "web_search_requests") if server_tool_use else 0
    ledger.record(
        phase=phase,
        model=model,
        input_tokens=_usage_int(usage, "input_tokens"),
        output_tokens=_usage_int(usage, "output_tokens"),
        cache_read_tokens=_usage_int(usage, "cache_read_input_tokens"),
        cache_write_tokens=_usage_int(usage, "cache_creation_input_tokens"),
        web_searches=int(web_searches or 0),
    )


class LedgerCallback(AsyncCallbackHandler):
    """Records real LangChain token usage into a ledger.

    ``with_structured_output`` returns the parsed object and discards the raw
    message, so usage is only reachable through the callback stream. Attach one
    per call site with the phase it belongs to.
    """

    def __init__(self, ledger: CostLedger, phase: str) -> None:
        self._ledger = ledger
        self._phase = phase

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            generations = getattr(response, "generations", None) or []
            message = generations[0][0].message
        except (IndexError, AttributeError):
            log.warning("cost_ledger.callback_no_message", phase=self._phase)
            return
        usage = getattr(message, "usage_metadata", None) or {}
        details = usage.get("input_token_details") or {}
        model = (getattr(message, "response_metadata", None) or {}).get("model_name") or ""
        if not model:
            model = ((getattr(response, "llm_output", None) or {}).get("model")) or ""
        self._ledger.record(
            phase=self._phase,
            model=model,
            input_tokens=_usage_int(usage, "input_tokens"),
            output_tokens=_usage_int(usage, "output_tokens"),
            cache_read_tokens=_usage_int(details, "cache_read"),
            cache_write_tokens=_usage_int(details, "cache_creation"),
        )


def ledger_config(phase: str) -> dict[str, Any]:
    """LangChain ``config=`` that charges a call to the current ledger.

    Returns an empty config outside a budgeted run, so a call site can pass it
    unconditionally without changing behaviour for callers that never opened a
    ledger.
    """
    ledger = current_ledger()
    if ledger is None:
        return {}
    return {"callbacks": [LedgerCallback(ledger, phase)]}


__all__ = [
    "BudgetExceeded",
    "CostEntry",
    "CostLedger",
    "LedgerCallback",
    "PRICES_USD_PER_MTOK",
    "WEB_SEARCH_USD_PER_CALL",
    "current_ledger",
    "estimate_tokens",
    "ledger_config",
    "price_for",
    "record_anthropic_usage",
    "use_ledger",
]
