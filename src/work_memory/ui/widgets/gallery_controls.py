"""Segmented gallery view mode switcher, discovery whisper, and empty-state builders."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.config.settings import normalize_gallery_view_mode
from work_memory.core.models import ProjectSuggestion
from work_memory.ui.theme import get_palette

_MODE_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("list", "List", "List view"),
    ("small", "S", "Small grid"),
    ("medium", "M", "Medium grid"),
    ("large", "L", "Large grid"),
)


@dataclass(slots=True)
class DiscoveryWhisperWidgets:
    """Widget handles for the subtle workspace project-discovery whisper bar."""

    bar: QWidget
    label: QLabel
    register_btn: QPushButton
    dismiss_btn: QPushButton


GRID_GAP = 22
GRID_CARD_SIZES: dict[str, tuple[int, int]] = {
    "small": (240, 150),
    "medium": (320, 200),
    "large": (440, 275),
}


def compute_gallery_columns(view_mode: str, width: int) -> int:
    """Compute fitting non-stretched grid columns for ``view_mode`` and ``width``."""
    mode = normalize_gallery_view_mode(view_mode)
    if mode == "list":
        return 1
    card_w, _cover_h = GRID_CARD_SIZES[mode]
    return max(1, (max(0, width) + GRID_GAP) // (card_w + GRID_GAP))


def build_discovery_whisper(
    on_confirm: Callable[[], None],
    on_dismiss: Callable[[], None],
) -> DiscoveryWhisperWidgets:
    """Build the subtle dismissible workspace discovery suggestion bar."""
    bar = QWidget()
    bar.setObjectName("discoveryWhisper")
    row = QHBoxLayout(bar)
    row.setContentsMargins(2, 0, 2, 6)
    row.setSpacing(12)

    pal = get_palette()
    label = QLabel()
    label.setStyleSheet(f"font-size: 12px; color: {pal.muted};")
    label.setTextFormat(Qt.TextFormat.RichText)

    register_btn = QPushButton("Register")
    register_btn.setObjectName("whisperRegisterButton")
    register_btn.setProperty("textButton", True)
    register_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    register_btn.clicked.connect(on_confirm)

    dismiss_btn = QPushButton("\u00d7")
    dismiss_btn.setObjectName("whisperCloseButton")
    dismiss_btn.setToolTip("Dismiss suggestion")
    dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    dismiss_btn.clicked.connect(on_dismiss)

    row.addWidget(label, 1)
    row.addWidget(register_btn, 0)
    row.addWidget(dismiss_btn, 0)
    bar.setVisible(False)
    return DiscoveryWhisperWidgets(bar, label, register_btn, dismiss_btn)


def update_discovery_whisper(
    widgets: DiscoveryWhisperWidgets, suggestions: Sequence[ProjectSuggestion]
) -> None:
    """Render the top discovery suggestion or hide the bar when none remain."""
    if not suggestions:
        widgets.bar.setVisible(False)
        return
    top = suggestions[0]
    pal = get_palette()
    escaped = top.abs_path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    widgets.label.setText(
        f"Suggested folder found in workspace: <b style='color:{pal.soft};'>{escaped}</b>"
    )
    reasons = ", ".join(top.reasons)
    widgets.bar.setToolTip(f"{top.abs_path} ({reasons})" if reasons else top.abs_path)
    widgets.bar.setVisible(True)


def refresh_whisper_theme(widgets: DiscoveryWhisperWidgets) -> None:
    """Re-style the discovery whisper bar text for the active theme."""
    pal = get_palette()
    widgets.label.setStyleSheet(f"font-size: 12px; color: {pal.muted};")


def build_empty_projects_panel() -> tuple[QFrame, QLabel, QLabel]:
    """Build the calm empty-state surface card for ProjectsView."""
    panel = QFrame()
    panel.setProperty("surface", True)
    inner = QVBoxLayout(panel)
    inner.setContentsMargins(20, 20, 20, 20)
    inner.setSpacing(6)
    heading = QLabel("No registered projects yet")
    heading.setProperty("role", "sectionTitle")
    body = QLabel()
    body.setProperty("role", "mutedBody")
    body.setWordWrap(True)
    inner.addWidget(heading)
    inner.addWidget(body)
    return panel, heading, body


def update_empty_projects_panel(
    heading: QLabel,
    body: QLabel,
    *,
    has_projects: bool,
    search_query: str,
) -> None:
    """Update the Projects empty-state message for search vs zero projects."""
    if has_projects and search_query:
        heading.setText("No matching projects")
        body.setText("Try another name, folder path, or status keyword.")
    else:
        heading.setText("No registered projects yet")
        body.setText(
            "Click '+ Register project' to add an existing folder (read-only), "
            "or add a workspace in Settings to see gentle project suggestions."
        )


class ViewModeSwitcher(QFrame):
    """Subtle 4-button segmented control switching between List, S, M, and L modes."""

    mode_changed = Signal(str)

    def __init__(self, initial_mode: str = "medium", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("viewModeSwitcher")
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)

        self._buttons: dict[str, QPushButton] = {}
        for mode, label, tooltip in _MODE_ITEMS:
            btn = QPushButton(label)
            btn.setObjectName(f"viewModeBtn_{mode}")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda _c=False, m=mode: self._select(m, emit=True))
            self._buttons[mode] = btn
            row.addWidget(btn)

        self.refresh_theme()
        self.set_mode(initial_mode)

    def refresh_theme(self) -> None:
        """Re-apply active theme colors to the switcher container and buttons."""
        pal = get_palette()
        self.setStyleSheet(
            f"QFrame#viewModeSwitcher {{ background-color: {pal.panel}; "
            f"border: 1px solid {pal.border}; border-radius: 9px; }}"
        )
        btn_css = (
            f"QPushButton {{ background: transparent; border: none; border-radius: 6px; "
            f"color: {pal.muted}; padding: 5px 10px; font-size: 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {pal.soft}; background-color: {pal.panel_alt}; }}"
            f"QPushButton:checked {{ background-color: {pal.accent_bg}; color: {pal.text}; }}"
        )
        for btn in self._buttons.values():
            btn.setStyleSheet(btn_css)

    def set_mode(self, mode: str) -> None:
        """Update the checked button state without emitting ``mode_changed``."""
        self._select(normalize_gallery_view_mode(mode), emit=False)

    def _select(self, mode: str, *, emit: bool) -> None:
        for key, btn in self._buttons.items():
            btn.setChecked(key == mode)
        if emit:
            self.mode_changed.emit(mode)
