"""Storage & portability settings card: custom data folder, .wmem import, backup & restore."""

from __future__ import annotations

import zipfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.config.paths import AppPaths, is_likely_cloud_synced_path
from work_memory.services.backup_service import BackupService
from work_memory.services.manifest_service import ManifestService
from work_memory.services.project_service import ProjectService


class PortabilityCard(QFrame):
    """Calm dark settings card for data folder relocation, .wmem import, and backups."""

    def __init__(
        self,
        app_paths: AppPaths,
        *,
        backup_service: BackupService | None = None,
        manifest_service: ManifestService | None = None,
        project_service: ProjectService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_paths = app_paths
        self._backup_service = backup_service
        self._manifest_service = manifest_service
        self._project_service = project_service
        self.setProperty("surface", True)

        inner = QVBoxLayout(self)
        inner.setContentsMargins(20, 18, 20, 18)
        inner.setSpacing(10)

        heading = QLabel("Storage & portability")
        heading.setProperty("role", "sectionTitle")
        inner.addWidget(heading)

        self._data_dir_pill = self._add_path_row(inner, "App data", str(app_paths.base_dir))
        self._add_path_row(inner, "Database", str(app_paths.db_path))
        self._add_path_row(inner, "Attachments", str(app_paths.attachments_dir))
        self._add_path_row(inner, "Drafts", str(app_paths.drafts_dir))
        self._add_path_row(inner, "Logs", str(app_paths.logs_dir))

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 0, 0)
        actions.setSpacing(8)
        self._change_dir_btn = self._make_btn("Change folder...", "changeDataFolderButton", self._on_change_folder)
        self._import_btn = self._make_btn("Import project (.wmem)...", "importWmemButton", self._on_import_wmem)
        self._backup_btn = self._make_btn("Create backup...", "createBackupButton", self._on_create_backup)
        self._restore_btn = self._make_btn("Restore backup...", "restoreBackupButton", self._on_restore_backup)

        self._change_dir_btn.setEnabled(backup_service is not None)
        self._import_btn.setEnabled(manifest_service is not None)
        self._backup_btn.setEnabled(backup_service is not None)
        self._restore_btn.setEnabled(backup_service is not None)

        for btn in (self._change_dir_btn, self._import_btn, self._backup_btn, self._restore_btn):
            actions.addWidget(btn)
        actions.addStretch(1)
        inner.addLayout(actions)

    @staticmethod
    def _add_path_row(parent: QVBoxLayout, label_text: str, path_text: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(12)
        key_label = QLabel(label_text)
        key_label.setProperty("role", "mutedBody")
        value_label = QLabel(path_text)
        value_label.setProperty("role", "monoPill")
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(key_label)
        row.addStretch(1)
        row.addWidget(value_label)
        parent.addLayout(row)
        return value_label

    @staticmethod
    def _make_btn(text: str, obj_name: str, slot: object) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName(obj_name)
        btn.setProperty("secondary", True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)  # type: ignore[arg-type]
        return btn

    def _on_change_folder(self) -> None:
        if self._backup_service is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Select Work Memory data folder")
        if not folder:
            return
        target = Path(folder)
        if is_likely_cloud_synced_path(target):
            ans = QMessageBox.warning(
                self,
                "Cloud-synced folder detected",
                "This path appears to be inside a cloud-synced folder (e.g., OneDrive, Dropbox, Google Drive).\n"
                "Placing a live SQLite database in a cloud-synced folder can cause file locks or corruption.\n\n"
                "Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        try:
            relocated = self._backup_service.relocate_data_dir(target)
        except (OSError, PermissionError, ValueError) as exc:
            QMessageBox.warning(self, "Unable to relocate data folder", str(exc))
            return
        self._data_dir_pill.setText(str(relocated))
        QMessageBox.information(
            self,
            "Data folder updated",
            f"Data copied to:\n{relocated}\n\nPlease restart Work Memory to switch to the new folder.",
        )

    def _on_import_wmem(self) -> None:
        if self._manifest_service is None:
            return
        bundle, _ = QFileDialog.getOpenFileName(
            self, "Import project memory (.wmem)", "", "Work Memory Bundle (*.wmem)"
        )
        if not bundle:
            return
        try:
            preview = self._manifest_service.inspect_bundle(bundle)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            QMessageBox.warning(self, "Invalid .wmem bundle", str(exc))
            return

        conflict_mode: str = "merge"
        if self._project_service is not None and self._project_service.get_project(preview.project_id) is not None:
            box = QMessageBox(self)
            box.setWindowTitle("Project already exists")
            box.setText(f'Project "{preview.project_name}" already exists in Work Memory.')
            merge_btn = box.addButton("Merge missing", QMessageBox.ButtonRole.AcceptRole)
            copy_btn = box.addButton("Import as copy", QMessageBox.ButtonRole.ActionRole)
            cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked == cancel_btn:
                return
            conflict_mode = "copy" if clicked == copy_btn else "merge"
            del merge_btn

        folder = QFileDialog.getExistingDirectory(
            self, f'Locate folder for "{preview.project_name}" (Cancel to import history only)'
        )
        target_folder = Path(folder) if folder else None
        try:
            res = self._manifest_service.import_project_bundle(
                bundle, target_project_folder=target_folder, conflict_mode=conflict_mode  # type: ignore[arg-type]
            )
        except (OSError, PermissionError, ValueError, zipfile.BadZipFile) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        msg = (
            f"Imported {res.imported_counts.get('capture_entries', 0)} notes, "
            f"{res.imported_counts.get('observed_events', 0)} file events, "
            f"{res.imported_counts.get('attachments', 0)} attachments, "
            f"{res.imported_counts.get('calendar_events', 0)} calendar events."
        )
        if res.missing_files:
            msg += f"\n\n{len(res.missing_files)} referenced project file(s) are not present on disk."
        QMessageBox.information(self, "Import complete", msg)

    def _on_create_backup(self) -> None:
        if self._backup_service is None:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Create full backup", "work_memory_backup.zip", "ZIP Archive (*.zip)"
        )
        if not dest:
            return
        try:
            saved = self._backup_service.create_full_backup(dest)
        except (OSError, PermissionError, ValueError) as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))
            return
        QMessageBox.information(self, "Backup created", f"Backup saved to:\n{saved}")

    def _on_restore_backup(self) -> None:
        if self._backup_service is None:
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "Restore full backup", "", "ZIP Archive (*.zip)"
        )
        if not src:
            return
        confirm = QMessageBox.question(
            self,
            "Restore backup?",
            "Restoring will replace your current Work Memory database and attachments "
            "(a .pre_restore.bak copy is kept in logs/).\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._backup_service.restore_full_backup(src)
        except (OSError, PermissionError, ValueError, zipfile.BadZipFile) as exc:
            QMessageBox.warning(self, "Restore failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Restore complete",
            "Backup restored cleanly. Restart Work Memory if settings were also restored.",
        )
