"""
Prompt-caching helpers for Anthropic calls made through langchain-anthropic.

Anthropic prompt caching is a prefix match: a large, stable prefix marked with
``cache_control`` is written once (~1.25x input cost) and then read at ~0.1x on
subsequent requests that share the exact prefix. langchain-anthropic forwards
``cache_control`` when a message's ``content`` is a list of content-block dicts.

Use ``cached_system(text)`` for a system prompt whose content repeats across
several calls (e.g. the scriptwriter writing each act of one story). The cached
prefix must clear the model minimum (~4096 tokens for Opus, ~2048 for Sonnet)
to actually cache — below that the breakpoint is a silent no-op, not an error.
"""

from __future__ import annotations


def cached_system(text: str) -> list[dict]:
    """System-message content with an ephemeral cache breakpoint on the whole block."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
