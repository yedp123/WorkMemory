"""Unit tests for desktop cropping, AnnotationEngine, FloatingToolbar, and CaptureOverlay."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from work_memory.media.screenshot import crop_from_desktop, pixmap_to_png_bytes
from work_memory.ui.capture.annotation_engine import AnnotationEngine
from work_memory.ui.capture.capture_overlay import CaptureOverlay
from work_memory.ui.capture.floating_toolbar import FloatingToolbar, compute_toolbar_pos


def _ensure_qapp(monkeypatch: pytest.MonkeyPatch) -> QApplication:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


def test_crop_from_desktop_handles_negative_offsets_and_dpr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_qapp(monkeypatch)
    virtual_rect = QRect(-1920, -200, 3840, 1280)
    dpr = 1.5
    desktop = QPixmap(round(virtual_rect.width() * dpr), round(virtual_rect.height() * dpr))
    desktop.setDevicePixelRatio(dpr)
    desktop.fill(QColor("#112233"))
    painter = QPainter(desktop)
    painter.fillRect(QRect(0, 0, 1920, 1080), QColor("#22aa55"))
    painter.fillRect(QRect(1920, 200, 1920, 1080), QColor("#3366cc"))
    painter.end()

    left_crop = crop_from_desktop(desktop, virtual_rect, QRect(-1500, -100, 200, 120))
    assert left_crop.size() == QSize(300, 180)
    assert left_crop.devicePixelRatio() == 1.5
    assert left_crop.toImage().pixelColor(10, 10).name() == "#22aa55"

    right_crop = crop_from_desktop(desktop, virtual_rect, QRect(100, 50, 160, 100))
    assert right_crop.size() == QSize(240, 150)
    assert right_crop.toImage().pixelColor(10, 10).name() == "#3366cc"

    assert crop_from_desktop(desktop, virtual_rect, QRect(5000, 5000, 100, 100)).isNull() is True
    assert crop_from_desktop(desktop, virtual_rect, QRect(0, 0, 0, 0)).isNull() is True


def test_annotation_engine_preserves_per_item_color_and_thickness_and_supports_undo_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_qapp(monkeypatch)
    img = QImage(240, 160, QImage.Format.Format_ARGB32)
    img.fill(QColor("#1c2026"))
    base = QPixmap.fromImage(img)
    orig_bytes = pixmap_to_png_bytes(base)

    engine = AnnotationEngine()
    assert engine.has_annotations() is False

    # 1. Draw red 2px (small) rect
    engine.set_color(QColor("#ef5350"))
    engine.set_size_preset("small")
    engine.add_shape("rect", QPointF(20, 20), QPointF(100, 80))

    # 2. Switch to blue 7px (large) circle + text — must NOT mutate earlier rect
    engine.set_color(QColor("#5aa9f0"))
    engine.set_size_preset("large")
    engine.add_shape("circle", QPointF(110, 20), QPointF(180, 90))
    engine.add_pen_stroke([QPointF(10, 10), QPointF(30, 25), QPointF(50, 15)])
    engine.add_text(QPointF(40, 110), "Review joint")

    assert engine.has_annotations() is True
    assert len(engine.items) == 4
    assert engine.items[0].color == QColor("#ef5350")
    assert engine.items[0].thickness == 2
    assert engine.items[1].color == QColor("#5aa9f0")
    assert engine.items[1].thickness == 7
    assert engine.items[3].color == QColor("#5aa9f0")
    assert engine.items[3].font_size == 24

    annotated = engine.render_annotated(base)
    assert pixmap_to_png_bytes(base) == orig_bytes
    assert pixmap_to_png_bytes(annotated) != orig_bytes

    assert engine.undo() is True
    assert len(engine.items) == 3
    assert engine.reset() is True
    assert engine.has_annotations() is False
    assert pixmap_to_png_bytes(engine.render_annotated(base)) == orig_bytes
    assert engine.undo() is False


def test_floating_toolbar_style_subbar_disclosure_icons_and_reposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_qapp(monkeypatch)
    tb = FloatingToolbar()
    tb.show()
    try:
        assert tb.style_bar.isVisible() is False
        for btn in tb.findChildren(QPushButton):
            assert btn.focusPolicy() == Qt.FocusPolicy.NoFocus
            assert not btn.icon().isNull()

        tools_seen: list[object] = []
        colors_seen: list[QColor] = []
        sizes_seen: list[str] = []
        tb.tool_selected.connect(tools_seen.append)
        tb.color_changed.connect(colors_seen.append)
        tb.size_preset_changed.connect(sizes_seen.append)

        rect_btn = tb.findChild(QPushButton, "toolbarTool_rect")
        large_btn = tb.findChild(QPushButton, "toolbarSize_large")
        blue_btn = tb.findChild(QPushButton, "toolbarColor_blue")
        assert rect_btn is not None and large_btn is not None and blue_btn is not None

        # Activating tool reveals style sub-bar
        rect_btn.click()
        assert tb.style_bar.isVisible() is True
        assert tools_seen[-1] == "rect"

        large_btn.click()
        blue_btn.click()
        assert sizes_seen == ["large"]
        assert colors_seen == [QColor("#5aa9f0")]

        # Combined height is respected when selection is near bottom edge of monitor
        monitor = QRect(0, 0, 1000, 700)
        bottom_sel = QRect(400, 560, 300, 120)
        tb.reposition_for_selection(bottom_sel, monitor)
        assert tb.y() + tb.height() <= monitor.bottom() + 1
        assert tb.y() < bottom_sel.top()

        # Clicking active tool again toggles it OFF and hides style sub-bar
        rect_btn.click()
        assert tb.style_bar.isVisible() is False
        assert tools_seen[-1] is None
    finally:
        tb.close()

    bounds = QRect(0, 0, 1000, 700)
    tb_size = QSize(420, 36)
    p_normal = compute_toolbar_pos(QRect(200, 100, 300, 200), tb_size, bounds)
    assert p_normal.y() == 308
    p_full = compute_toolbar_pos(QRect(0, 0, 1000, 700), tb_size, bounds)
    assert bounds.top() + 8 <= p_full.y() <= bounds.bottom() - tb_size.height()


def test_capture_overlay_drag_resize_style_annotate_and_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_qapp(monkeypatch)
    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(QColor("#223344"))
    frozen = QPixmap.fromImage(img)

    overlay = CaptureOverlay(frozen, QRect(0, 0, 400, 300))
    overlay.show()
    try:
        assert overlay.state == "selecting"

        # 1. Drag selection 200x120
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 30))
        QTest.mouseMove(overlay, pos=QPoint(239, 149))
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(239, 149))
        assert overlay.state == "adjusting"
        assert overlay._toolbar.isVisible() is True
        assert overlay._toolbar.style_bar.isVisible() is False

        # 2. Resize using SE handle (+20, +10) -> 220x130
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(239, 149))
        QTest.mouseMove(overlay, pos=QPoint(259, 159))
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(259, 159))
        assert overlay._selection == QRect(40, 30, 220, 130)

        # 3. Pick Rect + undo with Ctrl+Z, then switch to Blue + Large + Arrow + Text
        rect_btn = overlay.findChild(QPushButton, "toolbarTool_rect")
        arrow_btn = overlay.findChild(QPushButton, "toolbarTool_arrow")
        text_btn = overlay.findChild(QPushButton, "toolbarTool_text")
        blue_btn = overlay.findChild(QPushButton, "toolbarColor_blue")
        large_btn = overlay.findChild(QPushButton, "toolbarSize_large")
        assert rect_btn and arrow_btn and text_btn and blue_btn and large_btn

        rect_btn.click()
        assert overlay._toolbar.style_bar.isVisible() is True
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(60, 50))
        QTest.mouseMove(overlay, pos=QPoint(140, 110))
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(140, 110))
        assert overlay._engine.has_annotations() is True

        QTest.keyClick(overlay, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert overlay._engine.has_annotations() is False

        blue_btn.click()
        large_btn.click()
        arrow_btn.click()
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(60, 50))
        QTest.mouseMove(overlay, pos=QPoint(160, 120))
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(160, 120))
        assert overlay._engine.items[0].color == QColor("#5aa9f0")
        assert overlay._engine.items[0].thickness == 7

        text_btn.click()
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
        assert overlay._text_editor.isVisible() is True
        assert overlay._text_editor.font().pointSize() == 24
        QTest.keyClicks(overlay._text_editor, "Focus here")
        QTest.keyClick(overlay._text_editor, Qt.Key.Key_Return)
        assert len(overlay._engine.items) == 2
        assert overlay._engine.items[1].text == "Focus here"
        assert overlay._engine.items[1].color == QColor("#5aa9f0")
        assert overlay._engine.items[1].font_size == 24

        QTest.keyClick(overlay, Qt.Key.Key_Return)
        assert overlay.result() == QDialog.DialogCode.Accepted
        res = overlay.capture_result
        assert res is not None
        assert res.original.size() == QSize(220, 130)
        assert res.annotated is not None
        assert pixmap_to_png_bytes(res.original) != pixmap_to_png_bytes(res.annotated)
    finally:
        overlay.close()
