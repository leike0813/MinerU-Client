"""Main Qt window and UI workflow bindings for the MinerU client."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
    QProgressBar,
)

from core.config import AppConfig, AppOptions, ConfigManager
from core.models import TaskStatus, UploadFile
from services.api_client import MinerUApiClient
from services.logger import get_logger
from services.task_manager import TaskManager
from ui.theme import apply_theme
from widgets.file_queue import FileQueueWidget
from widgets.log_view import LogViewWidget
from widgets.status_summary import StatusSummaryWidget
from widgets.task_history import TaskHistoryWidget


logger = get_logger("ui")


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, app) -> None:
        """Configure widgets, load persisted state, and wire runtime signals."""
        super().__init__()
        apply_theme(app)
        self.setWindowTitle("MinerU PDF 解析客户端")
        self.resize(1100, 720)

        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
        self.api_client = MinerUApiClient(self.config.api_key or "")
        self.task_manager = TaskManager(self.api_client, self.config)
        self._current_files: dict[str, UploadFile] = {}
        self._is_running = False

        self._init_ui()
        self._load_config_to_ui()
        self._update_start_button_state()
        self._connect_signals()
        self.history_view.update_history(self.task_manager.get_history())
        self._update_summary_from_queue(self.file_queue.all_files())

    def _init_ui(self) -> None:
        """Construct the high-level layout, split panes, and shared widgets."""
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(16, 12, 16, 12)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        central_layout.addWidget(splitter, 1)

        self.file_queue = FileQueueWidget()
        self.history_view = TaskHistoryWidget()
        self.status_summary = StatusSummaryWidget()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.polling_label = QLabel()
        self.polling_label.setObjectName("pollingLabel")
        self.polling_label.clear()
        self.log_view = LogViewWidget()

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setChildrenCollapsible(False)
        left_splitter.addWidget(self._wrap_section("文件选择", self.file_queue))
        left_splitter.addWidget(self._wrap_section("任务历史", self.history_view))
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)
        splitter.addWidget(left_splitter)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setChildrenCollapsible(False)

        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(12)
        settings_layout.addWidget(self._create_section_label("设置"))
        settings_layout.addWidget(self._create_settings_panel())
        settings_layout.addWidget(self.status_summary)
        settings_layout.addWidget(self.progress_bar)
        settings_layout.addWidget(self.polling_label)
        settings_layout.addStretch()

        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(6)
        log_layout.addWidget(self._create_section_label("日志"))
        log_layout.addWidget(self.log_view)

        right_splitter.addWidget(settings_container)
        right_splitter.addWidget(log_container)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)
        splitter.addWidget(right_splitter)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def _create_section_label(self, text: str) -> QLabel:
        """Create a styled heading label for section delineation."""
        label = QLabel(text)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setStyleSheet("font-weight: 600; font-size: 14px; margin-bottom: 4px;")
        return label

    def _wrap_section(self, title: str, widget: QWidget) -> QWidget:
        """Wrap a widget with a titled container to keep layout code concise."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._create_section_label(title))
        layout.addWidget(widget)
        return container

    def _create_settings_panel(self) -> QWidget:
        """Build the settings form and action buttons used for uploads."""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        form.addRow("API Key", self.api_key_input)

        self.output_dir_input = QLineEdit()
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self._select_output_dir)
        output_layout = QHBoxLayout()
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.output_dir_input)
        output_layout.addWidget(browse_button)
        form.addRow("输出目录", output_layout)

        self.ocr_checkbox = QCheckBox("启用 OCR")
        form.addRow("", self.ocr_checkbox)

        self.formula_checkbox = QCheckBox("识别公式")
        form.addRow("", self.formula_checkbox)

        self.table_checkbox = QCheckBox("识别表格")
        form.addRow("", self.table_checkbox)

        self.language_combo = QComboBox()
        self.language_combo.addItems(["ch", "en", "jp"])
        form.addRow("语言", self.language_combo)

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 8)
        form.addRow("并发上传", self.concurrency_spin)

        self.auto_retry_checkbox = QCheckBox("自动重试失败文件")
        form.addRow("", self.auto_retry_checkbox)

        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 5)
        form.addRow("最大重试次数", self.retry_spin)

        container_layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.start_button = QPushButton("开始解析")
        self.start_button.clicked.connect(self._start_processing)
        button_row.addWidget(self.start_button)
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.clicked.connect(self._cancel_processing)
        self.cancel_button.setEnabled(False)
        button_row.addWidget(self.cancel_button)

        container_layout.addLayout(button_row)
        return container

    def _connect_signals(self) -> None:
        """Wire widget events and task manager signals to their handlers."""
        self.file_queue.files_changed.connect(self._update_summary_from_queue)
        self.file_queue.retry_requested.connect(self._on_retry_requested)

        self.output_dir_input.textChanged.connect(self._on_output_dir_changed)
        self.task_manager.batch_started.connect(self._on_batch_started)
        self.task_manager.batch_completed.connect(self._on_batch_completed)
        self.task_manager.batch_failed.connect(self._on_batch_failed)
        self.task_manager.file_updated.connect(self._on_file_updated)
        self.task_manager.progress_updated.connect(self.progress_bar.setValue)
        self.task_manager.history_updated.connect(self.history_view.update_history)
        self.task_manager.log_generated.connect(self._append_log)
        self.task_manager.polling_status.connect(self._on_polling_status)
        self.history_view.resume_requested.connect(self._on_history_resume_requested)
        self.history_view.redownload_requested.connect(self._on_history_redownload_requested)

    def _build_upload_files_from_entry(self, entry: dict) -> List[UploadFile]:
        """Recreate UploadFile instances from history entries."""
        uploads: List[UploadFile] = []
        for info in entry.get("files") or []:
            if isinstance(info, dict):
                path_text = info.get("path") or ""
                display = info.get("display_name") or path_text or "未命名文件"
            else:
                path_text = str(info)
                display = Path(path_text).name if path_text else "未命名文件"
            try:
                path_obj = Path(path_text) if path_text else Path(display)
            except Exception:
                path_obj = Path(display)
            uploads.append(
                UploadFile(
                    path=path_obj,
                    display_name=display,
                    status=TaskStatus.PENDING,
                    progress_label="等待解析",
                )
            )
        return uploads

    def _load_config_to_ui(self) -> None:
        """Load saved configuration values into the form widgets."""
        self.api_key_input.setText(self.config.api_key)
        self.output_dir_input.setText(self.config.output_dir)
        self.ocr_checkbox.setChecked(self.config.options.is_ocr)
        self.formula_checkbox.setChecked(self.config.options.enable_formula)
        self.table_checkbox.setChecked(self.config.options.enable_table)
        index = self.language_combo.findText(self.config.options.language)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        self.concurrency_spin.setValue(self.config.options.concurrency)
        self.auto_retry_checkbox.setChecked(self.config.options.auto_retry)
        self.retry_spin.setValue(self.config.options.max_retry_attempts)

    def _collect_options(self) -> AppOptions:
        """Build an AppOptions object from the current UI state."""
        return AppOptions(
            is_ocr=self.ocr_checkbox.isChecked(),
            enable_formula=self.formula_checkbox.isChecked(),
            enable_table=self.table_checkbox.isChecked(),
            language=self.language_combo.currentText(),
            concurrency=self.concurrency_spin.value(),
            auto_retry=self.auto_retry_checkbox.isChecked(),
            max_retry_attempts=self.retry_spin.value(),
        )

    def _persist_config(self) -> None:
        """Persist settings and refresh dependent services after user changes."""
        options = self._collect_options()
        config = AppConfig(
            api_key=self.api_key_input.text().strip(),
            output_dir=self.output_dir_input.text().strip(),
            options=options,
        )
        self.config = config
        self.config_manager.save(config)
        self.task_manager.update_config(config)
        self.api_client = MinerUApiClient(config.api_key or "")
        self.task_manager.set_api_client(self.api_client)

    # Slots
    def _start_processing(self) -> None:
        """Start a fresh batch after validating form fields."""
        api_key = self.api_key_input.text().strip()
        output_dir = self.output_dir_input.text().strip()
        files = self.file_queue.all_files()

        if not api_key:
            QMessageBox.warning(self, "缺少信息", "请先填写 API Key。")
            return
        if not output_dir:
            QMessageBox.warning(self, "缺少信息", "请选择输出目录。")
            return
        if not files:
            QMessageBox.warning(self, "缺少文件", "请先添加至少一个 PDF 文件。")
            return
        if not self._is_output_dir_valid():
            QMessageBox.critical(self, "输出目录无效", "所选输出目录不存在或不可访问。")
            self._update_start_button_state()
            return

        self._persist_config()

        try:
            self._current_files = {}
            self.task_manager.start_batch([Path(path) for path in files], Path(output_dir))
            self._toggle_controls(active=True)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to start batch: %s", exc)
            self._toggle_controls(active=False)
            self.polling_label.clear()
            self.statusBar().showMessage("任务启动失败", 5000)
            QMessageBox.critical(self, "任务启动失败", str(exc))

    def _cancel_processing(self) -> None:
        """Cancel the current batch and update the status bar."""
        self.task_manager.cancel_active_batch()
        self.statusBar().showMessage("正在取消任务……", 5000)
        self.polling_label.setText("正在取消任务……")

    def _select_output_dir(self) -> None:
        """Prompt the user to choose an output directory."""
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if directory:
            self.output_dir_input.setText(directory)

    def _on_batch_started(self, task) -> None:
        """React to the start of a batch and update status messages accordingly."""
        kind = getattr(task, "kind", "standard")
        if kind == "recovery":
            status_message = f"批次 {task.batch_id or '未知'} 正在恢复解析。"
            log_message = "重新开始轮询该批次的解析结果。"
            polling_text = "正在恢复解析进度…"
        elif kind == "redownload":
            status_message = f"批次 {task.batch_id or '未知'} 正在重新下载结果。"
            log_message = "重新下载该批次的解析结果。"
            polling_text = "正在重新下载结果…"
        else:
            status_message = f"批次 {task.batch_id or '处理中'} 已启动"
            log_message = "任务开始执行。"
            polling_text = "正在上传文件…"

        self.statusBar().showMessage(status_message)
        self.log_view.append(log_message)
        self.polling_label.setText(polling_text)
        self._toggle_controls(active=True)

    def _on_batch_completed(self, task) -> None:
        """Handle success states for standard, recovery, or re-download batches."""
        self._toggle_controls(active=False)
        kind = getattr(task, "kind", "standard")
        if kind == "recovery":
            status_message = f"批次 {task.batch_id} 解析结果获取完成"
            dialog_title = "结果获取完成"
            dialog_message = f"批次 {task.batch_id} 的解析结果已获取。"
            polling_text = "解析结果获取完成"
        elif kind == "redownload":
            status_message = f"批次 {task.batch_id} 结果重新下载完成"
            dialog_title = "重新下载完成"
            dialog_message = f"批次 {task.batch_id} 的解析结果已重新下载。"
            polling_text = "结果重新下载完成"
        else:
            status_message = "所有文件解析完成！"
            dialog_title = "任务完成"
            dialog_message = f"批次 {task.batch_id} 已完成。"
            polling_text = "解析任务完成"

        self.statusBar().showMessage(status_message, 8000)
        QMessageBox.information(self, dialog_title, dialog_message)
        self.progress_bar.setValue(100)

        if kind == "standard":
            self._current_files = {str(f.path.resolve()): f for f in task.files}
            self._update_summary(task.files)
            completed_keys = list(self._current_files.keys())
            if completed_keys:
                self.file_queue.remove_files(completed_keys)
            self._current_files.clear()
            self._update_summary([])
        else:
            self._current_files = {str(f.path.resolve()): f for f in task.files}
            self._update_summary(task.files)
        self._current_files.clear()

        self.polling_label.setText(polling_text)

    def _on_batch_failed(self, task, message: str) -> None:
        """Handle failures by notifying the user and suggesting remediation."""
        self._toggle_controls(active=False)
        kind = getattr(task, "kind", "standard")
        if kind == "recovery":
            status_message = "恢复任务失败"
            title = "恢复失败"
        elif kind == "redownload":
            status_message = "重新下载失败"
            title = "重新下载失败"
        else:
            status_message = "任务失败"
            title = "任务失败"

        self.statusBar().showMessage(status_message, 8000)
        QMessageBox.critical(self, title, message)
        self.polling_label.setText(f"{status_message}：{message}")

        if kind != "standard":
            self._show_reupload_prompt(task, message)

    def _on_file_updated(self, display_name: str, file_info: UploadFile) -> None:
        """Update UI elements when individual file progress changes."""
        self._current_files[str(file_info.path.resolve())] = file_info
        self.file_queue.update_file(file_info)
        self._update_summary(self._current_files.values())
        status_message = f"{display_name}: {file_info.progress_label}"
        if file_info.error:
            status_message += f" - {file_info.error}"
        self.statusBar().showMessage(status_message, 5000)

    def _append_log(self, message: str) -> None:
        """Append a new line to the runtime log viewer."""
        self.log_view.append(message)

    def _on_polling_status(self, message: str) -> None:
        """Display status updates in both the label and status bar."""
        self.polling_label.setText(message)
        if message:
            self.statusBar().showMessage(message, 5000)

    def _update_summary(self, files: Iterable[UploadFile]) -> None:
        """Recalculate the status summary widget based on provided files."""
        snapshot = list(files)
        total = len(snapshot)
        completed = sum(1 for f in snapshot if f.status == TaskStatus.COMPLETED)
        failed = sum(1 for f in snapshot if f.status == TaskStatus.FAILED)
        pending = total - completed - failed
        self.status_summary.update_counts(total, completed, failed, pending)

    def _update_summary_from_queue(self, _paths: List[str]) -> None:
        """Refresh the summary whenever the queued file set changes."""
        if self._current_files:
            self._update_summary(self._current_files.values())
            return
        files = [
            UploadFile(path=Path(p), display_name=Path(p).name)
            for p in self.file_queue.all_files()
        ]
        self._update_summary(files)

    def _toggle_controls(self, active: bool) -> None:
        """Toggle buttons and queue interactivity while work is in progress."""
        self._is_running = active
        self.cancel_button.setEnabled(active)
        self.file_queue.setEnabled(not active)
        self._update_start_button_state()

    def _on_retry_requested(self, key: str) -> None:
        """Prompt to restart the workflow when a failed file is retried."""
        reply = QMessageBox.question(
            self,
            "重新尝试",
            "确定要重新尝试该文件吗？将会重新开始任务。",
        )
        if reply == QMessageBox.Yes:
            self._start_processing()

    def _on_history_resume_requested(self, entry: dict) -> None:
        """Populate the queue and ask the task manager to resume polling."""
        batch_id = entry.get("batch_id")
        if not batch_id:
            return
        upload_files = self._build_upload_files_from_entry(entry)
        if upload_files:
            self.file_queue.load_from_files(upload_files)
            self._current_files.clear()
            self._update_summary(upload_files)
        try:
            self.task_manager.resume_batch(batch_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to resume batch %s: %s", batch_id, exc)
            QMessageBox.critical(self, "重新轮询失败", str(exc))

    def _on_history_redownload_requested(self, entry: dict) -> None:
        """Trigger a re-download workflow for a completed batch."""
        batch_id = entry.get("batch_id")
        if not batch_id:
            return
        try:
            self.task_manager.redownload_batch(batch_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to redownload batch %s: %s", batch_id, exc)
            QMessageBox.critical(self, "重新下载失败", str(exc))

    def _show_reupload_prompt(self, task, reason: str) -> None:
        """Display a dialog advising the user to re-upload missing files."""
        file_paths = []
        for file_info in getattr(task, "files", []):
            path_value = getattr(file_info, "path", None)
            display_name = getattr(file_info, "display_name", "")
            if path_value:
                try:
                    file_paths.append(str(Path(path_value)))
                except TypeError:
                    file_paths.append(display_name or str(path_value))
            elif display_name:
                file_paths.append(display_name)
        if not file_paths:
            return
        self._show_reupload_details(task.batch_id, file_paths, reason)

    def _show_reupload_details(self, batch_id: str, file_paths: List[str], reason: str | None) -> None:
        """Render the formatted re-upload advice dialog and log entry."""
        reason_text = f"原因：{reason}\n\n" if reason else ""
        details = "\n".join(file_paths)
        message = (
            f"{reason_text}请重新上传批次 {batch_id} 的以下文件：\n{details}"
        )
        QMessageBox.information(self, "重新上传提示", message)
        self.log_view.append(f"建议重新上传批次 {batch_id}：\n{details}")

    def _on_output_dir_changed(self, _text: str) -> None:
        """React to direct edits in the output field by revalidating the path."""
        if self.output_dir_input.text().strip() and not self._is_output_dir_valid():
            self.statusBar().showMessage("输出目录不存在或不可访问", 5000)
        self._update_start_button_state()

    def _is_output_dir_valid(self) -> bool:
        """Return True when the output directory exists and is a folder."""
        text = self.output_dir_input.text().strip()
        if not text:
            return False
        try:
            path = Path(text).expanduser()
        except (TypeError, ValueError, OSError):
            return False
        return path.exists() and path.is_dir()

    def _update_start_button_state(self) -> None:
        """Keep the start button disabled unless the form is ready."""
        allow_start = not self._is_running and self._is_output_dir_valid()
        self.start_button.setEnabled(allow_start)

    def closeEvent(self, event) -> None:
        """Ensure running tasks warn the user and that settings persist on exit."""
        if self.task_manager.has_active_task():
            reply = QMessageBox.question(
                self,
                "任务正在运行",
                "当前有任务正在运行，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.task_manager.cancel_active_batch()
        self._persist_config()
        super().closeEvent(event)
