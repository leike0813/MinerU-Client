"""Task orchestration, background workers, and history persistence for MinerU."""

from __future__ import annotations

import copy
import io
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional
from zipfile import ZipFile

from PySide6.QtCore import QObject, QThread, Signal

from core.config import AppConfig, AppOptions
from core.models import BatchTask, HistoryStatus, TaskStatus, UploadFile
from services.api_client import MinerUApiClient
from services.logger import get_logger


logger = get_logger("task_manager")


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Convert an ISO 8601 string to a datetime, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _store_result_package(
    task: BatchTask,
    output_root: Path,
    file_item: UploadFile,
    package_bytes: bytes,
    log_callback: Callable[[str], None],
) -> Path:
    """Extract a result ZIP into the batch folder and mirror the markdown summary."""
    batch_root = task.output_dir or (output_root / (task.batch_id or "batch"))
    file_stem = Path(file_item.display_name).stem
    target_dir = batch_root / file_stem
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    buffer = io.BytesIO(package_bytes)
    md_candidate = None
    with ZipFile(buffer) as archive:
        archive.extractall(target_dir)
        for member in archive.namelist():
            if Path(member).name == "full.md":
                md_candidate = target_dir / Path(member)
                break

    if md_candidate and md_candidate.exists():
        markdown_target = batch_root / f"{file_stem}.md"
        shutil.copyfile(md_candidate, markdown_target)
    else:
        log_callback(f"警告：{file_item.display_name} 的结果中未找到 full.md")

    return target_dir


class BatchWorker(QThread):
    """Execute full lifecycle of a batch task in a background thread."""

    progress_updated = Signal(int)
    file_updated = Signal(str, UploadFile)
    batch_completed = Signal(BatchTask)
    batch_failed = Signal(BatchTask, str)
    log_generated = Signal(str)
    polling_status = Signal(str)
    batch_prepared = Signal(BatchTask)
    batch_ready = Signal(BatchTask)

    POLL_INTERVAL = 2.0

    def __init__(
        self,
        task: BatchTask,
        api_client: MinerUApiClient,
        options: AppOptions,
        output_dir: Path,
        auto_retry: bool,
        max_retry: int,
    ) -> None:
        """Store dependencies and runtime configuration for a batch execution."""
        super().__init__()
        self._task = task
        self._api_client = api_client
        self._options = options
        self._output_dir = output_dir
        self._auto_retry = auto_retry
        self._max_retry = max_retry
        self._is_cancelled = False

    def cancel(self) -> None:
        """Request cancellation; the running loop checks this flag periodically."""
        self._is_cancelled = True

    def run(self) -> None:
        """Entry point executed by QThread.start that delegates to the worker loop."""
        try:
            self._run_internal()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Batch execution failed: %s", exc)
            self.batch_failed.emit(self._task, str(exc))

    def _run_internal(self) -> None:
        """Upload all files and then poll the API until completion or failure."""
        logger.info("Starting batch with %d files", len(self._task.files))
        self.progress_updated.emit(0)

        batch_meta = self._api_client.create_batch(self._task.files, self._options)
        self._task.batch_id = batch_meta.batch_id
        self.log_generated.emit(f"创建批次 {self._task.batch_id} 成功。")
        batch_dir = self._output_dir / self._task.batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        self._task.output_dir = batch_dir
        self.batch_prepared.emit(self._task)

        # Map each file's display name to the signed URL returned by the API.
        url_map = dict(zip([f.display_name for f in self._task.files], batch_meta.file_urls))
        total_files = len(self._task.files) or 1

        for index, file_item in enumerate(self._task.files, start=1):
            if self._is_cancelled:
                self.log_generated.emit("任务被用户取消。")
                self._update_file_status(file_item, TaskStatus.CANCELLED)
                continue

            try:
                file_item.status = TaskStatus.UPLOADING
                file_item.progress_label = "上传中"
                self._emit_file_update(file_item)
                signed_url = url_map[file_item.display_name]
                self._upload_with_retry(file_item, signed_url)
                file_item.status = TaskStatus.PROCESSING
                file_item.progress_label = "等待解析"
                self._emit_file_update(file_item)
                self.progress_updated.emit(int((index / total_files) * 40))
            except Exception as exc:  # pylint: disable=broad-except
                file_item.status = TaskStatus.FAILED
                file_item.error = str(exc)
                file_item.progress_label = "上传失败"
                self._emit_file_update(file_item)
                self.log_generated.emit(f"{file_item.display_name} 上传失败：{exc}")

        has_processing = any(file.status == TaskStatus.PROCESSING for file in self._task.files)
        self.progress_updated.emit(40)

        if not has_processing:
            raise RuntimeError("所有文件上传失败，批处理终止。")

        self.batch_ready.emit(self._task)
        self._poll_until_complete()

    def _upload_with_retry(self, file_item: UploadFile, signed_url: str) -> None:
        """Upload a single file, retrying when configured until success or failure."""
        attempts = 0
        while True:
            if self._is_cancelled:
                raise RuntimeError("任务被取消")
            try:
                file_item.attempts += 1
                file_item.progress_label = f"上传中 (第{file_item.attempts}次)"
                self._emit_file_update(file_item)
                self._api_client.upload_file(signed_url, Path(file_item.path))
                self.log_generated.emit(f"{file_item.display_name} 上传完成。")
                return
            except Exception as exc:  # pylint: disable=broad-except
                attempts += 1
                logger.exception(
                    "Upload failed for %s (attempt %d): %s",
                    file_item.display_name,
                    attempts,
                    exc,
                )
                if not self._auto_retry or attempts > self._max_retry:
                    raise
                time.sleep(1.5 * attempts)

    def _poll_until_complete(self) -> None:
        """Continuously poll the batch status endpoint and handle file state transitions."""
        pending = {
            file.display_name: file
            for file in self._task.files
            if file.status == TaskStatus.PROCESSING
        }
        total_files = len(self._task.files) or 1
        if pending:
            self.polling_status.emit(f"文件上传完成，等待解析（共 {len(pending)} 个文件）…")
        while pending and not self._is_cancelled:
            # Query the API for current progress and update rows accordingly.
            self.polling_status.emit(f"正在解析，剩余 {len(pending)} / {total_files} 个文件…")
            payload = self._api_client.fetch_batch_status(self._task.batch_id)
            extract_result = payload.get("data", {}).get("extract_result", [])
            for item in extract_result:
                name = item.get("file_name")
                if name not in pending:
                    continue

                state = (item.get("state") or "").lower()
                file_item = pending[name]

                if state == "done":
                    zip_url = item.get("full_zip_url")
                    try:
                        if not zip_url:
                            raise RuntimeError("结果链接缺失")
                        package_bytes = self._api_client.download_result(zip_url)
                        target_dir = _store_result_package(
                            self._task,
                            self._output_dir,
                            file_item,
                            package_bytes,
                            self.log_generated.emit,
                        )
                        file_item.status = TaskStatus.COMPLETED
                        file_item.progress_label = "解析完成"
                        file_item.error = None
                        self._emit_file_update(file_item)
                        self.log_generated.emit(f"{name} 解析完成，结果已保存至 {target_dir}")
                        pending.pop(name, None)
                    except Exception as exc:  # pylint: disable=broad-except
                        file_item.status = TaskStatus.FAILED
                        file_item.error = str(exc)
                        file_item.progress_label = "结果处理失败"
                        self._emit_file_update(file_item)
                        pending.pop(name, None)
                        self.log_generated.emit(f"{name} 下载或解压失败：{exc}")
                elif state in {"failed", "error"}:
                    file_item.status = TaskStatus.FAILED
                    file_item.error = item.get("message", "解析失败")
                    file_item.progress_label = "解析失败"
                    self._emit_file_update(file_item)
                    pending.pop(name, None)
                    self.log_generated.emit(f"{name} 解析失败：{file_item.error}")
                elif state in {"pending", "queued"}:
                    file_item.progress_label = "等待解析"
                    self._emit_file_update(file_item)
                elif state in {"running", "processing"}:
                    progress_info = item.get("extract_progress", {}) or {}
                    extracted = progress_info.get("extracted_pages")
                    total_pages = progress_info.get("total_pages")
                    if extracted is not None and total_pages:
                        file_item.progress_label = f"解析中 ({extracted}/{total_pages})"
                    else:
                        file_item.progress_label = "解析中"
                    self._emit_file_update(file_item)
                elif state == "converting":
                    file_item.progress_label = "转换中"
                    self._emit_file_update(file_item)

            completed = len([f for f in self._task.files if f.status == TaskStatus.COMPLETED])
            overall = 40 + int((completed / total_files) * 60)
            self.progress_updated.emit(min(100, overall))
            time.sleep(self.POLL_INTERVAL)

        if self._is_cancelled:
            for file in pending.values():
                file.status = TaskStatus.CANCELLED
                file.progress_label = "已取消"
                self._emit_file_update(file)
            self.polling_status.emit("任务已取消")
            raise RuntimeError("任务被取消")

        self._task.mark_completed()
        self.progress_updated.emit(100)
        self.polling_status.emit("解析任务完成")
        self.batch_completed.emit(self._task)

    def _emit_file_update(self, file_item: UploadFile) -> None:
        """Emit a unified signal whenever a file's state changes."""
        self.file_updated.emit(file_item.display_name, file_item)

    def _update_file_status(self, file_item: UploadFile, status: TaskStatus) -> None:
        """Helper to update a file's status while keeping UI state consistent."""
        file_item.status = status
        if status == TaskStatus.CANCELLED:
            file_item.progress_label = "已取消"
        self._emit_file_update(file_item)


class ResultRecoveryWorker(QThread):
    """Worker dedicated to resuming polling or redownloading results for existing batches."""

    progress_updated = Signal(int)
    file_updated = Signal(str, UploadFile)
    batch_completed = Signal(BatchTask)
    batch_failed = Signal(BatchTask, str)
    log_generated = Signal(str)
    polling_status = Signal(str)

    POLL_INTERVAL = 2.0

    def __init__(
        self,
        task: BatchTask,
        api_client: MinerUApiClient,
        output_dir: Path,
        mode: str,
    ) -> None:
        """Prepare the recovery worker with the batch context and desired mode."""
        super().__init__()
        self._task = task
        self._api_client = api_client
        self._output_dir = output_dir
        self._mode = mode
        self._is_cancelled = False
        self._task.output_dir = output_dir

    def cancel(self) -> None:
        """Signal that the recovery workflow should abort at the next opportunity."""
        self._is_cancelled = True

    def run(self) -> None:
        """Execute either the polling resume path or the ZIP re-download routine."""
        try:
            if self._mode == "resume":
                self._resume_polling()
            else:
                self._redownload_results()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Result recovery failed: %s", exc)
            self.batch_failed.emit(self._task, str(exc))

    def _emit_file_update(self, file_item: UploadFile) -> None:
        """Forward file state changes to the UI."""
        self.file_updated.emit(file_item.display_name, file_item)

    def _resume_polling(self) -> None:
        """Recreate the polling loop for an already uploaded batch."""
        self.progress_updated.emit(40)
        pending: Dict[str, UploadFile] = {}
        total_files = len(self._task.files) or 1

        for file_item in self._task.files:
            if file_item.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                self._emit_file_update(file_item)
                continue
            file_item.status = TaskStatus.PROCESSING
            if not file_item.progress_label or file_item.progress_label == "待上传":
                file_item.progress_label = "等待解析"
            pending[file_item.display_name] = file_item
            self._emit_file_update(file_item)

        if pending:
            self.polling_status.emit(f"继续解析，剩余 {len(pending)} / {total_files} 个文件…")
        else:
            self.polling_status.emit("检查批次状态…")

        while pending and not self._is_cancelled:
            # Poll repeatedly until every outstanding file reaches a terminal state.
            self.polling_status.emit(f"正在解析，剩余 {len(pending)} / {total_files} 个文件…")
            payload = self._api_client.fetch_batch_status(self._task.batch_id)
            extract_result = payload.get("data", {}).get("extract_result", [])
            for item in extract_result:
                name = item.get("file_name")
                if name not in pending:
                    continue

                state = (item.get("state") or "").lower()
                file_item = pending[name]

                if state == "done":
                    zip_url = item.get("full_zip_url")
                    try:
                        if not zip_url:
                            raise RuntimeError("结果链接缺失")
                        package_bytes = self._api_client.download_result(zip_url)
                        target_dir = _store_result_package(
                            self._task,
                            self._output_dir,
                            file_item,
                            package_bytes,
                            self.log_generated.emit,
                        )
                        file_item.status = TaskStatus.COMPLETED
                        file_item.progress_label = "解析完成"
                        file_item.error = None
                        self._emit_file_update(file_item)
                        self.log_generated.emit(f"{name} 解析完成，结果已保存至 {target_dir}")
                        pending.pop(name, None)
                    except Exception as exc:  # pylint: disable=broad-except
                        file_item.status = TaskStatus.FAILED
                        file_item.error = str(exc)
                        file_item.progress_label = "结果处理失败"
                        self._emit_file_update(file_item)
                        pending.pop(name, None)
                        self.log_generated.emit(f"{name} 下载或解压失败：{exc}")
                elif state in {"failed", "error"}:
                    file_item.status = TaskStatus.FAILED
                    file_item.error = item.get("message", "解析失败")
                    file_item.progress_label = "解析失败"
                    self._emit_file_update(file_item)
                    pending.pop(name, None)
                    self.log_generated.emit(f"{name} 解析失败：{file_item.error}")
                elif state in {"pending", "queued"}:
                    file_item.progress_label = "等待解析"
                    self._emit_file_update(file_item)
                elif state in {"running", "processing"}:
                    progress_info = item.get("extract_progress", {}) or {}
                    extracted = progress_info.get("extracted_pages")
                    total_pages = progress_info.get("total_pages")
                    if extracted is not None and total_pages:
                        file_item.progress_label = f"解析中 ({extracted}/{total_pages})"
                    else:
                        file_item.progress_label = "解析中"
                    self._emit_file_update(file_item)
                elif state == "converting":
                    file_item.progress_label = "转换中"
                    self._emit_file_update(file_item)

            completed = len([f for f in self._task.files if f.status == TaskStatus.COMPLETED])
            overall = 40 + int((completed / total_files) * 60)
            self.progress_updated.emit(min(100, overall))
            time.sleep(self.POLL_INTERVAL)

        if self._is_cancelled:
            for file in pending.values():
                file.status = TaskStatus.CANCELLED
                file.progress_label = "已取消"
                self._emit_file_update(file)
            self.polling_status.emit("任务已取消")
            raise RuntimeError("任务被取消")

        self._task.mark_completed()
        self.progress_updated.emit(100)
        self.polling_status.emit("解析任务完成")
        self.batch_completed.emit(self._task)

    def _redownload_results(self) -> None:
        """Download finished results again without re-uploading files."""
        self.progress_updated.emit(0)
        payload = self._api_client.fetch_batch_status(self._task.batch_id)
        extract_result = payload.get("data", {}).get("extract_result", [])
        if not extract_result:
            raise RuntimeError("未获取到批次状态信息。")

        total_items = len(extract_result)
        for index, item in enumerate(extract_result, start=1):
            # Iterate over each file and rebuild the on-disk structure if finished.
            name = item.get("file_name") or f"文件{index}"
            state = (item.get("state") or "").lower()
            file_item = self._ensure_file_item(name)

            if state == "done":
                zip_url = item.get("full_zip_url")
                if not zip_url:
                    raise RuntimeError(f"{name} 的结果链接缺失")
                package_bytes = self._api_client.download_result(zip_url)
                target_dir = _store_result_package(
                    self._task,
                    self._output_dir,
                    file_item,
                    package_bytes,
                    self.log_generated.emit,
                )
                file_item.status = TaskStatus.COMPLETED
                file_item.error = None
                file_item.progress_label = "重新下载完成"
                self.log_generated.emit(f"{name} 结果已重新下载至 {target_dir}")
            elif state in {"failed", "error"}:
                file_item.status = TaskStatus.FAILED
                file_item.error = item.get("message", "解析失败")
                file_item.progress_label = "解析失败"
                self.log_generated.emit(f"{name} 解析失败：{file_item.error}")
            else:
                raise RuntimeError("批次仍在解析中，请先重新开始轮询。")

            self._emit_file_update(file_item)
            self.progress_updated.emit(int((index / total_items) * 100))

        self._task.mark_completed()
        self.polling_status.emit("结果重新下载完成")
        self.batch_completed.emit(self._task)

    def _ensure_file_item(self, display_name: str) -> UploadFile:
        """Return an existing tracked file or create a placeholder when missing."""
        for file_item in self._task.files:
            if file_item.display_name == display_name:
                return file_item
        file_item = UploadFile(path=Path(display_name), display_name=display_name)
        self._task.files.append(file_item)
        return file_item


class TaskManager(QObject):
    """High-level orchestrator coordinating batch tasks and persistence."""

    batch_started = Signal(BatchTask)
    batch_completed = Signal(BatchTask)
    batch_failed = Signal(BatchTask, str)
    file_updated = Signal(str, UploadFile)
    progress_updated = Signal(int)
    history_updated = Signal(list)
    log_generated = Signal(str)
    polling_status = Signal(str)

    HISTORY_FILE = Path(".mineru_history.json")

    def __init__(self, api_client: MinerUApiClient, config: AppConfig) -> None:
        """Initialise the manager with the API client and persisted configuration."""
        super().__init__()
        self._api_client = api_client
        self._config = config
        self._history = self._load_history()
        self._active_worker: Optional[QThread] = None

    def start_batch(self, file_paths: Iterable[Path], output_dir: Path | str) -> None:
        """Kick off a brand new batch upload for the selected files."""
        self._ensure_idle()

        destination = Path(output_dir).expanduser()
        if not destination.exists() or not destination.is_dir():
            raise FileNotFoundError(f"输出目录不存在：{destination}")

        files = [
            UploadFile(path=Path(path), display_name=Path(path).name)
            for path in file_paths
        ]
        task = BatchTask(batch_id=None, files=files, output_dir=destination)

        worker = BatchWorker(
            task=task,
            api_client=self._api_client,
            options=self._config.options,
            output_dir=destination,
            auto_retry=self._config.options.auto_retry,
            max_retry=self._config.options.max_retry_attempts,
        )
        worker.progress_updated.connect(self.progress_updated)
        worker.file_updated.connect(self.file_updated)
        worker.batch_completed.connect(self._handle_batch_completed)
        worker.batch_failed.connect(self._handle_batch_failed)
        worker.log_generated.connect(self.log_generated)
        worker.polling_status.connect(self.polling_status)
        worker.batch_prepared.connect(self._handle_batch_prepared)
        worker.batch_ready.connect(self._handle_batch_ready)
        self._active_worker = worker
        self.batch_started.emit(task)
        try:
            worker.start()
        except Exception:
            self._active_worker = None
            raise

    def resume_batch(self, batch_id: str) -> None:
        """Resume polling for a previously uploaded batch that has not finished."""
        self._ensure_idle()
        entry = self._find_history_entry(batch_id)
        if not entry:
            raise RuntimeError(f"未找到批次 {batch_id} 的历史记录。")

        destination = Path(entry.get("output_dir", "")).expanduser()
        if not destination.exists() or not destination.is_dir():
            raise FileNotFoundError("批次输出目录不存在，请先创建或修改后重试。")

        files = self._files_from_history(entry)
        task = BatchTask(batch_id=batch_id, files=files, output_dir=destination, kind="recovery")
        created_at = _parse_datetime(entry.get("created_at"))
        if created_at:
            task.created_at = created_at

        worker = ResultRecoveryWorker(
            task=task,
            api_client=self._api_client,
            output_dir=destination,
            mode="resume",
        )
        worker.progress_updated.connect(self.progress_updated)
        worker.file_updated.connect(self.file_updated)
        worker.batch_completed.connect(self._handle_batch_completed)
        worker.batch_failed.connect(self._handle_batch_failed)
        worker.log_generated.connect(self.log_generated)
        worker.polling_status.connect(self.polling_status)
        self._active_worker = worker
        self.batch_started.emit(task)
        self._update_history_entry(batch_id, status=HistoryStatus.PROCESSING.value, last_error=None)
        try:
            worker.start()
        except Exception:
            self._active_worker = None
            raise

    def redownload_batch(self, batch_id: str) -> None:
        """Force a re-download of final results for a completed batch."""
        self._ensure_idle()
        entry = self._find_history_entry(batch_id)
        if not entry:
            raise RuntimeError(f"未找到批次 {batch_id} 的历史记录。")

        destination = Path(entry.get("output_dir", "")).expanduser()
        if not destination.exists() or not destination.is_dir():
            raise FileNotFoundError("批次输出目录不存在，请先创建或修改后重试。")

        files = self._files_from_history(entry)
        task = BatchTask(batch_id=batch_id, files=files, output_dir=destination, kind="redownload")
        created_at = _parse_datetime(entry.get("created_at"))
        if created_at:
            task.created_at = created_at

        worker = ResultRecoveryWorker(
            task=task,
            api_client=self._api_client,
            output_dir=destination,
            mode="redownload",
        )
        worker.progress_updated.connect(self.progress_updated)
        worker.file_updated.connect(self.file_updated)
        worker.batch_completed.connect(self._handle_batch_completed)
        worker.batch_failed.connect(self._handle_batch_failed)
        worker.log_generated.connect(self.log_generated)
        worker.polling_status.connect(self.polling_status)
        self._active_worker = worker
        self.batch_started.emit(task)
        self._update_history_entry(batch_id, status=HistoryStatus.PROCESSING.value, last_error=None)
        try:
            worker.start()
        except Exception:
            self._active_worker = None
            raise

    def cancel_active_batch(self) -> None:
        """Attempt to cancel the in-flight worker, if any."""
        if self._active_worker and self._active_worker.isRunning():
            cancel = getattr(self._active_worker, "cancel", None)
            if callable(cancel):
                cancel()

    def update_config(self, config: AppConfig) -> None:
        """Replace the in-memory configuration reference."""
        self._config = config

    def set_api_client(self, api_client: MinerUApiClient) -> None:
        """Swap the API client backing future workers (e.g., after key changes)."""
        self._api_client = api_client

    def has_active_task(self) -> bool:
        """Return True when either worker is currently running."""
        return bool(self._active_worker and self._active_worker.isRunning())

    def get_history(self) -> List[dict]:
        """Provide a defensive copy of history for UI consumption."""
        return copy.deepcopy(self._history)

    def _ensure_idle(self) -> None:
        """Validate that no worker is active before starting a new one."""
        if self._active_worker and self._active_worker.isRunning():
            raise RuntimeError("已有任务正在执行，请等待完成后再试。")

    def _handle_batch_prepared(self, task: BatchTask) -> None:
        """Persist early batch metadata as soon as upload URLs are ready."""
        files = [
            {"path": str(file.path), "display_name": file.display_name}
            for file in task.files
        ]
        self._update_history_entry(
            task.batch_id,
            created_at=task.created_at.isoformat(),
            output_dir=str(task.output_dir or ""),
            files=files,
            status=HistoryStatus.UPLOADING.value,
            success=0,
            failed=0,
            last_error=None,
        )

    def _handle_batch_ready(self, task: BatchTask) -> None:
        """Update history once uploads finish and the API begins processing."""
        self._update_history_entry(
            task.batch_id,
            status=HistoryStatus.PROCESSING.value,
            last_error=None,
        )

    def _handle_batch_completed(self, task: BatchTask) -> None:
        """Finalise history when a batch successfully finishes."""
        logger.info("Batch %s completed", task.batch_id)
        completed_at = (task.completed_at or datetime.utcnow()).isoformat()
        self._update_history_entry(
            task.batch_id,
            status=HistoryStatus.COMPLETED.value,
            success=task.success_count(),
            failed=task.failure_count(),
            completed_at=completed_at,
            timestamp=completed_at,
            last_error=None,
        )
        self.batch_completed.emit(task)
        self._active_worker = None

    def _handle_batch_failed(self, task: BatchTask, message: str) -> None:
        """Persist the failure reason and propagate the failure signal."""
        logger.error("Batch %s failed: %s", task.batch_id, message)
        if task.batch_id:
            timestamp = datetime.utcnow().isoformat()
            self._update_history_entry(
                task.batch_id,
                status=HistoryStatus.FAILED.value,
                last_error=message,
                timestamp=timestamp,
            )
        self.batch_failed.emit(task, message)
        self._active_worker = None

    def _load_history(self) -> List[dict]:
        """Read the history JSON file from disk, normalising legacy structures."""
        if not self.HISTORY_FILE.exists():
            return []
        try:
            raw = json.loads(self.HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("History file is corrupted, starting fresh.")
            return []

        normalized = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            normalized.append(self._normalize_history_entry(entry))
        return normalized[: self._config.history_limit]

    def _normalize_history_entry(self, entry: Dict) -> Dict:
        """Set default values and ensure history entries use the latest schema."""
        files: List[Dict[str, str]] = []
        for item in entry.get("files", []):
            if isinstance(item, dict):
                path_text = item.get("path") or ""
                display = item.get("display_name") or Path(path_text).name
            else:
                path_text = str(item)
                display = Path(path_text).name
            files.append({"path": path_text, "display_name": display})

        created = entry.get("created_at") or entry.get("timestamp") or ""
        completed = entry.get("completed_at") or None
        status = entry.get("status")
        if not status:
            status = HistoryStatus.COMPLETED.value if completed else HistoryStatus.UNKNOWN.value

        normalized = {
            "batch_id": entry.get("batch_id"),
            "created_at": created,
            "completed_at": completed,
            "timestamp": entry.get("timestamp") or completed or created,
            "status": status,
            "success": entry.get("success", 0),
            "failed": entry.get("failed", 0),
            "output_dir": entry.get("output_dir", ""),
            "files": files,
            "last_error": entry.get("last_error"),
        }
        return normalized

    def _save_history(self) -> None:
        """Persist the current history list to disk."""
        serialized = copy.deepcopy(self._history)
        self.HISTORY_FILE.write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _emit_history_update(self) -> None:
        """Notify listeners whenever history changes."""
        self.history_updated.emit(copy.deepcopy(self._history))

    def _update_history_entry(self, batch_id: Optional[str], **updates) -> Optional[dict]:
        """Upsert a history entry with the provided fields and keep the list trimmed."""
        if not batch_id:
            return None
        entry = self._find_history_entry(batch_id)
        if entry is None:
            entry = {
                "batch_id": batch_id,
                "created_at": updates.get("created_at") or datetime.utcnow().isoformat(),
                "completed_at": updates.get("completed_at"),
                "timestamp": updates.get("timestamp"),
                "status": updates.get("status", HistoryStatus.UNKNOWN.value),
                "success": updates.get("success", 0),
                "failed": updates.get("failed", 0),
                "output_dir": updates.get("output_dir", ""),
                "files": updates.get("files", []),
                "last_error": updates.get("last_error"),
            }
            if not entry.get("timestamp"):
                entry["timestamp"] = entry["completed_at"] or entry["created_at"]
            self._history.insert(0, entry)
        else:
            for key, value in updates.items():
                if key == "files":
                    entry[key] = value or []
                elif value is not None:
                    entry[key] = value

        entry["timestamp"] = entry.get("timestamp") or entry.get("completed_at") or entry.get("created_at")
        self._history = self._history[: self._config.history_limit]
        self._save_history()
        self._emit_history_update()
        return entry

    def _find_history_entry(self, batch_id: str) -> Optional[dict]:
        """Return the history entry for a given batch id, or None when missing."""
        for entry in self._history:
            if entry.get("batch_id") == batch_id:
                return entry
        return None

    def _files_from_history(self, entry: Dict) -> List[UploadFile]:
        """Reconstruct UploadFile objects from persisted history metadata."""
        files: List[UploadFile] = []
        for info in entry.get("files", []):
            path_text = info.get("path") if isinstance(info, dict) else str(info)
            display = info.get("display_name") if isinstance(info, dict) else Path(path_text).name
            path_value = Path(path_text) if path_text else Path(display)
            upload = UploadFile(path=path_value, display_name=display)
            files.append(upload)
        return files
