# Expert Mode — idea instructions

Applied on top of `idea_generator_shared.md` when the requested format is
**expert interview video**.

## What the show is

Expert Mode takes a complex business or economic shift and gets an expert to
decode what is really happening, why it matters, and what happens next — in
five minutes or less.

The feeling the audience should leave with:

> "I didn't understand this before. Now I understand the system, I see where
> this is going, I know why I should care and what to capitalise on."

## Every idea must deliver three things

An idea that cannot carry all three is not an Expert Mode idea.

1. **What's actually happening?** — the system, policy, technology, market or
   shift sitting behind the headline.
2. **Why does it matter?** — who is affected, where money, talent or business
   opportunity is moving, who wins and who loses.
3. **What happens next?** — what is likely to follow, and what the audience
   should be watching or doing.

## Selection criteria

Score each candidate against all seven. Favour ideas that score highly across
the set rather than ideas that are exceptional on one axis and weak elsewhere.

| # | Criterion | The question to ask |
|---|---|---|
| 1 | **Complexity** | Is there a system, mechanism or chain of events that needs explaining? |
| 2 | **Consequence** | Does this materially affect businesses, founders, investors, workers or consumers? |
| 3 | **Tension** | Is there a surprising contradiction, misconception or unanswered question? |
| 4 | **Change** | Is something genuinely shifting — money, regulation, technology, behaviour, power or markets? |
| 5 | **Stakes** | Are there clear winners, losers, risks or opportunities? |
| 6 | **Expertise** | Can we find someone who genuinely understands the subject, rather than someone merely adjacent to it? |
| 7 | **Takeaway** | Can the expert credibly say what happens next and what the audience should watch or do? |

## Who is watching

People running businesses in the UAE: SME owners, founders, and the operators
around them. Assume a viewer with a company to run, decisions to make this
quarter, and no time for a briefing aimed at somebody else.

This is the single most common way an Expert Mode idea goes wrong. An idea
addressed to fund managers, policymakers, sovereign investors or sustainability
executives is the wrong show, however strong the subject. Check `target_audience`
before you commit to an idea: if it does not name people running companies, the
framing is wrong and the idea needs re-pointing or dropping.

## Answer the questions operators are actually asking

The prompt includes a list of questions UAE operators have asked in public
forums. Treat it as the clearest available evidence of what this audience wants
explained, and prefer ideas that answer one of them — or answer the real
question sitting underneath several of them.

Two rules about that list:

- **It is demand evidence, never factual evidence.** A thread proves a question
  is live and widely asked. It proves nothing about any answer in it, and it is
  not a citable source. Every fact still comes from the research sources.
- **Answer the question, do not repeat it.** "Should I go free zone or
  mainland?" is the question; the episode is the mechanism that decides it, and
  the thing most people get wrong about that decision.

A recurring question is the strongest signal this show can get. When several
people keep asking the same thing, an expert who can settle it is worth five
minutes of anyone's time — and that is a better reason to make an episode than
any news hook.

## The two tests every idea must pass

**The UAE test.** The idea must turn on something specific to this market that a
well-read outsider would get wrong or not know at all — a rule, a cost, a
channel, a customer behaviour, a way capital actually moves here. If the same
episode could be made about Singapore or Saudi Arabia by swapping the names, it
is not an Expert Mode idea.

**The Monday test.** A viewer running a UAE business should be able to name one
decision they would make, revisit or delay because of what they just learned.
"Interesting to know" is not a takeaway. Name the decision.

## The kinds of topics that work

All four are at the altitude of a company, not a country.

- **A rule, cost or process that just changed for operators.**
  e.g. What corporate tax actually did to the free-zone-versus-mainland
  decision — and who should now be rethinking their structure.
- **How money really reaches UAE companies.**
  e.g. Why UAE startups are borrowing instead of raising, what the terms look
  like, and which businesses that suits.
- **What it actually takes to operate here.**
  e.g. What hiring really costs once Emiratisation quotas, visa timing and
  salary expectations are counted — and how that changes a growth plan.
- **A local market mechanic outsiders get wrong.**
  e.g. Why a product that sells itself in Europe needs a distributor here, and
  what that does to your pricing.

## Avoid

- **National-scale bets and megaprojects.** "The UAE is betting $150 million
  on X", "the Emirates wants to become a Y economy". These are documentary
  subjects: a viewer running a company cannot act on a sovereign programme.
  Cover one only where it changes a rule, cost or opening that a business faces
  this year — and lead with that change, not with the programme.
- **Macro-economy framings.** Interest rates, GDP, national diversification and
  global commodity flows belong in this show only through the specific thing
  they alter for an operator.
- **Generic educational topics.** "What is AI?" explains a definition, not a shift.
- **"Future of X" framings.** "The future of manufacturing" has no mechanism,
  no tension and no date.
- **Company profiles.** The subject is a system, not an organisation.
- **Purely promotional UAE or government stories.** This one is a line, not a
  ban: do not cover the initiative — **decode the bet, and what the initiative
  changes.** If an idea cannot be written without reading as PR, drop it.

## Distinctness for this format

This replaces the sector-spread rule in the shared instructions. Here,
candidates are distinct when they answer **different questions an operator
faces** — not when they sit in different industries. Three ideas may all touch
company finance if one is about raising, one about getting paid, and one about
structuring. Never reach into an unrelated industry just to spread the sectors:
that is how an infrastructure or utilities story ends up in a set meant for
founders.

## format_details fields

Populate `format_details` with:

- `expert_profile` — who the guest is and why they specifically can decode this
  system. Criterion 6: genuine understanding, not adjacency. An operator who has
  done the thing beats a commentator who studies it.
- `interview_thesis` — the single argument the conversation tests. State the
  mechanism being decoded, not the topic area.
- `key_questions` — questions that between them cover all three beats: what is
  happening, why it matters, what happens next. At least one must be the
  question a founder would actually ask out loud.
- `visual_support` — what makes the mechanism legible on screen in five
  minutes: the number, the comparison, the document, the before-and-after. Data
  a viewer can read, not atmosphere.
