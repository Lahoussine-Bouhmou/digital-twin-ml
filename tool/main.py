"""
Entry point for the Layout Viewer 3D tool.

Usage (from PARENT folder of 'tool'):
    python tool/main.py
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Add the tool folder itself to sys.path so sibling imports work
_tool_dir = str(Path(__file__).resolve().parent)
if _tool_dir not in sys.path:
    sys.path.insert(0, _tool_dir)

# Fix PySide6/Qt DLL conflicts in conda environments:
# Remove conda's qt paths from PATH so PySide6 finds its own Qt DLLs
_conda_prefix = os.environ.get("CONDA_PREFIX", "")
if _conda_prefix:
    _qt_plugin_path = os.path.join(_conda_prefix, "Library", "plugins")
    if os.environ.get("QT_PLUGIN_PATH", "").startswith(_conda_prefix):
        del os.environ["QT_PLUGIN_PATH"]
    # Also try setting PySide6's own plugin path
    try:
        import PySide6
        _pyside_dir = str(Path(PySide6.__file__).parent)
        os.environ["QT_PLUGIN_PATH"] = os.path.join(_pyside_dir, "plugins")
    except Exception:
        pass

from PySide6.QtWidgets import QApplication
from main_window import MainWindow


DARK_THEME_QSS = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Calibri", sans-serif;
    font-size: 12px;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    background: #1e1e2e;
}
QTabBar::tab {
    background: #313244;
    color: #a6adc8;
    padding: 6px 16px;
    border: 1px solid #45475a;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #1e1e2e;
    color: #cdd6f4;
    border-bottom: 2px solid #89b4fa;
}
QTabBar::tab:hover {
    background: #45475a;
}
QToolBar {
    background: #181825;
    border-bottom: 1px solid #45475a;
    spacing: 4px;
    padding: 2px;
}
QToolBar QToolButton {
    background: transparent;
    color: #cdd6f4;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
}
QToolBar QToolButton:hover {
    background: #313244;
    border-color: #45475a;
}
QToolBar QToolButton:pressed {
    background: #45475a;
}
QPushButton {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 16px;
    min-width: 80px;
}
QPushButton:hover {
    background: #45475a;
    border-color: #585b70;
}
QPushButton:pressed {
    background: #585b70;
}
QPushButton:disabled {
    background: #1e1e2e;
    color: #585b70;
    border-color: #313244;
}
QTableView {
    background: #181825;
    alternate-background-color: #1e1e2e;
    color: #cdd6f4;
    gridline-color: #313244;
    border: 1px solid #45475a;
    selection-background-color: #45475a;
    selection-color: #cdd6f4;
}
QTableView::item {
    padding: 4px;
}
QHeaderView::section {
    background: #313244;
    color: #a6adc8;
    border: 1px solid #45475a;
    padding: 4px 8px;
    font-weight: bold;
}
QListWidget {
    background: #181825;
    color: #f9e2af;
    border: 1px solid #45475a;
    font-size: 11px;
}
QListWidget::item {
    padding: 2px 4px;
}
QLabel {
    color: #cdd6f4;
}
QStatusBar {
    background: #181825;
    color: #a6adc8;
    border-top: 1px solid #45475a;
}
QSplitter::handle {
    background: #45475a;
    width: 2px;
}
QScrollBar:vertical {
    background: #1e1e2e;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #1e1e2e;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #45475a;
    border-radius: 4px;
    min-width: 20px;
}
"""


def main() -> None:
    """Launch the Layout Viewer 3D application."""
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME_QSS)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
