"""Color palettes for Work Memory's Calm Dark and Soft Warm-Paper Light themes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThemePalette:
    """Complete semantic color tokens for either ``'dark'`` or ``'light'`` theme."""

    mode: str
    bg: str
    panel: str
    panel_alt: str
    border: str
    border_soft: str
    text: str
    muted: str
    soft: str
    accent: str
    accent_bg: str
    green: str
    amber: str
    purple: str
    scrollbar_handle: str
    scrollbar_hover: str
    input_bg: str
    focus_border: str
    hover_border: str
    primary_bg: str
    primary_hover: str
    primary_text: str
    primary_disabled_bg: str
    section_title: str
    body_text: str
    dim_text: str
    pill_active_border: str
    pill_paused_border: str
    brand_logo_bg: str
    brand_logo_fg: str
    nav_indicator: str
    cal_selected_bg: str
    cal_selected_border: str
    cal_selected_text: str
    cal_today_bg: str
    cal_today_border: str
    cal_hover_bg: str
    cal_in_month_text: str
    cal_out_month_text: str
    titlebar_bg: str
    titlebar_text: str
    row_hover_rgba: str
    danger_text: str
    danger_border: str


DARK_PALETTE = ThemePalette(
    mode="dark",
    bg="#17191d",
    panel="#1e2126",
    panel_alt="#24282e",
    border="#30353d",
    border_soft="#262a31",
    text="#edf0f3",
    muted="#929aa5",
    soft="#c2c8d0",
    accent="#a9b8df",
    accent_bg="#2a3242",
    green="#8dbda4",
    amber="#d8b57c",
    purple="#b7a6de",
    scrollbar_handle="#2d323b",
    scrollbar_hover="#3d4450",
    input_bg="#202329",
    focus_border="#535d6e",
    hover_border="#4b5361",
    primary_bg="#dce3f1",
    primary_hover="#ebf0f9",
    primary_text="#20242b",
    primary_disabled_bg="#4b5260",
    section_title="#cbd1d8",
    body_text="#c3cad2",
    dim_text="#78828e",
    pill_active_border="#3a5247",
    pill_paused_border="#544730",
    brand_logo_bg="#343b47",
    brand_logo_fg="#d9e1f3",
    nav_indicator="#aab9df",
    cal_selected_bg="#2d3b55",
    cal_selected_border="#7f95c7",
    cal_selected_text="#f4f7fc",
    cal_today_bg="#212733",
    cal_today_border="#55627a",
    cal_hover_bg="#2a2f37",
    cal_in_month_text="#bfc5cd",
    cal_out_month_text="#505863",
    titlebar_bg="#17191d",
    titlebar_text="#edf0f3",
    row_hover_rgba="rgba(255, 255, 255, 0.045)",
    danger_text="#e58f8f",
    danger_border="#a15252",
)

# Soft warm paper / oatmeal light palette — intentionally avoids pure #ffffff.
LIGHT_PALETTE = ThemePalette(
    mode="light",
    bg="#eae6df",
    panel="#f2efe9",
    panel_alt="#e2ddd4",
    border="#cfc9be",
    border_soft="#dbd6cc",
    text="#23272e",
    muted="#666d78",
    soft="#434954",
    accent="#4a66a0",
    accent_bg="#d5deee",
    green="#387a5b",
    amber="#9e6d2b",
    purple="#6d56a0",
    scrollbar_handle="#c2bbb0",
    scrollbar_hover="#aba396",
    input_bg="#f5f2ec",
    focus_border="#7689ae",
    hover_border="#b3ab9f",
    primary_bg="#3b4e73",
    primary_hover="#4a618e",
    primary_text="#f2efe9",
    primary_disabled_bg="#c9c2b8",
    section_title="#2e333c",
    body_text="#363b45",
    dim_text="#6d7480",
    pill_active_border="#7fae98",
    pill_paused_border="#c4a678",
    brand_logo_bg="#24282e",
    brand_logo_fg="#edf0f3",
    nav_indicator="#4a66a0",
    cal_selected_bg="#cfd9ec",
    cal_selected_border="#5a74ab",
    cal_selected_text="#1d2636",
    cal_today_bg="#e4dfd5",
    cal_today_border="#8b96ab",
    cal_hover_bg="#dcd6cc",
    cal_in_month_text="#3a3f48",
    cal_out_month_text="#9fa4ad",
    titlebar_bg="#e8e4dc",
    titlebar_text="#23272e",
    row_hover_rgba="rgba(35, 39, 46, 0.05)",
    danger_text="#a84444",
    danger_border="#c27a7a",
)
