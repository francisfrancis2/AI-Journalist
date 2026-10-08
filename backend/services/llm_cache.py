"""
Prompt-caching helpers for Anthropic calls made through langchain-anthropic.

Anthropic prompt caching is a prefix match: a large, stable prefix marked with
``cache_control`` is written once (~1.25x input cost) and then read at ~0.1x on
subsequent requests that share the exact prefix. langchain-anthropic forwards
``cache_control`` when a message's ``content`` is a list of content-block dicts.

Use ``cached_text(text)`` for any Anthropic content-block prefix and
``cached_system(text)`` for a LangChain system prompt whose content repeats
across several calls (e.g. the scriptwriter writing each act of one story).
The cached prefix must clear the model minimum to actually cache — below it the
breakpoint is a silent no-op, not an error. Measured 2026-10-08 against the
models this app uses (two identical calls, reading cache_read_input_tokens on
the second):

    claude-opus-4-7     ~1024   no-op at 600, cached at 1100
    claude-sonnet-4-6   ~1024   no-op at 600, cached at 1100
    claude-haiku-4-5    ~4096   no-op at 3000, cached at 4200

Haiku's bar is four times Sonnet's, which is the opposite of what you might
assume from its price. A short system prompt that caches fine on Sonnet will
silently fail to cache on Haiku, so re-measure after moving a call between
tiers rather than trusting the breakpoint to carry over.
"""

from __future__ import annotations


def cached_text(text: str) -> list[dict]:
    """Anthropic text content with an ephemeral cache breakpoint."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def cached_system(text: str) -> list[dict]:
    """LangChain system-message content cached as one stable prefix."""
    return cached_text(text)
