"""Calm dark EventDialog for creating and editing scheduled calendar events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import CalendarEvent, CalendarEventStatus, Project
from work_memory.services.history_service import parse_utc_to_local
from work_memory.ui.theme import get_palette

_REMINDER_OPTIONS: tuple[tuple[str, int | None], ...] = (
    ("No reminder", None),
    ("At time of event", 0),
    ("10 min before", 10),
    ("30 min before", 30),
    ("1 hour before", 60),
)
_STATUS_OPTIONS: tuple[tuple[str, CalendarEventStatus], ...] = (
    ("Scheduled", "scheduled"),
    ("Completed", "completed"),
    ("Cancelled", "cancelled"),
)


@dataclass(frozen=True, slots=True)
class EventFormData:
    """Validated form payload produced by ``EventDialog``."""

    title: str
    local_date: date
    local_time: time
    project_id: str | None
    reminder_minutes: int | None
    description: str
    status: CalendarEventStatus = "scheduled"


class EventDialog(QDialog):
    """Modal dark dialog for scheduling, editing, or deleting a calendar event."""

    def __init__(
        self,
        projects: Sequence[Project],
        *,
        initial_date: date | None = None,
        initial_project_id: str | None = None,
        event: CalendarEvent | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._event = event
        self._form_data: EventFormData | None = None
        self._delete_requested = False

        pal = get_palette()
        self._pal = pal
        is_edit = event is not None
        self.setWindowTitle("Edit event" if is_edit else "Schedule event")
        self.setMinimumWidth(460)
        self.setStyleSheet(
            f"QDialog {{ background-color: {pal.panel}; color: {pal.text}; border: 1px solid {pal.border}; }}"
            f"QLineEdit, QDateEdit, QTimeEdit, QComboBox {{ background-color: {pal.input_bg}; color: {pal.text}; "
            f"border: 1px solid {pal.border}; border-radius: 8px; padding: 6px 10px; font-size: 12px; }}"
            f"QLineEdit:focus, QDateEdit:focus, QTimeEdit:focus, QComboBox:focus {{ border-color: {pal.focus_border}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        heading = QLabel("Edit scheduled event" if is_edit else "Schedule event")
        heading.setStyleSheet(f"color: {pal.text}; font-size: 16px; font-weight: 600;")
        sub = QLabel("Planned events stay separate from observed file activity.")
        sub.setStyleSheet(f"color: {pal.muted}; font-size: 12px;")
        root.addWidget(heading)
        root.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._title_input = QLineEdit()
        self._title_input.setObjectName("eventTitleInput")
        self._title_input.setPlaceholderText("e.g. Client review, Render deadline, Rig check")

        self._date_edit = QDateEdit()
        self._date_edit.setObjectName("eventDateEdit")
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")

        self._time_edit = QTimeEdit()
        self._time_edit.setObjectName("eventTimeEdit")
        self._time_edit.setDisplayFormat("HH:mm")

        self._project_combo = QComboBox()
        self._project_combo.setObjectName("eventProjectCombo")
        self._project_combo.addItem("General (no specific project)", None)
        for proj in projects:
            self._project_combo.addItem(proj.name, proj.id)

        self._reminder_combo = QComboBox()
        self._reminder_combo.setObjectName("eventReminderCombo")
        for label, mins in _REMINDER_OPTIONS:
            self._reminder_combo.addItem(label, mins)

        self._desc_input = QLineEdit()
        self._desc_input.setObjectName("eventDescriptionInput")
        self._desc_input.setPlaceholderText("Optional notes or meeting link")

        form.addRow(self._lbl("Title"), self._title_input)
        form.addRow(self._lbl("Date"), self._date_edit)
        form.addRow(self._lbl("Time"), self._time_edit)
        form.addRow(self._lbl("Project"), self._project_combo)
        form.addRow(self._lbl("Reminder"), self._reminder_combo)
        self._status_combo: QComboBox | None = None
        if is_edit:
            self._status_combo = QComboBox()
            self._status_combo.setObjectName("eventStatusCombo")
            for label, status_val in _STATUS_OPTIONS:
                self._status_combo.addItem(label, status_val)
            form.addRow(self._lbl("Status"), self._status_combo)
        form.addRow(self._lbl("Description"), self._desc_input)
        root.addLayout(form)

        self._populate_initial(initial_date, initial_project_id, event)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        if is_edit:
            del_btn = QPushButton("Delete")
            del_btn.setObjectName("eventDeleteButton")
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setStyleSheet(
                f"QPushButton {{ background: {pal.panel_alt}; color: {pal.danger_text}; border: 1px solid {pal.border}; "
                "border-radius: 8px; padding: 7px 12px; font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {pal.danger_border}; }}"
            )
            del_btn.clicked.connect(self._on_delete)
            footer.addWidget(del_btn)
        footer.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("secondary", True)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Save changes" if is_edit else "Schedule")
        save_btn.setObjectName("eventSaveButton")
        save_btn.setProperty("primary", True)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)

        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

    @property
    def form_data(self) -> EventFormData | None:
        """Return validated form values when accepted, else ``None``."""
        return self._form_data

    @property
    def delete_requested(self) -> bool:
        """Return ``True`` when the user clicked Delete in Edit mode."""
        return self._delete_requested

    def _populate_initial(
        self, initial_date: date | None, initial_project_id: str | None, event: CalendarEvent | None
    ) -> None:
        if event is not None:
            local_dt = parse_utc_to_local(event.event_at_utc)
            self._title_input.setText(event.title)
            self._date_edit.setDate(QDate(local_dt.year, local_dt.month, local_dt.day))
            self._time_edit.setTime(QTime(local_dt.hour, local_dt.minute))
            self._desc_input.setText(event.description)
            pid = event.project_id
            rem_idx = self._reminder_combo.findData(event.reminder_minutes)
            self._reminder_combo.setCurrentIndex(rem_idx if rem_idx >= 0 else 2)
            if self._status_combo is not None and (st_idx := self._status_combo.findData(event.status)) >= 0:
                self._status_combo.setCurrentIndex(st_idx)
        else:
            d = initial_date or date.today()
            self._date_edit.setDate(QDate(d.year, d.month, d.day))
            self._time_edit.setTime(QTime(15, 0))
            pid = initial_project_id
            rem_idx = self._reminder_combo.findData(10)
            self._reminder_combo.setCurrentIndex(max(rem_idx, 0))

        if pid and (idx := self._project_combo.findData(pid)) >= 0:
            self._project_combo.setCurrentIndex(idx)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {get_palette().soft}; font-size: 12px;")
        return lbl

    def _on_save(self) -> None:
        title = self._title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Schedule event", "Please enter an event title.")
            self._title_input.setFocus()
            return
        qd = self._date_edit.date()
        qt = self._time_edit.time()
        status: CalendarEventStatus = (
            self._status_combo.currentData() if self._status_combo is not None else "scheduled"
        )
        self._form_data = EventFormData(
            title=title,
            local_date=date(qd.year(), qd.month(), qd.day()),
            local_time=time(qt.hour(), qt.minute()),
            project_id=self._project_combo.currentData(),
            reminder_minutes=self._reminder_combo.currentData(),
            description=self._desc_input.text().strip(),
            status=status,
        )
        self.accept()

    def _on_delete(self) -> None:
        self._delete_requested = True
        self.accept()
