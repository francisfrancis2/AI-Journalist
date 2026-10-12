"""
vidIQ MCP client built on the official MCP SDK (mcp 2.x).

Two credit-saving layers wrap every tool call, because credits are billed per
`tools/call` and the SDK by itself does nothing to reduce that:

  1. DiskCache      — persistent, keyed on (tool, canonical args). A repeat call
                      costs 0 credits. Survives across CLI invocations, unlike the
                      SDK's own in-process SEP-2549 cache (which is also
                      server-driven, so it only fires if vidIQ declares results
                      cacheable — we cannot rely on that).
  2. validate_args  — checks arguments against the tool's own inputSchema BEFORE
                      dispatch, so a malformed call fails locally for free instead
                      of being rejected server-side after billing.

Requires the sandbox venv: sandbox/vidiq/.venv (Python 3.11, matching Dockerfile).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx2
import jsonschema
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = "https://mcp.vidiq.com/mcp"


class VidIQError(RuntimeError):
    """Transport, auth, or protocol failure."""


class ArgValidationError(VidIQError):
    """Arguments did not match the tool's inputSchema. Raised before any spend."""


def _flatten(exc: BaseException, out: List[BaseException]) -> None:
    """MCP SDK raises nested ExceptionGroups; pull out the real causes."""
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            _flatten(sub, out)
    else:
        out.append(exc)


def describe_exception(exc: BaseException) -> str:
    leaves: List[BaseException] = []
    _flatten(exc, leaves)
    return "; ".join("%s: %s" % (type(e).__name__, str(e)[:200]) for e in leaves) or str(exc)


async def preflight_auth(token: str, url: str = MCP_URL) -> None:
    """Verify credentials with one unauthenticated-level HTTP probe.

    Free: this is an `initialize` attempt, not a tools/call. The SDK collapses
    HTTP status into a generic -32603, so we check the status ourselves to give
    an actionable message.
    """
    async with httpx2.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                url,
                headers={
                    "Authorization": "Bearer %s" % token,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "preflight", "version": "0"}},
                },
            )
        except Exception as exc:
            raise VidIQError("cannot reach %s: %s" % (url, exc)) from exc

    if resp.status_code == 401:
        raise VidIQError(
            "401 Unauthorized — VIDIQ_API_KEY is missing or invalid.\n"
            "  Generate a key at https://app.vidiq.com/account/settings/mcp"
        )
    if resp.status_code == 403:
        raise VidIQError(
            "403 Forbidden — the key authenticated but MCP access is not enabled.\n"
            "  MCP is officially a Max-tier feature; Boost access is a launch-period grant."
        )
    if resp.status_code >= 400:
        raise VidIQError("HTTP %s from preflight: %s" % (resp.status_code, resp.text[:300]))


# ── persistent response cache ─────────────────────────────────────────────────

def extract_embedded_json(payload: Any) -> Any:
    """Split vidIQ's hybrid text+JSON responses into {"text": ..., "data": ...}.

    vidIQ tools answer LLM-first: a markdown summary with a JSON block appended
    (e.g. "Keyword data (JSON):\n{...}"). Both halves are useful — the prose is
    ready to drop into a prompt, the JSON is what deterministic code extracts
    from — so keep them side by side rather than discarding either.

    Non-string payloads pass through untouched.
    """
    if not isinstance(payload, str):
        return payload

    # Find the first balanced {...} or [...] block and parse it.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = payload.find(opener)
        while start != -1:
            depth, in_str, escaped = 0, False, False
            for i in range(start, len(payload)):
                ch = payload[i]
                if in_str:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(payload[start:i + 1])
                        except ValueError:
                            break
                        return {"text": payload[:start].strip(), "data": data}
            start = payload.find(opener, start + 1)
    return {"text": payload, "data": None}


class DiskCache:
    """Content-addressed cache of tool responses. A hit costs zero credits."""

    def __init__(self, directory: Path, ttl_seconds: float, enabled: bool = True) -> None:
        self._dir = directory
        self._ttl = ttl_seconds
        self.enabled = enabled
        if enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(tool: str, args: Dict[str, Any]) -> str:
        canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:20]

    def _path(self, key: str) -> Path:
        return self._dir / ("%s.json" % key)

    def get(self, tool: str, args: Dict[str, Any]) -> Optional[Tuple[Any, float]]:
        """Return (payload, age_seconds) on a fresh hit, else None."""
        if not self.enabled:
            return None
        path = self._path(self.key(tool, args))
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text())
        except (ValueError, OSError):
            return None
        age = time.time() - record.get("cached_at", 0)
        if self._ttl and age > self._ttl:
            return None
        return record.get("payload"), age

    def set(self, tool: str, args: Dict[str, Any], payload: Any) -> None:
        if not self.enabled:
            return
        self._path(self.key(tool, args)).write_text(json.dumps(
            {"tool": tool, "args": args, "cached_at": time.time(), "payload": payload},
            indent=2,
        ))

    def stats(self) -> List[Dict[str, Any]]:
        rows = []
        for path in sorted(self._dir.glob("*.json")) if self._dir.exists() else []:
            try:
                rec = json.loads(path.read_text())
            except (ValueError, OSError):
                continue
            rows.append({
                "tool": rec.get("tool"), "args": rec.get("args"),
                "age_hours": round((time.time() - rec.get("cached_at", 0)) / 3600, 1),
                "bytes": path.stat().st_size, "key": path.stem,
            })
        return rows

    def clear(self) -> int:
        removed = 0
        for path in self._dir.glob("*.json") if self._dir.exists() else []:
            path.unlink()
            removed += 1
        return removed


# ── session ───────────────────────────────────────────────────────────────────

def unwrap(result: Any) -> Any:
    """Normalise a CallToolResult into plain Python (structured content preferred).

    SDK 2.x exposes snake_case field names; camelCase is only the wire alias.
    """
    structured = getattr(result, "structured_content", None)
    if structured:
        return structured
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                return text
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result


class VidIQSession:
    """Async MCP session with schema validation and disk caching."""

    def __init__(self, token: str, cache: DiskCache, url: str = MCP_URL,
                 timeout: float = 180.0) -> None:
        self._token = token
        self._url = url
        self._timeout = timeout
        self.cache = cache
        self._session: Optional[ClientSession] = None
        self._stack: List[Any] = []
        self._schemas: Dict[str, dict] = {}
        self.cache_hits = 0
        self.billable_calls = 0

    async def __aenter__(self) -> "VidIQSession":
        http = httpx2.AsyncClient(
            headers={"Authorization": "Bearer %s" % self._token},
            timeout=self._timeout,
        )
        transport_cm = streamable_http_client(self._url, http_client=http)
        streams = await transport_cm.__aenter__()
        session_cm = ClientSession(streams[0], streams[1])
        session = await session_cm.__aenter__()
        await session.initialize()
        self._session = session
        self._stack = [session_cm, transport_cm, http]
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for item in self._stack:
            try:
                if hasattr(item, "__aexit__"):
                    await item.__aexit__(None, None, None)
                elif hasattr(item, "aclose"):
                    await item.aclose()
            except Exception:
                pass  # teardown noise must not mask the real error

    async def list_tools(self) -> List[Any]:
        """Enumerate tools, following pagination. Free — protocol, not a tool call."""
        tools: List[Any] = []
        cursor: Optional[str] = None
        while True:
            from mcp import types
            params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
            result = await self._session.list_tools(params=params)
            tools.extend(result.tools)
            cursor = result.next_cursor
            if not cursor:
                break
        self._schemas = {t.name: (t.input_schema or {}) for t in tools}
        return tools

    def load_schemas(self, tools_json: List[dict]) -> None:
        """Seed schemas from a saved tools.json so validation works offline."""
        self._schemas = {t["name"]: (t.get("inputSchema") or {}) for t in tools_json}

    def validate_args(self, tool: str, args: Dict[str, Any]) -> None:
        """Fail locally, for free, rather than paying for a rejected call."""
        schema = self._schemas.get(tool)
        if not schema:
            return  # unknown tool: let the server decide
        try:
            jsonschema.validate(instance=args, schema=schema)
        except jsonschema.ValidationError as exc:
            required = schema.get("required") or []
            props = list((schema.get("properties") or {}).keys())
            raise ArgValidationError(
                "args rejected by %s's inputSchema (0 credits spent).\n"
                "  problem : %s\n"
                "  required: %s\n"
                "  accepts : %s" % (tool, exc.message, required or "(none)", props or "(unknown)")
            ) from exc

    async def call_tool(self, tool: str, args: Dict[str, Any], *,
                        validate: bool = True, use_cache: bool = True) -> Tuple[Any, bool]:
        """Return (payload, from_cache). Only a cache miss spends credits.

        `use_cache=False` is mandatory for anything whose value changes server-side
        independently of its arguments — the credit balance above all. Caching that
        would freeze a stale number and silently corrupt every spend measurement.
        """
        cached = self.cache.get(tool, args) if use_cache else None
        if cached is not None:
            self.cache_hits += 1
            return cached[0], True
        if validate:
            self.validate_args(tool, args)
        try:
            result = await self._session.call_tool(tool, args)
        except BaseException as exc:
            raise VidIQError(describe_exception(exc)) from exc
        if getattr(result, "is_error", False):
            # The server ran and rejected the call. It may still have billed, so do
            # NOT cache this — caching an error would make the failure permanent.
            self.billable_calls += 1
            raise VidIQError(
                "tool '%s' returned isError. Credits may still have been spent.\n  %s"
                % (tool, json.dumps(unwrap(result), default=str)[:400]))

        payload = unwrap(result)
        self.billable_calls += 1
        if use_cache:
            self.cache.set(tool, args, payload)
        return payload, False
