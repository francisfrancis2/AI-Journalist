# Documentary — idea instructions

Applied on top of `idea_generator_shared.md` when the requested format is
**documentary**.

This definition is derived from the reference corpus (516 analysed scripts
across Emirates Insider, Business Insider, CNBC, Vox and Johnny Harris), not
from a style guide. Where the libraries disagree, Emirates Insider wins — it is
our own channel.

## What a documentary is here

A documentary takes one concrete subject — a person, a company, a product, a
place or a process — and uses it to explain how a larger system works. The
subject is the way in; the system is the payload.

The corpus is near-unanimous on one point: **a documentary is carried by a
human story.** 100% of Emirates Insider scripts and 89–98% of the Business
Insider and CNBC sets follow named people through a real situation. Only the
systems-explainer libraries (Vox at 62%) sometimes drop it. If an idea has no
person a crew can film, it is an explainer, not a documentary.

## Shape the idea must support

| | Corpus evidence |
|---|---|
| **Four acts** | The dominant structure in every library — 10 of 14 at Emirates Insider, 69 of 127 at Business Insider |
| **~5 minutes** | Emirates Insider median; the wider corpus runs 7–9 minutes |
| **~8 concrete facts** | Median stat count per script, consistent across all five libraries |
| **Opens on a person, a question or a number** | The three recurring hook types |
| **Closes forward** | Aspirational or forward-looking statements dominate the closings |

An idea must be rich enough to sustain four acts. If the whole story is one
revelation, it is a segment, not a documentary.

## The kinds of topics that work

Drawn from what the corpus actually covers:

- **A founder or operator who built something against a real constraint.**
  Emirates Insider's centre of gravity: raising capital, building a category,
  growing food in a desert. The business outcome must be specific and
  verifiable, not aspirational.
- **The economics behind a thing people take for granted.** The "why is this so
  expensive" family — the single most repeated title formula in the corpus.
  Price, scarcity or supply chain as the entry point to an industry.
- **How a system, industry or place actually works.** The "explained" and
  "how X became Y" family. A mechanism most people use but cannot describe.
- **A place or institution making a visible bet.** Infrastructure, energy,
  food security, technology — where the physical world is changing and a crew
  could stand in it.

## Distinctness for this format

Spread the set across unrelated industries. A documentary slate works when each
film opens a different world, so two strong ideas from the same sector make a
weaker set than one from each. If two candidates would send a crew to similar
places to film similar processes, they are not distinct enough.

## Selection criteria

1. **Is there a person?** Named, reachable, with something at stake. The corpus
   says this is close to non-negotiable.
2. **Is there a system behind the person?** Without one it is a profile.
3. **Can it hold four acts?** Enough turns, obstacles or reveals to structure.
4. **Is it filmable?** A place, a process, an object. "Visual world" is a
   required field because the corpus is a visual medium.
5. **Are there about eight hard facts available?** Numbers, dates, named
   parties. Thin evidence shows immediately at this length.
6. **Does it resolve forward?** The corpus closes on where this is heading, not
   on a summary.

## Avoid

- **Company profiles with no system.** A business that is merely successful is
  not a documentary; what the business reveals about its market is.
- **Explainers with no protagonist.** If nobody can be filmed, it is the wrong
  format — propose it as an expert interview instead.
- **Subjects with no physical world.** Pure policy or pure finance with nothing
  to point a camera at.
- **Promotional framings.** Follow a real constraint and a real outcome; if the
  only available story is that something succeeded, drop it.

## format_details fields

Populate `format_details` with:

- `protagonist_or_system` — the named person or operator, **and** the system
  their story explains. Both halves, every time.
- `access_path` — who must agree to be filmed and why they plausibly would.
- `visual_world` — where a crew physically goes and what they shoot.
- `story_arc` — the four-act shape: the situation, the complication, the turn,
  and where it points next.
