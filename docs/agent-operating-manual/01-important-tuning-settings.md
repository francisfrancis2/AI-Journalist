## Important Tuning Settings

**Source file:** `backend/config.py`

These settings control agent model selection, quality thresholds, and retry behavior:

- `claude_opus_model`: high-stakes generation model option.
- `claude_model`: default creative and analytical model used by most agents.
- `claude_haiku_model`: faster model used for lightweight tasks, including Research Hub report consolidation and follow-ups.
- `quality_score_threshold`: pre-script storyline approval threshold.
- `script_audit_score_threshold`: final script quality threshold.
- `max_refinement_cycles`: storyline refinement attempts before scripting.
- `max_script_revision_cycles`: post-script rewrite attempts.
- `max_pipeline_cycles`: full research-to-script restart limit.
- `anthropic_deep_research_max_uses`: product-wide deep-research ceiling; set to 2 and enforced again by the provider tool.
- `idea_generator_total_timeout_seconds`: run-wide Idea Generator deadline, 300s. This single bound wraps research, synthesis, repair and persistence, so it is the five-minute ceiling rather than one phase's limit.
- `idea_generator_research_timeout_seconds` / `idea_generator_synthesis_timeout_seconds` / `idea_generator_repair_timeout_seconds`: nominal phase budgets. Each is clamped at run time to the time left before the ceiling, so they can be generous without putting the ceiling at risk.
- `idea_generator_persist_reserve_seconds`: time held back from the phase budgets so writing ideas to the database is never the step that breaches the ceiling.
- `idea_generator_candidate_count`: candidates synthesised before validation, 5. **This is the main latency lever** — synthesis time tracks output tokens almost linearly. Measured 2026-10-08: 5 candidates ≈ 154s, 6 ≈ 203s.
- `idea_generator_synthesis_max_tokens` / `idea_generator_repair_max_tokens`: bound both worst-case cost and synthesis latency. Setting these too low truncates the structured response mid-object and fails the parse.
- `idea_generator_max_cost_usd`: hard spend ceiling per run, $1.00. Enforced pre-flight by `backend/services/cost_ledger.py`: a phase is refused before it runs when its worst case will not fit what is left. Synthesis first steps its evidence digest down (40/650 → 30/450 → 20/320) and only refuses if even the smallest would breach. Measured spend for a full run is ~$0.58, of which agentic web search is the largest share — `anthropic_search_max_uses_per_query` is the lever there, not the synthesis payload.
- `benchmark_default_rebuild_docs`: target docs per benchmark source; 125 gives a ~500-doc combined corpus.
- `benchmark_corpus_stale_after_days`: corpus freshness threshold.
