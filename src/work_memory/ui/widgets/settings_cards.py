"""Extracted card and row builders used by SettingsView."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import Workspace
from work_memory.ui.theme import get_palette


@dataclass(slots=True)
class StartupCardWidgets:
    """Widget handles for the Windows Startup card in SettingsView."""

    card: QFrame
    startup_cb: QCheckBox


def build_readonly_banner() -> QFrame:
    """Build the calm green-accented read-only workspace guarantee banner."""
    pal = get_palette()
    banner = QFrame()
    banner.setObjectName("readOnlyBanner")
    inner = QVBoxLayout(banner)
    inner.setContentsMargins(20, 18, 20, 18)
    inner.setSpacing(6)

    heading = QLabel("Read-only workspace protection")
    heading.setObjectName("readOnlyBannerHeading")
    heading.setStyleSheet(f"color: {pal.green}; font-size: 13px; font-weight: 600;")
    body = QLabel(
        "Work Memory observes your folders without renaming, moving, or writing files "
        "inside them. All notes, screenshots, voice recordings, and history live in "
        "Work Memory's own local storage."
    )
    body.setProperty("role", "mutedBody")
    body.setWordWrap(True)

    inner.addWidget(heading)
    inner.addWidget(body)
    return banner


def build_startup_card(
    enabled: bool, on_toggled: Callable[[bool], None]
) -> StartupCardWidgets:
    """Build the calm Windows Startup settings card."""
    card = QFrame()
    card.setProperty("surface", True)
    inner = QVBoxLayout(card)
    inner.setContentsMargins(20, 18, 20, 18)
    inner.setSpacing(8)

    heading = QLabel("Startup")
    heading.setProperty("role", "sectionTitle")
    inner.addWidget(heading)

    startup_cb = QCheckBox("Launch quietly in system tray when Windows starts")
    startup_cb.setObjectName("launchAtStartupCheckBox")
    with QSignalBlocker(startup_cb):
        startup_cb.setChecked(enabled)
    startup_cb.toggled.connect(on_toggled)
    inner.addWidget(startup_cb)

    hint = QLabel(
        "Uses a per-user Windows login entry without administrator rights so background "
        "monitoring starts silently in the tray."
    )
    hint.setProperty("role", "mutedBody")
    hint.setWordWrap(True)
    inner.addWidget(hint)
    return StartupCardWidgets(card=card, startup_cb=startup_cb)


def build_workspace_row(
    ws: Workspace,
    *,
    is_paused: bool,
    relink_enabled: bool,
    on_relink: Callable[[str], None],
    on_remove: Callable[[str], None],
) -> QWidget:
    """Build a single monitored-workspace row with status pill, Relink, and Remove buttons."""
    row_widget = QWidget()
    row = QHBoxLayout(row_widget)
    row.setContentsMargins(0, 10, 0, 10)
    row.setSpacing(12)

    info = QVBoxLayout()
    info.setSpacing(2)
    path_label = QLabel(ws.root_path)
    path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    is_row_paused = is_paused or not ws.is_active
    if is_row_paused:
        detail = "Paused (read-only)"
    elif ws.last_scan_utc:
        detail = f"Watching (read-only) \u00b7 Last scan {ws.last_scan_utc}"
    else:
        detail = "Scanning baseline (read-only)..."
    detail_label = QLabel(detail)
    detail_label.setProperty("role", "mutedBody")
    info.addWidget(path_label)
    info.addWidget(detail_label)

    pill = QLabel("Paused" if is_row_paused else "Active")
    pill.setProperty("pill", "paused" if is_row_paused else "active")

    relink_btn = QPushButton("Relink")
    relink_btn.setObjectName(f"relinkWorkspace_{ws.id}")
    relink_btn.setProperty("secondary", True)
    relink_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    relink_btn.setEnabled(relink_enabled)
    relink_btn.setToolTip("Point this workspace to a moved or renamed folder")
    relink_btn.clicked.connect(lambda _c=False, ws_id=ws.id: on_relink(ws_id))

    remove_btn = QPushButton("Remove")
    remove_btn.setProperty("secondary", True)
    remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    remove_btn.setToolTip("Stop observing this folder (files on disk stay untouched)")
    remove_btn.clicked.connect(lambda _c=False, ws_id=ws.id: on_remove(ws_id))

    row.addLayout(info, 1)
    row.addWidget(pill)
    row.addWidget(relink_btn)
    row.addWidget(remove_btn)
    return row_widget
