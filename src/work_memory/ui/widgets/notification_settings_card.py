"""Modular Notifications & Reminders settings card with custom inline intervals."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from work_memory.config.settings import (
    DEFAULT_REMINDER_MESSAGE,
    AppSettings,
    normalize_reminder_message,
)
from work_memory.ui.theme import get_palette

_CUSTOM_DATA = -1


def _card_stylesheet() -> str:
    pal = get_palette()
    return (
        f"QComboBox, QSpinBox, QLineEdit {{ background-color: {pal.input_bg}; color: {pal.text}; "
        f"border: 1px solid {pal.border}; border-radius: 8px; padding: 5px 10px; font-size: 12px; }}"
        f"QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {pal.focus_border}; }}"
        f"QComboBox QAbstractItemView {{ background-color: {pal.panel_alt}; color: {pal.text}; "
        f"border: 1px solid {pal.border}; selection-background-color: {pal.accent_bg}; }}"
    )


class _IntervalSelector(QWidget):
    """Preset combo box with progressive inline ``QSpinBox`` for custom values."""

    changed = Signal()

    def __init__(
        self,
        *,
        combo_name: str,
        spin_name: str,
        presets: Sequence[tuple[str, int]],
        current: int,
        min_val: int,
        max_val: int,
        suffix: str,
        default_custom: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._min_val = min_val
        self._max_val = max_val
        self._default_custom = default_custom

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.combo = QComboBox()
        self.combo.setObjectName(combo_name)
        for text, val in presets:
            self.combo.addItem(text, val)
        self.combo.addItem("Custom...", _CUSTOM_DATA)

        self.spin = QSpinBox()
        self.spin.setObjectName(spin_name)
        self.spin.setRange(min_val, max_val)
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(96)

        layout.addWidget(self.combo)
        layout.addWidget(self.spin)

        self.set_value(current)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.spin.valueChanged.connect(self._on_spin_changed)

    def value(self) -> int:
        """Return the active integer setting (preset or custom spinbox value)."""
        data = int(self.combo.currentData())
        return self.spin.value() if data == _CUSTOM_DATA else data

    def set_value(self, raw_value: int) -> None:
        """Select matching preset or reveal ``Custom...`` with ``raw_value``."""
        with QSignalBlocker(self.combo), QSignalBlocker(self.spin):
            idx = self.combo.findData(raw_value)
            if idx >= 0 and raw_value != _CUSTOM_DATA:
                self.combo.setCurrentIndex(idx)
                self.spin.setValue(max(self._min_val, min(raw_value or self._default_custom, self._max_val)))
                self.spin.setVisible(False)
            else:
                custom_idx = self.combo.findData(_CUSTOM_DATA)
                self.combo.setCurrentIndex(max(0, custom_idx))
                self.spin.setValue(max(self._min_val, min(raw_value, self._max_val)))
                self.spin.setVisible(True)

    def _on_combo_changed(self) -> None:
        is_custom = int(self.combo.currentData()) == _CUSTOM_DATA
        self.spin.setVisible(is_custom)
        self.changed.emit()

    def _on_spin_changed(self) -> None:
        if int(self.combo.currentData()) == _CUSTOM_DATA:
            self.changed.emit()


class NotificationSettingsCard(QFrame):
    """Quiet settings card supporting preset and custom notification/reminder intervals."""

    settings_changed = Signal()

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("surface", True)
        self.setStyleSheet(_card_stylesheet())

        inner = QVBoxLayout(self)
        inner.setContentsMargins(20, 18, 20, 18)
        inner.setSpacing(12)

        heading = QLabel("Notifications & reminders")
        heading.setProperty("role", "sectionTitle")
        inner.addWidget(heading)

        self.new_file_cb = QCheckBox("Notify when a new file is created in a monitored folder")
        self.new_file_cb.setObjectName("newFileNotifCheckBox")
        with QSignalBlocker(self.new_file_cb):
            self.new_file_cb.setChecked(settings.new_file_notifications)
        self.new_file_cb.toggled.connect(self._emit_changed)
        inner.addWidget(self.new_file_cb)

        self._repeat_sel = _IntervalSelector(
            combo_name="repeatedSaveCombo",
            spin_name="repeatedSaveSpinBox",
            presets=[("Never", 0), ("Every save", 1), ("Every 3 saves", 3), ("Every 5 saves", 5), ("Every 10 saves", 10)],
            current=settings.repeated_save_interval,
            min_val=1,
            max_val=999,
            suffix=" saves",
            default_custom=7,
        )
        self._duration_sel = _IntervalSelector(
            combo_name="notifDurationCombo",
            spin_name="notifDurationSpinBox",
            presets=[("10 seconds", 10), ("30 seconds", 30), ("1 minute", 60), ("5 minutes", 300), ("Until dismissed", 0)],
            current=settings.notification_duration_sec,
            min_val=5,
            max_val=3600,
            suffix=" sec",
            default_custom=45,
        )
        self._reminder_sel = _IntervalSelector(
            combo_name="saveReminderCombo",
            spin_name="saveReminderSpinBox",
            presets=[("Off", 0), ("Every 5 minutes", 5), ("Every 15 minutes", 15), ("Every 30 minutes", 30), ("Every 60 minutes", 60)],
            current=settings.save_reminder_minutes,
            min_val=1,
            max_val=480,
            suffix=" min",
            default_custom=20,
        )

        for label_txt, selector in (
            ("Repeated-save reminder", self._repeat_sel),
            ("Notification duration", self._duration_sel),
            ("Periodic save reminder", self._reminder_sel),
        ):
            row = QHBoxLayout()
            lbl = QLabel(label_txt)
            lbl.setProperty("role", "mutedBody")
            row.addWidget(lbl)
            row.addStretch(1)
            row.addWidget(selector)
            inner.addLayout(row)
            selector.changed.connect(self._on_interval_changed)

        self.reminder_message_row = QWidget()
        msg_layout = QHBoxLayout(self.reminder_message_row)
        msg_layout.setContentsMargins(0, 0, 0, 0)
        msg_layout.setSpacing(12)
        msg_lbl = QLabel("Reminder message")
        msg_lbl.setProperty("role", "mutedBody")
        self.reminder_message_edit = QLineEdit()
        self.reminder_message_edit.setObjectName("saveReminderMessageEdit")
        self.reminder_message_edit.setPlaceholderText(DEFAULT_REMINDER_MESSAGE)
        self.reminder_message_edit.setMinimumWidth(260)
        with QSignalBlocker(self.reminder_message_edit):
            self.reminder_message_edit.setText(normalize_reminder_message(settings.save_reminder_message))
        self.reminder_message_edit.editingFinished.connect(self._on_message_finished)
        msg_layout.addWidget(msg_lbl)
        msg_layout.addStretch(1)
        msg_layout.addWidget(self.reminder_message_edit)
        inner.addWidget(self.reminder_message_row)
        self.reminder_message_row.setVisible(self._reminder_sel.value() > 0)

    def refresh_theme(self) -> None:
        """Re-apply theme colors to inputs and combo popups inside this card."""
        self.setStyleSheet(_card_stylesheet())

    @property
    def repeat_combo(self) -> QComboBox:
        return self._repeat_sel.combo

    @property
    def repeat_spin(self) -> QSpinBox:
        return self._repeat_sel.spin

    @property
    def duration_combo(self) -> QComboBox:
        return self._duration_sel.combo

    @property
    def duration_spin(self) -> QSpinBox:
        return self._duration_sel.spin

    @property
    def reminder_combo(self) -> QComboBox:
        return self._reminder_sel.combo

    @property
    def reminder_spin(self) -> QSpinBox:
        return self._reminder_sel.spin

    def apply_to(self, settings: AppSettings) -> None:
        """Copy notification and reminder UI values into ``settings``."""
        settings.new_file_notifications = self.new_file_cb.isChecked()
        settings.repeated_save_interval = self._repeat_sel.value()
        settings.notification_duration_sec = self._duration_sel.value()
        settings.save_reminder_minutes = self._reminder_sel.value()
        settings.save_reminder_message = normalize_reminder_message(self.reminder_message_edit.text())

    def _on_interval_changed(self) -> None:
        self.reminder_message_row.setVisible(self._reminder_sel.value() > 0)
        self.settings_changed.emit()

    def _on_message_finished(self) -> None:
        normalized = normalize_reminder_message(self.reminder_message_edit.text())
        if self.reminder_message_edit.text() != normalized:
            with QSignalBlocker(self.reminder_message_edit):
                self.reminder_message_edit.setText(normalized)
        self.settings_changed.emit()

    def _emit_changed(self) -> None:
        self.settings_changed.emit()
