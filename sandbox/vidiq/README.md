# vidIQ MCP probe (sandbox)

Isolated test harness for evaluating vidIQ's MCP server before any V2 app changes.

**Isolation guarantees:** nothing here imports from `backend/`. Runs in its own venv
(`sandbox/vidiq/.venv`, Python 3.11 — matching the production `Dockerfile`) with the
official MCP SDK. Nothing is added to the app's `pyproject.toml` or `requirements.txt`.
Deleting `sandbox/` removes every trace.

Built on `mcp` 2.2.0. Invoke through `./run.sh`, which selects the venv:

```bash
./sandbox/vidiq/run.sh discover
```

## Setup

Already done: Python 3.11 (Homebrew), `sandbox/vidiq/.venv`, and the `mcp` SDK.
Pins are frozen in `requirements.txt`; rebuild with
`/opt/homebrew/bin/python3.11 -m venv .venv && ./.venv/bin/pip install -r requirements.txt`.

1. Generate an MCP API key at https://app.vidiq.com/account/settings/mcp
2. `export VIDIQ_API_KEY=vq_...` — or add `VIDIQ_API_KEY=vq_...` to the repo `.env`
   (already gitignored; the probe reads it from there as a fallback).

Every command runs a **free** auth preflight first, so a bad key fails with an
actionable message instead of a generic protocol error.

## Workflow

### Step 1 — discover (FREE, 0 credits)

```bash
./sandbox/vidiq/run.sh discover
```

`initialize` + `tools/list` are protocol calls, not tool calls, so this costs nothing.
Writes full JSON schemas for all ~50 tools to `out/tools.json`, prints a name +
description table, and writes a starter `out/plan.json` with guessed tool names.

**vidIQ does not publish tool names or schemas.** This step is how you learn them.
Read `out/tools.json` and correct `out/plan.json` before going further.

### Step 2 — baseline the budget (FREE)

```bash
./sandbox/vidiq/run.sh balance
```

The credit-balance tool is a documented 0-credit utility. Note the starting number.

### Step 3 — dry run (FREE)

```bash
./sandbox/vidiq/run.sh pull --query "UAE economic diversification" --dry-run
```

Prints exactly which tools would be called with which arguments, and the estimated
credit spend. Nothing is sent.

### Step 4 — the real pull

```bash
# stage 1 only: 1 call, ~5 credits
./sandbox/vidiq/run.sh pull --query "UAE economic diversification" --max-calls 1

# after filling in extract_keywords: keywords + videos for 2 keywords, ~15 credits
./sandbox/vidiq/run.sh pull --query "UAE economic diversification" \
    --max-calls 3 --keyword-limit 2
```

Every raw response is saved to `out/response_*.json`, and every call is appended to
`out/call_log.jsonl` with the before/after balance so you build an **empirical**
credit cost table rather than trusting the ~5 figure from third-party reviews.

### Step 5 — inspect (FREE, offline)

```bash
./sandbox/vidiq/run.sh inspect
```

Prints the structure of every saved response (keys, types, sample values), flags
candidate `title` / `url` / `views` / `volume` fields, and summarises measured credit
cost per tool. **This output is the raw material for the requirements doc.**

## Measured findings (2026-09-30, live)

- **60 tools** discovered for 0 credits. Schemas in `out/tools.json`.
- **5 credits per call**, confirmed: `vidiq_keyword_research` and `vidiq_youtube_search`
  both debit 5. Balance went 4000 -> 3975 across 5 calls.
- **Starting pool: 4,000** = 2,000 renewable (Boost cap, resets 2026-10-27) + 2,000
  add-on credits that do *not* refill. So ~800 calls, not the ~400 a Boost-only
  reading suggests.
- **Two response shapes.** `vidiq_keyword_research` returns markdown prose with an
  embedded JSON block; `vidiq_youtube_search` returns pure structured JSON. The probe
  normalises both via `extract_embedded_json`.
- **`vidiq_balance` must never be cached** — it changes independently of its (empty)
  arguments. Caching it froze the number and made every per-call delta read 0.
- **`order=viewCount` ranks by lifetime views**, which surfaces old viral noise:
  "dubai" returns Dubai-chocolate shorts, "economy" returns airline-seat videos.
  Documentary use wants specific multi-word keywords, `publishedAfter`, and
  `videoDuration=long` — or `vidiq_outliers` / `vidiq_trending_videos` instead.

## Budget controls

| Control | Effect |
|---|---|
| **disk cache** | a repeat `(tool, args)` costs **0 credits**, across separate runs |
| **schema validation** | bad arguments fail locally, before dispatch — no wasted spend |
| `--dry-run` | prints the plan, spends nothing |
| `--max-calls N` | **hard** cap; raises `BUDGET STOP` rather than exceeding it (default 3) |
| `--keyword-limit N` | how many keywords feed stage 2, i.e. stage-2 call count (default 1) |
| confirmation prompt | shown unless `--yes`, with the estimated credit cost |
| watch-tool refusal | any tool matching `watch` (10 credits) is refused without `--allow-expensive` |
| balance before/after | every call logs its measured credit delta to `out/call_log.jsonl` |
| `--no-cache` | force a fresh billable call |
| `--cache-ttl-days N` | cache freshness window (default 7 — keyword volume moves weekly) |

On Boost ($19/mo, 2,000 credits) a full `--max-calls 3` run costs ~15 credits, or
~0.75% of the monthly pool. You can run this ~130 times before exhausting it — and
the pool is shared with vidIQ's UI features, so keep `balance` in the loop.

## The response cache — where the credit savings come from

```bash
./sandbox/vidiq/run.sh cache           # what is cached, and credits saved on re-run
./sandbox/vidiq/run.sh cache --clear   # drop it all
```

Keyed on a SHA-256 of `(tool, canonical args)` and stored in `out/cache/`. Identical
calls across separate CLI invocations are served from disk and **never billed**, which
matters because iterating on prompts means running the same query repeatedly.

This is a cache we control, not the SDK's. The SDK's own SEP-2549 cache is
server-driven (it only fires if vidIQ marks results cacheable) and its default store is
in-process, so it saves nothing between runs.

The balance tool is **deliberately never cached** — it must reflect reality.

## Two-stage plan format (`out/plan.json`)

```json
{
  "balance_tool": "<free credit-balance tool>",
  "stage1_keywords": { "tool": "<keyword research tool>", "args": { "query": "{query}" } },
  "extract_keywords": "keywords[].keyword",
  "stage2_videos":   { "tool": "<trending/outlier tool>", "args": { "query": "{keyword}" } }
}
```

- `{query}` is substituted with `--query`; `{keyword}` with each extracted keyword.
- `extract_keywords` is a dotted path, `[]` to explode a list. Leave it `null` on the
  first run — stage 2 is then skipped, and you read the real path out of
  `out/response_stage1_*.json`.
- Fix `args` to match the real input schema in `out/tools.json`; the generated guess
  assumes a `query` parameter that may not be what vidIQ actually expects.

## Also available: interactive exploration

`.mcp.json` at the repo root now declares the vidIQ server, so in an interactive
Claude Code session you can query it conversationally with `${VIDIQ_API_KEY}` from
your environment. Useful for poking at tools the scripted probe doesn't cover —
but remember every tool call there spends from the same pool.

## Next: the requirements document

Once `inspect` shows you real field names, the spec should nail down:

1. **Which tools**, with measured credit cost and observed latency.
2. **Field mapping** — vidIQ field → `RawSource` field, plus which fields have no home
   and need a new model (search volume and competition score have no equivalent in
   `backend/models/research.py` today).
3. **Where each signal is consumed** — research fan-out, angle synthesis prompt, hook
   generation prompt.
4. **Cache key and TTL** — keyword volume moves weekly, so per-keyword caching is what
   makes the Boost pool viable.
5. **Call budget per story** and the config knob that enforces it, mirroring how
   `duration_target.news_query_cap` caps NewsAPI today.
6. **Degradation behaviour** — vidIQ must fail open. Credit exhaustion should lower
   quality, never fail a story.
