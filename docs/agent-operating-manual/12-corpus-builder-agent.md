## Corpus Builder Agent

**Source file:** `backend/agents/corpus_builder.py`

### Responsibilities

CorpusBuilderAgent — one-time agent that builds benchmark reference corpora.

Run manually via:
    python -m backend.scripts.build_corpus

Workflow:
  1. Fetch reference documentaries from YouTube (metadata + transcripts)
  2. Extract structural features from each transcript using Claude Haiku
  3. Synthesise cross-corpus patterns using Claude Sonnet
  4. Write pattern library to DB + local JSON cache

### Agent Classes

- `CorpusBuilderAgent`

### Model Configuration

- `ChatAnthropic(model=settings.claude_model, max_tokens=1024, temperature=0.1)`
- `ChatAnthropic(model=settings.claude_model, max_tokens=2048, temperature=0.1)`

### Structured Outputs

- `DocStructure`
- `_PatternSynthesisOutput`

### Main Methods

- `InsufficientBenchmarkCorpusError.def __init__(self, *, library_key: str, have: int, need: int, fetched_videos: int=0, new_videos: int=0, missing_transcripts: int=0, extraction_failures: int=0)`
- `_PatternSynthesisOutput.def _coerce_str_to_list(cls, v: object)`
- `CorpusBuilderAgent.def __init__(self, db: AsyncSession)`
- `CorpusBuilderAgent.async def _extract_structure(self, title: str, transcript: str)`
- `CorpusBuilderAgent.async def _synthesise_patterns(self, docs: list[BIReferenceDocORM], structures: list[DocStructure], titles: list[str], channel_label: str='Business Insider')`
- `CorpusBuilderAgent.async def _get_next_version(self, library_key: str)`
- `CorpusBuilderAgent.async def _save_library(self, library: BIPatternLibrary, library_key: str)`
- `CorpusBuilderAgent.def _structure_from_doc(doc: BIReferenceDocORM)`
- `CorpusBuilderAgent.async def refresh_latest_fraction(self, max_docs: int=50, library_key: str='bi', channel_label: str='Business Insider', channel_identifier: Optional[str]=None, refresh_fraction: float=0.25)`
- `CorpusBuilderAgent.async def build(self, max_docs: int=125, library_key: str='bi', channel_label: str='Business Insider', channel_identifier: Optional[str]=None)`

### Editable Prompt Files

**Prompt file:** `backend/prompts/corpus_builder_extract.md`

```markdown
You are a documentary structure analyst. Given a YouTube documentary transcript,
extract its structural features. Be precise and data-driven.
```

**Prompt file:** `backend/prompts/corpus_builder_synthesise.md`

```markdown
You are a documentary research analyst. Given structural data from multiple
{channel_label} YouTube documentaries, synthesise the common patterns that make them successful.
Focus on patterns that are consistent across the corpus and actionable for scoring new storylines.
```

### Output Schemas

```python
class _PatternSynthesisOutput(BaseModel):
    avg_act_count: float
    avg_act_duration_seconds: float
    hook_type_distribution: dict[str, float]
    title_formula_distribution: dict[str, float]
    closing_device_distribution: dict[str, float]
    avg_stat_count: float
    avg_rhetorical_questions: float
    human_story_act_avg: float
    sample_hooks: list[str] = Field(max_length=5)
    key_observations: list[str]

    @field_validator("sample_hooks", "key_observations", mode="before")
    @classmethod
    def _coerce_str_to_list(cls, v: object) -> object:
        if isinstance(v, str):
            return [v]
        return v
```

### Run Logic

This file contains longer corpus-build helper flows. Review the source file for full implementation details.
