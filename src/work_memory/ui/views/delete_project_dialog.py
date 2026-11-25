"""Modal confirmation dialog requiring typed 'delete' before removing a project."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.ui.theme import get_palette


class DeleteProjectDialog(QDialog):
    """Modal guard requiring the user to type ``delete`` before unregistering a project."""

    def __init__(self, project_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        pal = get_palette()
        self.setWindowTitle("Delete Project")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet(
            f"QDialog {{ background-color: {pal.panel}; color: {pal.text}; border: 1px solid {pal.border}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        prompt = QLabel(
            f'Are you sure you want to delete "{project_name}"?\n'
            'If yes, please write "delete" below and confirm.'
        )
        prompt.setWordWrap(True)
        prompt.setStyleSheet(f"color: {pal.text}; font-size: 14px; font-weight: 600;")
        root.addWidget(prompt)

        hint = QLabel(
            "Your actual project folder and files on disk will NOT be deleted or modified "
            "\u2014 this only removes the project from Work Memory."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {pal.muted}; font-size: 12px;")
        root.addWidget(hint)

        self._confirm_input = QLineEdit()
        self._confirm_input.setObjectName("deleteConfirmInput")
        self._confirm_input.setProperty("darkInput", True)
        self._confirm_input.setPlaceholderText('Type "delete" to confirm')
        self._confirm_input.textChanged.connect(self._on_text_changed)
        self._confirm_input.returnPressed.connect(self._on_return_pressed)
        root.addWidget(self._confirm_input)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 6, 0, 0)
        footer.setSpacing(10)
        footer.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("secondary", True)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        self._confirm_btn = QPushButton("Confirm")
        self._confirm_btn.setObjectName("deleteConfirmButton")
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm_btn.setStyleSheet(
            f"QPushButton {{ background-color: {pal.panel_alt}; color: {pal.danger_text}; "
            f"border: 1px solid {pal.danger_border}; border-radius: 8px; padding: 7px 15px; "
            "font-size: 12px; font-weight: 600; }}"
            f"QPushButton:hover:enabled {{ border-color: {pal.danger_text}; }}"
            f"QPushButton:disabled {{ color: {pal.muted}; border-color: {pal.border_soft}; }}"
        )
        self._confirm_btn.clicked.connect(self.accept)

        footer.addWidget(cancel_btn)
        footer.addWidget(self._confirm_btn)
        root.addLayout(footer)

    def _on_text_changed(self, text: str) -> None:
        self._confirm_btn.setEnabled(text.strip().lower() == "delete")

    def _on_return_pressed(self) -> None:
        if self._confirm_btn.isEnabled():
            self.accept()
