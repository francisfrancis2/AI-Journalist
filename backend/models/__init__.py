"""Pydantic and ORM models for the AI Journalist application."""

from backend.models.research import (
    AnalysisResult,
    EvaluationCriteria,
    EvaluationReport,
    KeyFinding,
    RawSource,
    ResearchPackage,
    ResearchQuery,
    SourceCredibility,
    SourceType,
    StoryAct,
    StorylineProposal,
)
from backend.models.story import (
    BenchmarkComparison,
    FinalScript,
    IdeationStage,
    ScriptSection,
    ScriptAuditCriteria,
    ScriptAuditReport,
    ScriptSectionAudit,
    StoryCreate,
    StoryListItem,
    StoryORM,
    StoryRead,
    StoryStatus,
    StoryTone,
)
from backend.models.benchmark import (
    LibraryKnowledgeCard,
    LibraryKnowledgeCardORM,
    LibraryReferenceCard,
    LibraryReferencePack,
)
from backend.models.research_session import (
    ResearchSessionCitation,
    ResearchSessionCreate,
    ResearchSessionListItem,
    ResearchSessionORM,
    ResearchSessionRead,
    ResearchSessionStatus,
    ResearchSessionTurn,
    ResearchSessionTurnCreate,
)

__all__ = [
    # research
    "SourceType",
    "SourceCredibility",
    "RawSource",
    "ResearchQuery",
    "ResearchPackage",
    "KeyFinding",
    "AnalysisResult",
    "StoryAct",
    "StorylineProposal",
    "EvaluationCriteria",
    "EvaluationReport",
    # story
    "StoryStatus",
    "StoryTone",
    "IdeationStage",
    "StoryORM",
    "StoryCreate",
    "StoryRead",
    "StoryListItem",
    "ScriptSection",
    "FinalScript",
    "ScriptAuditCriteria",
    "ScriptSectionAudit",
    "BenchmarkComparison",
    "ScriptAuditReport",
    # library knowledge
    "LibraryKnowledgeCard",
    "LibraryKnowledgeCardORM",
    "LibraryReferenceCard",
    "LibraryReferencePack",
    # research sessions
    "ResearchSessionORM",
    "ResearchSessionStatus",
    "ResearchSessionCreate",
    "ResearchSessionTurnCreate",
    "ResearchSessionRead",
    "ResearchSessionListItem",
    "ResearchSessionCitation",
    "ResearchSessionTurn",
]
