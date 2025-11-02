# MinerU 客户端架构说明（中文）

本文档描述当前代码版本的整体架构、线程与信号模型、数据持久化设计以及关键业务流程，便于快速理解与维护。

> 相关 API 文档已迁移至：`docs/API_DOC.md`

---

## 1. 分层结构概览

项目采用“应用 → 表现（UI）→ 服务 → 核心”的四层结构：

1) 应用层（`app.py`, `main.py`）
- 启动 Qt 事件循环，初始化日志，创建主窗口。

2) 表现层（`ui/`, `widgets/`）
- `ui/main_window.py`：主窗口与整体布局，包含“文件选择 / 任务历史 / 设置 / 日志”四大区块（带标题）。
- `widgets/`：可复用控件（文件队列、日志视图、状态摘要、任务历史等）。
- `ui/theme/`：包含暗色主题 QSS，后续可扩展更多主题。

3) 服务层（`services/`）
- `api_client.py`：HTTP API 调用封装及重试策略。
- `task_manager.py`：批次上传、轮询、结果下载、历史记录持久化、自动重试。
- `logger.py`：标准化日志记录，提供文件与控制台双写。

4) 核心层（`core/`）
- `config.py`：应用配置（路径、API Key、选项）及 AES 加密存储。
- `models.py`：领域模型（上传文件、批次状态、历史记录项等）。

---

## 2. 启动流程与依赖图

```mermaid
flowchart TD
    A([main.py]) -->|创建| B[App(QApplication)]
    B --> C[load_theme]
    B --> D[MainWindow]
    D --> E[FileQueueWidget]
    D --> F[TaskHistoryWidget]
    D --> G[StatusSummaryWidget]
    D --> H[LogViewWidget]
    D --> I[ConfigPanel]
```

- `main.py` 调用 `App.run()`，内部创建 `QApplication` 实例并加载主题。
- `MainWindow` 在初始化时读取 `AppConfig`，绑定 UI 控件与服务层。
- UI 控件通过信号连接 `TaskManager`；后者再调用 `MinerUApiClient` 进行网络请求。

---

## 3. TaskManager 线程模型

`TaskManager` 在 `start_batch` 时会：

1. 为每个批次创建 `BatchWorker(QThread)`。
2. 将 `UploadFile` 列表传入，调用 `MinerUApiClient.create_batch` 上传文件。
3. 通过信号 `progress_updated`, `file_updated`, `batch_completed`, `batch_failed` 等反馈状态。
4. 定时轮询远端状态（`POLL_INTERVAL=2s`），直至成功/失败/取消。
5. 下载结果包，解压到批次目录，并复制 `full.md` 到批次根目录。

所有线程间通信都使用 Qt 信号/槽，避免 GIL 争用。`TaskManager` 本身运行在主线程，只负责调度与状态同步。

---

## 4. 历史记录与配置持久化

- 历史记录保存在 `~/.mineru_history.json`，结构化记录批次状态、最后更新时间、错误信息。
- 配置持久化文件：
  - `config.json`：除 API Key 外的其他选项。
  - `key.key`：AES 密钥文件。
  - API Key 会使用 `ConfigManager` 的 `TokenCipher` 进行加密存储。
- `AppConfig.load()` 会在启动时读取这些文件，若缺失则创建默认配置。

---

## 5. 主界面核心交互

| 模块 | 入口 | 说明 |
| ---- | ---- | ---- |
| 文件队列 | `widgets/file_queue.py` | 维护拖拽/选择添加的文件列表，支持删除与批量清空。 |
| 状态摘要 | `widgets/status_summary.py` | 显示当前批次计数、成功/失败任务数，以及是否正在运行。 |
| 日志视图 | `widgets/log_view.py` | 滚动展示运行日志，支持复制。 |
| 任务历史 | `widgets/task_history.py` | 展示历史记录列表，支持重新轮询、打开目录。 |
| 设置面板 | `ui/main_window.py` | 修改 API Key、输出目录、批处理选项，并持久化到配置文件。 |

---

## 6. API Client 概要

`MinerUApiClient` 使用 `requests` 库与官方 API 通信，封装以下行为：

- `create_batch(files, options)`：创建批次并返回签名上传 URL。
- `upload_file(url, file_path)`：将文件上传到签名地址。
- `poll_batch_status(batch_id)`：轮询解析状态。
- `download_result(download_url)`：下载 ZIP 结果包。

遇到网络错误/超时时会进行指数退避重试。所有请求会带上 `Authorization` 头与 `AppOptions` 中配置的参数。

---

## 7. 编译与发布注意事项

### Nuitka 打包建议

- 参考 `README.md` 提供的脚本参数，确保 UI/核心/文档目录被一并打包。
- 对于 Windows 平台，建议使用 MSVC 工具链以减少兼容性问题。

### python-build-standalone (PBS) + MSVC

- 使用 PBS 的独立 Python，可减少用户环境差异导致的构建问题。
- 构建前需在 PBS 解释器中安装项目依赖及 Nuitka。

---

## 8. 后续扩展方向

- 多语言界面支持（Qt 翻译文件）。
- 自定义任务分组与标签。
- 断点续传、增量同步结果。
- CI/CD 自动化打包流程（GitHub Actions + Nuitka）。

---

## 9. 常见排错

1. **无法连接 API**：检查网络是否代理、API Key 是否正确、或官方服务是否维护。
2. **解析超时**：适当增加轮询间隔或重试次数，可在 `AppOptions` 中配置。
3. **下载结果失败**：确认输出目录是否存在/可写，以及签名 URL 是否过期。
4. **Qt 插件缺失**：Nuitka 打包时需包含 `platforms`、`styles`、`iconengines` 等必要插件。

---

## 10. 术语表

- **批次（Batch）**：一次上传的文件集合。
- **上传文件（UploadFile）**：批次中的单个文件项，包含路径、显示名称、状态。
- **轮询（Polling）**：定期向 API 查询批次进度。
- **历史记录（HistoryEntry）**：批次执行结果及元数据的持久化记录。

---

如需了解 API 字段与示例，请参阅 `docs/API_DOC.md`。
