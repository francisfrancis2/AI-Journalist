# Untitled UI v2.0 — design system import

Source: Untitled UI v2.0 (Community), duplicated into our workspace.
File key: `z5wKZcrPjEsRorTuEHxc6r`

## How this was extracted

Figma REST API, not MCP. MCP is node-scoped and needs a `node-id` per call, which
is what stalled the April 2026 attempt. REST is file-scoped: one request returns
the page index, a second returns the foundations pages.

Variables (`/v1/files/:key/variables/local`) are **Enterprise-only** and returned
403, and this kit publishes **zero** styles — everything is defined as variables.
So tokens were derived from the raw node tree of the Colors page, reading the
`Swatch` fill plus the `Number` and `Hex` text nodes of each `_Swatch base`.

Extractor: `sandbox/figma/extract.py` (gitignored output in `sandbox/figma/out/`).

## What was applied

8 of 20 CSS custom properties in `frontend/app/globals.css`. Because all 549
`var(--...)` references across 18 component files resolve through these
definitions, re-skinning the app was a one-file change.

- **Neutrals** moved to the kit's true-neutral gray ramp (the previous values
  were slightly warm: `#4d4d4f`, `#8a8a8c`, `#adadad`).
- **Status colours were already exact matches** to this kit and were not touched.
- **Brand tokens kept** — `--color-action: #1c26a8` is EDB Blue. Importing a
  generic kit should not silently discard brand identity.

## Accessibility outcome

| token | before | after |
|---|---|---|
| `--color-text-primary` | 8.4:1 (AAA) | 17.9:1 (AAA) |
| `--color-text-secondary` | 3.4:1 (AA-large only) | 7.8:1 (AAA) |
| `--color-text-tertiary` | **2.2:1 (FAIL)** | 4.7:1 (AA) |

`--color-text-tertiary` is the most-used token in the codebase (98 references)
and was failing WCAG contrast entirely on white.

## Not applied

Typography. The kit uses Inter 400/500/600 at 12/14/16/18/20/24px; the app uses a
system stack via `next/font`. Switching requires a `layout.tsx` change and was
kept separate from the colour swap so each can be judged on its own.
