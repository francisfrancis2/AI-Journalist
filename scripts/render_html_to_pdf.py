#!/usr/bin/env python3
"""Render a local HTML file to PDF using Playwright Chromium."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def _render(html_path: Path, pdf_path: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--allow-file-access-from-files", "--no-sandbox"],
        )
        page = await browser.new_page(viewport={"width": 1240, "height": 1754})
        await page.emulate_media(media="screen")
        await page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        await page.pdf(
            path=str(pdf_path.resolve()),
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
        )
        await browser.close()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "Usage: python scripts/render_html_to_pdf.py <input.html> <output.pdf>",
            file=sys.stderr,
        )
        return 1

    html_path = Path(argv[1])
    pdf_path = Path(argv[2])

    if not html_path.exists():
        print(f"Input HTML not found: {html_path}", file=sys.stderr)
        return 1

    asyncio.run(_render(html_path, pdf_path))
    print(f"Rendered {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
