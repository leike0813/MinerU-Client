"""Utility helpers for applying the bundled Qt stylesheet."""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication, theme_name: str = "dark") -> None:
    """Apply the chosen QSS theme to a QApplication instance."""
    theme_path = Path(__file__).resolve().parent / f"{theme_name}.qss"
    if not theme_path.exists():
        return
    app.setStyleSheet(theme_path.read_text(encoding="utf-8"))
