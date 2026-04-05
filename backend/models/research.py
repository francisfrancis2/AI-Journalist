"""
Pydantic models that represent intermediate research and analysis artefacts
flowing through the LangGraph pipeline.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl


# ── Source Types ──────────────────────────────────────────────────────────────

class SourceType(str, Enum):
    WEB_SEARCH = "web_search"
    WEB_SCRAPE = "web_scrape"
    NEWS_API = "news_api"
    FINANCIAL_DATA = "financial_data"
    RSS_FEED = "rss_feed"


class SourceCredibility(str, Enum):
    HIGH = "high"       # Reuters, Bloomberg, AP, academic papers
    MEDIUM = "medium"   # Established outlets, company press releases
    LOW = "low"         # Blogs, unknown sources


# ── Raw Source ────────────────────────────────────────────────────────────────

class RawSource(BaseModel):
    """A single piece of information gathered from any data source."""
    source_type: SourceType
    url: Optional[str] = None
    title: str
    content: str
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    credibility: SourceCredibility = SourceCredibility.MEDIUM
    relevance_score: float = Field(0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Research Package ──────────────────────────────────────────────────────────

class ResearchQuery(BaseModel):
    """A structured query issued by the Researcher agent."""
    query_text: str
    sub_queries: list[str] = Field(default_factory=list)
    target_source_types: list[SourceType] = Field(
        default_factory=lambda: [SourceType.WEB_SEARCH, SourceType.NEWS_API]
    )
    time_range_days: Optional[int] = None  # None = no restriction


class ResearchPackage(BaseModel):
    """All raw data collected for a topic during the research phase."""
    topic: str
    queries_issued: list[ResearchQuery] = Field(default_factory=list)
    sources: list[RawSource] = Field(default_factory=list)
    total_sources: int = 0
    research_duration_seconds: float = 0.0

    def add_source(self, source: RawSource) -> None:
        self.sources.append(source)
        self.total_sources = len(self.sources)

    def top_sources(self, n: int = 10) -> list[RawSource]:
        return sorted(self.sources, key=lambda s: s.relevance_score, reverse=True)[:n]


# ── Analysis ──────────────────────────────────────────────────────────────────

class KeyFinding(BaseModel):
    """A single verified fact or insight extracted from raw sources."""
    claim: str
    supporting_sources: list[str] = Field(default_factory=list)  # source URLs / titles
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    category: str = "general"  # e.g. "financial", "human_interest", "trend"


class AnalysisResult(BaseModel):
    """Structured analysis produced by the Analyst agent."""
    topic: str
    executive_summary: str
    key_findings: list[KeyFinding]
    narrative_angles: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    recommended_tone: str = "explanatory"
    controversies: list[str] = Field(default_factory=list)
    notable_quotes: list[dict[str, str]] = Field(default_factory=list)  # [{quote, speaker, source}]
    financial_metrics: Optional[dict[str, Any]] = None


# ── Storyline ─────────────────────────────────────────────────────────────────

class StoryAct(BaseModel):
    """One structural act within the documentary storyline."""
    act_number: int
    act_title: str
    purpose: str  # e.g. "Establish the problem", "Present evidence", "Resolution"
    key_points: list[str]
    estimated_duration_seconds: int = 120
    required_visuals: list[str] = Field(default_factory=list)


class StorylineProposal(BaseModel):
    """A documentary storyline proposal created by the Storyline Creator agent."""
    title: str
    logline: str                    # One-sentence pitch
    opening_hook: str               # First 30 seconds concept
    acts: list[StoryAct]
    closing_statement: str
    unique_angle: str               # What makes this story different
    target_audience: str
    tone: str
    total_estimated_duration_seconds: int = 0

    def compute_duration(self) -> None:
        self.total_estimated_duration_seconds = sum(a.estimated_duration_seconds for a in self.acts)


# ── Evaluation ────────────────────────────────────────────────────────────────

class EvaluationCriteria(BaseModel):
    """Scores (0–1) across editorial dimensions."""
    factual_accuracy: float = Field(0.0, ge=0.0, le=1.0)
    narrative_coherence: float = Field(0.0, ge=0.0, le=1.0)
    audience_engagement: float = Field(0.0, ge=0.0, le=1.0)
    source_diversity: float = Field(0.0, ge=0.0, le=1.0)
    originality: float = Field(0.0, ge=0.0, le=1.0)
    production_feasibility: float = Field(0.0, ge=0.0, le=1.0)

    @property
    def overall_score(self) -> float:
        weights = {
            "factual_accuracy": 0.25,
            "narrative_coherence": 0.20,
            "audience_engagement": 0.20,
            "source_diversity": 0.15,
            "originality": 0.10,
            "production_feasibility": 0.10,
        }
        return sum(
            getattr(self, field) * weight for field, weight in weights.items()
        )


class EvaluationReport(BaseModel):
    """Full evaluation output from the Evaluator agent."""
    criteria: EvaluationCriteria
    overall_score: float = 0.0
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    approved_for_scripting: bool = False
    requires_additional_research: bool = False
    evaluator_notes: str = ""

    def compute_overall(self) -> None:
        self.overall_score = self.criteria.overall_score
        self.approved_for_scripting = self.overall_score >= 0.75
