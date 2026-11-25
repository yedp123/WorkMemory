"""Shared QScrollArea wrapper helper keeping per-page and embedded scrolling isolated."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


def wrap_in_scroll_area(
    host: QWidget | None = None,
    *,
    margins: tuple[int, int, int, int] = (0, 30, 0, 40),
    spacing: int = 16,
    embedded: bool = False,
    attach_to_host: bool = True,
) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    """Create a frameless resizable ``QScrollArea`` with styled inner layout."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)

    content = QWidget()
    if embedded:
        scroll.setObjectName("embeddedScrollArea")
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")
        content.setObjectName("embeddedScrollContent")
        content.setStyleSheet("background: transparent;")
    else:
        content.setObjectName("scrollContent")

    inner = QVBoxLayout(content)
    inner.setContentsMargins(*margins)
    inner.setSpacing(spacing)
    scroll.setWidget(content)

    if attach_to_host and host is not None:
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)

    return scroll, content, inner
