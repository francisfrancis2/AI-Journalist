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
    BIReferenceDocORM,
    BIPatternLibraryORM,
    LibraryKnowledgeCard,
    LibraryKnowledgeCardORM,
    LibraryReferenceCard,
    LibraryReferencePack,
)
from backend.models.notification import AdminNotificationORM, AdminNotificationRead
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
from backend.models.user import (
    ChangePasswordRequest,
    LoginRequest,
    Token,
    UserCreate,
    UserORM,
    UserRead,
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
    "BIReferenceDocORM",
    "BIPatternLibraryORM",
    "LibraryKnowledgeCard",
    "LibraryKnowledgeCardORM",
    "LibraryReferenceCard",
    "LibraryReferencePack",
    # notifications
    "AdminNotificationORM",
    "AdminNotificationRead",
    # research sessions
    "ResearchSessionORM",
    "ResearchSessionStatus",
    "ResearchSessionCreate",
    "ResearchSessionTurnCreate",
    "ResearchSessionRead",
    "ResearchSessionListItem",
    "ResearchSessionCitation",
    "ResearchSessionTurn",
    # users
    "UserORM",
    "UserCreate",
    "UserRead",
    "LoginRequest",
    "ChangePasswordRequest",
    "Token",
]
