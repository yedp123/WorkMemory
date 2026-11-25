"""Calm Projects landing view with independent scroll, gallery modes, and discovery whisper."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QVBoxLayout,
    QWidget,
)

from work_memory.config.paths import AppPaths
from work_memory.config.settings import AppSettings, normalize_gallery_view_mode, save_settings
from work_memory.core.event_bus import EventBus
from work_memory.core.models import Project, ProjectSuggestion
from work_memory.services.project_service import ProjectService
from work_memory.services.relink_service import RelinkService
from work_memory.ui.views.delete_project_dialog import DeleteProjectDialog
from work_memory.ui.views.register_project_dialog import (
    RegisterProjectDialog,
    RegisterProjectInput,
    local_date_to_created_utc,
)
from work_memory.ui.widgets import cover_actions as ca
from work_memory.ui.widgets import gallery_controls as gc
from work_memory.ui.widgets.project_card import ProjectCard
from work_memory.ui.widgets.project_date_groups import populate_grouped_sections
from work_memory.ui.widgets.project_hero import relink_project_with_dialog
from work_memory.ui.widgets.scroll_helpers import wrap_in_scroll_area
from work_memory.ui.workers import run_in_pool


class ProjectsView(QWidget):
    """Primary Projects view presenting calm cards, live search, and subtle suggestions."""

    project_selected = Signal(str)
    project_deleted = Signal(str)

    def __init__(
        self,
        project_service: ProjectService | None = None,
        event_bus: EventBus | None = None,
        parent: QWidget | None = None,
        *,
        relink_service: RelinkService | None = None,
        settings: AppSettings | None = None,
        app_paths: AppPaths | None = None,
        workspace_roots_provider: Callable[[], Sequence[Path]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_service, self._event_bus = project_service, event_bus
        self._relink_service = relink_service
        self._settings, self._app_paths = settings, app_paths
        self._workspace_roots_provider = workspace_roots_provider
        self._view_mode = normalize_gallery_view_mode(
            settings.gallery_view_mode if settings is not None else "medium"
        )
        self._projects: list[Project] = []
        self._suggestions: list[ProjectSuggestion] = []
        self._search_query, self._refresh_seq = "", 0
        self._active_workers: set[QObject] = set()
        self._collapsed_years: set[int] = set()

        self._scroll_area, _content, layout = wrap_in_scroll_area(
            self, margins=(0, 30, 0, 40), spacing=16
        )
        self._grid_columns = gc.compute_gallery_columns(self._view_mode, self._viewport_width())

        layout.addLayout(self._build_header())
        self._whisper = gc.build_discovery_whisper(
            self._on_confirm_suggestion, self._on_dismiss_suggestion
        )
        self._whisper_bar = self._whisper.bar
        self._whisper_register_btn = self._whisper.register_btn
        self._whisper_dismiss_btn = self._whisper.dismiss_btn
        layout.addWidget(self._whisper_bar)

        self._grid_host = QWidget()
        self._sections_layout = QVBoxLayout(self._grid_host)
        self._sections_layout.setContentsMargins(0, 8, 0, 0)
        self._sections_layout.setSpacing(14)
        layout.addWidget(self._grid_host)

        self._empty_panel, self._empty_heading, self._empty_body = gc.build_empty_projects_panel()
        layout.addWidget(self._empty_panel)
        layout.addStretch(1)

        if event_bus is not None:
            event_bus.workspaces_changed.connect(self.refresh_async)
            event_bus.projects_changed.connect(self.refresh_async)
            event_bus.project_updated.connect(self._on_bus_project_updated)
            event_bus.suggestions_changed.connect(self.refresh_async)

        self.refresh_async() if self._project_service is not None else self._render()

    @property
    def scroll_area(self) -> QScrollArea:
        """Return this view's independent ``QScrollArea``."""
        return self._scroll_area

    def vertical_scroll_bar(self) -> QScrollBar:
        """Return this view's vertical scrollbar."""
        return self._scroll_area.verticalScrollBar()

    @property
    def view_mode(self) -> str:
        """Return the active gallery view mode (``list``, ``small``, ``medium``, ``large``)."""
        return self._view_mode

    def set_view_mode(self, mode: str) -> None:
        """Switch gallery view mode, reflow cards, and persist choice if configured."""
        normalized = normalize_gallery_view_mode(mode)
        self._view_mode = normalized
        self._view_switcher.set_mode(normalized)
        self._grid_columns = gc.compute_gallery_columns(normalized, self._viewport_width())
        self._render_grid()
        if self._settings is not None:
            self._settings.gallery_view_mode = normalized
        if self._app_paths is not None:
            target = self._settings or AppSettings(gallery_view_mode=normalized)
            target.gallery_view_mode = normalized
            roots = (
                tuple(self._workspace_roots_provider())
                if self._workspace_roots_provider is not None
                else ()
            )
            save_settings(self._app_paths, target, workspace_roots=roots)

    def cached_projects(self) -> list[Project]:
        """Return the latest projects loaded into this view."""
        return list(self._projects)

    def set_search_query(self, query: str) -> None:
        """Filter displayed projects live (completed projects stay searchable)."""
        self._search_query = query.strip().lower()
        self._render_grid()

    def refresh_theme(self) -> None:
        """Re-render gallery cards and switcher using active theme colors."""
        self._view_switcher.refresh_theme()
        gc.refresh_whisper_theme(self._whisper)
        self._render_grid()

    @Slot(object)
    def _on_bus_project_updated(self, _project: object) -> None:
        self.refresh_async()

    def refresh_async(self) -> None:
        """Reload projects and run read-only workspace discovery off the GUI thread."""
        if (service := self._project_service) is None:
            return
        self._refresh_seq += 1
        seq = self._refresh_seq
        run_in_pool(
            self, self._active_workers,
            lambda: (seq, service.list_projects(), service.discover_suggestions()),
            self._on_loaded,
        )

    def _viewport_width(self) -> int:
        vp_w = self._scroll_area.viewport().width()
        return vp_w if vp_w > 0 else self.width()

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 8)
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        for text, role in (("Projects", "pageTitle"), ("Your work, without the filing cabinet.", "subtitle")):
            lbl = QLabel(text)
            lbl.setProperty("role", role)
            title_col.addWidget(lbl)

        self._view_switcher = gc.ViewModeSwitcher(self._view_mode)
        self._view_switcher.mode_changed.connect(self.set_view_mode)

        self._register_btn = QPushButton("+ Register project")
        self._register_btn.setObjectName("registerProjectButton")
        self._register_btn.setProperty("primary", True)
        self._register_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._register_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._register_btn.setEnabled(self._project_service is not None)
        self._register_btn.clicked.connect(self._on_open_register_dialog)
        header.addLayout(title_col, 1)
        header.addWidget(self._view_switcher, 0, Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self._register_btn, 0, Qt.AlignmentFlag.AlignBottom)
        return header

    def _on_loaded(self, payload: object) -> None:
        seq, projects, suggestions = payload  # type: ignore[misc]
        if seq != self._refresh_seq:
            return
        self._projects, self._suggestions = list(projects), list(suggestions)
        self._render()

    def _render(self) -> None:
        gc.update_discovery_whisper(self._whisper, self._suggestions)
        self._render_grid()

    def _filtered_projects(self) -> list[Project]:
        if not (q := self._search_query):
            return self._projects
        return [p for p in self._projects if q in f"{p.name} {p.description} {p.rel_path} {p.abs_path} {p.status}".lower()]

    def _make_project_card(self, project: Project) -> ProjectCard:
        cover_path = (
            self._project_service.get_project_cover_path(project)
            if self._project_service is not None
            else None
        )
        card = ProjectCard(
            project, view_mode=self._view_mode, cover_pixmap=ca.load_cover_pixmap(cover_path),
        )
        card.clicked.connect(self.project_selected.emit)
        card.pin_toggled.connect(self._on_pin_toggled)
        card.relink_requested.connect(self._on_relink_requested)
        card.change_cover_requested.connect(self._on_change_cover_requested)
        card.reset_cover_requested.connect(self._on_reset_cover_requested)
        card.delete_requested.connect(self._on_delete_requested)
        return card

    def _on_year_section_toggled(self, year: int, expanded: bool) -> None:
        if expanded:
            self._collapsed_years.discard(year)
        else:
            self._collapsed_years.add(year)

    def _render_grid(self) -> None:
        while self._sections_layout.count():
            if (item := self._sections_layout.takeAt(0)) is not None and (w := item.widget()) is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        visible = self._filtered_projects()
        if not visible:
            self._grid_host.setVisible(False)
            self._empty_panel.setVisible(True)
            gc.update_empty_projects_panel(
                self._empty_heading,
                self._empty_body,
                has_projects=bool(self._projects),
                search_query=self._search_query,
            )
            return

        self._empty_panel.setVisible(False)
        self._grid_host.setVisible(True)
        populate_grouped_sections(
            self._sections_layout,
            visible,
            collapsed_years=self._collapsed_years,
            view_mode=self._view_mode,
            cols=self._grid_columns,
            make_card=self._make_project_card,
            on_year_toggled=self._on_year_section_toggled,
        )

    def resizeEvent(self, event: QEvent) -> None:
        """Reflow columns cleanly for the active view mode when the window resizes."""
        super().resizeEvent(event)  # type: ignore[arg-type]
        next_cols = gc.compute_gallery_columns(self._view_mode, self._viewport_width())
        if next_cols != self._grid_columns:
            self._grid_columns = next_cols
            self._render_grid()

    def _on_pin_toggled(self, project_id: str) -> None:
        if (service := self._project_service) is None:
            return
        run_in_pool(self, self._active_workers, lambda: service.toggle_pin(project_id), lambda _p: self.refresh_async(), self._show_task_error)

    def _on_open_register_dialog(self) -> None:
        if self._project_service is None:
            return
        dialog = RegisterProjectDialog(self)
        if dialog.exec() == RegisterProjectDialog.DialogCode.Accepted and (data := dialog.result_input()):
            self._register_from_input(data)

    def _register_from_input(self, data: RegisterProjectInput) -> None:
        if (service := self._project_service) is None:
            return
        created_ts = local_date_to_created_utc(data.created_date) if data.created_date is not None else None
        def _work() -> Project:
            if data.create_folder:
                return service.create_new_project(
                    data.folder_path, name=data.name, description=data.description,
                    confirm_create_folder=True, created_at_utc=created_ts,
                )
            return service.register_existing_project(
                data.folder_path, name=data.name, description=data.description, created_at_utc=created_ts,
            )
        run_in_pool(self, self._active_workers, _work, lambda _p: self.refresh_async(), self._show_task_error)

    def _find_project(self, project_id: str) -> Project | None:
        proj = next((p for p in self._projects if p.id == project_id), None)
        if proj is None and self._project_service is not None:
            proj = self._project_service.get_project(project_id)
        return proj

    def _on_delete_requested(self, project_id: str) -> None:
        if (service := self._project_service) is None or (proj := self._find_project(project_id)) is None:
            return
        if DeleteProjectDialog(proj.name, self).exec() == DeleteProjectDialog.DialogCode.Accepted:
            def _on_done(removed: object) -> None:
                if removed:
                    self.project_deleted.emit(project_id)
                self.refresh_async()
            run_in_pool(self, self._active_workers, lambda: service.delete_project(project_id), _on_done, self._show_task_error)

    def _on_confirm_suggestion(self) -> None:
        if (service := self._project_service) is None or not self._suggestions:
            return
        suggestion = self._suggestions.pop(0)
        gc.update_discovery_whisper(self._whisper, self._suggestions)
        on_done = (lambda _p: None) if self._event_bus is not None else (lambda _p: self.refresh_async())
        run_in_pool(self, self._active_workers, lambda: service.confirm_suggestion(suggestion), on_done, self._show_task_error)

    def _on_dismiss_suggestion(self) -> None:
        if (service := self._project_service) is None or not self._suggestions:
            return
        suggestion = self._suggestions.pop(0)
        gc.update_discovery_whisper(self._whisper, self._suggestions)
        on_done = (lambda _r: None) if self._event_bus is not None else (lambda _r: self.refresh_async())
        run_in_pool(self, self._active_workers, lambda: service.dismiss_suggestion(suggestion.workspace_id, suggestion.rel_path), on_done, self._show_task_error)

    def _show_task_error(self, message: str) -> None:
        QMessageBox.warning(self, "Project Registration", message)

    def _on_relink_requested(self, project_id: str) -> None:
        if self._relink_service is not None and relink_project_with_dialog(self, self._relink_service, self._find_project(project_id)) is not None:
            self.refresh_async()

    def _on_change_cover_requested(self, project_id: str) -> None:
        proj = self._find_project(project_id)
        if (chosen := ca.choose_cover_image_dialog(self, proj.name if proj is not None else "project")) is not None:
            ca.run_set_cover_async(self, self._active_workers, self._project_service, project_id, chosen, on_done=lambda _p: self.refresh_async())

    def _on_reset_cover_requested(self, project_id: str) -> None:
        ca.run_clear_cover_async(self, self._active_workers, self._project_service, project_id, on_done=lambda _p: self.refresh_async())
