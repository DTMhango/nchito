"""SQLAlchemy models, one module per aggregate. Importing this package registers every table."""

from app.models.applications import (
    AgentTask,
    Application,
    ApplicationEvent,
    ApplicationPacket,
    Contact,
    DispatchAttempt,
    InterviewPack,
    InterviewRound,
    MailThread,
    PendingAction,
    PortalAccount,
    SubmitPermit,
)
from app.models.base import Base
from app.models.bulk import BulkItem, BulkOperation, EmployerPolicy
from app.models.calendar import CalendarFeed, InterviewEvent
from app.models.changes import JobChange, JobVersion, JobWatch
from app.models.documents import ApplicationDocument
from app.models.followups import FollowupDue, OutboundMessage, WindDown
from app.models.kit import (
    Answer,
    Experience,
    Fact,
    Guardrail,
    GuardrailWaiver,
    Person,
    Prompt,
    Reference,
    Skill,
    Template,
    Track,
    VaultDocument,
)
from app.models.platform import (
    ApiToken,
    AuditEvent,
    AuthSession,
    ConfigRevision,
    Connection,
    LedgerEntry,
    LlmPrice,
    LoginAttempt,
    Notification,
    Owner,
    Setting,
    SettingRevision,
    Theme,
    ThemeRevision,
    WorkerHeartbeat,
)
from app.models.preferences import PreferenceFeedback, PreferenceSuggestion
from app.models.search import (
    Assessment,
    Campaign,
    CustomFacet,
    EmployerAlias,
    Job,
    JobSighting,
    PayEstimate,
    Rubric,
    Run,
    SavedView,
    Schedule,
    SkillAlias,
    Source,
    TagRule,
    TrustedSite,
    WatchedEmployer,
)

__all__ = [
    "AgentTask", "Answer", "ApiToken", "Application", "ApplicationDocument", "ApplicationEvent",
    "ApplicationPacket", "Assessment", "AuditEvent", "AuthSession", "Base", "BulkItem", "BulkOperation",
    "CalendarFeed", "Campaign", "ConfigRevision", "Connection", "Contact", "CustomFacet", "DispatchAttempt",
    "EmployerAlias", "EmployerPolicy", "Experience", "Fact", "FollowupDue", "Guardrail", "GuardrailWaiver",
    "InterviewEvent", "InterviewPack", "InterviewRound", "Job", "JobChange", "JobSighting", "JobVersion",
    "JobWatch", "LedgerEntry", "LlmPrice", "LoginAttempt", "MailThread", "Notification", "OutboundMessage", "Owner",
    "PayEstimate", "PendingAction", "Person", "PortalAccount", "PreferenceFeedback", "PreferenceSuggestion",
    "Prompt", "Reference", "Rubric", "Run", "SavedView", "Schedule", "Setting", "SettingRevision", "Skill",
    "SkillAlias", "Source", "SubmitPermit", "TagRule", "Template", "Theme", "ThemeRevision", "Track", "TrustedSite",
    "VaultDocument", "WatchedEmployer", "WindDown", "WorkerHeartbeat",
]
