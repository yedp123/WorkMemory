"""WeChat-style icon floating toolbar and progressive style sub-bar."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from work_memory.ui.capture.annotation_engine import AnnotationTool
from work_memory.ui.capture.style_subbar import StyleSubBar
from work_memory.ui.capture.toolbar_icons import make_toolbar_icon
from work_memory.ui.theme import ACCENT, ACCENT_BG, BORDER, PANEL


def compute_toolbar_pos(selection: QRect, toolbar_size: QSize, bounds: QRect) -> QPoint:
    """Position the toolbar below ``selection``, flipping or tucking inside ``bounds``."""
    gap, pad = 8, 8
    tb_w, tb_h = toolbar_size.width(), toolbar_size.height()

    min_x = bounds.left() + pad
    max_x = max(min_x, bounds.right() - tb_w - pad + 1)
    x = max(min_x, min(selection.right() - tb_w + 1, max_x))

    y_below = selection.bottom() + 1 + gap
    y_above = selection.top() - gap - tb_h
    if y_below + tb_h <= bounds.bottom() - pad + 1:
        y = y_below
    elif y_above >= bounds.top() + pad:
        y = y_above
    else:
        max_y = max(bounds.top() + pad, bounds.bottom() - tb_h - pad + 1)
        y = max(bounds.top() + pad, min(selection.bottom() + 1 - gap - tb_h, max_y))
    return QPoint(x, y)


class FloatingToolbar(QWidget):
    """Icon toolbar with Undo/Reset/Cancel/Confirm and progressive style sub-bar."""

    tool_selected = Signal(object)
    color_changed = Signal(QColor)
    size_preset_changed = Signal(str)
    undo_clicked = Signal()
    reset_clicked = Signal()
    cancel_clicked = Signal()
    confirm_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("captureFloatingToolbarContainer")
        self._tool_buttons: dict[AnnotationTool, QPushButton] = {}
        self._active_tool: AnnotationTool | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        main_bar = QFrame()
        main_bar.setObjectName("captureFloatingToolbar")
        main_bar.setStyleSheet(
            f"QFrame#captureFloatingToolbar {{ background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 9px; }}"
        )
        row = QHBoxLayout(main_bar)
        row.setContentsMargins(7, 4, 7, 4)
        row.setSpacing(3)

        btn_css = (
            "QPushButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 0px; }"
            "QPushButton:hover { background-color: #272b33; }"
            f"QPushButton:checked {{ background-color: {ACCENT_BG}; border-color: {ACCENT}; }}"
            "QPushButton:disabled { opacity: 0.35; }"
        )
        for tool_id, tip in (
            ("rect", "Rectangle"),
            ("circle", "Circle"),
            ("arrow", "Arrow"),
            ("pen", "Pen"),
            ("text", "Text"),
        ):
            btn = self._make_icon_btn(
                tool_id, f"toolbarTool_{tool_id}", tip, btn_css, checkable=True
            )
            btn.clicked.connect(lambda checked, t=tool_id: self._on_tool_clicked(t, checked))  # type: ignore[arg-type]
            self._tool_buttons[tool_id] = btn  # type: ignore[index]
            row.addWidget(btn)

        row.addWidget(self._make_separator())

        self._undo_btn = self._make_icon_btn("undo", "toolbarUndoButton", "Undo (Ctrl+Z)", btn_css)
        self._undo_btn.clicked.connect(self.undo_clicked.emit)
        self._reset_btn = self._make_icon_btn("reset", "toolbarResetButton", "Reset", btn_css)
        self._reset_btn.clicked.connect(self.reset_clicked.emit)
        self._undo_btn.setEnabled(False)
        self._reset_btn.setEnabled(False)
        row.addWidget(self._undo_btn)
        row.addWidget(self._reset_btn)

        row.addWidget(self._make_separator())

        cancel_css = (
            "QPushButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 0px; }"
            "QPushButton:hover { background-color: #362528; }"
        )
        confirm_css = (
            "QPushButton { background-color: #24382f; border: 1px solid #3c6551; border-radius: 6px; padding: 0px; }"
            "QPushButton:hover { background-color: #2b4539; border-color: #6ec494; }"
        )
        self._cancel_btn = self._make_icon_btn("cancel", "toolbarCancelButton", "Cancel (Esc)", cancel_css)
        self._cancel_btn.clicked.connect(self.cancel_clicked.emit)
        self._confirm_btn = self._make_icon_btn("confirm", "toolbarConfirmButton", "Confirm (Enter)", confirm_css)
        self._confirm_btn.clicked.connect(self.confirm_clicked.emit)
        row.addWidget(self._cancel_btn)
        row.addWidget(self._confirm_btn)

        self._style_bar = StyleSubBar()
        self._style_bar.setVisible(False)
        self._style_bar.color_changed.connect(self.color_changed.emit)
        self._style_bar.size_preset_changed.connect(self.size_preset_changed.emit)

        root.addWidget(main_bar, 0, Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._style_bar, 0, Qt.AlignmentFlag.AlignRight)
        self.adjustSize()

    @property
    def active_tool(self) -> AnnotationTool | None:
        """Return the currently selected annotation tool, or ``None`` for move/resize."""
        return self._active_tool

    @property
    def style_bar(self) -> StyleSubBar:
        """Return the progressive style sub-bar widget."""
        return self._style_bar

    def clear_active_tool(self) -> None:
        """Uncheck any active drawing tool, hide the style sub-bar, and emit ``None``."""
        if self._active_tool is not None:
            self._active_tool = None
            for btn in self._tool_buttons.values():
                btn.setChecked(False)
            self._style_bar.setVisible(False)
            self.adjustSize()
            self.tool_selected.emit(None)

    def set_history_available(self, has_items: bool) -> None:
        """Enable or disable Undo and Reset based on whether annotations exist."""
        self._undo_btn.setEnabled(has_items)
        self._reset_btn.setEnabled(has_items)

    def reposition_for_selection(self, selection_rect: QRect, monitor_rect: QRect) -> None:
        """Place the toolbar (including sub-bar when visible) inside ``monitor_rect``."""
        if (lay := self.layout()) is not None:
            lay.activate()
        self.adjustSize()
        self.move(compute_toolbar_pos(selection_rect, self.sizeHint(), monitor_rect))

    def position_near(self, selection: QRect, bounds: QRect) -> None:
        """Alias for ``reposition_for_selection``."""
        self.reposition_for_selection(selection, bounds)

    def _on_tool_clicked(self, tool: AnnotationTool, checked: bool) -> None:
        self._active_tool = tool if checked else None
        for key, btn in self._tool_buttons.items():
            btn.setChecked(key == self._active_tool)
        self._style_bar.setVisible(self._active_tool is not None)
        if (lay := self.layout()) is not None:
            lay.activate()
        self.adjustSize()
        self.tool_selected.emit(self._active_tool)

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFixedSize(1, 18)
        sep.setStyleSheet(f"background-color: {BORDER}; border: none;")
        return sep

    @staticmethod
    def _make_icon_btn(
        icon_name: str, obj_name: str, tooltip: str, css: str, *, checkable: bool = False
    ) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName(obj_name)
        btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        btn.setFixedSize(28, 28)
        btn.setIconSize(QSize(18, 18))
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(css)
        btn.setIcon(make_toolbar_icon(icon_name, checkable_tool=checkable))
        return btn
