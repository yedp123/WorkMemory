"""Core protocol interfaces for pluggable local services and providers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from work_memory.core.models import (
    CalendarEvent,
    CaptureEntry,
    ObservedEvent,
    Project,
    ProjectSummaryView,
)


class SummaryProvider(Protocol):
    """Protocol for offline rule-based or local AI project summary engines."""

    def generate_summary(
        self,
        project: Project,
        *,
        captures: Sequence[CaptureEntry],
        observed_events: Sequence[ObservedEvent],
        scheduled_events: Sequence[CalendarEvent],
    ) -> ProjectSummaryView:
        """Synthesize a ``ProjectSummaryView`` from separated project records."""
        ...
