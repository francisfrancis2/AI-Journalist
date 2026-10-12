#!/usr/bin/env python3
"""Render saved probe responses as the deliverable: keywords + most-watched videos.

Handles both vidIQ response shapes seen in testing:
  - pure structured JSON      -> {"results": [...]}            (vidiq_youtube_search)
  - hybrid markdown + JSON    -> {"text": ..., "data": {...}}  (vidiq_keyword_research)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
sys.path.insert(0, str(HERE))
from mcp_client import extract_embedded_json  # noqa: E402


def payload_data(raw):
    """Return the structured half regardless of which shape the tool used.

    Three vintages exist on disk: a raw markdown string (saved before the splitter
    existed), a split {"text","data"} dict, and pure structured JSON.
    """
    if isinstance(raw, str):
        raw = extract_embedded_json(raw)
    if isinstance(raw, dict) and set(raw.keys()) == {"text", "data"}:
        return raw.get("data") or {}
    return raw if isinstance(raw, dict) else {}


def main() -> None:
    for path in sorted(OUT.glob("response_stage1_*.json")):
        d = payload_data(json.loads(path.read_text()))
        seed, related = d.get("seedKeyword") or {}, d.get("relatedKeywords") or []
        print("=" * 90)
        print("KEYWORDS — seed: %s" % seed.get("keyword"))
        print("=" * 90)
        print("  seed: vol=%.1f comp=%s overall=%.1f monthly=%s (%s)\n" % (
            seed.get("volume") or 0, seed.get("competition"),
            seed.get("overall") or 0, seed.get("monthlySearchesDisplay"),
            seed.get("volumeScoreLabel")))
        print("  %-30s %7s %7s %8s %12s" % ("keyword", "volume", "comp", "overall", "monthly"))
        print("  " + "-" * 68)
        for k in sorted(related, key=lambda r: (r.get("overall") or 0), reverse=True):
            print("  %-30s %7.1f %7s %8s %12s" % (
                k["keyword"][:30], k.get("volume") or 0, k.get("competition"),
                round(k["overall"], 1) if k.get("overall") else "-",
                k.get("monthlySearchesDisplay")))
        print()

    for path in sorted(OUT.glob("response_stage2_*.json")):
        d = payload_data(json.loads(path.read_text()))
        results = [r for r in (d.get("results") or []) if r.get("kind") == "video"]
        kw = path.name.split("response_stage2_")[1].split("_vidiq")[0]
        print("=" * 90)
        print("MOST-WATCHED VIDEOS — keyword: %s  (%d results)" % (kw, len(results)))
        print("=" * 90)
        for r in results:
            views = "{:,}".format(int(r["viewCount"])) if r.get("viewCount") else "?"
            print("  %-58s %14s views" % (r.get("title", "")[:58], views))
            print("    %-30s %s   https://youtube.com/watch?v=%s" % (
                (r.get("channelTitle") or "?")[:30], (r.get("publishedAt") or "?")[:10], r.get("id")))
        print()


if __name__ == "__main__":
    main()
