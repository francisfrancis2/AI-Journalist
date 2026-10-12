#!/usr/bin/env python3
"""
Generate a client-ready PDF research brief from vidIQ MCP data.

Two sections, as specified:
  1. Top keywords/phrases by YouTube search volume (monthly searches + 0-100 scores)
  2. Top 10 most-viewed videos for those keywords (view counts + watch links)

Live mode costs 5 credits per call: 1 keyword call + (N+1) video calls.
Cached calls are free, so re-running the same topic costs nothing.

  ./run.sh-equivalent:
    .venv/bin/python brief.py --topic "UAE economic diversification"
    .venv/bin/python brief.py --topic "..." --keywords 3 --dry-run
    .venv/bin/python brief.py --offline          # rebuild from saved snapshots, 0 credits
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mcp_client import (  # noqa: E402
    DiskCache, VidIQError, VidIQSession, extract_embedded_json, preflight_auth,
)

OUT = HERE / "out"
CACHE_DIR = OUT / "cache"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

KEYWORD_TOOL = "vidiq_keyword_research"
VIDEO_TOOL = "vidiq_youtube_search"
BALANCE_TOOL = "vidiq_balance"


# ── data collection ───────────────────────────────────────────────────────────

def _load_key() -> str:
    import os
    key = os.environ.get("VIDIQ_API_KEY", "").strip()
    if key:
        return key
    env = HERE.parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("VIDIQ_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("VIDIQ_API_KEY not set (env or .env).")


def _payload_data(raw: Any) -> Dict[str, Any]:
    """Normalise either vidIQ response shape into its structured half."""
    if isinstance(raw, str):
        raw = extract_embedded_json(raw)
    if isinstance(raw, dict) and set(raw.keys()) == {"text", "data"}:
        return raw.get("data") or {}
    return raw if isinstance(raw, dict) else {}


async def collect_live(topic: str, n_keywords: int, video_limit: int,
                       no_cache: bool, seed_term: Optional[str] = None,
                       video_keywords: Optional[List[str]] = None,
                       documentary: bool = False,
                       order: str = "viewCount") -> Dict[str, Any]:
    """`topic` is the headline shown to the reader; `seed_term` is what vidIQ searches.

    They differ whenever the request is a documentary title — titles carry near-zero
    search volume, while the subject behind them is what an audience actually queries.
    """
    search_seed = seed_term or topic
    token = _load_key()
    await preflight_auth(token)
    cache = DiskCache(CACHE_DIR, ttl_seconds=7 * 86400, enabled=not no_cache)

    async with VidIQSession(token, cache) as session:
        before, _ = await session.call_tool(BALANCE_TOOL, {}, validate=False, use_cache=False)

        kw_raw, kw_cached = await session.call_tool(
            KEYWORD_TOOL,
            {"mode": "research", "keyword": search_seed, "includeRelated": True},
            validate=False)
        print("  keywords: %s" % ("CACHED (0 credits)" if kw_cached else "fetched (~5 credits)"))
        kw_data = _payload_data(kw_raw)

        seed = kw_data.get("seedKeyword") or {}
        related = [k for k in (kw_data.get("relatedKeywords") or [])
                   if (k.get("estimatedMonthlySearch") or 0) > 0]
        related.sort(key=lambda k: k.get("estimatedMonthlySearch") or 0, reverse=True)
        top_keywords = related[:n_keywords]

        # Always include the seed topic so the video set stays anchored to the
        # subject; the highest-volume related terms are often broad head terms
        # whose most-viewed videos drift off-topic.
        # Highest-volume terms are usually broad head terms ("drone", "logistics")
        # whose most-viewed videos are consumer entertainment. video_keywords lets the
        # video search use topically precise terms while the keyword table still
        # reports demand ranking as requested.
        queries = [search_seed] + (video_keywords
                                   or [k["keyword"] for k in top_keywords])
        if documentary:
            # No documentary genre filter exists, so approximate it two ways:
            # the word itself in the query text, and YouTube's own duration bands.
            # 'medium' is 4-20min and 'long' is >20min, so a 10-minute floor needs
            # both bands plus a local cut.
            queries = queries + ["%s documentary" % q for q in queries[:2]]
            duration_bands = ["long", "medium"]
        else:
            duration_bands = [None]

        videos: List[Dict[str, Any]] = []
        for q in queries:
            for band in duration_bands:
                # order=viewCount asks "most-viewed videos containing this word",
                # which entertainment channels always win. order=relevance asks
                # YouTube for topical matches, which we then rank by views locally —
                # "most-viewed among genuinely relevant" rather than the reverse.
                call_args: Dict[str, Any] = {
                    "query": q, "order": order, "type": ["video"],
                    "limit": video_limit,
                }
                if band:
                    call_args["videoDuration"] = band
                vid_raw, vid_cached = await session.call_tool(
                    VIDEO_TOOL, call_args, validate=False)
                print("  videos %-32s %-7s %s" % (
                    repr(q)[:32], band or "any",
                    "CACHED (0 credits)" if vid_cached else "fetched (~5 credits)"))
                for row in (_payload_data(vid_raw).get("results") or []):
                    if row.get("kind") == "video" and row.get("id"):
                        row["_matched_keyword"] = q
                        videos.append(row)

        after, _ = await session.call_tool(BALANCE_TOOL, {}, validate=False, use_cache=False)

    return {
        "topic": topic, "search_seed": search_seed,
        "seed": seed, "keywords": related, "top_keywords": top_keywords,
        "videos": videos, "queries": queries, "video_keywords": video_keywords,
        "genre_filter": True,
        "documentary": documentary, "order": order,
        "balance_before": (before or {}).get("totalCredits"),
        "balance_after": (after or {}).get("totalCredits"),
    }


def collect_offline(topic: str, n_keywords: int) -> Dict[str, Any]:
    """Rebuild from snapshots already on disk. Costs nothing."""
    kw_files = sorted(OUT.glob("response_*keyword_research*.json"))
    if not kw_files:
        sys.exit("No saved keyword snapshot in out/. Run a live pull first.")
    kw_data = _payload_data(json.loads(kw_files[0].read_text()))
    seed = kw_data.get("seedKeyword") or {}
    related = [k for k in (kw_data.get("relatedKeywords") or [])
               if (k.get("estimatedMonthlySearch") or 0) > 0]
    related.sort(key=lambda k: k.get("estimatedMonthlySearch") or 0, reverse=True)

    if len(kw_files) > 1:
        print("  ! %d keyword snapshots on disk; using %s"
              % (len(kw_files), kw_files[0].name))
    print("  ! OFFLINE MODE merges every video snapshot in out/, which may span")
    print("    different topics. Use it for layout checks; run live for a real brief.")

    videos: List[Dict[str, Any]] = []
    for path in sorted(OUT.glob("response_*youtube_search*.json")):
        for row in (_payload_data(json.loads(path.read_text())).get("results") or []):
            if row.get("kind") == "video" and row.get("id"):
                row.setdefault("_matched_keyword", path.stem)
                videos.append(row)
    return {
        "topic": topic or seed.get("keyword") or "(unknown topic)",
        "seed": seed, "keywords": related, "top_keywords": related[:n_keywords],
        "videos": videos, "queries": [], "balance_before": None, "balance_after": None,
        "offline": True,
    }


# ── universal relevance filter ────────────────────────────────────────────────
# Topic vocabulary is derived from vidIQ's OWN related keywords for the seed, so
# this works for any subject with nothing hardcoded. Only the entertainment
# exclusions are fixed, because those are genre markers, not topic markers.

_STOP = {"the", "and", "for", "you", "your", "how", "why", "what", "best", "top",
         "new", "with", "this", "that", "from", "get", "make", "can", "are", "was",
         "has", "its", "all", "out", "about", "video", "videos", "youtube", "full"}

ENTERTAINMENT_RE = re.compile(
    r"(episode\s*[\d|]|full movie|prank|fortnite|minecraft|gameplay|simulator|"
    r"\bsong\b|cartoons?|kids tv|\bvlog\b|unboxing|giveaway|reaction|"
    r"try not to|challenge\s*!|\bskit\b|\bmeme)", re.I)
MILITARY_RE = re.compile(
    r"\b(strike|attack|war|weapon|missile|combat|military|kamikaze|fpv|ukrain\w*|"
    r"russia\w*)\b", re.I)


def _stems(text: str, n: int = 5) -> set:
    """Crude prefix stems so 'delivery'/'deliveries' and 'drone'/'drones' unify."""
    return {w[:n] for w in re.findall(r"[a-z]{3,}", (text or "").lower())
            if w not in _STOP}


def build_vocabulary(seed: str, related: List[Dict[str, Any]]) -> Dict[str, set]:
    """Topic vocabulary straight from vidIQ's keyword research. No hardcoding."""
    seed_stems = _stems(seed)
    vocab = set(seed_stems)
    for k in related:
        vocab |= _stems(k.get("keyword", ""))
    return {"seed": seed_stems, "vocab": vocab}


def passes_genre(video: Dict[str, Any], vocabulary: Dict[str, set],
                 min_hits: int = 2, allow_military: bool = False) -> bool:
    """On-topic when the TITLE carries >=min_hits topic stems, one of them from the seed.

    Title-only on purpose: descriptions mention anything in passing, so matching
    them lets travel vlogs through on a stray 'delivery'.
    """
    title = video.get("title") or ""
    if ENTERTAINMENT_RE.search(title):
        return False
    if not allow_military and MILITARY_RE.search(title):
        return False
    hits = _stems(title) & vocabulary["vocab"]
    return len(hits) >= min_hits and bool(_stems(title) & vocabulary["seed"])


def top_videos(videos: List[Dict[str, Any]], limit: int = 10, min_seconds: int = 0,
               vocabulary: Optional[Dict[str, set]] = None, allow_military: bool = False,
               min_hits: int = 2) -> List[Dict[str, Any]]:
    """Dedupe by id, apply the duration floor and topic filter, rank by views."""
    best: Dict[str, Dict[str, Any]] = {}
    for v in videos:
        if min_seconds and iso_to_seconds(v.get("duration")) < min_seconds:
            continue
        if vocabulary and not passes_genre(v, vocabulary, min_hits, allow_military):
            continue
        prev = best.get(v["id"])
        if prev is None or (v.get("viewCount") or 0) > (prev.get("viewCount") or 0):
            best[v["id"]] = v
    ranked = sorted(best.values(), key=lambda v: v.get("viewCount") or 0, reverse=True)
    return ranked[:limit]


# ── rendering ─────────────────────────────────────────────────────────────────

def iso_to_seconds(iso: Optional[str]) -> int:
    """Parse an ISO-8601 duration (PT#H#M#S) into seconds. 0 when absent."""
    if not iso:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    h, mn, sec = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mn * 60 + sec


def fmt_duration(iso: Optional[str]) -> str:
    total = iso_to_seconds(iso)
    if not total:
        return "—"
    h, rem = divmod(total, 3600)
    mn, sec = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, mn, sec) if h else "%d:%02d" % (mn, sec)


def _n(value: Optional[float]) -> str:
    return "{:,}".format(int(value)) if value else "—"


def _compact(value: Optional[float]) -> str:
    v = float(value or 0)
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= cut:
            return ("%.1f%s" % (v / cut, suffix)).replace(".0", "")
    return str(int(v))


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


_KEEP_UPPER = {"uae", "gcc", "usa", "uk", "eu", "ai", "ev", "gdp", "opec", "nato", "un"}


def _display_title(topic: str) -> str:
    """Title-case only when the source was a lowercased API seed, not user input."""
    if topic != topic.lower():
        return topic                      # the user gave us their own casing; keep it
    return " ".join(w.upper() if w in _KEEP_UPPER else w.capitalize()
                    for w in topic.split())


GENRE_NOTE = (
    "<li>Titles were screened against a topic vocabulary derived from vidIQ&rsquo;s own "
    "related keywords, excluding entertainment formats. This is a title heuristic, so a "
    "well-named outlier can still slip through.</li>"
)


def build_html(payload: Dict[str, Any], videos: List[Dict[str, Any]]) -> str:
    topic, seed = _display_title(payload["topic"]), payload["seed"]
    keywords = payload["keywords"]
    generated = datetime.now(timezone.utc).strftime("%d %B %Y")
    total_views = sum(v.get("viewCount") or 0 for v in videos)
    max_month = max([k.get("estimatedMonthlySearch") or 0 for k in keywords] or [1])

    kw_rows = []
    for i, k in enumerate(keywords, 1):
        vol = float(k.get("volume") or 0)
        comp = k.get("competition")
        share = (k.get("estimatedMonthlySearch") or 0) / max_month * 100
        kw_rows.append(f"""
      <tr>
        <td class="rank">{i}</td>
        <td class="term">{_esc(k.get('keyword'))}</td>
        <td class="num strong">{_n(k.get('estimatedMonthlySearch'))}</td>
        <td class="meter-cell">
          <div class="meter"><span style="width:{share:.1f}%"></span></div>
        </td>
        <td class="num">{vol:.0f}</td>
        <td class="num muted">{('%.0f' % comp) if comp is not None else '—'}</td>
        <td class="label">{_esc(k.get('volumeScoreLabel') or '—')}</td>
      </tr>""")

    vid_rows = []
    for i, v in enumerate(videos, 1):
        url = "https://youtube.com/watch?v=%s" % v.get("id")
        published = (v.get("publishedAt") or "")[:10] or "—"
        vid_rows.append(f"""
      <tr>
        <td class="rank">{i}</td>
        <td>
          <a class="vtitle" href="{_esc(url)}">{_esc(v.get('title'))}</a>
          <div class="vmeta">{_esc(v.get('channelTitle') or '—')} &nbsp;·&nbsp; {published}</div>
          <a class="vurl" href="{_esc(url)}">{_esc(url)}</a>
        </td>
        <td class="num nowrap dur">{fmt_duration(v.get('duration'))}</td>
        <td class="num strong nowrap">{_n(v.get('viewCount'))}</td>
      </tr>""")

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>YouTube Demand Brief — {_esc(topic)}</title>
<style>
  @page {{ size: A4; margin: 14mm 13mm 16mm; }}
  :root {{
    --surface:#fcfcfb; --rule:#e6e5e0; --rule-soft:#f0efea;
    --ink:#0b0b0b; --ink-2:#52514e; --ink-3:#8a8880;
    --series-1:#2a78d6; --track:#e9eef6; --accent-soft:#eef4fc;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--surface); color:var(--ink);
    font:11px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:10px; margin-bottom:16px; }}
  .eyebrow {{ font-size:9px; letter-spacing:.14em; text-transform:uppercase;
              color:var(--ink-3); font-weight:600; }}
  h1 {{ font-size:23px; line-height:1.2; margin:6px 0 4px; letter-spacing:-.01em; }}
  .sub {{ color:var(--ink-2); font-size:11px; }}
  .sub b {{ color:var(--ink); font-weight:600; }}

  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:9px; margin:0 0 20px; }}
  .kpi {{ border:1px solid var(--rule); border-radius:7px; padding:10px 11px; background:#fff; }}
  .kpi .k {{ font-size:8.5px; letter-spacing:.09em; text-transform:uppercase;
             color:var(--ink-3); font-weight:600; }}
  .kpi .v {{ font-size:22px; font-weight:650; letter-spacing:-.02em; margin-top:3px; }}
  .kpi .n {{ font-size:9.5px; color:var(--ink-2); margin-top:1px; }}

  h2 {{ font-size:13px; margin:0 0 3px; letter-spacing:-.005em; }}
  .lede {{ color:var(--ink-2); font-size:10px; margin:0 0 9px; max-width:150mm; }}
  section {{ margin-bottom:20px; }}

  table {{ width:100%; border-collapse:collapse; }}
  thead th {{
    font-size:8.5px; letter-spacing:.07em; text-transform:uppercase; color:var(--ink-3);
    font-weight:600; text-align:left; padding:0 7px 5px; border-bottom:1px solid var(--rule);
  }}
  tbody td {{ padding:6px 7px; border-bottom:1px solid var(--rule-soft); vertical-align:middle; }}
  tbody tr:nth-child(even) td {{ background:#fafaf8; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .strong {{ font-weight:650; }}
  .muted {{ color:var(--ink-2); }}
  .nowrap {{ white-space:nowrap; }}
  .rank {{ width:22px; color:var(--ink-3); font-size:9.5px; font-variant-numeric:tabular-nums; }}
  .term {{ font-weight:550; }}
  .label {{ font-size:9.5px; color:var(--ink-2); white-space:nowrap; }}

  .meter-cell {{ width:74px; padding-right:2px; }}
  .meter {{ height:7px; background:var(--track); border-radius:4px; overflow:hidden; }}
  .meter span {{ display:block; height:100%; background:var(--series-1); border-radius:4px; }}

  .vtitle {{ color:var(--ink); font-weight:600; font-size:11.5px; text-decoration:none; }}
  .vmeta {{ color:var(--ink-2); font-size:9.5px; margin-top:1px; }}
  .dur {{ font-size:10px; color:var(--ink-2); font-variant-numeric:tabular-nums; }}
  .vurl {{ color:var(--series-1); font-size:9px; text-decoration:none;
           font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
  tbody tr {{ page-break-inside:avoid; }}

  .note {{ border-top:1px solid var(--rule); margin-top:18px; padding-top:9px;
           font-size:9px; color:var(--ink-2); }}
  .note b {{ color:var(--ink); }}
  .warn {{ background:#fff4e5; border:1px solid #f0c48a; border-radius:6px;
           padding:7px 9px; font-size:9.5px; color:#7a4a05; margin-top:14px; }}
  .note ul {{ margin:5px 0 0; padding-left:15px; }}
  .note li {{ margin-bottom:2px; }}
</style></head>
<body>
  <header>
    <div class="eyebrow">YouTube Audience Demand Brief</div>
    <h1>{_esc(topic)}</h1>
    <div class="sub">{f"Subject searched: <b>{_esc(payload.get('search_seed'))}</b> &nbsp;·&nbsp; " if payload.get("search_seed") and payload["search_seed"] != payload["topic"] else ""}Source: <b>vidIQ</b> &nbsp;·&nbsp; Generated {generated}
      &nbsp;·&nbsp; Seed keyword demand: <b>{_n(seed.get('estimatedMonthlySearch'))}</b>
      searches/month ({_esc(seed.get('volumeScoreLabel') or 'n/a')})</div>
  </header>

  <div class="kpis">
    <div class="kpi"><div class="k">Seed monthly searches</div>
      <div class="v">{_n(seed.get('estimatedMonthlySearch'))}</div>
      <div class="n">volume {float(seed.get('volume') or 0):.0f}/100 ·
        competition {seed.get('competition') if seed.get('competition') is not None else '—'}/100</div></div>
    <div class="kpi"><div class="k">Keywords with demand</div>
      <div class="v">{len(keywords)}</div>
      <div class="n">non-zero monthly search volume</div></div>
    <div class="kpi"><div class="k">Top keyword</div>
      <div class="v">{_compact(keywords[0].get('estimatedMonthlySearch')) if keywords else '—'}</div>
      <div class="n">{_esc(keywords[0].get('keyword')) if keywords else '—'}</div></div>
    <div class="kpi"><div class="k">Combined views, top 10</div>
      <div class="v">{_compact(total_views)}</div>
      <div class="n">across the videos listed below</div></div>
  </div>

  <section>
    <h2>1 &nbsp;Top keywords and phrases by search volume</h2>
    <p class="lede">Ranked by estimated monthly YouTube searches. <b>Volume</b> and
      <b>competition</b> are vidIQ's 0–100 scores — high volume with low competition is
      the opening. The bar shows each term's share of the highest-volume term.</p>
    <table>
      <thead><tr>
        <th></th><th>Keyword / phrase</th><th class="num">Monthly searches</th>
        <th></th><th class="num">Volume</th><th class="num">Comp.</th><th>Demand</th>
      </tr></thead>
      <tbody>{''.join(kw_rows)}
      </tbody>
    </table>
  </section>

  <section>
    <h2>2 &nbsp;Top 10 most-viewed {"long-form videos" if payload.get("documentary") else "videos"} for these keywords</h2>
    <p class="lede">{"Topically matched on YouTube, then ranked by lifetime views" if payload.get("order") == "relevance" else "Highest lifetime view counts across YouTube"}, de-duplicated. Every title and URL links to the video. Searched on:
      <b>{_esc(", ".join(payload.get("queries") or []) or "top keywords by volume")}</b>.</p>
    <table>
      <thead><tr>
        <th></th><th>Video</th><th class="num">Length</th><th class="num">Views</th>
      </tr></thead>
      <tbody>{''.join(vid_rows)}
      </tbody>
    </table>
  </section>

  {'<div class="warn">LAYOUT PREVIEW — rebuilt offline from mixed snapshots; '
    'keywords and videos may come from different topics.</div>'
    if payload.get("offline") else ""}

  <div class="note">
    <b>Method &amp; caveats.</b>
    <ul>
      <li>Keyword metrics from vidIQ <code>keyword_research</code>; videos from
          <code>youtube_search</code> sorted by view count.</li>
      <li>Views are <b>lifetime</b> totals, not recent momentum — a high-ranking video may
          be years old. For current traction, rank by views-per-hour instead.</li>
      <li>Broad head terms can surface topically unrelated videos that happen to share a
          word. Results are anchored by also querying the seed topic directly.</li>
      {'<li>YouTube exposes no documentary <i>genre</i> filter. Long-form here means '
       'duration-filtered (medium 4–20min and long &gt;20min bands) plus '
       '&ldquo;documentary&rdquo; query variants — a close proxy, not a genre guarantee.</li>'
       if payload.get("documentary") else ""}
      {GENRE_NOTE if payload.get("genre_filter") else ""}
      <li>Search volumes are vidIQ estimates, not YouTube-published figures.</li>
    </ul>
  </div>
</body></html>"""


def render_pdf(html_path: Path, pdf_path: Path) -> None:
    if not Path(CHROME).exists():
        sys.exit("Chrome not found at %s — cannot render PDF." % CHROME)
    subprocess.run([
        CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        "--print-to-pdf=%s" % pdf_path.resolve(), html_path.resolve().as_uri(),
    ], check=True, capture_output=True, timeout=120)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--topic", help="research request / documentary topic")
    p.add_argument("--seed", default=None,
                   help="keyword vidIQ searches, when it differs from the display title")
    p.add_argument("--keywords", type=int, default=3,
                   help="how many top keywords also get a video search (default 3)")
    p.add_argument("--video-keywords", default=None,
                   help="comma-separated keywords to drive the video search, instead "
                        "of the highest-volume ones (keeps the report topically tight)")
    p.add_argument("--documentary", action="store_true",
                   help="bias toward long-form documentary: adds 'documentary' query "
                        "variants and searches YouTube's medium+long duration bands")
    p.add_argument("--genre-filter", action="store_true",
                   help="keep only titles matching the topic vocabulary derived from "
                        "vidIQ's related keywords; drops entertainment")
    p.add_argument("--min-hits", type=int, default=2,
                   help="topic stems a title must carry to qualify (default 2)")
    p.add_argument("--allow-military", action="store_true",
                   help="keep military/strike titles, which --genre-filter drops")
    p.add_argument("--order", default="viewCount",
                   choices=["viewCount", "relevance", "date", "rating"],
                   help="YouTube sort. 'relevance' finds topical matches which are then "
                        "ranked by views locally; 'viewCount' returns raw popularity")
    p.add_argument("--min-minutes", type=int, default=4,
                   help="drop videos shorter than this many minutes (e.g. 10)")
    p.add_argument("--video-limit", type=int, default=10,
                   help="videos requested per keyword before merging (default 10)")
    p.add_argument("--offline", action="store_true",
                   help="rebuild from saved snapshots — 0 credits")
    p.add_argument("--no-cache", action="store_true", help="force fresh billable calls")
    p.add_argument("--dry-run", action="store_true", help="show the call plan and cost, then stop")
    p.add_argument("--out", default=None, help="output basename (default: derived from topic)")
    args = p.parse_args()

    if not args.offline and not args.topic:
        sys.exit("--topic is required (or use --offline to rebuild from snapshots).")

    if args.dry_run:
        base = 1 + args.keywords
        calls = 1 + (base + 2) * 2 if args.documentary else 1 + base
        print("PLAN for %r" % args.topic)
        print("  %s x1, %s x%d (seed + %d keywords)"
              % (KEYWORD_TOOL, VIDEO_TOOL, 1 + args.keywords, args.keywords))
        print("  worst case %d billable calls ~ %d credits (cached calls are free)"
              % (calls, calls * 5))
        return

    if args.offline:
        print("Offline rebuild from saved snapshots (0 credits)")
        payload = collect_offline(args.topic, args.keywords)
    else:
        print("Collecting vidIQ data for %r" % args.topic)
        vkw = ([w.strip() for w in args.video_keywords.split(",") if w.strip()]
               if args.video_keywords else None)
        payload = asyncio.run(collect_live(args.topic, args.keywords, args.video_limit,
                                           args.no_cache, args.seed, vkw,
                                           args.documentary, args.order))
        if payload["balance_before"] and payload["balance_after"]:
            print("  credits: %s -> %s (spent %s)"
                  % (payload["balance_before"], payload["balance_after"],
                     payload["balance_before"] - payload["balance_after"]))

    vocabulary = (build_vocabulary(payload.get("search_seed") or payload["topic"],
                                   payload["keywords"])
                  if args.genre_filter else None)
    if vocabulary:
        print("  topic vocabulary (%d stems, from vidIQ keywords): %s"
              % (len(vocabulary["vocab"]), ", ".join(sorted(vocabulary["vocab"]))[:140]))
    videos = top_videos(payload["videos"], 10, args.min_minutes * 60,
                        vocabulary, args.allow_military, args.min_hits)
    if not payload["keywords"]:
        sys.exit("No keywords with non-zero search volume — nothing to report.")

    stem = args.out or "brief_" + "".join(
        c if c.isalnum() else "-" for c in payload["topic"].lower())[:50].strip("-")
    OUT.mkdir(parents=True, exist_ok=True)
    html_path, pdf_path = OUT / (stem + ".html"), OUT / (stem + ".pdf")
    html_path.write_text(build_html(payload, videos))
    render_pdf(html_path, pdf_path)

    if args.min_minutes:
        kept = len({v["id"] for v in payload["videos"]})
        print("\n  duration filter: >=%d min — %d of %d unique videos qualified"
              % (args.min_minutes, len(videos), kept))
    print("\n  keywords : %d with demand (top: %s)"
          % (len(payload["keywords"]), payload["keywords"][0]["keyword"]))
    print("  videos   : %d ranked, %s combined views"
          % (len(videos), _n(sum(v.get("viewCount") or 0 for v in videos))))
    print("\n  HTML: %s" % html_path)
    print("  PDF : %s  (%.0f KB)" % (pdf_path, pdf_path.stat().st_size / 1024))


if __name__ == "__main__":
    main()
