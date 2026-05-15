# Editable Agent Prompts

These Markdown files are the system prompts used by the AI Journalist agents.

Edit the relevant `.md` file to change an agent's instructions. The backend reads
the file when the agent calls the model, so local development picks up prompt
changes on the next run.

For deployed Fly apps, commit the prompt changes and redeploy the backend so the
container includes the updated files.

Prompt files with placeholders use Python `str.format` syntax:

- `benchmarker.md`: `{doc_count}`, `{avg_act_count}`, `{avg_act_duration_seconds}`, `{avg_stat_count}`, `{human_story_act_avg}`
- `corpus_builder_synthesise.md`: `{channel_label}`

Do not put secrets, API keys, database URLs, or passwords in prompt files.
