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
]
