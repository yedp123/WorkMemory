"""Non-focus-stealing floating notification toast for contextual capture and reminders."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.services.notification_service import NotificationPayload
from work_memory.ui.theme import get_palette


def reposition_toasts(toasts: list[ToastPopup]) -> None:
    """Stack active ``ToastPopup`` windows cleanly above the primary screen taskbar."""
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    geom = screen.availableGeometry()
    margin = 16
    y_cursor = geom.bottom() - margin
    for toast in reversed(toasts):
        if not toast.isVisible():
            continue
        toast.adjustSize()
        w, h = toast.width(), toast.height()
        x = geom.right() - w - margin
        y = y_cursor - h
        toast.move(x, y)
        y_cursor = y - 10


class ToastPopup(QFrame):
    """Frameless, non-activating floating notification toast."""

    add_note_requested = Signal(object)
    screenshot_requested = Signal(object)
    voice_requested = Signal(object)
    milestone_requested = Signal(object)
    open_project_requested = Signal(object)
    dismissed = Signal(object)

    def __init__(self, payload: NotificationPayload, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._payload = payload
        self.setObjectName("toastPopup")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(340)

        pal = get_palette()
        self._pal = pal
        accent = (
            pal.purple
            if payload.kind == "calendar_event"
            else (pal.amber if payload.kind in ("timed_reminder", "info") else pal.accent)
        )
        self.setStyleSheet(
            f"QFrame#toastPopup {{ background-color: {pal.panel}; border: 1px solid {pal.border}; "
            f"border-left: 3px solid {accent}; border-radius: 10px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 12, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel(payload.title)
        title.setStyleSheet(f"color: {pal.text}; font-size: 12px; font-weight: 600; border: none;")
        close_btn = QPushButton("\u00d7")
        close_btn.setObjectName("toastDismissButton")
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {pal.muted}; font-size: 15px; padding: 0; }}"
            f"QPushButton:hover {{ color: {pal.text}; }}"
        )
        close_btn.clicked.connect(self.dismiss)
        head.addWidget(title, 1)
        head.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        msg = QLabel(payload.message)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color: {pal.soft}; font-size: 12px; border: none;")
        root.addWidget(msg)

        if payload.kind != "info":
            actions = QHBoxLayout()
            actions.setSpacing(6)
            if payload.kind == "calendar_event":
                if payload.project_id:
                    open_btn = self._make_action_btn(
                        "Open Project", "toastOpenProjectButton", self._on_open_project, accent_color=pal.purple
                    )
                    actions.addWidget(open_btn)
                dismiss_btn = self._make_action_btn("Dismiss", "toastDismissActionButton", self.dismiss)
                actions.addWidget(dismiss_btn)
            else:
                note_btn = self._make_action_btn("Add Note", "toastAddNoteButton", self._on_add_note)
                actions.addWidget(note_btn)

                if payload.kind in ("new_file", "repeated_save"):
                    shot_btn = self._make_action_btn("Screenshot", "toastScreenshotButton", self._on_screenshot)
                    actions.addWidget(shot_btn)
                    voice_btn = self._make_action_btn("Voice", "toastVoiceButton", self._on_voice)
                    actions.addWidget(voice_btn)
                    if payload.event_id:
                        star_btn = self._make_action_btn(
                            "\u2605 Milestone", "toastMilestoneButton", self._on_milestone, accent_color=pal.amber
                        )
                        actions.addWidget(star_btn)

            actions.addStretch(1)
            root.addLayout(actions)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        if payload.duration_sec > 0:
            self._timer.start(payload.duration_sec * 1000)

    def _make_action_btn(
        self, text: str, obj_name: str, slot: object, *, accent_color: str | None = None
    ) -> QPushButton:
        pal = self._pal
        btn = QPushButton(text)
        btn.setObjectName(obj_name)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fg = accent_color or pal.soft
        bdr = accent_color or pal.border
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {pal.panel_alt}; color: {fg}; border: 1px solid {bdr}; "
            "border-radius: 6px; padding: 4px 9px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ border-color: {pal.hover_border}; color: {pal.text}; }}"
        )
        btn.clicked.connect(slot)  # type: ignore[arg-type]
        return btn

    def _on_add_note(self) -> None:
        self.add_note_requested.emit(self._payload)
        self.dismiss()

    def _on_screenshot(self) -> None:
        self.screenshot_requested.emit(self._payload)
        self.dismiss()

    def _on_voice(self) -> None:
        self.voice_requested.emit(self._payload)
        self.dismiss()

    def _on_milestone(self) -> None:
        self.milestone_requested.emit(self._payload)
        self.dismiss()

    def _on_open_project(self) -> None:
        self.open_project_requested.emit(self._payload)
        self.dismiss()

    def dismiss(self) -> None:
        """Stop auto-dismiss timer, hide, and notify listeners."""
        self._timer.stop()
        self.hide()
        self.dismissed.emit(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure the auto-dismiss timer stops if closed directly."""
        self._timer.stop()
        super().closeEvent(event)
