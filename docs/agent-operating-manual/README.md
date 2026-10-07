# Agent Operating Manual

One file per runtime agent. Each is **generated from the source** by
`backend/services/agent_manual.py` (AST extraction of classes, model config,
structured outputs, method signatures and the editable prompt files), so the
manual cannot drift from the code the way a hand-written doc would.

Regenerate after changing an agent — the files are a snapshot, not live.

## Pipeline agents

The seven LangGraph nodes, in execution order (`backend/graph/journalist_graph.py`):

| # | Agent | Source |
|---|---|---|
| 03 | [Research Agent](03-research-agent.md) | `backend/agents/research.py` |
| 04 | [Angles & Hooks Agent](04-angles-and-hooks-agent.md) | `backend/agents/angles_and_hooks.py` |
| 05 | [Chapter Writer Agent](05-chapter-writer-agent.md) | `backend/agents/chapter_writer.py` |
| 06 | [Chief Editor & Evaluator Agent](06-chief-editor-and-evaluator-agent.md) | `backend/agents/chief_editor_evaluator.py` |
| 07 | [Scriptwriter Agent](07-scriptwriter-agent.md) | `backend/agents/scriptwriter.py` |

The Chief Editor also owns the post-script **audit** and **rewrite** nodes, via
`ScriptAuditSkill` and `ScriptRewriteSkill`. Each pipeline agent pairs a cheap
structuring call with a more capable reasoning call — the `*Skill` classes are
that second half, which is why they are documented with their parent rather
than separately.

## Standalone agents

Outside the graph, but runtime agents all the same:

| # | Agent | Source |
|---|---|---|
| 12 | [Corpus Builder Agent](12-corpus-builder-agent.md) | `backend/agents/corpus_builder.py` |
| 13 | [Idea Generator Agent](13-idea-generator-agent.md) | `backend/agents/idea_generator.py` |
| 14 | [Research Report Synthesizer](14-research-report-synthesizer.md) | `backend/services/research_report.py` |

## Shared

- [Important Tuning Settings](01-important-tuning-settings.md) — model choices,
  loop budgets and caps that apply across agents.

## Regenerating

```python
from backend.services.agent_manual import build_agent_manual_markdown
```

`_AGENT_SOURCES` in `agent_manual.py` is the registry. An agent missing from it
is missing from the manual — which is how the Idea Generator and the Research
Report Synthesizer went undocumented until now.
