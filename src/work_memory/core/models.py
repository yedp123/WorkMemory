"""Pure Python domain models using UUIDv7 identifiers and UTC timestamps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from work_memory.core.ids import new_id, utc_now_iso

ProjectStatus = Literal["ongoing", "completed"]
CoverStyle = Literal["c1", "c2", "c3", "c4", "c5", "c6"]
ObservedEventType = Literal["created", "modified", "renamed", "moved", "deleted"]
AttachmentKind = Literal["screenshot", "annotated_screenshot", "audio", "image"]
AudioRetention = Literal["both", "text", "audio"]
CalendarEventStatus = Literal["scheduled", "completed", "cancelled"]

_PROJECT_STATUSES = ("ongoing", "completed")
_COVER_STYLES = ("c1", "c2", "c3", "c4", "c5", "c6")
_OBSERVED_EVENT_TYPES = ("created", "modified", "renamed", "moved", "deleted")
_ATTACHMENT_KINDS = ("screenshot", "annotated_screenshot", "audio", "image")
_AUDIO_RETENTIONS = ("both", "text", "audio")
_CALENDAR_STATUSES = ("scheduled", "completed", "cancelled")


@dataclass(slots=True)
class Workspace:
    """A user-registered root directory observed strictly read-only."""

    name: str
    root_path: str
    id: str = field(default_factory=new_id)
    is_active: bool = True
    last_scan_utc: str | None = None
    created_at_utc: str = field(default_factory=utc_now_iso)
    updated_at_utc: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class BaselineEntry:
    """Read-only file metadata snapshot used for baseline and restart reconciliation."""

    workspace_id: str
    rel_path: str
    file_size: int
    mtime_ns: int
    file_id: int = 0
    updated_at_utc: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class Project:
    """An explicitly registered project folder within a monitored workspace."""

    workspace_id: str
    name: str
    rel_path: str
    id: str = field(default_factory=new_id)
    description: str = ""
    status: ProjectStatus = "ongoing"
    cover_style: CoverStyle = "c1"
    cover_image_path: str | None = None
    root_rel_path: str = ""
    abs_path: str = ""
    last_known_state: str = ""
    summary_custom: str | None = None
    summary_generated: str | None = None
    summary_updated_utc: str | None = None
    last_activity_utc: str | None = None
    is_pinned: bool = False
    created_at_utc: str = field(default_factory=utc_now_iso)
    updated_at_utc: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.status not in _PROJECT_STATUSES:
            raise ValueError(f"Invalid project status: {self.status!r}")
        if self.cover_style not in _COVER_STYLES:
            raise ValueError(f"Invalid cover style: {self.cover_style!r}")
        if not self.root_rel_path and self.rel_path:
            self.root_rel_path = self.rel_path
        elif not self.rel_path and self.root_rel_path:
            self.rel_path = self.root_rel_path


@dataclass(frozen=True, slots=True)
class ProjectSuggestion:
    """A candidate project folder discovered during read-only workspace scanning."""

    workspace_id: str
    name: str
    rel_path: str
    abs_path: str
    score: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DismissedSuggestion:
    """Persisted record of a user-dismissed project discovery suggestion."""

    workspace_id: str
    rel_path: str
    dismissed_at_utc: str


@dataclass(slots=True)
class ObservedEvent:
    """A normalized filesystem activity record stored separately from user captures."""

    workspace_id: str
    rel_path: str
    event_type: ObservedEventType
    occurred_at_utc: str
    id: str = field(default_factory=new_id)
    project_id: str | None = None
    old_rel_path: str | None = None
    file_size: int | None = None
    is_baseline: bool = False
    is_milestone: bool = False
    group_key: str | None = None
    created_at_utc: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.event_type not in _OBSERVED_EVENT_TYPES:
            raise ValueError(f"Invalid observed event type: {self.event_type!r}")


@dataclass(slots=True)
class CaptureEntry:
    """A user-authored memory entry (note, transcript, and linked attachments)."""

    id: str = field(default_factory=new_id)
    project_id: str | None = None
    rel_path: str | None = None
    note_text: str = ""
    transcript_text: str = ""
    transcription: str | None = None
    audio_retention: str = "both"
    is_milestone: bool = False
    captured_at_utc: str = field(default_factory=utc_now_iso)
    created_at_utc: str = field(default_factory=utc_now_iso)
    updated_at_utc: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.audio_retention not in _AUDIO_RETENTIONS:
            raise ValueError(f"Invalid audio retention mode: {self.audio_retention!r}")
        if self.transcription is None and self.transcript_text:
            self.transcription = self.transcript_text
        elif not self.transcript_text and self.transcription:
            self.transcript_text = self.transcription


@dataclass(slots=True)
class Attachment:
    """An app-owned screenshot, annotated copy, image, or voice recording."""

    capture_entry_id: str
    kind: AttachmentKind
    stored_rel_path: str
    id: str = field(default_factory=new_id)
    original_attachment_id: str | None = None
    mime_type: str = ""
    byte_size: int = 0
    sha256: str = ""
    created_at_utc: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.kind not in _ATTACHMENT_KINDS:
            raise ValueError(f"Invalid attachment kind: {self.kind!r}")


@dataclass(slots=True)
class CalendarEvent:
    """A planned event or reminder stored separately from historical activity."""

    title: str
    starts_at_utc: str = ""
    id: str = field(default_factory=new_id)
    project_id: str | None = None
    description: str = ""
    event_at_utc: str = ""
    reminder_minutes: int | None = 10
    status: CalendarEventStatus = "scheduled"
    remind_at_utc: str | None = None
    notified_at_utc: str | None = None
    created_at_utc: str = field(default_factory=utc_now_iso)
    updated_at_utc: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.status not in _CALENDAR_STATUSES:
            raise ValueError(f"Invalid calendar event status: {self.status!r}")
        if not self.event_at_utc and self.starts_at_utc:
            self.event_at_utc = self.starts_at_utc
        elif not self.starts_at_utc and self.event_at_utc:
            self.starts_at_utc = self.event_at_utc
        if not self.event_at_utc:
            raise ValueError("CalendarEvent requires event_at_utc or starts_at_utc.")


@dataclass(frozen=True, slots=True)
class DayMarkers:
    """Per-day activity indicators distinguishing observed, captured, and planned records."""

    has_observed: bool = False
    has_captures: bool = False
    has_events: bool = False

    @property
    def has_any(self) -> bool:
        """Return ``True`` when at least one category has activity on this day."""
        return self.has_observed or self.has_captures or self.has_events


@dataclass(frozen=True, slots=True)
class ObservedGroup:
    """A cohesive batch of observed file changes grouped by project and short time window."""

    project_id: str | None
    project_name: str
    occurred_at_utc: str
    local_date_label: str
    local_time_label: str
    events: tuple[ObservedEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class DayTimeline:
    """Unified query-time view keeping observed, captured, and planned records distinct."""

    local_date: date | None
    observed_groups: tuple[ObservedGroup, ...] = ()
    captures: tuple[CaptureEntry, ...] = ()
    scheduled_events: tuple[CalendarEvent, ...] = ()
    project_names: dict[str, str] = field(default_factory=dict)
    capture_attachments: dict[str, tuple[Attachment, ...]] = field(default_factory=dict)
    attachments_dir: str = ""

    @property
    def is_empty(self) -> bool:
        """Return ``True`` when all three categories are empty."""
        return not (self.observed_groups or self.captures or self.scheduled_events)


@dataclass(frozen=True, slots=True)
class SearchResults:
    """Structured search results across projects, observed files, notes, and events."""

    query: str
    projects: tuple[Project, ...] = ()
    observed_events: tuple[ObservedEvent, ...] = ()
    captures: tuple[CaptureEntry, ...] = ()
    calendar_events: tuple[CalendarEvent, ...] = ()
    timeline: DayTimeline | None = None


@dataclass(frozen=True, slots=True)
class MilestoneItem:
    """A user-starred observed event or capture entry surfaced at the top of a project."""

    item_id: str
    item_type: Literal["observed", "capture"]
    project_id: str
    timestamp_utc: str
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class MilestoneDetail:
    """Full detail payload for inspecting a starred observed event or capture entry."""

    item_id: str
    item_type: Literal["observed", "capture"]
    project_id: str | None
    project_name: str
    timestamp_utc: str
    local_date: date
    local_time_label: str
    title: str
    body_text: str
    rel_path: str | None = None
    event_type: str | None = None
    old_rel_path: str | None = None
    file_size: int | None = None
    attachments: tuple[Attachment, ...] = ()
    attachments_dir: str = ""
    transcription: str | None = None
    audio_retention: str = "both"
    is_milestone: bool = True


@dataclass(frozen=True, slots=True)
class SummaryReference:
    """Clickable entry-point linking a summary item back to an original record or date."""

    label: str
    item_type: Literal["capture", "observed", "date"]
    item_id: str | None = None
    local_date: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectSummaryView:
    """Structured Last Known State and recent activity summary for one project."""

    project_id: str
    confirmed_text: str
    inferred_text: str
    custom_text: str | None
    recent_summary: str
    references: list[SummaryReference] = field(default_factory=list)
    updated_utc: str = ""


@dataclass(frozen=True, slots=True)
class ManifestPreview:
    """Summary metadata read from a portable ``.wmem`` bundle before import."""

    schema_version: str
    exported_at_utc: str
    project_id: str
    project_name: str
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Outcome of importing a portable ``.wmem`` project bundle."""

    project_id: str
    imported_counts: dict[str, int] = field(default_factory=dict)
    missing_files: list[str] = field(default_factory=list)
    skipped: bool = False


