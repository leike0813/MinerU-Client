"""Task history panel that allows resuming or downloading past batches."""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.models import HistoryStatus


STATUS_LABELS = {
    HistoryStatus.UPLOADING.value: "上传中",
    HistoryStatus.PROCESSING.value: "解析中",
    HistoryStatus.COMPLETED.value: "已完成",
    HistoryStatus.FAILED.value: "失败",
    HistoryStatus.UNKNOWN.value: "未知",
}


class TaskHistoryWidget(QWidget):
    """Display historical batch results with recovery actions."""

    resume_requested = Signal(dict)
    redownload_requested = Signal(dict)

    def __init__(self, parent=None) -> None:
        """Initialise storage and construct the history tree UI."""
        super().__init__(parent)
        self._entries: List[Dict] = []
        self._init_ui()

    def _init_ui(self) -> None:
        """Create toolbar buttons and configure the history tree widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self.resume_button = QPushButton("重新轮询")
        self.resume_button.setEnabled(False)
        self.resume_button.clicked.connect(self._emit_resume)
        toolbar.addWidget(self.resume_button)

        self.redownload_button = QPushButton("重新下载结果")
        self.redownload_button.setEnabled(False)
        self.redownload_button.clicked.connect(self._emit_redownload)
        toolbar.addWidget(self.redownload_button)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["批次 ID", "状态", "时间", "成功", "失败", "输出目录"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 160)
        self.tree.setColumnWidth(3, 60)
        self.tree.setColumnWidth(4, 60)
        self.tree.setStyleSheet(
            """
            QTreeWidget {
                selection-background-color: #24262a;
                selection-color: #ffffff;
            }
            QTreeWidget::item:selected {
                background-color: #1f6fb2;
                color: #ffffff;
            }
            QTreeWidget::item:selected:active {
                background-color: #4a90e2;
                color: #ffffff;
            }
            QTreeWidget::item:selected:!active {
                background-color: #1f3652;
                color: #ffffff;
            }
            """
        )
        self.tree.itemSelectionChanged.connect(self._update_button_state)
        self.tree.itemDoubleClicked.connect(self._handle_double_click)
        layout.addWidget(self.tree)

    def update_history(self, entries: List[Dict]) -> None:
        """Refresh the tree widget based on the provided history records."""
        self._entries = entries or []
        selected_batch = self._current_selection_id()
        self.tree.clear()
        for entry in self._entries:
            batch_id = entry.get("batch_id", "")
            status_value = entry.get("status", HistoryStatus.UNKNOWN.value)
            status_text = STATUS_LABELS.get(status_value, status_value)
            timestamp = entry.get("timestamp") or entry.get("completed_at") or entry.get("created_at") or ""
            success = str(entry.get("success", 0))
            failed = str(entry.get("failed", 0))
            output_dir = entry.get("output_dir", "")

            item = QTreeWidgetItem([batch_id, status_text, timestamp, success, failed, output_dir])
            item.setData(0, Qt.UserRole, self._clone_entry(entry))
            if entry.get("last_error"):
                item.setToolTip(1, entry["last_error"])
                item.setToolTip(0, entry["last_error"])
            self.tree.addTopLevelItem(item)
            if batch_id and batch_id == selected_batch:
                item.setSelected(True)

        self._update_button_state()

    def _current_selection_id(self) -> Optional[str]:
        """Return the batch id of the currently selected tree row."""
        items = self.tree.selectedItems()
        if not items:
            return None
        entry = items[0].data(0, Qt.UserRole) or {}
        return entry.get("batch_id")

    def _selected_entry(self) -> Optional[Dict]:
        """Return a cloned copy of the currently selected entry."""
        items = self.tree.selectedItems()
        if not items:
            return None
        entry = items[0].data(0, Qt.UserRole)
        return self._clone_entry(entry) if entry else None

    def _update_button_state(self) -> None:
        """Enable or disable action buttons based on selection state."""
        entry = self._selected_entry()
        if not entry:
            self.resume_button.setEnabled(False)
            self.redownload_button.setEnabled(False)
            return

        status = entry.get("status", HistoryStatus.UNKNOWN.value)
        self.resume_button.setEnabled(
            status in {HistoryStatus.PROCESSING.value, HistoryStatus.UPLOADING.value, HistoryStatus.FAILED.value}
        )
        self.redownload_button.setEnabled(status == HistoryStatus.COMPLETED.value)

    def _handle_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        """Trigger the appropriate action when a row is double-clicked."""
        entry = item.data(0, Qt.UserRole)
        if not entry:
            return
        status = entry.get("status", HistoryStatus.UNKNOWN.value)
        if status == HistoryStatus.COMPLETED.value:
            self._emit_redownload()
        else:
            self._emit_resume()

    def _emit_resume(self) -> None:
        """Emit the resume signal for the currently selected entry."""
        entry = self._selected_entry()
        if entry:
            self.resume_requested.emit(entry)

    def _emit_redownload(self) -> None:
        """Emit the redownload signal for the currently selected entry."""
        entry = self._selected_entry()
        if entry:
            self.redownload_requested.emit(entry)

    def _clone_entry(self, entry: Optional[Dict]) -> Dict:
        """Return a shallow copy of an entry to avoid accidental mutation."""
        if not entry:
            return {}
        clone = dict(entry)
        clone["files"] = list(entry.get("files", []))
        return clone
