# Agent Operating Manual Files

The checked-in manual keeps only current, source-backed agent docs.
The complete current manual is generated from `backend/services/agent_manual.py`.

Current runtime agents:

- `ResearchAgent` — `backend/agents/research.py`
- `AnglesAndHooksAgent` — `backend/agents/angles_and_hooks.py`
- `ChapterWriterAgent` — `backend/agents/chapter_writer.py`
- `ChiefEditorEvaluatorAgent` — `backend/agents/chief_editor_evaluator.py`
- [Scriptwriter Agent](07-scriptwriter-agent.md) — `backend/agents/scriptwriter.py`

Supporting/admin agent:

- [Corpus Builder Agent](12-corpus-builder-agent.md) — `backend/agents/corpus_builder.py`

Shared settings:

- [Important Tuning Settings](01-important-tuning-settings.md)
