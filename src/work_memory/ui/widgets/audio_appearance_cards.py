"""Audio volume, mute, test-sound, and Soft Light / Dark appearance settings cards."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from work_memory.config.settings import AppSettings, normalize_theme_mode, normalize_volume
from work_memory.media.sound_effects import SoundEffectsPlayer
from work_memory.ui.theme import get_palette


class AudioSettingsCard(QFrame):
    """Settings card for UI sound enable, volume slider, mute toggle, and live test cues."""

    settings_changed = Signal()

    def __init__(
        self,
        settings: AppSettings,
        *,
        sound_player: SoundEffectsPlayer | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._sound_player = sound_player
        self.setProperty("surface", True)

        inner = QVBoxLayout(self)
        inner.setContentsMargins(20, 18, 20, 18)
        inner.setSpacing(12)

        heading = QLabel("Sound & audio cues")
        heading.setProperty("role", "sectionTitle")
        inner.addWidget(heading)

        self.enable_sounds_cb = QCheckBox(
            "Play subtle sounds for screenshots and notifications"
        )
        self.enable_sounds_cb.setObjectName("enableSoundsCheckBox")
        with QSignalBlocker(self.enable_sounds_cb):
            self.enable_sounds_cb.setChecked(settings.enable_sounds)
        self.enable_sounds_cb.toggled.connect(self._on_controls_changed)
        inner.addWidget(self.enable_sounds_cb)

        row = QHBoxLayout()
        row.setSpacing(10)
        vol_lbl = QLabel("Volume")
        vol_lbl.setProperty("role", "mutedBody")

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("soundVolumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setSingleStep(5)
        self.volume_slider.setPageStep(10)
        self.volume_slider.setMinimumWidth(140)
        with QSignalBlocker(self.volume_slider):
            self.volume_slider.setValue(normalize_volume(settings.sound_volume, 70))
        self.volume_slider.valueChanged.connect(self._on_volume_changed)

        self.volume_value_lbl = QLabel(f"{self.volume_slider.value()}%")
        self.volume_value_lbl.setObjectName("soundVolumeValueLabel")
        self.volume_value_lbl.setFixedWidth(38)
        self.volume_value_lbl.setProperty("role", "mutedBody")

        self.mute_btn = QPushButton("Muted" if settings.sound_muted else "Mute")
        self.mute_btn.setObjectName("soundMuteButton")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        with QSignalBlocker(self.mute_btn):
            self.mute_btn.setChecked(settings.sound_muted)
        self.mute_btn.toggled.connect(self._on_mute_toggled)

        self.test_ding_btn = QPushButton("Test ding")
        self.test_ding_btn.setObjectName("testDingButton")
        self.test_ding_btn.setProperty("secondary", True)
        self.test_ding_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.test_ding_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_ding_btn.clicked.connect(self._on_test_ding)

        self.test_click_btn = QPushButton("Test click")
        self.test_click_btn.setObjectName("testClickButton")
        self.test_click_btn.setProperty("secondary", True)
        self.test_click_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.test_click_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_click_btn.clicked.connect(self._on_test_click)

        row.addWidget(vol_lbl)
        row.addWidget(self.volume_slider, 1)
        row.addWidget(self.volume_value_lbl)
        row.addWidget(self.mute_btn)
        row.addWidget(self.test_ding_btn)
        row.addWidget(self.test_click_btn)
        inner.addLayout(row)

        self.refresh_theme()
        self._sync_enabled_state()

    def set_sound_player(self, sound_player: SoundEffectsPlayer | None) -> None:
        """Bind or update the ``SoundEffectsPlayer`` used for live audio tests."""
        self._sound_player = sound_player

    def apply_to(self, settings: AppSettings) -> None:
        """Copy sound toggle, volume slider, and mute button state into ``settings``."""
        settings.enable_sounds = self.enable_sounds_cb.isChecked()
        settings.sound_volume = int(self.volume_slider.value())
        settings.sound_muted = self.mute_btn.isChecked()

    def refresh_theme(self) -> None:
        """Re-apply active palette colors to slider and mute toggle."""
        pal = get_palette()
        self.volume_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height: 4px; background: {pal.border}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {pal.accent}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -4px 0; "
            f"background: {pal.text}; border-radius: 6px; }}"
        )
        muted = self.mute_btn.isChecked()
        self.mute_btn.setText("Muted" if muted else "Mute")
        if muted:
            self.mute_btn.setStyleSheet(
                f"QPushButton {{ background-color: {pal.panel_alt}; color: {pal.amber}; "
                f"border: 1px solid {pal.amber}; border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; }}"
            )
        else:
            self.mute_btn.setStyleSheet(
                f"QPushButton {{ background-color: {pal.panel_alt}; color: {pal.soft}; "
                f"border: 1px solid {pal.border}; border-radius: 8px; padding: 6px 12px; font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {pal.hover_border}; color: {pal.text}; }}"
            )

    def _sync_enabled_state(self) -> None:
        on = self.enable_sounds_cb.isChecked()
        muted = self.mute_btn.isChecked()
        self.volume_slider.setEnabled(on and not muted)
        self.mute_btn.setEnabled(on)
        self.test_ding_btn.setEnabled(on and not muted)
        self.test_click_btn.setEnabled(on and not muted)

    def _on_controls_changed(self) -> None:
        self._sync_enabled_state()
        self.settings_changed.emit()

    def _on_volume_changed(self, value: int) -> None:
        self.volume_value_lbl.setText(f"{value}%")
        self.settings_changed.emit()

    def _on_mute_toggled(self, _checked: bool) -> None:
        self.refresh_theme()
        self._sync_enabled_state()
        self.settings_changed.emit()

    def _on_test_ding(self) -> None:
        if self._sound_player is not None:
            self._sound_player.play_test_ding()

    def _on_test_click(self) -> None:
        if self._sound_player is not None:
            self._sound_player.play_test_click()


class AppearanceSettingsCard(QFrame):
    """Settings card to switch cleanly between Calm Dark and Soft Warm-Paper Light themes."""

    theme_changed = Signal(str)

    def __init__(self, theme_mode: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("surface", True)

        inner = QVBoxLayout(self)
        inner.setContentsMargins(20, 18, 20, 18)
        inner.setSpacing(10)

        heading = QLabel("Appearance")
        heading.setProperty("role", "sectionTitle")
        inner.addWidget(heading)

        row = QHBoxLayout()
        row.setSpacing(12)
        hint = QLabel("Theme palette (avoiding harsh pure white in light mode)")
        hint.setProperty("role", "mutedBody")
        hint.setWordWrap(True)

        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("themeModeCombo")
        self.theme_combo.addItem("Dark (Calm Charcoal)", "dark")
        self.theme_combo.addItem("Light (Soft Warm Paper)", "light")
        self.set_theme_mode(theme_mode)
        self.theme_combo.currentIndexChanged.connect(
            lambda: self.theme_changed.emit(self.theme_mode())
        )

        row.addWidget(hint, 1)
        row.addWidget(self.theme_combo)
        inner.addLayout(row)

    def theme_mode(self) -> str:
        """Return currently selected theme mode (``'dark'`` or ``'light'``)."""
        return normalize_theme_mode(self.theme_combo.currentData())

    def set_theme_mode(self, mode: str) -> None:
        """Select ``mode`` in the theme dropdown without emitting ``theme_changed``."""
        normalized = normalize_theme_mode(mode)
        with QSignalBlocker(self.theme_combo):
            idx = self.theme_combo.findData(normalized)
            if idx >= 0:
                self.theme_combo.setCurrentIndex(idx)
