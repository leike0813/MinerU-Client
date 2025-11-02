"""Status overview widget summarising batch progress statistics."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget


class StatusSummaryWidget(QWidget):
    """Compact summary of current batch progress."""

    def __init__(self, parent=None) -> None:
        """Initialise labels and layout container."""
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        """Create the grid layout and the labels representing counts."""
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(24)

        self.total_label = QLabel("总文件: 0")
        self.completed_label = QLabel("完成: 0")
        self.failed_label = QLabel("失败: 0")
        self.pending_label = QLabel("进行中: 0")

        layout.addWidget(self.total_label, 0, 0)
        layout.addWidget(self.completed_label, 0, 1)
        layout.addWidget(self.failed_label, 0, 2)
        layout.addWidget(self.pending_label, 0, 3)

    def update_counts(self, total: int, completed: int, failed: int, pending: int) -> None:
        """Update each label with the latest batch metrics."""
        self.total_label.setText(f"总文件: {total}")
        self.completed_label.setText(f"完成: {completed}")
        self.failed_label.setText(f"失败: {failed}")
        self.pending_label.setText(f"进行中: {pending}")
