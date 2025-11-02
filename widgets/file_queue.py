"""Interactive queue widget for managing PDF uploads in the MinerU client."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.models import TaskStatus, UploadFile


STATUS_LABELS = {
    TaskStatus.PENDING: "待上传",
    TaskStatus.UPLOADING: "上传中",
    TaskStatus.PROCESSING: "解析中",
    TaskStatus.COMPLETED: "完成",
    TaskStatus.FAILED: "失败",
    TaskStatus.CANCELLED: "已取消",
}


class _FileTreeWidget(QTreeWidget):
    """Custom tree widget that supports drag and drop of file paths."""

    files_dropped = Signal(list)

    def __init__(self) -> None:
        """Initialise headers, drag/drop behaviour, and selection policy."""
        super().__init__()
        self.setAcceptDrops(True)
        self.setHeaderLabels(["文件名", "状态", "阶段", "尝试次数", "错误信息"])
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setColumnWidth(0, 260)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 160)
        self.setColumnWidth(3, 80)

    def dragEnterEvent(self, event):
        """Accept drag operations that contain URLs representing files."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """Allow drag movement while the data contains recognised file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        """Emit a signal with file paths when the user drops URLs onto the widget."""
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class FileQueueWidget(QWidget):
    """Display and manage PDF files waiting to be processed."""

    files_changed = Signal(list)
    retry_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        """Set up the widget tree and prepare internal bookkeeping."""
        super().__init__(parent)
        self._items: Dict[str, QTreeWidgetItem] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        """Create buttons, wire events, and embed the tree widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("添加文件")
        self.add_button.clicked.connect(self._browse_files)
        button_row.addWidget(self.add_button)

        self.remove_button = QPushButton("移除所选")
        self.remove_button.clicked.connect(self._remove_selected)
        button_row.addWidget(self.remove_button)

        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.clear)
        button_row.addWidget(self.clear_button)

        button_row.addStretch()
        layout.addLayout(button_row)

        self.tree = _FileTreeWidget()
        self.tree.files_dropped.connect(self._handle_dropped_files)
        self.tree.itemDoubleClicked.connect(self._handle_item_double_clicked)
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
        layout.addWidget(self.tree)

    def _key_for_path(self, path: Path | str) -> str:
        """Return a normalised absolute path string used as dictionary key."""
        if isinstance(path, Path):
            try:
                return str(path.expanduser().resolve())
            except Exception:
                return str(path)
        try:
            return str(Path(path).expanduser().resolve())
        except Exception:
            return str(path)

    def add_files(self, paths: Iterable[str | Path]) -> None:
        """Add new files to the queue, ignoring duplicates and non-PDF inputs."""
        accepted: List[str] = []
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists() or path.suffix.lower() != ".pdf":
                continue
            key = self._key_for_path(path)
            if key in self._items:
                continue
            status_text = STATUS_LABELS.get(TaskStatus.PENDING, TaskStatus.PENDING.value)
            item = QTreeWidgetItem(
                [path.name, status_text, "待上传", "0", ""]
            )
            item.setData(0, Qt.UserRole, key)
            item.setData(1, Qt.UserRole, TaskStatus.PENDING.value)
            self.tree.addTopLevelItem(item)
            self._items[key] = item
            accepted.append(key)
        if accepted:
            self.files_changed.emit(list(self._items.keys()))

    def load_from_files(self, files: Iterable[UploadFile]) -> None:
        """Replace the current queue contents with provided UploadFile objects."""
        self.tree.clear()
        self._items.clear()
        for file_info in files:
            key = self._key_for_path(file_info.path)
            status_text = STATUS_LABELS.get(file_info.status, file_info.status.value)
            progress_text = file_info.progress_label or status_text
            item = QTreeWidgetItem(
                [
                    file_info.display_name,
                    status_text,
                    progress_text,
                    str(file_info.attempts),
                    file_info.error or "",
                ]
            )
            item.setData(0, Qt.UserRole, key)
            item.setData(1, Qt.UserRole, file_info.status.value)
            self.tree.addTopLevelItem(item)
            self._items[key] = item
        self.files_changed.emit(list(self._items.keys()))

    def update_file(self, file_info: UploadFile) -> None:
        """Update an existing item to reflect fresh status information."""
        key = self._key_for_path(file_info.path)
        item = self._items.get(key)
        if not item:
            # fallback to name-based lookup if absolute path differs (e.g., remote rename)
            for candidate_key, candidate_item in self._items.items():
                if candidate_item.text(0) == file_info.display_name:
                    item = candidate_item
                    key = candidate_key
                    break
        if not item:
            status_text = STATUS_LABELS.get(file_info.status, file_info.status.value)
            item = QTreeWidgetItem(
                [
                    file_info.display_name,
                    status_text,
                    file_info.progress_label,
                    str(file_info.attempts),
                    file_info.error or "",
                ]
            )
            item.setData(0, Qt.UserRole, key)
            item.setData(1, Qt.UserRole, file_info.status.value)
            self.tree.addTopLevelItem(item)
            self._items[key] = item
        status_text = STATUS_LABELS.get(file_info.status, file_info.status.value)
        item.setText(1, status_text)
        item.setData(1, Qt.UserRole, file_info.status.value)
        item.setText(2, file_info.progress_label)
        item.setText(3, str(file_info.attempts))
        item.setText(4, file_info.error or "")
        self.files_changed.emit(list(self._items.keys()))

    def remove_file(self, key: str) -> None:
        """Remove a single file from the queue by its lookup key."""
        item = self._items.pop(key, None)
        if item:
            index = self.tree.indexOfTopLevelItem(item)
            if index >= 0:
                self.tree.takeTopLevelItem(index)
            self.files_changed.emit(list(self._items.keys()))

    def remove_files(self, keys: Iterable[str]) -> None:
        """Remove multiple files from the queue in one pass."""
        changed = False
        for key in list(keys):
            item = self._items.pop(key, None)
            if not item:
                continue
            index = self.tree.indexOfTopLevelItem(item)
            if index >= 0:
                self.tree.takeTopLevelItem(index)
            changed = True
        if changed:
            self.files_changed.emit(list(self._items.keys()))

    def clear(self) -> None:
        """Remove every file from the queue and reset state."""
        self.tree.clear()
        self._items.clear()
        self.files_changed.emit([])

    def _browse_files(self) -> None:
        """Open a file chooser dialog to add PDFs to the queue."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 PDF 文件", "", "PDF 文件 (*.pdf)"
        )
        if file_paths:
            self.add_files(file_paths)

    def _remove_selected(self) -> None:
        """Remove any highlighted entries from the queue."""
        selected = [item.data(0, Qt.UserRole) for item in self.tree.selectedItems()]
        for key in selected:
            if key:
                self.remove_file(key)

    def selected_files(self) -> List[str]:
        """Return the keys for the currently selected queue items."""
        return [item.data(0, Qt.UserRole) for item in self.tree.selectedItems() if item]

    def all_files(self) -> List[str]:
        """Return all keys currently tracked by the queue."""
        return list(self._items.keys())

    def _handle_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Emit a retry request when the user double-clicks a failed entry."""
        key = item.data(0, Qt.UserRole)
        status_value = item.data(1, Qt.UserRole)
        if key and status_value == TaskStatus.FAILED.value:
            self.retry_requested.emit(key)

    def _handle_dropped_files(self, paths: List[str]) -> None:
        """Add files dropped from the OS file manager into the queue."""
        self.add_files(paths)
