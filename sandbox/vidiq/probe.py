#!/usr/bin/env python3
"""
vidIQ MCP probe — isolated test harness (official MCP SDK).

Touches NOTHING in backend/. Runs in sandbox/vidiq/.venv (Python 3.11, matching
the production Dockerfile) so nothing here can affect the V2 app.

Credit model — verify empirically via `inspect`:
  initialize / tools/list  : 0 credits (protocol, not tool calls)
  credit-balance tool      : 0 credits (documented free utility)
  standard tools           : ~5 credits
  *watch* tools            : ~10 credits  <- refused unless --allow-expensive

Three layers stop credits leaking:
  disk cache          a repeat (tool, args) costs 0 credits, across runs
  schema validation   bad args fail locally, before dispatch
  --max-calls         hard cap; raises BUDGET STOP rather than exceeding it

Run via ./run.sh (which selects the venv) or .venv/bin/python probe.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_client import (  # noqa: E402
    MCP_URL, ArgValidationError, DiskCache, VidIQError, VidIQSession,
    extract_embedded_json, preflight_auth,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "out"
TOOLS_FILE = OUT / "tools.json"
PLAN_FILE = OUT / "plan.json"
CALL_LOG = OUT / "call_log.jsonl"
CACHE_DIR = OUT / "cache"

EXPENSIVE_PATTERNS = (r"watch",)
KEYWORD_HINTS = ("keyword", "search_volume", "search-volume", "searchvolume", "term")
VIDEO_HINTS = ("outlier", "trending", "top_video", "video_search", "popular", "velocity")
BALANCE_HINTS = ("credit", "balance", "quota", "usage")

# Ordered by preference. vidiq_balance's declared outputSchema calls totalCredits
# "the headline number" (renewableCredits + addOnCredits), so it must win.
BALANCE_KEYS = ("totalCredits", "renewableCredits", "credits", "credit", "balance",
                "remaining", "available", "credits_remaining", "credit_balance",
                "remaining_credits")


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_api_key() -> str:
    key = os.environ.get("VIDIQ_API_KEY", "").strip()
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("VIDIQ_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(
        "VIDIQ_API_KEY not set.\n"
        "  Generate a key at https://app.vidiq.com/account/settings/mcp\n"
        "  Then: export VIDIQ_API_KEY=... (or add VIDIQ_API_KEY=... to .env)"
    )


def _is_expensive(name: str) -> bool:
    return any(re.search(p, name, re.I) for p in EXPENSIVE_PATTERNS)


def _score(tool: Dict[str, Any], hints: tuple) -> int:
    blob = (tool.get("name", "") + " " + (tool.get("description") or "")).lower()
    return sum(3 if h in tool.get("name", "").lower() else 1 for h in hints if h in blob)


def _suggest(tools: List[Dict[str, Any]], hints: tuple) -> List[str]:
    ranked = sorted(((_score(t, hints), t["name"]) for t in tools if _score(t, hints) > 0),
                    key=lambda pair: -pair[0])
    return [name for _, name in ranked[:5]]


def _resolve_path(data: Any, path: str) -> List[Any]:
    """Tiny dotted-path resolver. 'keywords[].keyword' -> list of values."""
    if not path:
        return []
    current: List[Any] = [data]
    for part in path.split("."):
        explode = part.endswith("[]")
        key = part[:-2] if explode else part
        nxt: List[Any] = []
        for item in current:
            if isinstance(item, dict) and key in item:
                value = item[key]
            elif key == "" and isinstance(item, list):
                value = item
            else:
                continue
            if explode and isinstance(value, list):
                nxt.extend(value)
            else:
                nxt.append(value)
        current = nxt
    return current


def _find_balance(node: Any, depth: int = 0) -> Optional[float]:
    """Recursively hunt for a numeric credit balance; vidIQ's shape is unpublished."""
    if depth > 6:
        return None
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return float(node)
    if isinstance(node, dict):
        for key in BALANCE_KEYS:
            value = node.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        for key in BALANCE_KEYS:
            if key in node:
                found = _find_balance(node[key], depth + 1)
                if found is not None:
                    return found
        for value in node.values():
            if isinstance(value, (dict, list)):
                found = _find_balance(value, depth + 1)
                if found is not None:
                    return found
    if isinstance(node, list):
        for item in node:
            found = _find_balance(item, depth + 1)
            if found is not None:
                return found
    return None


def _describe(value: Any, depth: int = 0, prefix: str = "") -> List[str]:
    pad = "  " * depth
    if depth > 4:
        return ["%s%s: ..." % (pad, prefix)]
    if isinstance(value, dict):
        lines = ["%s%s{" % (pad, prefix + ": " if prefix else "")]
        for k, v in list(value.items())[:25]:
            lines.extend(_describe(v, depth + 1, k))
        lines.append("%s}" % pad)
        return lines
    if isinstance(value, list):
        if not value:
            return ["%s%s: [] (empty)" % (pad, prefix)]
        head = ["%s%s: [%d items], first:" % (pad, prefix, len(value))]
        head.extend(_describe(value[0], depth + 1, ""))
        return head
    sample = repr(value)
    return ["%s%s: %s = %s" % (pad, prefix, type(value).__name__,
                               sample if len(sample) <= 90 else sample[:90] + "...")]


def _make_cache(args: argparse.Namespace) -> DiskCache:
    ttl_days = getattr(args, "cache_ttl_days", 7)
    return DiskCache(CACHE_DIR, ttl_seconds=ttl_days * 86400,
                     enabled=not getattr(args, "no_cache", False))


# ── budget-guarded caller ─────────────────────────────────────────────────────

def _rank_keywords(payload: Any, plan: dict, limit: int) -> List[str]:
    """Pick the top-N keywords, ranked by a numeric field rather than API order.

    vidIQ returns relatedKeywords ordered by relatedScore, so "highest volume"
    needs an explicit sort. Falls back to the legacy flat `extract_keywords` path.
    """
    spec = plan.get("keywords") or {}
    if spec.get("path"):
        rows = _resolve_path(payload, spec["path"])
        if rows and isinstance(rows[0], list):      # path landed on the list itself
            rows = rows[0]
        name_field = spec.get("name_field", "keyword")
        rank_field = spec.get("rank_field")
        rows = [r for r in rows if isinstance(r, dict) and r.get(name_field)]
        if rank_field:
            rows.sort(key=lambda r: (r.get(rank_field) or 0), reverse=True)
        picked = [r[name_field] for r in rows[:limit]]
        if picked:
            print("\n  top %d keywords by %s:" % (len(picked), rank_field or "api order"))
            for row in rows[:limit]:
                print("    %-28s %s=%s" % (row[name_field], rank_field or "-",
                                           row.get(rank_field) if rank_field else "-"))
        else:
            print("\n  NO keywords extracted — check plan.keywords.path")
        return picked

    if plan.get("extract_keywords"):
        picked = [k for k in _resolve_path(payload, plan["extract_keywords"])
                  if isinstance(k, str)][:limit]
        print("\n  extracted keywords: %s" % (picked or "NONE — check the path"))
        return picked
    return []


class Budget:
    """Hard cap on billable calls, with before/after balance accounting."""

    def __init__(self, session: VidIQSession, max_calls: int, balance_tool: Optional[str]):
        self._session = session
        self._max = max_calls
        self._balance_tool = balance_tool
        self.spent_calls = 0
        self.cache_hits = 0
        self.start_balance: Optional[float] = None
        self.last_balance: Optional[float] = None

    async def read_balance(self) -> Optional[float]:
        """Free utility call — deliberately uncached so it reflects reality."""
        if not self._balance_tool:
            return None
        try:
            payload, _ = await self._session.call_tool(
                self._balance_tool, {}, validate=False, use_cache=False)
        except VidIQError as exc:
            print("  ! balance check failed: %s" % exc)
            return None
        found = _find_balance(payload)
        if found is None:
            print("  ! no numeric balance in: %s" % json.dumps(payload)[:200])
        return found

    async def call(self, name: str, args: dict, *, label: str, allow_expensive: bool) -> Any:
        # A cache hit is free, so it must not consume budget or be refused.
        cached = self._session.cache.get(name, args)
        if cached is not None:
            payload, age = cached
            self.cache_hits += 1
            print("  -> CACHED %s(%s)  age=%.1fh  0 credits"
                  % (name, json.dumps(args), age / 3600))
            return extract_embedded_json(payload)

        if self.spent_calls >= self._max:
            raise SystemExit(
                "BUDGET STOP: hit --max-calls=%d. Nothing further was called." % self._max)
        if _is_expensive(name) and not allow_expensive:
            raise SystemExit(
                "REFUSED: '%s' looks like a 10-credit watch tool. "
                "Re-run with --allow-expensive if you really want it." % name)

        # Validate before spending anything.
        try:
            self._session.validate_args(name, args)
        except ArgValidationError as exc:
            raise SystemExit("ARGS REJECTED LOCALLY — %s" % exc)

        before = self.last_balance if self.last_balance is not None else await self.read_balance()
        if self.start_balance is None:
            self.start_balance = before

        print("  -> [%d/%d] %s(%s)" % (self.spent_calls + 1, self._max, name, json.dumps(args)))
        payload, from_cache = await self._session.call_tool(name, args)
        payload = extract_embedded_json(payload)
        self.spent_calls += 1

        # Balance reads bypass the cache (use_cache=False), so this delta is real.
        # It previously read 0 because cached balances were being replayed.
        after = await self.read_balance()
        self.last_balance = after
        delta = (before - after) if (before is not None and after is not None) else None
        print("     credits: %s -> %s (delta %s)" % (before, after, delta))

        OUT.mkdir(parents=True, exist_ok=True)
        snapshot = OUT / ("response_%s_%s.json" % (label, name.replace("/", "_")))
        snapshot.write_text(json.dumps(payload, indent=2, default=str))
        with CALL_LOG.open("a") as fh:
            fh.write(json.dumps({
                "ts": _now(), "tool": name, "args": args,
                "balance_before": before, "balance_after": after, "credit_delta": delta,
                "bytes": len(json.dumps(payload, default=str)), "snapshot": snapshot.name,
            }) + "\n")
        print("     saved: %s" % _rel(snapshot))
        return payload


# ── commands ──────────────────────────────────────────────────────────────────

async def cmd_discover(args: argparse.Namespace) -> None:
    """FREE. Enumerate tools with full schemas and write a starter plan."""
    OUT.mkdir(parents=True, exist_ok=True)
    token = _load_api_key()
    await preflight_auth(token)
    print("auth OK (0 credits)\n")

    async with VidIQSession(token, _make_cache(args)) as session:
        tools = await session.list_tools()

    # by_alias keeps the MCP wire shape (inputSchema, not input_schema) so the saved
    # file is a faithful record of the protocol and matches what every reader expects.
    serialised = [t.model_dump(mode="json", by_alias=True, exclude_none=True)
                  if hasattr(t, "model_dump") else dict(t) for t in tools]
    TOOLS_FILE.write_text(json.dumps(serialised, indent=2))
    print("Discovered %d tools (0 credits spent). Full schemas: %s\n"
          % (len(serialised), _rel(TOOLS_FILE)))

    for tool in sorted(serialised, key=lambda t: t["name"]):
        required = (tool.get("inputSchema") or {}).get("required") or []
        flag = "  [10cr?]" if _is_expensive(tool["name"]) else ""
        desc = (tool.get("description") or "").split("\n")[0][:64]
        print("  %-38s %-64s req=%s%s" % (tool["name"], desc, required or "-", flag))

    kw, vid, bal = (_suggest(serialised, KEYWORD_HINTS),
                    _suggest(serialised, VIDEO_HINTS),
                    _suggest(serialised, BALANCE_HINTS))
    print("\n── suggested for your use case ──")
    print("  keyword volume : %s" % (kw or "NONE MATCHED — pick manually"))
    print("  popular videos : %s" % (vid or "NONE MATCHED — pick manually"))
    print("  credit balance : %s" % (bal or "NONE MATCHED — pick manually"))

    def _args_for(name: Optional[str], placeholder: str) -> dict:
        """Pre-fill args from the tool's real required fields."""
        if not name:
            return {placeholder: "{%s}" % placeholder}
        schema = next((t.get("inputSchema") or {} for t in serialised if t["name"] == name), {})
        required = schema.get("required") or []
        props = list((schema.get("properties") or {}).keys())
        target = required[0] if required else (props[0] if props else placeholder)
        return {target: "{%s}" % placeholder}

    plan = {
        "_README": [
            "Tool names and arg keys below are GUESSES from name matching.",
            "Verify against out/tools.json inputSchema before running `pull`.",
            "args templates: {query} in stage1, {keyword} in stage2.",
            "extract_keywords: dotted path into stage1's response, e.g. 'keywords[].keyword'.",
            "Leave extract_keywords null on the first run; stage2 is then skipped and you",
            "read the real path out of out/response_stage1_*.json.",
        ],
        "balance_tool": bal[0] if bal else None,
        "stage1_keywords": {"tool": kw[0] if kw else None,
                            "args": _args_for(kw[0] if kw else None, "query")},
        "extract_keywords": None,
        "stage2_videos": {"tool": vid[0] if vid else None,
                          "args": _args_for(vid[0] if vid else None, "keyword")},
    }
    if not PLAN_FILE.exists() or args.reset_plan:
        PLAN_FILE.write_text(json.dumps(plan, indent=2))
        print("\nWrote starter plan: %s  <-- check tool names AND arg keys before `pull`"
              % _rel(PLAN_FILE))
    else:
        print("\nKept existing %s (use --reset-plan to overwrite)." % _rel(PLAN_FILE))


async def cmd_balance(args: argparse.Namespace) -> None:
    """FREE. Baseline the credit pool."""
    plan = json.loads(PLAN_FILE.read_text()) if PLAN_FILE.exists() else {}
    tool = args.tool or plan.get("balance_tool")
    if not tool:
        sys.exit("No balance tool known. Run `discover` first, or pass --tool NAME.")
    token = _load_api_key()
    await preflight_auth(token)
    # Balance must never be served from cache.
    cache = DiskCache(CACHE_DIR, ttl_seconds=0, enabled=False)
    async with VidIQSession(token, cache) as session:
        if TOOLS_FILE.exists():
            session.load_schemas(json.loads(TOOLS_FILE.read_text()))
        payload, _ = await session.call_tool(tool, {}, validate=False, use_cache=False)
    print(json.dumps(payload, indent=2, default=str))
    found = _find_balance(payload)
    print("\nparsed balance: %s" % ("%s credits" % found if found is not None else "NOT FOUND"))


async def cmd_pull(args: argparse.Namespace) -> None:
    """Run the two-stage pull under a hard call cap."""
    if not PLAN_FILE.exists():
        sys.exit("No plan found. Run `discover` first.")
    plan = json.loads(PLAN_FILE.read_text())
    s1, s2 = plan.get("stage1_keywords") or {}, plan.get("stage2_videos") or {}
    if not s1.get("tool"):
        sys.exit("plan.json stage1_keywords.tool is empty — fill it in from out/tools.json.")

    s1_args = {k: (v.replace("{query}", args.query) if isinstance(v, str) else v)
               for k, v in (s1.get("args") or {}).items()}
    stage2_on = bool((plan.get("keywords") or plan.get("extract_keywords")) and s2.get("tool"))
    cache = _make_cache(args)

    would_cache_hit = cache.get(s1["tool"], s1_args) is not None
    print("PLAN for query: %r" % args.query)
    print("  cache : %s (ttl %sd, %d entries)"
          % ("ON" if cache.enabled else "OFF", args.cache_ttl_days, len(cache.stats())))
    print("  stage1: %s(%s)%s"
          % (s1["tool"], json.dumps(s1_args), "  [CACHED -> 0 credits]" if would_cache_hit else ""))
    if stage2_on:
        spec = plan.get("keywords") or {}
        print("  stage2: %s  x%d keywords (ranked by %s from %s)"
              % (s2["tool"], args.keyword_limit,
                 spec.get("rank_field") or "api order",
                 spec.get("path") or plan.get("extract_keywords")))
    else:
        print("  stage2: SKIPPED (set plan.keywords after inspecting stage1)")
    planned = (0 if would_cache_hit else 1) + (args.keyword_limit if stage2_on else 0)
    print("  worst-case billable calls: %d  (cap --max-calls=%d)  est. ~%d credits"
          % (planned, args.max_calls, planned * 5))

    if args.dry_run:
        return print("\n--dry-run: nothing called, 0 credits spent.")
    if not args.yes:
        if input("\nProceed and spend credits? [y/N] ").strip().lower() not in ("y", "yes"):
            return print("Aborted. 0 credits spent.")

    token = _load_api_key()
    await preflight_auth(token)
    async with VidIQSession(token, cache) as session:
        if TOOLS_FILE.exists():
            session.load_schemas(json.loads(TOOLS_FILE.read_text()))
        else:
            print("! out/tools.json missing — arg validation disabled. Run `discover` first.")
        budget = Budget(session, args.max_calls, plan.get("balance_tool"))

        print("\n── stage 1: keywords ──")
        kw_payload = await budget.call(s1["tool"], s1_args, label="stage1",
                                       allow_expensive=args.allow_expensive)

        keywords = _rank_keywords(kw_payload, plan, args.keyword_limit)

        if keywords and s2.get("tool"):
            print("\n── stage 2: popular videos ──")
            for kw in keywords:
                s2_args = {k: (v.replace("{keyword}", kw) if isinstance(v, str) else v)
                           for k, v in (s2.get("args") or {}).items()}
                await budget.call(s2["tool"], s2_args,
                                  label="stage2_%s" % re.sub(r"\W+", "-", kw)[:24],
                                  allow_expensive=args.allow_expensive)

        print("\n── budget report ──")
        print("  billable calls : %d" % budget.spent_calls)
        print("  cache hits     : %d  (0 credits)" % budget.cache_hits)
        # vidIQ debits asynchronously; wait before the authoritative read.
        if budget.spent_calls and budget.start_balance is not None:
            print("  settling %ds for vidIQ to debit..." % args.settle_seconds)
            await asyncio.sleep(args.settle_seconds)
            settled = await budget.read_balance()
            if settled is not None:
                spent = budget.start_balance - settled
                print("  balance        : %s -> %s (settled)" % (budget.start_balance, settled))
                print("  credits spent  : %s  (~%.1f per call)"
                      % (spent, spent / budget.spent_calls))
                with CALL_LOG.open("a") as fh:
                    fh.write(json.dumps({
                        "ts": _now(), "tool": "_RUN_TOTAL_SETTLED",
                        "args": {"calls": budget.spent_calls},
                        "balance_before": budget.start_balance, "balance_after": settled,
                        "credit_delta": spent, "bytes": 0, "snapshot": None,
                    }) + "\n")
        else:
            print("  balance        : %s (no billable calls)" % budget.start_balance)
    print("\nNow run: ./run.sh inspect")


async def cmd_call(args: argparse.Namespace) -> None:
    """Single arbitrary tool call, still budget-guarded and schema-validated."""
    plan = json.loads(PLAN_FILE.read_text()) if PLAN_FILE.exists() else {}
    tool_args = json.loads(args.args)
    cache = _make_cache(args)
    if cache.get(args.tool, tool_args) is not None:
        print("Cached — 0 credits.")
    elif not args.yes:
        print("Will call %s(%s) — ~5 credits." % (args.tool, args.args))
        if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            return print("Aborted. 0 credits spent.")

    token = _load_api_key()
    await preflight_auth(token)
    async with VidIQSession(token, cache) as session:
        if TOOLS_FILE.exists():
            session.load_schemas(json.loads(TOOLS_FILE.read_text()))
        budget = Budget(session, 1, plan.get("balance_tool"))
        payload = await budget.call(args.tool, tool_args, label="manual",
                                    allow_expensive=args.allow_expensive)
    print(json.dumps(payload, indent=2, default=str)[:4000])


def cmd_inspect(args: argparse.Namespace) -> None:
    """FREE, offline. Summarise saved responses so you can write the spec."""
    files = sorted(OUT.glob("response_*.json"))
    if not files:
        print("No saved responses in %s. Run `pull` first." % _rel(OUT))
    for path in files:
        payload = json.loads(path.read_text())
        print("\n" + "=" * 78)
        print("  %s" % path.name)
        print("=" * 78)
        print("\n".join(_describe(payload)))
        print("\n-- candidate fields --")
        for key in ("title", "url", "link", "videoId", "video_id", "views", "viewCount",
                    "view_count", "vph", "views_per_hour", "outlierScore", "keyword",
                    "volume", "searchVolume", "search_volume", "competition"):
            hits = _resolve_path(payload, key) or _resolve_path(payload, "results[].%s" % key)
            if hits:
                print("   %-18s -> %s" % (key, repr(hits[:3])[:140]))
    if CALL_LOG.exists():
        print("\n" + "=" * 78)
        print("  empirical credit cost per tool")
        print("=" * 78)
        for line in CALL_LOG.read_text().splitlines():
            rec = json.loads(line)
            print("  %-36s delta=%-6s bytes=%s"
                  % (rec["tool"], rec.get("credit_delta"), rec.get("bytes")))


def cmd_cache(args: argparse.Namespace) -> None:
    """FREE, offline. Inspect or clear the credit-saving response cache."""
    cache = DiskCache(CACHE_DIR, ttl_seconds=args.cache_ttl_days * 86400)
    if args.clear:
        return print("Cleared %d cached responses." % cache.clear())
    rows = cache.stats()
    if not rows:
        return print("Cache empty (%s)." % _rel(CACHE_DIR))
    print("%d cached responses in %s — each one is a call you will not pay for again:\n"
          % (len(rows), _rel(CACHE_DIR)))
    for row in rows:
        stale = " STALE" if row["age_hours"] > args.cache_ttl_days * 24 else ""
        print("  %-30s age=%6.1fh  %6dB  %s%s"
              % (row["tool"], row["age_hours"], row["bytes"],
                 json.dumps(row["args"])[:60], stale))
    print("\nEstimated credits saved on re-runs: ~%d" % (len(rows) * 5))


# ── CLI ───────────────────────────────────────────────────────────────────────

def _add_cache_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-cache", action="store_true",
                        help="bypass the disk cache and force a billable call")
    parser.add_argument("--cache-ttl-days", type=int, default=7,
                        help="how long cached responses stay fresh (default 7)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="FREE: list tools + schemas, write starter plan")
    d.add_argument("--reset-plan", action="store_true", help="overwrite an existing plan.json")
    _add_cache_flags(d)
    d.set_defaults(func=cmd_discover, is_async=True)

    b = sub.add_parser("balance", help="FREE: read credit balance (never cached)")
    b.add_argument("--tool", help="override the balance tool name")
    b.set_defaults(func=cmd_balance, is_async=True)

    u = sub.add_parser("pull", help="run the two-stage keyword+video pull")
    u.add_argument("--query", required=True, help="research topic or ideation request")
    u.add_argument("--max-calls", type=int, default=3,
                   help="HARD cap on billable calls (default 3)")
    u.add_argument("--keyword-limit", type=int, default=1,
                   help="how many keywords feed stage 2 (default 1, ~5 credits each)")
    u.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing")
    u.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    u.add_argument("--allow-expensive", action="store_true",
                   help="permit 10-credit watch tools")
    u.add_argument("--settle-seconds", type=int, default=20,
                   help="wait before the authoritative post-run balance read (default 20)")
    _add_cache_flags(u)
    u.set_defaults(func=cmd_pull, is_async=True)

    c = sub.add_parser("call", help="single arbitrary tool call")
    c.add_argument("--tool", required=True)
    c.add_argument("--args", default="{}", help="JSON arguments object")
    c.add_argument("--yes", action="store_true")
    c.add_argument("--allow-expensive", action="store_true")
    _add_cache_flags(c)
    c.set_defaults(func=cmd_call, is_async=True)

    i = sub.add_parser("inspect", help="FREE, offline: summarise saved responses")
    i.set_defaults(func=cmd_inspect, is_async=False)

    k = sub.add_parser("cache", help="FREE, offline: inspect or clear the response cache")
    k.add_argument("--clear", action="store_true", help="delete every cached response")
    k.add_argument("--cache-ttl-days", type=int, default=7)
    k.set_defaults(func=cmd_cache, is_async=False)

    args = p.parse_args()
    try:
        if args.is_async:
            asyncio.run(args.func(args))
        else:
            args.func(args)
    except (VidIQError, ArgValidationError) as exc:
        sys.exit("\nvidIQ error: %s" % exc)


if __name__ == "__main__":
    main()
