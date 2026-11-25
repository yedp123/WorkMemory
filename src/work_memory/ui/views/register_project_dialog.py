"""Clean dark dialog to register an existing folder or opt in to create a new one."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.ids import utc_now_iso
from work_memory.ui.theme import get_palette


@dataclass(frozen=True, slots=True)
class RegisterProjectInput:
    """Validated user input collected from ``RegisterProjectDialog``."""

    name: str
    folder_path: str
    description: str
    create_folder: bool
    created_date: date | None = None


def local_date_to_created_utc(chosen: date | None) -> str:
    """Convert a local ``datetime.date`` into an ISO-8601 UTC timestamp string."""
    if chosen is None:
        return utc_now_iso()
    if chosen == date.today():
        local_dt = datetime.now().astimezone()
    else:
        local_dt = datetime.combine(chosen, time(12, 0)).astimezone()
    return local_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class RegisterProjectDialog(QDialog):
    """Modal dialog for registering an existing folder or explicitly creating a new one."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result_input: RegisterProjectInput | None = None
        self._auto_filled_name = ""

        pal = get_palette()
        self._pal = pal
        self.setWindowTitle("Register Project")
        self.setModal(True)
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        title = QLabel("Register Project")
        title.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {pal.text};")
        root.addWidget(title)

        root.addLayout(self._build_name_group())
        root.addLayout(self._build_path_group())

        self._create_checkbox = QCheckBox("Create new empty project folder at this path")
        self._create_checkbox.setObjectName("createFolderCheckbox")
        self._create_checkbox.setChecked(False)
        self._create_checkbox.toggled.connect(self._on_create_toggled)
        root.addWidget(self._create_checkbox)

        root.addLayout(self._build_date_group())
        root.addLayout(self._build_desc_group())

        self._error_label = QLabel()
        self._error_label.setStyleSheet(f"color: {pal.amber}; font-size: 12px;")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        root.addLayout(self._build_footer())

    def result_input(self) -> RegisterProjectInput | None:
        """Return validated dialog input after acceptance, or ``None`` if cancelled."""
        return self._result_input

    def _build_name_group(self) -> QVBoxLayout:
        group = QVBoxLayout()
        group.setSpacing(5)
        label = QLabel("Project name")
        label.setStyleSheet(f"font-size: 12px; color: {self._pal.muted};")
        self._name_input = QLineEdit()
        self._name_input.setObjectName("regNameInput")
        self._name_input.setProperty("darkInput", True)
        self._name_input.setPlaceholderText("e.g. Character Rigging Study")
        group.addWidget(label)
        group.addWidget(self._name_input)
        return group

    def _build_path_group(self) -> QVBoxLayout:
        group = QVBoxLayout()
        group.setSpacing(5)
        self._path_label = QLabel("Existing folder path")
        self._path_label.setStyleSheet(f"font-size: 12px; color: {self._pal.muted};")

        row = QHBoxLayout()
        row.setSpacing(8)
        self._path_input = QLineEdit()
        self._path_input.setObjectName("regPathInput")
        self._path_input.setProperty("darkInput", True)
        self._path_input.setPlaceholderText(r"e.g. D:\Projects\Rigging_Study")

        browse_btn = QPushButton("Browse...")
        browse_btn.setObjectName("regBrowseButton")
        browse_btn.setProperty("secondary", True)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._on_browse)

        row.addWidget(self._path_input, 1)
        row.addWidget(browse_btn)
        group.addWidget(self._path_label)
        group.addLayout(row)
        return group

    def _build_date_group(self) -> QHBoxLayout:
        pal = self._pal
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel("Creation date (MM/DD/YYYY)")
        label.setStyleSheet(f"font-size: 12px; color: {pal.muted};")
        self._created_date_edit = QDateEdit(QDate.currentDate())
        self._created_date_edit.setObjectName("regCreatedDateEdit")
        self._created_date_edit.setDisplayFormat("MM/dd/yyyy")
        self._created_date_edit.setCalendarPopup(True)
        self._created_date_edit.setMinimumWidth(140)
        self._created_date_edit.setStyleSheet(
            f"QDateEdit {{ background-color: {pal.input_bg}; color: {pal.text}; "
            f"border: 1px solid {pal.border}; border-radius: 8px; padding: 6px 10px; font-size: 12px; }}"
            f"QDateEdit:focus {{ border-color: {pal.focus_border}; }}"
        )
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self._created_date_edit)
        return row

    def _build_desc_group(self) -> QVBoxLayout:
        group = QVBoxLayout()
        group.setSpacing(5)
        label = QLabel("Short description (optional)")
        label.setStyleSheet(f"font-size: 12px; color: {self._pal.muted};")
        self._desc_input = QLineEdit()
        self._desc_input.setObjectName("regDescInput")
        self._desc_input.setProperty("darkInput", True)
        self._desc_input.setPlaceholderText("What is this project about?")
        group.addWidget(label)
        group.addWidget(self._desc_input)
        return group

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 6, 0, 0)
        footer.setSpacing(10)

        self._safety_hint = QLabel("Observed read-only. Files stay where they are.")
        self._safety_hint.setStyleSheet(f"font-size: 11px; color: {self._pal.muted};")

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("secondary", True)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        self._confirm_btn = QPushButton("Register")
        self._confirm_btn.setObjectName("regConfirmButton")
        self._confirm_btn.setProperty("primary", True)
        self._confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm_btn.clicked.connect(self._on_confirm)

        footer.addWidget(self._safety_hint, 1)
        footer.addWidget(cancel_btn)
        footer.addWidget(self._confirm_btn)
        return footer

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select project folder")
        if not folder:
            return
        self._path_input.setText(folder)
        current_name = self._name_input.text().strip()
        if not current_name or current_name == self._auto_filled_name:
            inferred = Path(folder).name
            self._name_input.setText(inferred)
            self._auto_filled_name = inferred

    def _on_create_toggled(self, checked: bool) -> None:
        if checked:
            self._path_label.setText("New project folder path")
            self._safety_hint.setText("Creates one empty folder at your confirmed path.")
            self._confirm_btn.setText("Create & Register")
        else:
            self._path_label.setText("Existing folder path")
            self._safety_hint.setText("Observed read-only. Files stay where they are.")
            self._confirm_btn.setText("Register")
        self._error_label.setVisible(False)

    def _on_confirm(self) -> None:
        folder_text = self._path_input.text().strip()
        name_text = self._name_input.text().strip()
        create_folder = self._create_checkbox.isChecked()

        if not folder_text:
            self._show_error("Please choose or enter a folder path.")
            return

        target = Path(folder_text).expanduser()
        if not name_text:
            name_text = target.name
        if not name_text:
            self._show_error("Please enter a project name.")
            return

        if not create_folder and not target.is_dir():
            self._show_error(
                "Folder does not exist. Choose an existing folder or check "
                "'Create new empty project folder at this path'."
            )
            return
        if create_folder and target.exists() and not target.is_dir():
            self._show_error("A file already exists at that target path.")
            return

        qd = self._created_date_edit.date()
        self._result_input = RegisterProjectInput(
            name=name_text,
            folder_path=str(target),
            description=self._desc_input.text().strip(),
            create_folder=create_folder,
            created_date=date(qd.year(), qd.month(), qd.day()) if qd.isValid() else None,
        )
        self.accept()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)
