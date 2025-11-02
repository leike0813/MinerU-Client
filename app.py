"""Bootstrap helpers for launching the MinerU Qt application."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from services.logger import setup_logging
from ui.main_window import MainWindow


def run() -> None:
    """Initialise logging, create the Qt application, and start the event loop."""
    app = QApplication(sys.argv)
    setup_logging()

    # Instantiate the main window after logging is ready so UI events are captured.
    window = MainWindow(app)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
