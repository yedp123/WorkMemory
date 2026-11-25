"""Shared UI helpers for scheduling, editing, and updating calendar events."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from PySide6.QtWidgets import QDialog, QWidget

from work_memory.core.models import CalendarEvent, CalendarEventStatus, Project
from work_memory.services.calendar_service import CalendarService
from work_memory.services.project_service import ProjectService
from work_memory.ui.widgets.event_dialog import EventDialog


def open_create_event_dialog(
    parent: QWidget,
    calendar_service: CalendarService | None,
    project_service: ProjectService | None,
    *,
    initial_date: date | None = None,
    initial_project_id: str | None = None,
    fallback_projects: Sequence[Project] = (),
) -> bool:
    """Open ``EventDialog`` in Create mode and persist via ``CalendarService``."""
    if calendar_service is None:
        return False
    projects = project_service.list_projects() if project_service is not None else list(fallback_projects)
    dlg = EventDialog(
        projects,
        initial_date=initial_date,
        initial_project_id=initial_project_id,
        parent=parent,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted or dlg.form_data is None:
        return False
    data = dlg.form_data
    calendar_service.create_event(
        title=data.title,
        local_date=data.local_date,
        local_time=data.local_time,
        project_id=data.project_id,
        reminder_minutes=data.reminder_minutes,
        description=data.description,
    )
    return True


def open_edit_event_dialog(
    parent: QWidget,
    calendar_service: CalendarService | None,
    project_service: ProjectService | None,
    event: CalendarEvent,
    *,
    fallback_projects: Sequence[Project] = (),
) -> bool:
    """Open ``EventDialog`` in Edit mode and update or delete via ``CalendarService``."""
    if calendar_service is None:
        return False
    projects = project_service.list_projects() if project_service is not None else list(fallback_projects)
    dlg = EventDialog(projects, event=event, parent=parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    if dlg.delete_requested:
        return calendar_service.delete_event(event.id)
    if dlg.form_data is None:
        return False
    data = dlg.form_data
    calendar_service.update_event(
        event.id,
        title=data.title,
        local_date=data.local_date,
        local_time=data.local_time,
        project_id=data.project_id,
        reminder_minutes=data.reminder_minutes,
        description=data.description,
        status=data.status,
    )
    return True


def apply_event_status(
    calendar_service: CalendarService | None, event_id: str, status: CalendarEventStatus
) -> None:
    """Update a scheduled event's status explicitly via ``CalendarService``."""
    if calendar_service is not None:
        calendar_service.set_status(event_id, status)
