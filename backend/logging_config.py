"""Central structlog configuration and field scrubbing."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

import structlog

_WORD_RE = re.compile(r"\S+")
_TEXT_KEYS = {"topic", "query", "title", "objective"}
_EMAIL_KEYS = {"email", "new_user", "deleted_user"}
_URL_KEYS = {"url"}


def _fingerprint_text(value: Any) -> str:
    text = " ".join(str(value).split())
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"[redacted:{len(_WORD_RE.findall(text))}w/{len(text)}c/{digest}]"


def _mask_email(value: Any) -> str:
    text = str(value).strip()
    if "@" not in text:
        return "[redacted-email]"
    local, _, domain = text.partition("@")
    prefix = local[:1] if local else "*"
    return f"{prefix}***@{domain}"


def _summarize_url(value: Any) -> str:
    text = str(value).strip()
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return "[redacted-url]"
    path_hint = "/..." if parsed.path and parsed.path != "/" else ""
    query_hint = "?..." if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{path_hint}{query_hint}"


def scrub_event_fields(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Redact user-provided text, emails, and full URLs from structured logs."""
    for key, value in list(event_dict.items()):
        if value is None:
            continue
        if key in _TEXT_KEYS:
            event_dict[key] = _fingerprint_text(value)
        elif key in _EMAIL_KEYS:
            event_dict[key] = _mask_email(value)
        elif key in _URL_KEYS:
            event_dict[key] = _summarize_url(value)
    return event_dict


def configure_logging() -> None:
    """Insert the scrubber into structlog while preserving the existing config."""
    current = structlog.get_config()
    processors = list(current.get("processors") or [])
    if scrub_event_fields in processors:
        return

    processors.insert(0, scrub_event_fields)
    structlog.configure(
        processors=processors,
        context_class=current.get("context_class", dict),
        logger_factory=current.get("logger_factory", structlog.PrintLoggerFactory()),
        wrapper_class=current.get("wrapper_class", structlog.make_filtering_bound_logger(0)),
        cache_logger_on_first_use=current.get("cache_logger_on_first_use", False),
    )
