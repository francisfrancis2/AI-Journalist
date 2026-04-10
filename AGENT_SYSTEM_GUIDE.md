# AI Journalist Agent System Guide

This document describes how the agent system is wired today, what each agent does, what it reads and writes, and where to make changes safely.

It is based on the current implementation in:

- `backend/graph/journalist_graph.py`
- `backend/graph/state.py`
- `backend/agents/*.py`
- `backend/models/*.py`
- `backend/tools/*.py`
- `backend/api/routes/stories.py`
- `backend/config.py`

## 1. System Overview

The main story pipeline is a LangGraph state machine. A story is created through the Stories API, then processed in the background through these agents:

1. `ResearcherAgent`
2. `AnalystAgent`
3. `StorylineCreatorAgent`
4. `EvaluatorAgent`
5. `BenchmarkAgent` in parallel with evaluator
6. `ScriptwriterAgent`

Primary graph file:

- `backend/graph/journalist_graph.py`

Pipeline entry point:

- `POST /api/v1/stories/` in `backend/api/routes/stories.py`

Background runner:

- `_run_pipeline()` in `backend/api/routes/stories.py`

FastAPI app boot:

- `backend/api/main.py`

## 2. Runtime Flow

### 2.1 Story creation

When the frontend creates a story:

1. A `StoryORM` row is inserted with `status=pending`.
2. FastAPI schedules `_run_pipeline()` as a background task.
3. `_run_pipeline()` creates the initial LangGraph state with `create_initial_state()`.
4. The graph streams node updates.
5. After each node finishes, the story status is updated in the database.
6. At the end, all major artifacts are persisted back to the `stories` table.

Relevant files:

- `backend/api/routes/stories.py`
- `backend/models/story.py`
- `backend/graph/state.py`

### 2.2 Graph routing

Current graph topology:

`researcher -> analyst -> storyline_creator -> evaluator -> scriptwriter`

Conditional routing after evaluation:

- if `approved_for_scripting = True` -> `scriptwriter`
- else if more refinement cycles remain:
  - if `needs_more_research = True` and research iterations remain -> `researcher`
  - otherwise -> `storyline_creator`
- else -> `scriptwriter` with best effort

Important note:

- `route_after_researcher()` always sends the pipeline to `analyst`.
- The graph is compiled once at module import time as `journalist_graph`.

Relevant file:

- `backend/graph/journalist_graph.py`

## 3. Shared State Contract

All graph nodes communicate through `JournalistState`.

Definition:

- `backend/graph/state.py`

Important fields:

- Identity:
  - `story_id`
  - `topic`
  - `tone`
- Research:
  - `research_package`
  - `research_iteration`
- Analysis:
  - `analysis_result`
- Storyline:
  - `storyline_proposals`
  - `selected_storyline`
- Evaluation:
  - `evaluation_report`
  - `benchmark_report`
  - `refinement_cycle`
- Script:
  - `final_script`
  - `script_s3_key`
- Routing flags:
  - `needs_more_research`
  - `approved_for_scripting`
  - `pipeline_complete`
- Error handling:
  - `error`
  - `failed_node`

Safe rule for changes:

- If you change one agent’s output shape, update:
  - the state field type
  - the Pydantic model in `backend/models`
  - the persistence block in `backend/api/routes/stories.py`
  - any downstream agents that consume that field

## 4. Configuration and Setup

Central settings file:

- `backend/config.py`

### 4.1 Models

Current Claude model split:

- `claude_model = "claude-sonnet-4-6"`
  - used by creative/long-form agents:
    - `StorylineCreatorAgent`
    - `ScriptwriterAgent`
- `claude_haiku_model = "claude-haiku-4-5-20251001"`
  - used by faster structured agents:
    - `ResearcherAgent`
    - `AnalystAgent`
    - `EvaluatorAgent`
    - `BenchmarkAgent`

Global generation defaults in settings:

- `claude_max_tokens`
- `claude_temperature`

Note:

- Most agents override token and temperature per class instead of reading those two values directly.

### 4.2 Pipeline controls

Graph control settings:

- `max_research_iterations`
- `max_refinement_cycles`
- `target_script_duration_min`
- `target_script_duration_max`
- `min_sources_required`
- `quality_score_threshold`

Important note:

- `quality_score_threshold` exists in settings, but the evaluator currently hardcodes approval logic at `0.75` through `EvaluationReport.compute_overall()`.
- If you want one source of truth, move that threshold check into config-aware code.

### 4.3 External services

Configured external dependencies:

- Anthropic
- Tavily
- NewsAPI
- Alpha Vantage
- PostgreSQL
- S3-compatible storage
- Playwright
- YouTube API for benchmark corpus building

## 5. Data Models Passed Between Agents

Primary model file:

- `backend/models/research.py`

Main artifacts:

- `ResearchPackage`
  - list of queries issued
  - list of gathered `RawSource` entries
- `AnalysisResult`
  - executive summary
  - key findings
  - angles
  - data gaps
  - quotes
  - controversies
  - financial metrics
- `StorylineProposal`
  - title
  - logline
  - opening hook
  - acts
  - closing statement
  - unique angle
  - target audience
  - tone
- `EvaluationReport`
  - criteria
  - overall score
  - strengths
  - weaknesses
  - improvement suggestions
  - approval flag
- `BenchmarkReport`
  - BI similarity metrics
  - strengths/gaps
  - grade
- `FinalScript`
  - title
  - sections
  - sources
  - metadata

Persistence model:

- `backend/models/story.py`

## 6. Agent-by-Agent Outline

## 6.1 ResearcherAgent

File:

- `backend/agents/researcher.py`

Purpose:

- First graph node.
- Plans research queries.
- Chooses which source families to use.
- Executes source fetches in parallel.
- Scrapes top URLs for fuller article text.
- Produces a `ResearchPackage`.

Model setup:

- Uses `ChatAnthropic`
- Model: `settings.claude_haiku_model`
- Max tokens: `1536`
- Temperature: `0.2`
- Structured output: `ResearchPlan`

Internal output schema:

- `ResearchPlan`
  - `topic_type`
  - `use_sources`
  - `primary_queries`
  - `deep_dive_queries`
  - `financial_symbols`
  - `rss_keyword`

Inputs read from state:

- `topic`

Outputs written to state:

- `research_package`
- `needs_more_research = False`

Graph side effects:

- `research_iteration` is incremented in `researcher_node()` in the graph file, not inside the agent.

Tools used:

- `WebSearchTool` from `backend/tools/web_search.py`
- `NewsAPITool` from `backend/tools/news_api.py`
- `RSSParserTool` from `backend/tools/rss_parser.py`
- `FinancialDataTool` from `backend/tools/financial_data.py`
- `WebScraperTool` from `backend/tools/web_scraper.py`

Execution logic:

1. Plan research with Claude.
2. Build `queries_issued`.
3. Conditionally launch tool calls based on `use_sources`.
4. Gather all tool responses concurrently.
5. Add results into a `ResearchPackage`.
6. Scrape top 5 web-search URLs with Playwright.
7. Return the completed package.

Where to modify behavior:

- Change source routing logic:
  - `_SYSTEM_PROMPT` in `backend/agents/researcher.py`
- Add another source provider:
  - add tool class in `backend/tools`
  - instantiate it in `ResearcherAgent.__init__`
  - branch it into `fetch_tasks`
  - update `SourceType` in `backend/models/research.py`
- Change how many sources or scrapes happen:
  - `plan.primary_queries[:2]`
  - `plan.financial_symbols[:3]`
  - `package.top_sources(5)`

Risks to keep in mind:

- More sources increases cost and latency quickly.
- The scraper opens real browser pages, so it is the slowest and most failure-prone part of research.

## 6.2 AnalystAgent

File:

- `backend/agents/analyst.py`

Purpose:

- Converts raw research into structured editorial analysis.
- This is the bridge between data collection and narrative design.

Model setup:

- Uses `ChatAnthropic`
- Model: `settings.claude_haiku_model`
- Max tokens: `2048`
- Temperature: `0.2`
- Structured output: `AnalysisOutput`

Inputs read from state:

- `research_package`
- `topic`
- `tone`

Outputs written to state:

- `analysis_result`

Execution logic:

1. Builds a compact source digest from top sources.
2. Sends topic, tone, source count, and digest to Claude.
3. Parses the result into `AnalysisResult`.

Important implementation details:

- Source digest is capped by `_MAX_SOURCE_CHARS = 60_000`.
- Only `package.top_sources(20)` are included in the digest.

Where to modify behavior:

- Editorial framing:
  - `_SYSTEM_PROMPT` in `backend/agents/analyst.py`
- How much context the model sees:
  - `_MAX_SOURCE_CHARS`
  - `_build_source_digest()`
- Additional structured outputs:
  - `AnalysisOutput`
  - `AnalysisResult` in `backend/models/research.py`

Good use cases for changes:

- Add entity extraction
- Add timeline extraction
- Add risk analysis
- Add stronger quote validation

## 6.3 StorylineCreatorAgent

File:

- `backend/agents/storyline_creator.py`

Purpose:

- Generates documentary structures from analysis.
- Produces exactly 2 candidate storylines and picks one as the selected storyline.

Model setup:

- Uses `ChatAnthropic`
- Model: `settings.claude_model`
- Max tokens: `4096`
- Temperature: `0.5`
- Structured output: `StorylineCreatorOutput`

Inputs read from state:

- `analysis_result`
- `topic`
- `tone`
- `refinement_cycle`
- optional `evaluation_report` if refining

Outputs written to state:

- `storyline_proposals`
- `selected_storyline`

Execution logic:

1. Builds a prompt from analysis findings, angles, and quotes.
2. If refining, injects evaluation weaknesses and suggestions.
3. Requests 2 proposals.
4. Converts them into `StorylineProposal`.
5. Selects `recommended_proposal_index`.

Important implementation details:

- Duration target is taken from settings and injected into the prompt.
- The selected storyline is not scored here; it is just the model’s own recommendation.

Where to modify behavior:

- Story structure style:
  - `_SYSTEM_PROMPT`
- Number of proposals:
  - prompt text
  - `StorylineCreatorOutput`
  - downstream assumptions
- Act schema:
  - `StoryActOutput`
  - `StoryAct` in `backend/models/research.py`

Good use cases for changes:

- Force more investigative arcs
- Add chapter cards
- Add interview-led structures
- Add region- or audience-specific templates

## 6.4 EvaluatorAgent

File:

- `backend/agents/evaluator.py`

Purpose:

- Editorial gatekeeper before script generation.
- Scores the selected storyline against six criteria.
- Decides if the story is ready for scripting.

Model setup:

- Uses `ChatAnthropic`
- Model: `settings.claude_haiku_model`
- Max tokens: `1500`
- Temperature: `0.1`
- Structured output: `EvaluatorOutput`

Inputs read from state:

- `selected_storyline`
- `analysis_result`
- `research_package`
- `topic`

Outputs written to state:

- `evaluation_report`
- `approved_for_scripting`
- `needs_more_research`

Scoring criteria:

- factual_accuracy
- narrative_coherence
- audience_engagement
- source_diversity
- originality
- production_feasibility

Approval logic:

- `EvaluationCriteria.overall_score` uses weighted averages.
- `EvaluationReport.compute_overall()` marks approval at `>= 0.75`.

Where to modify behavior:

- Evaluation rubric:
  - `_SYSTEM_PROMPT`
  - `EvaluationCriteria` weights in `backend/models/research.py`
- Approval threshold:
  - `EvaluationReport.compute_overall()`
- Research escalation behavior:
  - how `requires_additional_research` is prompted and consumed

Good use cases for changes:

- Tighten readiness threshold
- Make source diversity count more heavily
- Penalize weak hooks more strongly

## 6.5 BenchmarkAgent

File:

- `backend/agents/benchmarker.py`

Purpose:

- Scores the selected storyline against the local BI benchmark library.
- Runs in parallel with `EvaluatorAgent`.
- Produces a separate comparative benchmark report.

Model setup:

- Uses `ChatAnthropic`
- Model: `settings.claude_haiku_model`
- Max tokens: `1500`
- Temperature: `0.1`
- Structured output: `BenchmarkScores`

Inputs read from state:

- `selected_storyline`
- `topic`

Outputs written to state:

- `benchmark_report`

Dependency:

- Requires the benchmark corpus JSON cache to exist at:
  - `settings.bi_pattern_cache_path`

Fallback behavior:

- If no corpus exists, returns `{"benchmark_report": None}` and does not fail the graph.

Execution logic:

1. Load `BIPatternLibrary` from JSON cache.
2. Build a comparison prompt with storyline + corpus stats.
3. Score the storyline against the benchmark criteria.
4. Convert to `BenchmarkReport`.

Benchmark criteria:

- hook_potency
- title_formula_fit
- act_architecture
- data_density
- human_narrative_placement
- tension_release_rhythm
- closing_device

Where to modify behavior:

- Benchmark rubric:
  - `_SYSTEM_PROMPT`
- Weighting:
  - `BenchmarkReport.from_scores()` in `backend/models/benchmark.py`
- Corpus source:
  - `settings.bi_pattern_cache_path`

## 6.6 ScriptwriterAgent

File:

- `backend/agents/scriptwriter.py`

Purpose:

- Final graph node.
- Writes the full documentary script act-by-act.
- Uploads the final script JSON to S3-compatible storage.

Model setup:

- Uses `ChatAnthropic`
- Model: `settings.claude_model`
- Max tokens: `4096`
- Temperature: `0.4`
- Structured output: `ActOutput`

Inputs read from state:

- `selected_storyline`
- `analysis_result`
- `topic`
- `story_id`
- `research_package`
- optional `evaluation_report`

Outputs written to state:

- `final_script`
- `script_s3_key`

Execution logic:

1. For each act in the selected storyline, build an act-specific prompt.
2. Write all acts concurrently using `asyncio.gather`.
3. Build `FinalScript`.
4. Attempt S3 upload.
5. Return the final script and optional S3 key.

Important implementation details:

- Script sections are written independently in parallel.
- The final word count is recomputed from generated narration, not trusted from model output.
- Duration estimate uses `_WORDS_PER_MINUTE = 150`.
- S3 upload failures are logged as warnings and do not fail the story.

Where to modify behavior:

- Voice/style:
  - `_SYSTEM_PROMPT`
- Section payload:
  - `ActOutput`
  - `ScriptSection` / `FinalScript` in `backend/models/story.py`
- Upload behavior:
  - `_upload_to_s3()`

S3 setup details:

- Uses `aioboto3`
- Reads:
  - `aws_access_key_id`
  - `aws_secret_access_key`
  - `aws_region`
  - `s3_endpoint_url`
  - `s3_bucket_scripts`

## 6.7 CorpusBuilderAgent

File:

- `backend/agents/corpus_builder.py`

Purpose:

- Not part of the main per-story graph.
- Builds the benchmark reference corpus used by `BenchmarkAgent`.

How it is intended to run:

- Manual/offline build process
- File comment says:
  - `python -m backend.scripts.build_corpus`

Inputs:

- YouTube channel data
- Video transcripts

Outputs:

- `BIReferenceDocORM` rows
- `BIPatternLibraryORM` row
- JSON cache at `settings.bi_pattern_cache_path`

Model setup:

- Haiku for per-document structure extraction
- Sonnet for cross-corpus synthesis

Main steps:

1. Fetch BI channel videos via `YouTubeFetcher`
2. Skip existing videos already in DB
3. Fetch transcripts
4. Extract document structure for each transcript
5. Save raw benchmark docs
6. Synthesize corpus-wide patterns
7. Save DB row + JSON cache

Why it matters:

- If this corpus is stale or missing, benchmark scoring is weak or absent.

## 7. Tool Layer

These are not graph nodes, but they are part of the agent system.

### 7.1 WebSearchTool

File:

- `backend/tools/web_search.py`

Purpose:

- Tavily-backed web search
- Returns `RawSource` objects
- Includes simple domain-based credibility inference

Key methods:

- `search()`
- `multi_search()`

### 7.2 NewsAPITool

File:

- `backend/tools/news_api.py`

Purpose:

- Recent-news retrieval from NewsAPI

Key methods:

- `search_everything()`
- `top_headlines()`

### 7.3 RSSParserTool

File:

- `backend/tools/rss_parser.py`

Purpose:

- Polls curated RSS feeds and converts entries to `RawSource`

Key method:

- `fetch_all_default_feeds()`

### 7.4 FinancialDataTool

File:

- `backend/tools/financial_data.py`

Purpose:

- Fetches company overview, prices, earnings, and ticker search from Alpha Vantage

Key methods:

- `get_company_overview()`
- `get_daily_prices()`
- `get_earnings()`
- `search_ticker()`

### 7.5 WebScraperTool

File:

- `backend/tools/web_scraper.py`

Purpose:

- Uses Playwright to render and scrape article pages

Key methods:

- `scrape()`
- `scrape_many()`

### 7.6 YouTubeFetcher

Referenced from:

- `backend/agents/corpus_builder.py`
- implementation file:
  - `backend/tools/youtube_fetcher.py`

Purpose:

- Supplies videos and transcripts for the benchmark corpus build flow

## 8. Persistence Map

Final persistence happens in:

- `backend/api/routes/stories.py`

Fields written back to `StoryORM`:

- `status`
- `script_data`
- `script_s3_key`
- `quality_score`
- `word_count`
- `estimated_duration_minutes`
- `research_data`
- `analysis_data`
- `storyline_data`
- `evaluation_data`
- `iteration_count`
- `error_message`
- `benchmark_data`
- `title` if the script exists

If you add a new artifact:

1. add it to `JournalistState`
2. add its schema/model
3. write it in the pipeline final persistence block
4. expose it in `StoryRead` if the frontend needs it

## 9. API Entry Points Relevant to Agents

Main production endpoints:

- `POST /api/v1/stories/`
- `GET /api/v1/stories/`
- `GET /api/v1/stories/{story_id}`
- `GET /api/v1/stories/{story_id}/script`

Tool-testing endpoints:

- `POST /api/v1/research/web-search`
- `POST /api/v1/research/news`
- `GET /api/v1/research/news/headlines`
- `POST /api/v1/research/financial/overview`
- `POST /api/v1/research/financial/prices`
- `GET /api/v1/research/financial/search`
- `GET /api/v1/research/rss/fetch`
- `GET /api/v1/research/rss/defaults`

These are defined in:

- `backend/api/routes/research.py`

## 10. How to Change the System Safely

### 10.1 Change the model used by one agent

Edit the agent constructor in the relevant file:

- `backend/agents/researcher.py`
- `backend/agents/analyst.py`
- `backend/agents/storyline_creator.py`
- `backend/agents/evaluator.py`
- `backend/agents/benchmarker.py`
- `backend/agents/scriptwriter.py`

### 10.2 Add a new graph node

You need to update:

1. `backend/graph/state.py`
2. `backend/graph/journalist_graph.py`
3. `_NODE_STATUS_MAP` in `backend/api/routes/stories.py`
4. `StoryStatus` in `backend/models/story.py`
5. frontend status UI if you surface the new phase

### 10.3 Change routing rules

Update:

- `route_after_evaluator()` in `backend/graph/journalist_graph.py`
- optionally `route_after_researcher()`

### 10.4 Add another research source

Update:

1. `backend/models/research.py`
   - `SourceType`
2. add tool in `backend/tools`
3. wire it into `ResearcherAgent`
4. update any prompts that mention source families

### 10.5 Change approval threshold

Current effective threshold is in:

- `backend/models/research.py`
  - `EvaluationReport.compute_overall()`

If you want config-driven behavior, use:

- `backend/config.py`
  - `quality_score_threshold`

### 10.6 Change what is stored on each story

Update:

1. `StoryORM` in `backend/models/story.py`
2. response schema in `backend/models/story.py`
3. final persistence in `backend/api/routes/stories.py`
4. migrations if schema changes require DB changes

## 11. Practical Change Checklist

When editing any agent:

1. Check its input fields in `JournalistState`
2. Check its output schema in `backend/models`
3. Check downstream consumers
4. Check final persistence in `backend/api/routes/stories.py`
5. Check frontend expectations if the API response shape changes

When editing prompts:

1. Keep structured output schema aligned with the prompt
2. Avoid adding required fields without updating the Pydantic models
3. Re-check routing if flags like `needs_more_research` or `approved_for_scripting` can change semantics

## 12. Recommended Next Improvements

If you plan to iterate on the system, these are high-leverage changes:

- Make `quality_score_threshold` actually control evaluator approval
- Add per-agent latency and token usage logging
- Add source-count minimum enforcement before storylining
- Add explicit quote verification before script generation
- Add a timeline artifact in the analyst stage
- Add retries or fallbacks for S3 and Playwright-heavy steps
- Add snapshot tests for graph state transitions

## 13. Quick File Index

- App config:
  - `backend/config.py`
- FastAPI app:
  - `backend/api/main.py`
- Story pipeline API:
  - `backend/api/routes/stories.py`
- Tool testing API:
  - `backend/api/routes/research.py`
- Graph:
  - `backend/graph/journalist_graph.py`
  - `backend/graph/state.py`
- Agents:
  - `backend/agents/researcher.py`
  - `backend/agents/analyst.py`
  - `backend/agents/storyline_creator.py`
  - `backend/agents/evaluator.py`
  - `backend/agents/benchmarker.py`
  - `backend/agents/scriptwriter.py`
  - `backend/agents/corpus_builder.py`
- Schemas:
  - `backend/models/research.py`
  - `backend/models/benchmark.py`
  - `backend/models/story.py`
- Tools:
  - `backend/tools/web_search.py`
  - `backend/tools/news_api.py`
  - `backend/tools/rss_parser.py`
  - `backend/tools/financial_data.py`
  - `backend/tools/web_scraper.py`
  - `backend/tools/youtube_fetcher.py`
