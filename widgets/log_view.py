"""Widget that surfaces runtime logs and allows clearing/exporting them."""

from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget, QPlainTextEdit


class LogViewWidget(QWidget):
    """Simple log display with clear/export controls."""

    def __init__(self, parent=None) -> None:
        """Set up the log text area and supporting controls."""
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        """Create the layout containing the log view and toolbar buttons."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(160)
        layout.addWidget(self.log_area)

        self.clear_button = QPushButton("清空日志")
        self.clear_button.clicked.connect(self.log_area.clear)
        layout.addWidget(self.clear_button)

    def append(self, message: str) -> None:
        """Append a new line of text and keep the view scrolled to the bottom."""
        self.log_area.appendPlainText(message)
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_area.setTextCursor(cursor)

    def export_to_file(self, path: str) -> None:
        """Persist the current log contents to the specified file path."""
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.log_area.toPlainText())
