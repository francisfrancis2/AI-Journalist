## Important Tuning Settings

**Source file:** `backend/config.py`

These settings control agent model selection, quality thresholds, and retry behavior:

- `claude_opus_model`: high-stakes generation model option.
- `claude_model`: default creative and analytical model used by most agents.
- `claude_haiku_model`: faster model used for lightweight tasks.
- `quality_score_threshold`: pre-script storyline approval threshold.
- `script_audit_score_threshold`: final script quality threshold.
- `max_refinement_cycles`: storyline refinement attempts before scripting.
- `max_script_revision_cycles`: post-script rewrite attempts.
- `max_pipeline_cycles`: full research-to-script restart limit.
- `benchmark_default_rebuild_docs`: target docs per benchmark source; 125 gives a ~500-doc combined corpus.
- `benchmark_corpus_stale_after_days`: corpus freshness threshold.
