# MinerU PDF 解析客户端

一个基于 **PySide6** 构建的 MinerU 本地桌面客户端，提供批量上传、云端解析、结果下载与历史任务管理等功能，旨在让用户以可视化方式充分利用 MinerU 官方 API 的能力。

---

## ✨ 功能概览

- **图形化批量处理**：通过拖拽或文件选择器快速导入本地 PDF，并支持批量上传。
- **云端解析调度**：自动对接 MinerU API，执行上传、轮询解析状态、下载结果和整理输出。
- **任务恢复能力**：
  - 程序意外关闭后，可从历史记录中重新启动轮询任务；
  - 已完成的批次可再次下载结果；
  - 对于失败批次，提供重新上传文件的提示信息。
- **运行状态可视化**：实时展示上传/解析进度、任务统计、轮询日志和历史记录。
- **配置持久化**：保存 API Key、输出目录和解析选项，支持加密存储 API Key。
- **日志记录**：自动滚动保存运行日志，便于排查问题。

---

## 🛠️ 环境准备

1. **Python 版本**：建议 Python 3.10 及以上。
2. **安装依赖**：

   ```bash
   pip install -r requirements.txt
   ```

   > 本项目核心依赖包含：
   > - PySide6
   > - requests
   > - pydantic
   > - cryptography

3. **配置 MinerU API**：
   - 在应用首次启动时设置 API Key。
   - 若本地已有自定义 `config.json` / `key.key`，可直接放置于项目根目录。
   - 项目提供 `docs/API_DOC.md`，记录 MinerU API 的使用说明与字段含义。

---

## 🚀 启动方式

```bash
python main.py
```

启动后会加载主窗口，按照界面指引即可完成文件导入、选项配置以及任务启动。

---

## 📁 目录结构

| 目录 / 文件            | 说明                                                         |
| ---------------------- | ------------------------------------------------------------ |
| `main.py`              | 程序入口，负责启动 Qt 应用。                                 |
| `app.py`               | 应用初始化逻辑，挂载主题与主窗口。                           |
| `core/`                | 核心数据结构、配置模型与加密配置管理器。                     |
| `services/`            | 与 API、日志、任务调度相关的服务层模块。                     |
| `docs/`                | 项目文档（`API_DOC.md`、`ARCHITECTURE.md` 等）。              |
| `ui/`                  | 主界面、主题样式与 UI 相关定义。                             |
| `widgets/`             | 自定义控件：文件队列、日志视图、状态摘要、任务历史等。       |
| `tests/`               | 配置组件的单元测试示例。                                     |
| `logs/`                | 运行期间自动生成的日志。                                     |
| `config.json` / `key.key` | 用户配置与密钥文件，自动生成，可加密保存 API Key。         |

---

## 🔄 主要工作流程

1. **添加文件**：拖拽或点击“添加文件”，文件会显示在“文件选择”区。
2. **配置选项**：输入/编辑 API Key、输出目录、解析模板等参数，支持保存配置。
3. **启动批次**：点击“开始解析”后，任务交由后台线程执行，实时同步状态到界面。
4. **查看结果**：完成后可直接打开输出目录或下载的 Markdown 摘要。
5. **历史记录恢复**：可在历史标签页重启轮询或重新下载失败的批次结果。

---

## 🧪 测试说明

- 使用 `pytest` 运行单元测试：

  ```bash
  pytest
  ```

- 如需模拟 API 通信，可在测试中使用 `responses` 或自建 Mock 服务。

---

## 📦 发布与编译建议（Nuitka）

推荐使用 Nuitka 进行编译以获得更佳性能和体积：

```bash
python -m nuitka main.py \
  --standalone \
  --enable-plugin=pyside6 \
  --include-data-dir=ui=ui \
  --include-data-dir=widgets=widgets \
  --include-data-dir=core=core \
  --include-data-files=docs/API_DOC.md=docs/API_DOC.md \
  --include-data-files=docs/ARCHITECTURE.md=docs/ARCHITECTURE.md \
  --follow-imports \
  --nofollow-import-to=tests \
  --include-qt-plugins=sensible,styles \
  --windows-console-mode=disable \
  --output-dir=dist \
  --remove-output
```

### Windows 编译环境说明

- MinGW 方案：在 MSYS2 UCRT64 shell 中安装 `mingw-w64-ucrt-x86_64-toolchain` 与 `mingw-w64-ucrt-x86_64-zlib` 等依赖后再构建。
- MSVC 方案（推荐）：使用 VS 2022 Build Tools（x64 Native Tools 命令提示符），搭配下方 PBS 独立 Python 环境可最大化隔离系统差异。

## 🧱 使用 python-build-standalone（可选）

若希望构建与系统 Python/Conda 解耦，可使用 `python-build-standalone`（PBS）+ MSVC 搭建独立编译环境：

1. 下载 PBS 发行包（例：`cpython-3.11.x-windows-msvc-shared-full`）并解压到 `C:\\tools\\python311-standalone`。
2. 安装 VS 2022 Build Tools（x64 Native Tools 命令提示符）。
3. 在 PBS Python 中安装依赖：
   ```bat
   set PYTHON_HOME=C:\\tools\\python311-standalone
   %PYTHON_HOME%\\python.exe -m pip install -U pip wheel
   %PYTHON_HOME%\\python.exe -m pip install nuitka ordered-set zstandard
   %PYTHON_HOME%\\python.exe -m pip install PySide6 requests pydantic cryptography
   ```
4. 用 PBS Python 执行上方 Nuitka 构建命令（建议保留 `--windows-console-mode=disable`）。

更多细节与排错建议请参考 `docs/ARCHITECTURE.md` 的“与编译/发布相关的注意事项”。

---

如有疑问或建议，欢迎提交 Issue 或直接联系维护者。祝使用愉快！🙏
