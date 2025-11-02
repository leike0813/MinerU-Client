"""Entry point for launching the MinerU Qt application."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app import App


def main() -> int:
    """Create a Qt application and start the MinerU client UI."""
    app = QApplication(sys.argv)
    client = App(app)

    client.run()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
