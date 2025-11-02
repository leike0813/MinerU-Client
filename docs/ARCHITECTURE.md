# MinerU Client Architecture

## Overview

The application follows a four-layer structure:

1. **Application Layer (`app.py`, `main.py`)**  
   Boots the Qt event loop, sets up logging, and instantiates the main window.

2. **Presentation Layer (`ui/`, `widgets/`)**  
   Contains Qt Widgets and views responsible for rendering UI and handling user interactions.  
   `ui/main_window.py` orchestrates layout, configuration forms, and tabbed panels (logs/history).  
   `widgets/` hosts reusable components: file queue management, log viewer, status summary, and history list.

3. **Service Layer (`services/`)**  
   Encapsulates business workflows.  
   - `api_client.py` wraps MinerU HTTP endpoints with retry logic.  
   - `task_manager.py` coordinates background workers, handles retries, downloads, and history persistence.  
   - `logger.py` configures rotating file/console logging.

4. **Core Layer (`core/`)**  
   Holds configuration and domain models (`config.py`, `models.py`).  
   Configuration persistence encrypts the API key and offers typed access to runtime options.

## Threading Model

- `TaskManager` spawns a `BatchWorker` (`QThread`) for each batch execution to keep the UI responsive.
- Worker emits progress/file updates via Qt signals back to the `MainWindow`.
- Cancellation requests propagate through `TaskManager` to the worker, which checks a cancellation flag during uploads and polling.

## Persistence

- Application config stored in `config.json`, encrypted with a Fernet key (`key.key`).  
- Task history saved to `.mineru_history.json`, capped by `AppConfig.history_limit`.
- Log files written under `./logs/mineru-client_<timestamp>.log`, with the most recent run marked `_recent` and automatically rotated on startup.
- Batch results are extracted to `<output>/<batch_id>/<file_stem>/…`, and the Markdown summary `full.md` is duplicated to `<output>/<batch_id>/<file_stem>.md` for quick access.

## Extensibility Notes

- UI themes can be swapped by adding new `.qss` files under `ui/theme/` and calling `apply_theme(app, "theme_name")`.
- Additional widgets (e.g., analytics, queue inspectors) should live in `widgets/` and communicate via signals to keep the presentation layer modular.
- Service layer functions avoid Qt dependencies (except signal definitions) to stay testable; HTTP retries use `requests` + `urllib3.Retry`.
