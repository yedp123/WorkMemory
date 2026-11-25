"""Top bar and primary navigation bar builders for MainWindow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton

from work_memory.ui.app_icon import build_brand_pixmap


@dataclass(slots=True)
class TopBarWidgets:
    """References to interactive controls inside the shell top bar."""

    frame: QFrame
    search_input: QLineEdit
    capture_btn: QPushButton
    settings_btn: QPushButton
    status_dot: QPushButton


def build_top_bar(
    on_brand_click: Callable[[], None],
    on_search_changed: Callable[[str], None],
    on_capture_click: Callable[[], None],
    on_settings_click: Callable[[], None],
) -> TopBarWidgets:
    """Build the top bar with brand button, global search, + Capture, Settings, and status dot."""
    top_bar = QFrame()
    top_bar.setObjectName("topBar")
    top_bar.setFixedHeight(76)
    layout = QHBoxLayout(top_bar)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)

    brand_row = QHBoxLayout()
    brand_row.setSpacing(11)
    logo = QLabel()
    logo.setObjectName("brandLogo")
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    logo.setFixedSize(30, 30)
    logo.setPixmap(build_brand_pixmap(30))

    brand_btn = QPushButton("Work Memory")
    brand_btn.setObjectName("brandButton")
    brand_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    brand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    brand_btn.clicked.connect(on_brand_click)
    brand_row.addWidget(logo)
    brand_row.addWidget(brand_btn)
    layout.addLayout(brand_row)
    layout.addStretch(1)

    search_input = QLineEdit()
    search_input.setObjectName("globalSearch")
    search_input.setPlaceholderText("Search projects, files, notes...")
    search_input.setClearButtonEnabled(True)
    search_input.setMinimumWidth(260)
    search_input.setMaximumWidth(380)
    search_input.textChanged.connect(on_search_changed)
    layout.addWidget(search_input, 2)
    layout.addStretch(1)

    capture_btn = QPushButton("+ Capture")
    capture_btn.setObjectName("captureButton")
    capture_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    capture_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    capture_btn.setToolTip("Quick Capture (Ctrl+Shift+M)")
    capture_btn.clicked.connect(on_capture_click)
    layout.addWidget(capture_btn)

    settings_btn = QPushButton("\u2699")
    settings_btn.setObjectName("settingsButton")
    settings_btn.setCheckable(True)
    settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    settings_btn.setToolTip("Settings")
    settings_btn.clicked.connect(on_settings_click)
    layout.addWidget(settings_btn)

    status_dot = QPushButton()
    status_dot.setObjectName("statusDotButton")
    status_dot.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    status_dot.setCursor(Qt.CursorShape.PointingHandCursor)
    status_dot.setToolTip("Local-first storage ready (read-only)")
    status_dot.clicked.connect(on_settings_click)
    layout.addWidget(status_dot)

    return TopBarWidgets(top_bar, search_input, capture_btn, settings_btn, status_dot)


def build_nav_bar(
    on_projects_click: Callable[[], None],
    on_history_click: Callable[[], None],
) -> tuple[QFrame, QPushButton, QPushButton]:
    """Build the two-tab primary navigation bar (Projects and History)."""
    nav_bar = QFrame()
    nav_bar.setObjectName("navBar")
    nav_bar.setFixedHeight(56)
    layout = QHBoxLayout(nav_bar)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(28)

    projects_tab = QPushButton("Projects")
    projects_tab.setProperty("navTab", True)
    projects_tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    projects_tab.setCursor(Qt.CursorShape.PointingHandCursor)
    projects_tab.clicked.connect(on_projects_click)

    history_tab = QPushButton("History")
    history_tab.setProperty("navTab", True)
    history_tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    history_tab.setCursor(Qt.CursorShape.PointingHandCursor)
    history_tab.clicked.connect(on_history_click)

    layout.addWidget(projects_tab)
    layout.addWidget(history_tab)
    layout.addStretch(1)
    return nav_bar, projects_tab, history_tab
