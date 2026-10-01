#!/usr/bin/env python3
"""
Figma design-system extractor (REST API, personal access token).

File-scoped on purpose: the Figma MCP server is node-scoped and needs a
`node-id` per call, which is what stalled the April 2026 import attempt. The
REST API returns the whole document in one request, so no node links are needed.

Reads FIGMA_ACCESS_TOKEN and FIGMA_FILE_KEY from the environment or the repo .env.
Touches nothing in frontend/ or backend/ — it only writes to sandbox/figma/out/.

  python3 sandbox/figma/extract.py whoami    # verify the token, 1 request
  python3 sandbox/figma/extract.py pull      # fetch file + styles (+ variables)
  python3 sandbox/figma/extract.py tokens    # derive colors/type/radii/spacing
  python3 sandbox/figma/extract.py map       # propose a mapping to globals.css
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "out"
API = "https://api.figma.com/v1"

# The 24 custom properties the app actually styles against.
APP_TOKENS = [
    "--color-background-primary", "--color-background-secondary", "--color-background-tertiary",
    "--color-border-primary", "--color-border-secondary", "--color-border-tertiary",
    "--color-text-primary", "--color-text-secondary", "--color-text-tertiary",
    "--color-action", "--color-action-hover",
    "--color-success", "--color-success-bg", "--color-warning", "--color-warning-bg",
    "--color-danger", "--color-danger-bg",
    "--border-radius-sm", "--border-radius-md", "--border-radius-lg",
]


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _client() -> httpx.Client:
    token = _env("FIGMA_ACCESS_TOKEN")
    if not token:
        sys.exit(
            "FIGMA_ACCESS_TOKEN not set.\n"
            "  Create one at https://www.figma.com/settings -> Security -> Personal access tokens\n"
            "  Then add FIGMA_ACCESS_TOKEN=figd_... to the repo .env"
        )
    return httpx.Client(headers={"X-Figma-Token": token}, timeout=120.0)


def _file_key() -> str:
    key = _env("FIGMA_FILE_KEY")
    if not key:
        sys.exit("FIGMA_FILE_KEY not set. Add FIGMA_FILE_KEY=... to .env "
                 "(the segment after /design/ in your file URL).")
    return key


def _rgba_to_hex(color: dict, opacity: Optional[float] = None) -> str:
    r, g, b = (round(color.get(c, 0) * 255) for c in ("r", "g", "b"))
    alpha = color.get("a", 1) if opacity is None else opacity
    if alpha is not None and alpha < 0.999:
        return f"rgba({r}, {g}, {b}, {round(alpha, 3)})"
    return f"#{r:02x}{g:02x}{b:02x}"


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_whoami(_: argparse.Namespace) -> None:
    """1 request. Confirms the token works and reports what it can reach."""
    with _client() as client:
        me = client.get(f"{API}/me")
        if me.status_code == 403:
            sys.exit("403 — token rejected. Check it was copied whole and has not expired.")
        if me.status_code >= 400:
            sys.exit(f"HTTP {me.status_code}: {me.text[:200]}")
        data = me.json()
        print(f"token OK — {data.get('email')} ({data.get('handle')})")

        key = _env("FIGMA_FILE_KEY")
        if not key:
            print("FIGMA_FILE_KEY not set yet — add it to .env to check file access.")
            return
        meta = client.get(f"{API}/files/{key}", params={"depth": 1})
        if meta.status_code == 404:
            sys.exit(f"404 on file {key} — the token's account cannot see this file.\n"
                     "  If it is a Community file, duplicate it into your own drafts first "
                     "and use the NEW file key.")
        if meta.status_code >= 400:
            sys.exit(f"HTTP {meta.status_code} on file: {meta.text[:200]}")
        doc = meta.json()
        print(f"file OK — '{doc.get('name')}' (last modified {doc.get('lastModified')})")
        pages = (doc.get("document") or {}).get("children") or []
        print(f"pages ({len(pages)}): " + ", ".join(p.get("name", "?") for p in pages[:12]))

        var = client.get(f"{API}/files/{key}/variables/local")
        if var.status_code == 200:
            note = "available"
        else:
            note = "unavailable (Enterprise-only) - published styles will be used instead"
        print(f"variables endpoint -> HTTP {var.status_code} ({note})")


# Pages worth extracting from a large kit. A 100+ page file is far too big to
# pull whole, and the foundations pages carry every token we need.
FOUNDATION_HINTS = ("color", "typography", "spacing", "radius", "grid", "effect",
                    "shadow", "foundation", "variable", "token")


def cmd_pull(args: argparse.Namespace) -> None:
    """Fetch published styles, the page index, and only the foundation pages.

    Deliberately NOT a whole-file fetch: this kit has 109 pages, and requesting
    all of them is slow, huge, and mostly component artwork we do not need.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    key = _file_key()
    with _client() as client:
        # 1. Published styles — small, and the authoritative list of named tokens.
        resp = client.get(f"{API}/files/{key}/styles")
        if resp.status_code == 200:
            (OUT / "styles.json").write_text(json.dumps(resp.json(), indent=2))
            meta = resp.json().get("meta", {}).get("styles", [])
            print(f"  styles     {len(meta)} published styles saved")
        else:
            print(f"  styles     HTTP {resp.status_code} — skipped")

        # 2. Variables, when the plan allows.
        resp = client.get(f"{API}/files/{key}/variables/local")
        if resp.status_code == 200:
            (OUT / "variables.json").write_text(json.dumps(resp.json(), indent=2))
            print("  variables  saved")
        else:
            print(f"  variables  HTTP {resp.status_code} — Enterprise only, skipped")

        # 3. Page index at depth 1 (cheap), then fetch only foundation pages.
        resp = client.get(f"{API}/files/{key}", params={"depth": 1})
        resp.raise_for_status()
        doc = resp.json()
        (OUT / "index.json").write_text(json.dumps(doc, indent=2))
        pages = (doc.get("document") or {}).get("children") or []
        wanted = [p for p in pages
                  if any(h in (p.get("name") or "").lower() for h in FOUNDATION_HINTS)]
        print(f"  index      {len(pages)} pages, {len(wanted)} look like foundations:")
        for page in wanted:
            print(f"               - {page.get('name','').strip()}")
        if not wanted:
            print("  no foundation pages matched; re-run with --page NAME")
            return

        ids = ",".join(p["id"] for p in wanted[: args.max_pages])
        resp = client.get(f"{API}/files/{key}/nodes", params={"ids": ids})
        if resp.status_code != 200:
            print(f"  nodes      HTTP {resp.status_code}: {resp.text[:160]}")
            return
        path = OUT / "foundations.json"
        path.write_text(json.dumps(resp.json(), indent=2))
        print(f"  nodes      saved {path.relative_to(ROOT)} "
              f"({path.stat().st_size//1024} KB)")


def _walk(node: dict, fn) -> None:
    fn(node)
    for child in node.get("children") or []:
        _walk(child, fn)



def _merge_named_styles(named_colors: dict) -> None:
    """Attach published style names to hexes where the styles endpoint knows them."""
    path = OUT / "styles.json"
    if not path.exists():
        return
    for style in json.loads(path.read_text()).get("meta", {}).get("styles", []):
        if style.get("style_type") == "FILL" and style.get("name"):
            named_colors.setdefault("style:" + style["name"], style["name"])


def cmd_tokens(_: argparse.Namespace) -> None:
    """Derive colors, type ramp, radii and spacing from the pulled document."""
    file_path = OUT / "foundations.json"
    if not file_path.exists():
        sys.exit("No out/foundations.json — run `pull` first.")
    doc = json.loads(file_path.read_text())

    colors: Counter = Counter()
    fonts: Counter = Counter()
    radii: Counter = Counter()
    named_colors: dict[str, str] = {}

    def visit(node: dict) -> None:
        for fill in node.get("fills") or []:
            if fill.get("type") == "SOLID" and fill.get("visible", True):
                hexv = _rgba_to_hex(fill.get("color") or {}, fill.get("opacity"))
                colors[hexv] += 1
                name = (node.get("name") or "").strip()
                # Figma convention: swatch frames are named for their role.
                if name and len(name) < 48 and hexv not in named_colors:
                    named_colors[hexv] = name
        style = node.get("style") or {}
        if style.get("fontFamily"):
            fonts[(style["fontFamily"], style.get("fontWeight"),
                   round(style.get("fontSize", 0)))] += 1
        for key in ("cornerRadius", "rectangleCornerRadii"):
            value = node.get(key)
            if isinstance(value, (int, float)):
                radii[round(value)] += 1
            elif isinstance(value, list):
                for v in value:
                    radii[round(v)] += 1

    for node in (doc.get("nodes") or {}).values():
        _walk(node.get("document") or {}, visit)
    _merge_named_styles(named_colors)

    tokens = {
        "colors": [{"hex": h, "uses": n, "figma_name": named_colors.get(h)}
                   for h, n in colors.most_common(40)],
        "typography": [{"family": f, "weight": w, "size": s, "uses": n}
                       for (f, w, s), n in fonts.most_common(20)],
        "radii": [{"px": r, "uses": n} for r, n in sorted(radii.items())],
    }
    (OUT / "tokens.json").write_text(json.dumps(tokens, indent=2))

    print(f"colors: {len(colors)} distinct — top 12")
    for row in tokens["colors"][:12]:
        print(f"   {row['hex']:<22} {row['uses']:>4} uses   {row['figma_name'] or ''}")
    print(f"\ntype: {len(fonts)} distinct — top 8")
    for row in tokens["typography"][:8]:
        print(f"   {row['family']:<22} w{row['weight']:<4} {row['size']}px   {row['uses']} uses")
    print(f"\nradii: {[r['px'] for r in tokens['radii']][:10]}")
    print(f"\nsaved {(OUT / 'tokens.json').relative_to(ROOT)}")


def cmd_map(_: argparse.Namespace) -> None:
    """Propose Figma value -> app CSS custom property, for review before applying."""
    tokens_path = OUT / "tokens.json"
    if not tokens_path.exists():
        sys.exit("No out/tokens.json — run `tokens` first.")
    tokens = json.loads(tokens_path.read_text())

    current = {}
    css = (ROOT / "frontend/app/globals.css").read_text()
    for name in APP_TOKENS:
        match = re.search(rf"{re.escape(name)}:\s*([^;]+);", css)
        if match:
            current[name] = match.group(1).strip()

    mapping = {
        "_README": [
            "Proposed mapping from the Figma library to the app's CSS custom properties.",
            "Only these ~20 definitions change; the 549 var(--...) call sites do not.",
            "Review and edit `to` values, then ask Claude to apply it to globals.css.",
            "Brand tokens default to KEEPING the current value — swapping brand colour",
            "wholesale is rarely intended when importing a generic library.",
        ],
        "source_file": _env("FIGMA_FILE_KEY"),
        "mapping": [],
    }
    brand = {"--color-action", "--color-action-hover"}
    for name in APP_TOKENS:
        mapping["mapping"].append({
            "token": name,
            "from": current.get(name),
            "to": current.get(name) if name in brand else None,
            "keep_brand": name in brand,
            "candidates": [c["hex"] for c in tokens.get("colors", [])[:8]],
        })
    (OUT / "frontend-mapping.json").write_text(json.dumps(mapping, indent=2))
    print(f"wrote {(OUT / 'frontend-mapping.json').relative_to(ROOT)}")
    print(f"  {len(current)} current token values read from globals.css")
    print("  brand tokens pre-set to keep their current values:", ", ".join(sorted(brand)))
    print("\nReview the file, fill in the `to` values, then ask Claude to apply it.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn, help_text in (
        ("whoami", cmd_whoami, "verify the token and file access (1-3 requests)"),
        ("pull", cmd_pull, "fetch file + styles + variables into out/"),
        ("tokens", cmd_tokens, "derive colors, type, radii from the pulled file"),
        ("map", cmd_map, "propose a mapping to the app's CSS custom properties"),
    ):
        p = sub.add_parser(name, help=help_text)
        if name == "pull":
            p.add_argument("--max-pages", type=int, default=8,
                           help="cap on foundation pages fetched (default 8)")
        p.set_defaults(func=fn)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
