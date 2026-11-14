"""Compatibility entry point for the desktop UI."""
from ..core.config import PRESETS_FILE
from .main_window import MainWindow
from .automation import main, _automate
from .presets import load_presets, save_presets
from .preview_view import PreviewView
from .export_worker import ExportWorker

if __name__ == "__main__":
    raise SystemExit(main())
