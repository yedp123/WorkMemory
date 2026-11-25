"""Theme state manager and Qt stylesheet builder for Dark and Soft Light themes."""

from __future__ import annotations

from work_memory.config.settings import normalize_theme_mode
from work_memory.ui.theme_palettes import DARK_PALETTE, LIGHT_PALETTE, ThemePalette

_ACTIVE_MODE = "dark"
BG = DARK_PALETTE.bg
PANEL = DARK_PALETTE.panel
PANEL_ALT = DARK_PALETTE.panel_alt
BORDER = DARK_PALETTE.border
BORDER_SOFT = DARK_PALETTE.border_soft
TEXT = DARK_PALETTE.text
MUTED = DARK_PALETTE.muted
SOFT = DARK_PALETTE.soft
ACCENT = DARK_PALETTE.accent
ACCENT_BG = DARK_PALETTE.accent_bg
GREEN = DARK_PALETTE.green
AMBER = DARK_PALETTE.amber
PURPLE = DARK_PALETTE.purple


def get_palette(mode: str | None = None) -> ThemePalette:
    """Return the ``ThemePalette`` for ``mode`` or the currently active theme."""
    resolved = normalize_theme_mode(mode if mode is not None else _ACTIVE_MODE)
    return LIGHT_PALETTE if resolved == "light" else DARK_PALETTE


def active_theme_mode() -> str:
    """Return the active theme mode (``'dark'`` or ``'light'``)."""
    return _ACTIVE_MODE


def set_active_theme(mode: str) -> ThemePalette:
    """Update the active theme palette and sync legacy module-level constants."""
    global _ACTIVE_MODE, BG, PANEL, PANEL_ALT, BORDER, BORDER_SOFT, TEXT, MUTED
    global SOFT, ACCENT, ACCENT_BG, GREEN, AMBER, PURPLE
    pal = get_palette(mode)
    _ACTIVE_MODE = pal.mode
    BG, PANEL, PANEL_ALT = pal.bg, pal.panel, pal.panel_alt
    BORDER, BORDER_SOFT = pal.border, pal.border_soft
    TEXT, MUTED, SOFT = pal.text, pal.muted, pal.soft
    ACCENT, ACCENT_BG = pal.accent, pal.accent_bg
    GREEN, AMBER, PURPLE = pal.green, pal.amber, pal.purple
    return pal


def build_stylesheet(mode: str | None = None) -> str:
    """Return the calm QSS stylesheet for ``mode`` (or active theme)."""
    p = get_palette(mode)
    return f"""
        QMainWindow, QWidget#rootSurface, QScrollArea, QWidget#scrollContent {{
            background-color: {p.bg}; color: {p.text}; border: none;
            font-family: "Segoe UI", "Inter", sans-serif; font-size: 14px;
        }}
        QScrollArea#embeddedScrollArea, QWidget#embeddedScrollContent {{
            background-color: transparent; border: none;
        }}
        QPushButton {{ outline: none; }}
        QScrollBar:vertical {{
            background: {p.bg}; width: 8px; margin: 0px; border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {p.scrollbar_handle}; min-height: 28px; border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {p.scrollbar_hover}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px; width: 0px; border: none; background: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        QScrollBar:horizontal {{
            background: {p.bg}; height: 8px; margin: 0px; border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {p.scrollbar_handle}; min-width: 28px; border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {p.scrollbar_hover}; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            height: 0px; width: 0px; border: none; background: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
        QAbstractScrollArea::corner {{ background: {p.bg}; border: none; }}
        QFrame#topBar, QFrame#navBar {{
            background-color: {p.bg}; border: none; border-bottom: 1px solid {p.border};
        }}
        QLabel#brandLogo {{
            background: transparent; color: {p.brand_logo_fg}; border-radius: 9px;
        }}
        QPushButton#brandButton {{
            background: transparent; border: none; color: {p.text};
            font-size: 16px; font-weight: 600; padding: 0px; text-align: left;
        }}
        QLineEdit#globalSearch {{
            background-color: {p.input_bg}; color: {p.text}; border: 1px solid {p.border};
            border-radius: 9px; padding: 0px 12px; min-height: 38px; max-height: 38px;
            selection-background-color: {p.accent_bg};
        }}
        QLineEdit#globalSearch:focus {{ border-color: {p.focus_border}; }}
        QPushButton#captureButton {{
            background-color: {p.panel}; color: {p.soft}; border: 1px solid {p.border};
            border-radius: 8px; padding: 7px 13px; font-size: 12px; font-weight: 600;
        }}
        QPushButton#captureButton:hover {{
            background-color: {p.panel_alt}; border-color: {p.hover_border}; color: {p.text};
        }}
        QPushButton#settingsButton {{
            background-color: transparent; color: {p.muted}; border: none; border-radius: 8px;
            font-size: 16px; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
        }}
        QPushButton#settingsButton:hover {{ background-color: {p.panel}; color: {p.text}; }}
        QPushButton#settingsButton:checked {{ background-color: {p.panel_alt}; color: {p.text}; }}
        QPushButton#statusDotButton {{
            background-color: {p.green}; border: none; border-radius: 4px;
            min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px;
        }}
        QPushButton#statusDotButton[paused="true"] {{ background-color: {p.amber}; }}
        QPushButton[secondary="true"] {{
            background-color: {p.panel_alt}; color: {p.soft}; border: 1px solid {p.border};
            border-radius: 8px; padding: 7px 12px; font-size: 12px;
        }}
        QPushButton[secondary="true"]:hover {{ border-color: {p.hover_border}; color: {p.text}; }}
        QPushButton[secondary="true"]:disabled {{ color: {p.muted}; border-color: {p.border_soft}; }}
        QPushButton[primary="true"] {{
            background-color: {p.primary_bg}; color: {p.primary_text}; border: none;
            border-radius: 9px; padding: 9px 15px; font-size: 13px; font-weight: 600;
        }}
        QPushButton[primary="true"]:hover {{ background-color: {p.primary_hover}; }}
        QPushButton[primary="true"]:disabled {{ background-color: {p.primary_disabled_bg}; color: {p.muted}; }}
        QPushButton[textButton="true"] {{
            background: transparent; border: none; color: {p.accent}; padding: 4px 0px; font-size: 12px;
        }}
        QPushButton[textButton="true"]:hover {{ text-decoration: underline; }}
        QPushButton#backButton {{
            background: transparent; border: none; color: {p.muted};
            padding: 0px; font-size: 13px; text-align: left;
        }}
        QPushButton#backButton:hover {{ color: {p.text}; }}
        QPushButton#whisperCloseButton {{
            background: transparent; border: none; color: {p.muted}; font-size: 16px; padding: 0px 4px;
        }}
        QPushButton#whisperCloseButton:hover {{ color: {p.soft}; }}
        QLabel[pill="active"] {{
            background-color: transparent; border: 1px solid {p.pill_active_border};
            border-radius: 12px; color: {p.green}; padding: 2px 9px; font-size: 11px;
        }}
        QLabel[pill="paused"] {{
            background-color: transparent; border: 1px solid {p.pill_paused_border};
            border-radius: 12px; color: {p.amber}; padding: 2px 9px; font-size: 11px;
        }}
        QFrame[divider="true"] {{
            background-color: {p.border_soft}; border: none; min-height: 1px; max-height: 1px;
        }}
        QPushButton[navTab="true"] {{
            background: transparent; border: none; border-bottom: 2px solid transparent;
            color: {p.muted}; font-size: 14px; padding: 0px 2px; min-height: 54px; outline: none;
        }}
        QPushButton[navTab="true"]:hover {{ color: {p.soft}; }}
        QPushButton[navTab="true"][active="true"] {{
            color: {p.text}; border-bottom: 2px solid {p.nav_indicator};
        }}
        QFrame[surface="true"] {{
            background-color: {p.panel}; border: 1px solid {p.border}; border-radius: 13px;
        }}
        QFrame#readOnlyBanner {{
            background-color: {p.panel}; border: 1px solid {p.border};
            border-left: 3px solid {p.green}; border-radius: 13px;
        }}
        QFrame#lksPanel {{
            background-color: {p.panel}; border: 1px solid {p.border};
            border-left: 3px solid {p.accent}; border-radius: 13px;
        }}
        QFrame#milestonesPanel {{
            background-color: {p.panel}; border: 1px solid {p.border};
            border-left: 3px solid {p.amber}; border-radius: 13px;
        }}
        QLabel[role="pageTitle"] {{ color: {p.text}; font-size: 28px; font-weight: 600; }}
        QLabel[role="subtitle"] {{ color: {p.muted}; font-size: 13px; }}
        QLabel[role="sectionTitle"] {{ color: {p.section_title}; font-size: 13px; font-weight: 600; }}
        QLabel[role="mutedBody"] {{ color: {p.muted}; font-size: 13px; }}
        QLabel[role="monoPill"] {{
            background-color: {p.panel_alt}; border: 1px solid {p.border}; border-radius: 6px;
            color: {p.soft}; padding: 4px 8px;
            font-family: "Cascadia Code", "Consolas", monospace; font-size: 11px;
        }}
        QLabel[role="fileBadge"] {{
            background-color: {p.panel_alt}; color: {p.accent}; border: 1px solid {p.border};
            border-radius: 7px; font-size: 10px; font-weight: 600;
        }}
        QDialog, QMessageBox {{ background-color: {p.panel}; color: {p.text}; }}
        QMessageBox QLabel {{ color: {p.text}; background: transparent; }}
        QMessageBox QPushButton {{
            background-color: {p.panel_alt}; color: {p.text}; border: 1px solid {p.border};
            border-radius: 8px; padding: 6px 14px; font-size: 12px; min-width: 64px;
        }}
        QMessageBox QPushButton:hover {{ border-color: {p.hover_border}; background-color: {p.panel}; }}
        QMessageBox QPushButton:default {{ border-color: {p.accent}; }}
        QComboBox, QSpinBox, QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {p.input_bg}; color: {p.text}; border: 1px solid {p.border};
            border-radius: 8px; padding: 5px 10px; font-size: 12px;
        }}
        QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
            border-color: {p.focus_border};
        }}
        QComboBox QAbstractItemView {{
            background-color: {p.panel_alt}; color: {p.text};
            border: 1px solid {p.border}; selection-background-color: {p.accent_bg};
        }}
        QMenu {{
            background-color: {p.panel}; color: {p.text}; border: 1px solid {p.border}; padding: 4px;
        }}
        QMenu::item:selected {{ background-color: {p.accent_bg}; color: {p.text}; }}
        QLineEdit[darkInput="true"] {{
            background-color: {p.input_bg}; color: {p.text}; border: 1px solid {p.border};
            border-radius: 8px; padding: 7px 10px; font-size: 12px;
        }}
        QLineEdit[darkInput="true"]:focus {{ border-color: {p.focus_border}; }}
        QCheckBox {{ color: {p.soft}; font-size: 12px; spacing: 8px; }}
        QToolTip {{
            background-color: {p.panel_alt}; color: {p.text}; border: 1px solid {p.border}; padding: 4px 8px;
        }}
    """
