"""
main_window.py - Main application window for the Layout Viewer 3D tool.

PySide6 + pyvistaqt architecture:
  Left panel  (40%): QTabWidget with Import and Equipment tabs
  Right panel (60%): pyvistaqt.QtInteractor for 3D scene
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QSlider,
)
import pyvistaqt

import equipment_editor
from measurement_engine import MeasurementEngine
from scene_builder import SceneBuilder
import noise_generator

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Equipment table model
# ---------------------------------------------------------------------------
COLUMNS = [
    ("tag", "Tag"),
    ("equipment_type", "Type"),
    ("center_x_mm", "X (mm)"),
    ("center_y_mm", "Y (mm)"),
    ("width_mm", "Width"),
    ("depth_mm", "Depth"),
    ("diameter_mm", "Dia"),
    ("height_mm", "Height"),
    ("weight_kg", "Weight (kg)"),
]


class EquipmentTableModel(QAbstractTableModel):
    """Table model backed by the equipment list from parsed JSON."""

    WARN_COLOR = QColor("#6b5b00")
    WARN_BG = QColor("#3d3500")

    data_edited = Signal()  # fires after a successful setData()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[dict] = []

    def set_data(self, equipment: list[dict]):
        self.beginResetModel()
        self._data = list(equipment)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section][1]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._data[index.row()]
        key = COLUMNS[index.column()][0]
        val = row.get(key)

        if role == Qt.ItemDataRole.DisplayRole:
            if val is None:
                return "-"
            if isinstance(val, float):
                return str(int(val))
            return str(val)

        if role == Qt.ItemDataRole.BackgroundRole:
            defaults = row.get("defaults_applied", [])
            if key in defaults:
                return QBrush(self.WARN_BG)

        if role == Qt.ItemDataRole.ForegroundRole:
            defaults = row.get("defaults_applied", [])
            if key in defaults:
                return QBrush(self.WARN_COLOR)

        return None

    def flags(self, index):
        base = super().flags(index)
        key = COLUMNS[index.column()][0]
        row = self._data[index.row()]
        defaults = row.get("defaults_applied", [])
        if key in defaults:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole:
            return False
        key = COLUMNS[index.column()][0]
        try:
            self._data[index.row()][key] = int(float(value))
            # Remove from defaults_applied
            da = self._data[index.row()].get("defaults_applied", [])
            if key in da:
                da.remove(key)
            self.dataChanged.emit(index, index)
            self.data_edited.emit()
            return True
        except (ValueError, TypeError):
            return False

    def get_equipment_list(self) -> list[dict]:
        return self._data

    def tag_at_row(self, row: int) -> str:
        if 0 <= row < len(self._data):
            return self._data[row].get("tag", "")
        return ""


# ---------------------------------------------------------------------------
# Import tab
# ---------------------------------------------------------------------------
class ImportTab(QWidget):
    """Tab for loading SVG files and showing parse results."""

    svg_loaded = Signal(dict)  # emits parsed layout dict

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_data = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # File section
        layout.addWidget(QLabel("SVG Layout File:"))
        btn_row = QHBoxLayout()
        self._btn_svg = QPushButton("Load SVG...")
        self._btn_svg.clicked.connect(self._on_load_svg)
        btn_row.addWidget(self._btn_svg)
        self._lbl_svg = QLabel("No file loaded")
        self._lbl_svg.setStyleSheet("color: #888;")
        btn_row.addWidget(self._lbl_svg, 1)
        layout.addLayout(btn_row)

        # Excel section
        layout.addWidget(QLabel("Equipment List (optional):"))
        btn_row2 = QHBoxLayout()
        self._btn_xlsx = QPushButton("Load Excel...")
        self._btn_xlsx.clicked.connect(self._on_load_excel)
        self._btn_xlsx.setEnabled(False)
        btn_row2.addWidget(self._btn_xlsx)
        self._lbl_xlsx = QLabel("No file loaded")
        self._lbl_xlsx.setStyleSheet("color: #888;")
        btn_row2.addWidget(self._lbl_xlsx, 1)
        layout.addLayout(btn_row2)

        # Summary
        layout.addWidget(QLabel("Parse Summary:"))
        self._lbl_summary = QLabel("-")
        self._lbl_summary.setWordWrap(True)
        layout.addWidget(self._lbl_summary)

        # Warnings
        layout.addWidget(QLabel("Warnings:"))
        self._warnings_list = QListWidget()
        self._warnings_list.setMaximumHeight(150)
        layout.addWidget(self._warnings_list)

        layout.addStretch()

    def _on_load_svg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SVG Layout", "",
            "SVG Files (*.svg);;All Files (*)"
        )
        if not path:
            return

        from svg_layout_parser import SvgLayoutParser

        try:
            parser = SvgLayoutParser(path)
            result = parser.parse()
        except Exception as exc:
            QMessageBox.critical(self, "Parse Error", str(exc))
            return

        self._layout_data = result
        self._svg_path = path
        self._lbl_svg.setText(Path(path).name)
        self._lbl_svg.setStyleSheet("color: #aaddaa;")
        self._btn_xlsx.setEnabled(True)

        # Update summary
        n_eq = len(result.get("equipment", []))
        bnd = result.get("module_boundary", {})
        w = bnd.get("width_mm")
        l = bnd.get("length_mm")
        scale = result.get("scale_mm_per_pt")
        summary = (
            "Equipment: %d items\n"
            "Module: %s x %s mm\n"
            "Scale: %s mm/pt"
            % (n_eq,
               str(w) if w else "?",
               str(l) if l else "?",
               "%.2f" % scale if scale else "?")
        )
        self._lbl_summary.setText(summary)

        # Warnings
        self._warnings_list.clear()
        for warn in result.get("parser_warnings", []):
            self._warnings_list.addItem(warn)

        self.svg_loaded.emit(result)

    def _on_load_excel(self):
        if not self._layout_data:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Equipment List", "",
            "Excel Files (*.xlsx *.xls);;All Files (*)"
        )
        if not path:
            return

        from svg_layout_parser import SvgLayoutParser

        try:
            # Standalone parser: no SVG re-parse, just merge into existing list
            merger = SvgLayoutParser(svg_path=None, excel_path=path)
            merger._merge_excel(self._layout_data["equipment"])
        except Exception as exc:
            QMessageBox.critical(self, "Excel Merge Error", str(exc))
            return

        self._layout_data.setdefault("parser_warnings", []).extend(
            merger.warnings
        )

        self._lbl_xlsx.setText(Path(path).name)
        self._lbl_xlsx.setStyleSheet("color: #aaddaa;")

        n_eq = len(self._layout_data.get("equipment", []))
        bnd = self._layout_data.get("module_boundary", {})
        summary = (
            "Equipment: %d items (with Excel data)\n"
            "Module: %s x %s mm"
            % (n_eq,
               bnd.get("width_mm", "?"),
               bnd.get("length_mm", "?"))
        )
        self._lbl_summary.setText(summary)

        self._warnings_list.clear()
        for warn in self._layout_data.get("parser_warnings", []):
            self._warnings_list.addItem(warn)

        self.svg_loaded.emit(self._layout_data)

    def get_layout_data(self) -> dict | None:
        return self._layout_data


# ---------------------------------------------------------------------------
# Equipment tab
# ---------------------------------------------------------------------------
class EquipmentTab(QWidget):
    """Tab showing editable equipment table."""

    row_selected = Signal(str)  # emits tag name
    equipment_changed = Signal()  # fires when a cell edit completes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._suppress_emit = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        info = QLabel(
            "Cells highlighted in dark yellow use default values. "
            "Double-click to edit."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(info)

        self._model = EquipmentTableModel()
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QTableView.SelectionMode.SingleSelection
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setAlternatingRowColors(True)
        self._table.selectionModel().currentRowChanged.connect(
            self._on_row_changed
        )
        self._model.data_edited.connect(self.equipment_changed)
        layout.addWidget(self._table)

    def set_equipment(self, equipment: list[dict]):
        self._model.set_data(equipment)

    def get_table_model(self) -> EquipmentTableModel:
        return self._model

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex):
        if self._suppress_emit:
            return
        tag = self._model.tag_at_row(current.row())
        if tag:
            self.row_selected.emit(tag)

    def select_row_by_tag(self, tag: str):
        """Programmatically select the row matching tag; emission suppressed."""
        for row, eq in enumerate(self._model.get_equipment_list()):
            if eq.get("tag") == tag:
                self._suppress_emit = True
                try:
                    self._table.selectRow(row)
                    idx = self._model.index(row, 0)
                    self._table.scrollTo(idx)
                finally:
                    self._suppress_emit = False
                return


# ---------------------------------------------------------------------------
# Measurement tab
# ---------------------------------------------------------------------------
class MeasureTab(QWidget):
    """Distance measurement panel.

    Owns the pick-A/pick-B state machine and the Edge vs Center mode.
    Delegates distance math to MeasurementEngine via the MainWindow.
    """

    measurement_ready = Signal(object)   # MeasurementResult
    measurement_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ref_a = None
        self._ref_b = None
        self._pick_slot = "A"
        self._engine: MeasurementEngine | None = None
        self._last_result = None
        self._setup_ui()

    def set_engine(self, engine: MeasurementEngine):
        """Plug in the measurement engine (refreshed per-load)."""
        self._engine = engine

    # ----- UI --------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Distance Measurement"))

        # Pick A row
        row_a = QHBoxLayout()
        row_a.addWidget(QLabel("Pick A:"))
        self._lbl_a = QLabel("<none>")
        self._lbl_a.setStyleSheet("color: #aaddaa;")
        row_a.addWidget(self._lbl_a, 1)
        self._btn_clear_a = QPushButton("Clear")
        self._btn_clear_a.clicked.connect(self._clear_a)
        row_a.addWidget(self._btn_clear_a)
        layout.addLayout(row_a)

        # Pick B row
        row_b = QHBoxLayout()
        row_b.addWidget(QLabel("Pick B:"))
        self._lbl_b = QLabel("<none>")
        self._lbl_b.setStyleSheet("color: #aaddaa;")
        row_b.addWidget(self._lbl_b, 1)
        self._btn_clear_b = QPushButton("Clear")
        self._btn_clear_b.clicked.connect(self._clear_b)
        row_b.addWidget(self._btn_clear_b)
        layout.addLayout(row_b)

        # Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self._rb_edge = QRadioButton("Edge-to-Edge")
        self._rb_center = QRadioButton("Center-to-Center")
        self._rb_edge.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._rb_edge)
        self._mode_group.addButton(self._rb_center)
        self._rb_edge.toggled.connect(self._refresh_result_labels)
        mode_row.addWidget(self._rb_edge)
        mode_row.addWidget(self._rb_center)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Results box
        res_box = QFrame()
        res_box.setFrameShape(QFrame.Shape.StyledPanel)
        res_box.setStyleSheet("QFrame { background: #2a2a3a; padding: 6px; }")
        res_layout = QVBoxLayout(res_box)
        res_layout.setContentsMargins(8, 8, 8, 8)
        res_layout.addWidget(QLabel("Results:"))
        self._lbl_x = QLabel("X distance:   -")
        self._lbl_y = QLabel("Y distance:   -")
        self._lbl_d = QLabel("Direct:       -")
        for lbl in (self._lbl_x, self._lbl_y, self._lbl_d):
            lbl.setStyleSheet("font-family: Consolas; font-size: 13px;")
            res_layout.addWidget(lbl)
        layout.addWidget(res_box)

        # Clear all
        self._btn_clear_all = QPushButton("Clear All")
        self._btn_clear_all.clicked.connect(self._clear_all)
        layout.addWidget(self._btn_clear_all)

        layout.addStretch()

    # ----- state machine ---------------------------------------------------

    def receive_pick(self, ref):
        """External entry point: a 3D pick produced this MeasurementRef."""
        if ref is None:
            return
        if self._pick_slot == "A":
            self._ref_a = ref
            self._lbl_a.setText(ref.display_name)
            self._pick_slot = "B"
        else:
            self._ref_b = ref
            self._lbl_b.setText(ref.display_name)
            # Cycle: next pick replaces A again
            self._pick_slot = "A"

        if self._ref_a is not None and self._ref_b is not None and self._engine:
            self._last_result = self._engine.measure(self._ref_a, self._ref_b)
            self._refresh_result_labels()
            self.measurement_ready.emit(self._last_result)

    def _refresh_result_labels(self):
        r = self._last_result
        if r is None:
            self._lbl_x.setText("X distance:   -")
            self._lbl_y.setText("Y distance:   -")
            self._lbl_d.setText("Direct:       -")
            return
        if self._rb_edge.isChecked():
            x = r.dx_edge
            y = r.dy_edge
        else:
            x = r.dx_center
            y = r.dy_center
        self._lbl_x.setText("X distance:  %s mm" % _fmt_mm(x))
        self._lbl_y.setText("Y distance:  %s mm" % _fmt_mm(y))
        self._lbl_d.setText("Direct:      %s mm" % _fmt_mm(r.direct))

    def _clear_a(self):
        self._ref_a = None
        self._lbl_a.setText("<none>")
        self._pick_slot = "A"
        self._last_result = None
        self._refresh_result_labels()
        self.measurement_cleared.emit()

    def _clear_b(self):
        self._ref_b = None
        self._lbl_b.setText("<none>")
        self._pick_slot = "B"
        self._last_result = None
        self._refresh_result_labels()
        self.measurement_cleared.emit()

    def _clear_all(self):
        self._ref_a = None
        self._ref_b = None
        self._lbl_a.setText("<none>")
        self._lbl_b.setText("<none>")
        self._pick_slot = "A"
        self._last_result = None
        self._refresh_result_labels()
        self.measurement_cleared.emit()


def _fmt_mm(v: float) -> str:
    """Format a mm value with thousands separator."""
    return "{:,}".format(int(round(v)))


# ---------------------------------------------------------------------------
# Add-equipment dialog
# ---------------------------------------------------------------------------
class AddEquipmentDialog(QDialog):
    """Modal form to create a new equipment entry."""

    def __init__(self, layout_data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add equipment")
        self._layout_data = layout_data
        self._result: dict | None = None
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)

        form = QFormLayout()
        self._tag = QLineEdit()
        self._type = QComboBox()
        self._type.addItems(["box", "vertical_vessel", "horizontal_vessel"])
        self._type.currentTextChanged.connect(self._update_dim_fields)

        self._cx = _spin(-1e6, 1e6, 0)
        self._cy = _spin(-1e6, 1e6, 0)
        self._cz = _spin(-1e6, 1e6, 0)
        self._rot = _spin(0, 360, 0)

        # Dimension fields (shown selectively per type)
        self._width = _spin(1, 1e6, 2000)
        self._depth = _spin(1, 1e6, 2000)
        self._diameter = _spin(1, 1e6, 1500)
        self._length = _spin(1, 1e6, 4000)
        self._height = _spin(1, 1e6, 2000)
        self._weight = _spin(0, 1e7, 1000)

        form.addRow("Tag:", self._tag)
        form.addRow("Type:", self._type)
        form.addRow("Center X (mm):", self._cx)
        form.addRow("Center Y (mm):", self._cy)
        form.addRow("Elevation Z (mm):", self._cz)
        form.addRow("Rotation (deg):", self._rot)

        self._row_width = form.rowCount()
        form.addRow("Width (mm):", self._width)
        self._row_depth = form.rowCount()
        form.addRow("Depth (mm):", self._depth)
        self._row_diam = form.rowCount()
        form.addRow("Diameter (mm):", self._diameter)
        self._row_len = form.rowCount()
        form.addRow("Length (mm):", self._length)
        form.addRow("Height (mm):", self._height)
        form.addRow("Weight (kg):", self._weight)

        outer.addLayout(form)

        self._err = QLabel("")
        self._err.setStyleSheet("color: #ff8080;")
        outer.addWidget(self._err)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._try_accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        self._update_dim_fields(self._type.currentText())

    def _update_dim_fields(self, eq_type: str):
        show_w = show_d = show_diam = show_len = False
        if eq_type == "box":
            show_w = show_d = True
        elif eq_type == "vertical_vessel":
            show_diam = True
        elif eq_type == "horizontal_vessel":
            show_len = show_diam = True
        self._width.setEnabled(show_w)
        self._depth.setEnabled(show_d)
        self._diameter.setEnabled(show_diam)
        self._length.setEnabled(show_len)

    def _try_accept(self):
        tag = self._tag.text().strip()
        if not tag:
            self._err.setText("Tag is required.")
            return
        if not equipment_editor.validate_tag_unique(self._layout_data, tag):
            self._err.setText("Tag already exists; choose a unique name.")
            return
        try:
            self._result = equipment_editor.make_new_equipment(
                tag=tag,
                eq_type=self._type.currentText(),
                center_x_mm=self._cx.value(),
                center_y_mm=self._cy.value(),
                width_mm=self._width.value(),
                depth_mm=self._depth.value(),
                diameter_mm=self._diameter.value(),
                length_mm=self._length.value(),
                height_mm=self._height.value(),
                weight_kg=self._weight.value(),
                elevation_mm=self._cz.value(),
                rotation_deg=self._rot.value(),
            )
        except Exception as exc:
            self._err.setText(str(exc))
            return
        self.accept()

    def result_equipment(self) -> dict | None:
        return self._result


def _spin(minv: float, maxv: float, default: float) -> QDoubleSpinBox:
    sp = QDoubleSpinBox()
    sp.setDecimals(1)
    sp.setRange(float(minv), float(maxv))
    sp.setValue(float(default))
    sp.setSingleStep(100.0)
    return sp

# Added
def _int_spin(minv: int, maxv: int, default: int) -> QSpinBox:
    sp = QSpinBox()
    sp.setRange(int(minv), int(maxv))
    sp.setValue(int(default))
    sp.setSingleStep(1)
    return sp

# ---------------------------------------------------------------------------
# Edit tab
# ---------------------------------------------------------------------------
class EditTab(QWidget):
    """Add / delete / move / rotate / align equipment."""

    equipment_modified = Signal(str)  # tag or "__all__"
    noise_generation_requested = Signal(dict)
    noise_preview_requested = Signal(str)   # "prev", "next", "clean"
    noise_preview_index_requested = Signal(int)  # 0-based index

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_data: dict | None = None
        self._suppress_emit = False
        self._build_ui()
        self._refresh_state()

    # ---- wiring from MainWindow -----------------------------------------

    def set_layout_data(self, layout_data: dict | None):
        self._layout_data = layout_data
        self._reload_target_list()

    def select_tag(self, tag: str):
        """Programmatically select a single tag in the target list."""
        self._suppress_emit = True
        try:
            self._list.clearSelection()
            for i in range(self._list.count()):
                if self._list.item(i).text() == tag:
                    self._list.item(i).setSelected(True)
                    self._list.setCurrentRow(i)
                    break
        finally:
            self._suppress_emit = False
        self._refresh_state()

    # ---- UI --------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        outer = QVBoxLayout(container)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        outer.addWidget(QLabel("Targets (Ctrl/Shift-click for multi):"))
        self._list = QListWidget()
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._list.setMaximumHeight(140)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        outer.addWidget(self._list)

        row = QHBoxLayout()
        self._btn_add = QPushButton("+ Add...")
        self._btn_add.clicked.connect(self._on_add)
        row.addWidget(self._btn_add)
        self._btn_delete = QPushButton("Delete selected")
        self._btn_delete.clicked.connect(self._on_delete)
        row.addWidget(self._btn_delete)
        outer.addLayout(row)

        # --- Properties (single only)
        self._props_box = QFrame()
        self._props_box.setFrameShape(QFrame.Shape.StyledPanel)
        pb = QVBoxLayout(self._props_box)
        pb.setContentsMargins(8, 8, 8, 8)
        pb.addWidget(QLabel("Properties"))
        tag_row = QHBoxLayout()
        tag_row.addWidget(QLabel("Tag:"))
        self._tag_edit = QLineEdit()
        tag_row.addWidget(self._tag_edit, 1)
        self._btn_rename = QPushButton("Rename")
        self._btn_rename.clicked.connect(self._on_rename)
        tag_row.addWidget(self._btn_rename)
        pb.addLayout(tag_row)
        self._lbl_type = QLabel("Type: -")
        self._lbl_pos = QLabel("Position: -")
        self._lbl_rot = QLabel("Rotation: -")
        self._lbl_dims = QLabel("Dimensions: -")
        for lbl in (self._lbl_type, self._lbl_pos, self._lbl_rot, self._lbl_dims):
            lbl.setStyleSheet("font-family: Consolas; font-size: 12px;")
            pb.addWidget(lbl)
        outer.addWidget(self._props_box)

        # --- Move
        mv = QFrame()
        mv.setFrameShape(QFrame.Shape.StyledPanel)
        mvl = QVBoxLayout(mv)
        mvl.setContentsMargins(8, 8, 8, 8)
        mvl.addWidget(QLabel("Move"))
        mode_row = QHBoxLayout()
        self._rb_abs = QRadioButton("Absolute")
        self._rb_rel = QRadioButton("Relative")
        self._rb_abs.setChecked(True)
        self._mv_group = QButtonGroup(self)
        self._mv_group.addButton(self._rb_abs)
        self._mv_group.addButton(self._rb_rel)
        self._rb_abs.toggled.connect(self._on_move_mode_toggled)
        mode_row.addWidget(QLabel("Mode:"))
        mode_row.addWidget(self._rb_abs)
        mode_row.addWidget(self._rb_rel)
        mode_row.addStretch()
        mvl.addLayout(mode_row)
        xyz_row = QHBoxLayout()
        self._mv_x = _spin(-1e6, 1e6, 0)
        self._mv_y = _spin(-1e6, 1e6, 0)
        self._mv_z = _spin(-1e6, 1e6, 0)
        self._mv_x_lbl = QLabel("X:")
        self._mv_y_lbl = QLabel("Y:")
        self._mv_z_lbl = QLabel("Z:")
        xyz_row.addWidget(self._mv_x_lbl)
        xyz_row.addWidget(self._mv_x)
        xyz_row.addWidget(self._mv_y_lbl)
        xyz_row.addWidget(self._mv_y)
        xyz_row.addWidget(self._mv_z_lbl)
        xyz_row.addWidget(self._mv_z)
        mvl.addLayout(xyz_row)
        btn_row = QHBoxLayout()
        btn_mv = QPushButton("Apply Move")
        btn_mv.clicked.connect(self._on_apply_move)
        btn_row.addWidget(btn_mv)
        btn_reset = QPushButton("Reset fields")
        btn_reset.clicked.connect(self._reset_move_fields)
        btn_row.addWidget(btn_reset)
        mvl.addLayout(btn_row)
        outer.addWidget(mv)

        # --- Rotate
        rt = QFrame()
        rt.setFrameShape(QFrame.Shape.StyledPanel)
        rtl = QVBoxLayout(rt)
        rtl.setContentsMargins(8, 8, 8, 8)
        rtl.addWidget(QLabel("Rotate"))
        piv_grid = QGridLayout()
        self._rb_piv_center = QRadioButton("Center")
        self._rb_piv_bl = QRadioButton("Bottom-left")
        self._rb_piv_br = QRadioButton("Bottom-right")
        self._rb_piv_tl = QRadioButton("Top-left")
        self._rb_piv_tr = QRadioButton("Top-right")
        self._rb_piv_custom = QRadioButton("Custom")
        self._rb_piv_center.setChecked(True)
        self._piv_group = QButtonGroup(self)
        for rb in (
            self._rb_piv_center, self._rb_piv_bl, self._rb_piv_br,
            self._rb_piv_tl, self._rb_piv_tr, self._rb_piv_custom,
        ):
            self._piv_group.addButton(rb)
        piv_grid.addWidget(QLabel("Pivot:"), 0, 0)
        piv_grid.addWidget(self._rb_piv_center, 0, 1)
        piv_grid.addWidget(self._rb_piv_bl, 0, 2)
        piv_grid.addWidget(self._rb_piv_br, 0, 3)
        piv_grid.addWidget(self._rb_piv_tl, 1, 1)
        piv_grid.addWidget(self._rb_piv_tr, 1, 2)
        piv_grid.addWidget(self._rb_piv_custom, 1, 3)
        rtl.addLayout(piv_grid)
        custom_row = QHBoxLayout()
        self._piv_x = _spin(-1e6, 1e6, 0)
        self._piv_y = _spin(-1e6, 1e6, 0)
        custom_row.addWidget(QLabel("Custom X,Y:"))
        custom_row.addWidget(self._piv_x)
        custom_row.addWidget(self._piv_y)
        rtl.addLayout(custom_row)
        ang_row = QHBoxLayout()
        ang_row.addWidget(QLabel("Angle (deg):"))
        self._rot_angle = _spin(-3600, 3600, 0)
        ang_row.addWidget(self._rot_angle)
        for d in (90, -90, 180):
            b = QPushButton("%+d" % d)
            b.clicked.connect(lambda _=False, dd=d: self._rot_angle.setValue(dd))
            ang_row.addWidget(b)
        rtl.addLayout(ang_row)
        btn_rt = QPushButton("Apply Rotation")
        btn_rt.clicked.connect(self._on_apply_rotation)
        rtl.addWidget(btn_rt)
        outer.addWidget(rt)

        # --- Align (multi only)
        self._align_box = QFrame()
        self._align_box.setFrameShape(QFrame.Shape.StyledPanel)
        alg = QVBoxLayout(self._align_box)
        alg.setContentsMargins(8, 8, 8, 8)
        alg.addWidget(QLabel("Align (N>=2)"))
        ref_row = QHBoxLayout()
        ref_row.addWidget(QLabel("Reference:"))
        self._align_ref = QComboBox()
        ref_row.addWidget(self._align_ref, 1)
        alg.addLayout(ref_row)
        btn_row = QHBoxLayout()
        for label, edge in (
            ("Left", "left"), ("Right", "right"),
            ("Top", "top"), ("Bottom", "bottom"),
            ("H-Center", "h-center"), ("V-Center", "v-center"),
        ):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, e=edge: self._on_align(e))
            btn_row.addWidget(b)
        alg.addLayout(btn_row)
        outer.addWidget(self._align_box)

        # --- Actions
        act_row = QHBoxLayout()
        self._btn_duplicate = QPushButton("Duplicate")
        self._btn_duplicate.clicked.connect(self._on_duplicate)
        act_row.addWidget(self._btn_duplicate)
        outer.addLayout(act_row)

        # --- Progressive noise dataset (added)
        self._noise_box = QFrame()
        self._noise_box.setFrameShape(QFrame.Shape.StyledPanel)
        nl = QVBoxLayout(self._noise_box)
        nl.setContentsMargins(8, 8, 8, 8)
        nl.addWidget(QLabel("Progressive Noise Dataset"))

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Examples:"))
        self._noise_count = _int_spin(1, 10000, 20)
        row1.addWidget(self._noise_count)

        row1.addWidget(QLabel("Mode:"))
        self._noise_mode = QComboBox()
        self._noise_mode.addItem("Diffusion-like", "diffusion")        
        self._noise_mode.addItem("Linear", "linear")
        row1.addWidget(self._noise_mode)

        row1.addStretch()
        nl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Max dX (mm):"))
        self._noise_dx = _spin(0, 1e6, 3000)
        row2.addWidget(self._noise_dx)
        row2.addWidget(QLabel("Max dY (mm):"))
        self._noise_dy = _spin(0, 1e6, 3000)
        row2.addWidget(self._noise_dy)
        nl.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Max rot (deg):"))
        self._noise_rot = _spin(0, 3600, 20)
        row3.addWidget(self._noise_rot)
        row3.addWidget(QLabel("Seed:"))
        self._noise_seed = _int_spin(-1, 999999999, 42)
        self._noise_seed.setToolTip("-1 = random seed")
        row3.addWidget(self._noise_seed)
        nl.addLayout(row3)

        row4 = QHBoxLayout()
        self._noise_clamp = QCheckBox("Clamp equipment inside module boundary")
        self._noise_clamp.setChecked(True)
        row4.addWidget(self._noise_clamp)
        row4.addStretch()
        nl.addLayout(row4)

        self._noise_mode_help = QLabel()
        self._noise_mode_help.setWordWrap(True)
        self._noise_mode_help.setStyleSheet("color: #999; font-size: 11px;")
        nl.addWidget(self._noise_mode_help)

        self._noise_mode.currentIndexChanged.connect(
            self._update_noise_mode_help
        )        

        info = QLabel(
            "Generate noisy layouts from the current clean layout."
        )
        info.setStyleSheet("color: #999; font-size: 11px;")
        info.setWordWrap(True)
        nl.addWidget(info)

        self._btn_generate_noise = QPushButton("Generate noisy dataset...")
        self._btn_generate_noise.clicked.connect(
            self._on_generate_noise_clicked
        )
        nl.addWidget(self._btn_generate_noise)

        outer.addWidget(self._noise_box)

        # --- Noise preview navigation (added)
        self._noise_preview_box = QFrame()
        self._noise_preview_box.setFrameShape(QFrame.Shape.StyledPanel)
        npl = QVBoxLayout(self._noise_preview_box)
        npl.setContentsMargins(8, 8, 8, 8)

        npl.addWidget(QLabel("Noise Preview"))

        self._lbl_noise_preview = QLabel("No noisy layouts generated yet.")
        self._lbl_noise_preview.setWordWrap(True)
        self._lbl_noise_preview.setStyleSheet(
            "font-size: 11px; color: #cdd6f4;"
        )
        npl.addWidget(self._lbl_noise_preview)

        jump_row = QHBoxLayout()
        jump_row.addWidget(QLabel("Step:"))

        self._noise_step_spin = QSpinBox()
        self._noise_step_spin.setRange(1, 1)
        self._noise_step_spin.setEnabled(False)
        self._noise_step_spin.setKeyboardTracking(False)
        jump_row.addWidget(self._noise_step_spin)


        jump_row.addWidget(QLabel("/"))
        self._noise_step_total = QLabel("0")
        jump_row.addWidget(self._noise_step_total)

        jump_row.addStretch()
        npl.addLayout(jump_row)

        self._noise_step_slider = QSlider(Qt.Orientation.Horizontal)
        self._noise_step_slider.setRange(1, 1)
        self._noise_step_slider.setEnabled(False)
        self._noise_step_slider.setTracking(False)
        npl.addWidget(self._noise_step_slider)

        self._noise_step_slider.valueChanged.connect(
            self._on_noise_step_slider_changed
        )
        self._noise_step_spin.valueChanged.connect(
            self._on_noise_step_spin_changed
        )


        nav_row = QHBoxLayout()
        self._btn_noise_prev = QPushButton("← Previous")
        self._btn_noise_prev.clicked.connect(
            lambda: self.noise_preview_requested.emit("prev")
        )
        nav_row.addWidget(self._btn_noise_prev)

        self._btn_noise_next = QPushButton("Next →")
        self._btn_noise_next.clicked.connect(
            lambda: self.noise_preview_requested.emit("next")
        )
        nav_row.addWidget(self._btn_noise_next)

        npl.addLayout(nav_row)

        note = QLabel(
            "Preview only affects the right 3D view. "
            "The editable clean layout is kept unchanged."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #999; font-size: 11px;")
        npl.addWidget(note)

        outer.addWidget(self._noise_preview_box)

        # --- Validation
        self._validation_box = QFrame()
        val = self._validation_box
        val.setFrameShape(QFrame.Shape.StyledPanel)
        vl = QVBoxLayout(val)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.addWidget(QLabel("Validation"))
        self._lbl_val_oob = QLabel("-")
        self._lbl_val_coll = QLabel("-")
        for lbl in (self._lbl_val_oob, self._lbl_val_coll):
            lbl.setStyleSheet("font-family: Consolas; font-size: 12px;")
            vl.addWidget(lbl)
        outer.addWidget(val)

        self._update_noise_mode_help()
        self.set_noise_preview_state(0, 0)
        outer.addStretch()

        if hasattr(self, "_validation_box"):
            self._validation_box.hide()

    # ---- helpers ---------------------------------------------------------

    def _equipment_list(self) -> list[dict]:
        if not self._layout_data:
            return []
        return self._layout_data.get("equipment", [])

    def _selected_tags(self) -> list[str]:
        return [item.text() for item in self._list.selectedItems()]

    def _selected_equipment(self) -> list[dict]:
        tags = set(self._selected_tags())
        return [e for e in self._equipment_list() if e.get("tag") in tags]

    def _reload_target_list(self):
        self._suppress_emit = True
        try:
            current = set(self._selected_tags())
            self._list.clear()
            for eq in self._equipment_list():
                item = QListWidgetItem(eq.get("tag", ""))
                self._list.addItem(item)
                if item.text() in current:
                    item.setSelected(True)
        finally:
            self._suppress_emit = False
        self._refresh_state()

    def _on_selection_changed(self):
        if self._suppress_emit:
            return
        self._refresh_state()

    def _refresh_state(self):
        sel = self._selected_equipment()
        n = len(sel)

        # Single-item properties visibility
        self._props_box.setVisible(n == 1)
        if n == 1:
            eq = sel[0]
            self._tag_edit.setText(eq.get("tag", ""))
            self._lbl_type.setText("Type: %s" % eq.get("equipment_type", "-"))
            self._lbl_pos.setText(
                "Position: (%d, %d, %d) mm"
                % (eq.get("center_x_mm", 0), eq.get("center_y_mm", 0),
                   eq.get("elevation_mm", 0))
            )
            self._lbl_rot.setText(
                "Rotation: %.1f deg" % (eq.get("rotation_deg", 0) or 0)
            )
            self._lbl_dims.setText("Dimensions: %s" % _dims_summary(eq))

        # Enable/disable based on selection count
        self._btn_rename.setEnabled(n == 1)
        self._btn_duplicate.setEnabled(n == 1)
        self._rb_abs.setEnabled(n == 1)
        if n != 1 and self._rb_abs.isChecked():
            self._rb_rel.setChecked(True)

        # Sync Move spinboxes + labels to the current mode / target
        self._sync_move_fields()

        # Align section
        self._align_box.setVisible(n >= 2)
        if n >= 2:
            current = self._align_ref.currentText()
            self._align_ref.clear()
            for eq in sel:
                self._align_ref.addItem(eq.get("tag", ""))
            if current:
                idx = self._align_ref.findText(current)
                if idx >= 0:
                    self._align_ref.setCurrentIndex(idx)

        #self._refresh_validation()

        # added
        has_layout = self._layout_data is not None and bool(self._equipment_list())
        self._noise_box.setEnabled(has_layout)

    # ---- Move-field synchronization -------------------------------------

    def _sync_move_fields(self):
        """Update Move spinboxes + labels to match current mode / target.

        Absolute mode pre-populates with the selected equipment's current
        position so Apply is a pure no-op unless the user edits a field.
        Relative mode clears to 0 so Apply without edits is a no-op too.
        """
        sel = self._selected_equipment()
        is_abs = self._rb_abs.isChecked()

        # Label text depends on mode
        if is_abs:
            self._mv_x_lbl.setText("X:")
            self._mv_y_lbl.setText("Y:")
            self._mv_z_lbl.setText("Z:")
        else:
            self._mv_x_lbl.setText("dX:")
            self._mv_y_lbl.setText("dY:")
            self._mv_z_lbl.setText("dZ:")

        if is_abs and len(sel) == 1:
            eq = sel[0]
            self._set_move_values(
                eq.get("center_x_mm", 0),
                eq.get("center_y_mm", 0),
                eq.get("elevation_mm", 0),
            )
        elif not is_abs:
            self._set_move_values(0, 0, 0)

    def _set_move_values(self, x, y, z):
        for sp, v in ((self._mv_x, x), (self._mv_y, y), (self._mv_z, z)):
            sp.blockSignals(True)
            sp.setValue(float(v))
            sp.blockSignals(False)

    def _on_move_mode_toggled(self, _checked):
        self._sync_move_fields()

    def _reset_move_fields(self):
        self._sync_move_fields()

    # added many
    def _on_generate_noise_clicked(self):
        if not self._layout_data or not self._equipment_list():
            return

        seed_value = self._noise_seed.value()
        params = {
            "num_examples": int(self._noise_count.value()),
            "max_dx_mm": float(self._noise_dx.value()),
            "max_dy_mm": float(self._noise_dy.value()),
            "max_rot_deg": float(self._noise_rot.value()),
            "seed": None if seed_value < 0 else int(seed_value),
            "clamp_to_boundary": self._noise_clamp.isChecked(),
            "noise_mode": str(self._noise_mode.currentData() or "linear"),
        }
        self.noise_generation_requested.emit(params)

    def set_noise_preview_state(
        self,
        current_step: int,
        total_noisy: int,
    ):
        """
        current_step:
            0 = clean layout
            1..total_noisy = noisy step number

        total_noisy:
            number of noisy layouts available
        """
        total_steps = total_noisy  # noisy steps count
        has_any = total_noisy > 0

        if not has_any:
            self._lbl_noise_preview.setText("No noisy layouts generated yet.")
            self._btn_noise_prev.setEnabled(False)
            self._btn_noise_next.setEnabled(False)

            self._noise_step_slider.blockSignals(True)
            self._noise_step_slider.setRange(0, 0)
            self._noise_step_slider.setValue(0)
            self._noise_step_slider.setEnabled(False)
            self._noise_step_slider.blockSignals(False)

            self._noise_step_spin.blockSignals(True)
            self._noise_step_spin.setRange(0, 0)
            self._noise_step_spin.setValue(0)
            self._noise_step_spin.setEnabled(False)
            self._noise_step_spin.blockSignals(False)

            self._noise_step_total.setText("0")
            return

        self._noise_step_total.setText(str(total_steps))

        self._noise_step_slider.blockSignals(True)
        self._noise_step_slider.setRange(0, total_steps)
        self._noise_step_slider.setValue(current_step)
        self._noise_step_slider.setEnabled(True)
        self._noise_step_slider.blockSignals(False)

        self._noise_step_spin.blockSignals(True)
        self._noise_step_spin.setRange(0, total_steps)
        self._noise_step_spin.setValue(current_step)
        self._noise_step_spin.setEnabled(True)
        self._noise_step_spin.blockSignals(False)

        if current_step == 0:
            self._lbl_noise_preview.setText(
                "Showing clean layout (step 0 / %d)" % total_steps
            )
        else:
            self._lbl_noise_preview.setText(
                "Showing noisy step %d / %d" % (current_step, total_steps)
            )

        self._btn_noise_prev.setEnabled(current_step > 0)
        self._btn_noise_next.setEnabled(current_step < total_steps)

    def _update_noise_mode_help(self):
        mode = self._noise_mode.currentData()

        if mode == "diffusion":
            txt = (
                "Diffusion-like: each step samples fresh Gaussian noise. "
                "Noise amplitude increases with t."
            )
        else:
            txt = (
                "Linear: each equipment gets one target perturbation, "
                "then the perturbation is scaled progressively with t."
            )

        self._noise_mode_help.setText(txt)

    def _on_noise_step_slider_changed(self, value: int):
        if hasattr(self, "_noise_step_spin"):
            if self._noise_step_spin.value() != value:
                self._noise_step_spin.blockSignals(True)
                self._noise_step_spin.setValue(value)
                self._noise_step_spin.blockSignals(False)

        if self._noise_step_slider.isEnabled():
            self.noise_preview_index_requested.emit(value)

    def _emit_noise_step_jump_from_slider(self):
        if not hasattr(self, "_noise_step_slider"):
            return
        if not self._noise_step_slider.isEnabled():
            return
        self.noise_preview_index_requested.emit(
            self._noise_step_slider.value()
        )

    def _on_noise_step_spin_changed(self, value: int):
        if hasattr(self, "_noise_step_slider"):
            if self._noise_step_slider.value() != value:
                self._noise_step_slider.blockSignals(True)
                self._noise_step_slider.setValue(value)
                self._noise_step_slider.blockSignals(False)

        if self._noise_step_spin.isEnabled():
            self.noise_preview_index_requested.emit(value)


    def _refresh_validation(self):
        if not self._layout_data:
            self._lbl_val_oob.setText("-")
            self._lbl_val_coll.setText("-")
            return
        oob = equipment_editor.check_out_of_bounds(self._layout_data)
        coll = equipment_editor.check_collisions(self._layout_data)
        self._lbl_val_oob.setText(
            "Out of bounds: none" if not oob
            else "Out of bounds (%d): %s" % (len(oob), ", ".join(oob[:5]))
        )
        self._lbl_val_coll.setText(
            "Collisions: none" if not coll
            else "Collisions (%d): %s" % (
                len(coll),
                ", ".join("%s+%s" % p for p in coll[:5]),
            )
        )

    # ---- actions ---------------------------------------------------------

    def _on_add(self):
        if not self._layout_data:
            return
        dlg = AddEquipmentDialog(self._layout_data, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            eq = dlg.result_equipment()
            if eq is not None:
                self._layout_data.setdefault("equipment", []).append(eq)
                self._reload_target_list()
                self.select_tag(eq["tag"])
                self.equipment_modified.emit("__all__")

    def _on_delete(self):
        sel = self._selected_equipment()
        if not sel:
            return
        names = [e.get("tag", "") for e in sel]
        preview = ", ".join(names[:5])
        if len(names) > 5:
            preview += ", ...and %d more" % (len(names) - 5)
        resp = QMessageBox.question(
            self, "Delete equipment",
            "Delete %d item(s)?\n%s" % (len(names), preview),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        to_drop = set(names)
        self._layout_data["equipment"] = [
            e for e in self._equipment_list()
            if e.get("tag") not in to_drop
        ]
        self._reload_target_list()
        self.equipment_modified.emit("__all__")

    def _on_rename(self):
        sel = self._selected_equipment()
        if len(sel) != 1:
            return
        new_tag = self._tag_edit.text().strip()
        if not new_tag or new_tag == sel[0].get("tag"):
            return
        ok = equipment_editor.validate_tag_unique(
            self._layout_data, new_tag, exclude_tag=sel[0].get("tag")
        )
        if not ok:
            QMessageBox.warning(
                self, "Rename failed", "Tag '%s' already exists." % new_tag
            )
            return
        sel[0]["tag"] = new_tag
        self._reload_target_list()
        self.select_tag(new_tag)
        self.equipment_modified.emit("__all__")

    def _on_apply_move(self):
        sel = self._selected_equipment()
        if not sel:
            return
        if self._rb_abs.isChecked():
            if len(sel) != 1:
                return
            equipment_editor.move_absolute(
                sel[0],
                x_mm=self._mv_x.value(),
                y_mm=self._mv_y.value(),
                z_mm=self._mv_z.value(),
            )
        else:
            for eq in sel:
                equipment_editor.move_relative(
                    eq,
                    dx_mm=self._mv_x.value(),
                    dy_mm=self._mv_y.value(),
                    dz_mm=self._mv_z.value(),
                )
        self._refresh_state()
        self.equipment_modified.emit("__all__")

    def _on_apply_rotation(self):
        sel = self._selected_equipment()
        if not sel:
            return
        angle = self._rot_angle.value()
        for eq in sel:
            if self._rb_piv_center.isChecked():
                equipment_editor.rotate_around_center(eq, angle)
            elif self._rb_piv_bl.isChecked():
                equipment_editor.rotate_around_corner(eq, "bottom-left", angle)
            elif self._rb_piv_br.isChecked():
                equipment_editor.rotate_around_corner(eq, "bottom-right", angle)
            elif self._rb_piv_tl.isChecked():
                equipment_editor.rotate_around_corner(eq, "top-left", angle)
            elif self._rb_piv_tr.isChecked():
                equipment_editor.rotate_around_corner(eq, "top-right", angle)
            elif self._rb_piv_custom.isChecked():
                equipment_editor.rotate_around_pivot(
                    eq, self._piv_x.value(), self._piv_y.value(), angle
                )
        self._refresh_state()
        self.equipment_modified.emit("__all__")

    def _on_duplicate(self):
        sel = self._selected_equipment()
        if len(sel) != 1:
            return
        existing = {e.get("tag", "") for e in self._equipment_list()}
        new_eq = equipment_editor.duplicate_equipment(
            sel[0], existing_tags=existing
        )
        self._layout_data.setdefault("equipment", []).append(new_eq)
        self._reload_target_list()
        self.select_tag(new_eq["tag"])
        self.equipment_modified.emit("__all__")

    def _on_align(self, edge: str):
        sel_tags = self._selected_tags()
        if len(sel_tags) < 2:
            return
        ref_tag = self._align_ref.currentText() or sel_tags[0]
        equipment_editor.align_to(
            self._equipment_list(), ref_tag, sel_tags, edge
        )
        self._refresh_state()
        self.equipment_modified.emit("__all__")


def _dims_summary(eq: dict) -> str:
    et = eq.get("equipment_type", "")
    if et == "box":
        return "W %d x D %d x H %d mm" % (
            eq.get("width_mm", 0),
            eq.get("depth_mm", 0),
            eq.get("height_mm", 0),
        )
    if et == "vertical_vessel":
        return "Dia %d x H %d mm" % (
            eq.get("diameter_mm", 0),
            eq.get("height_mm", 0),
        )
    if et == "horizontal_vessel":
        return "L %d x Dia %d mm" % (
            eq.get("length_mm", 0),
            eq.get("diameter_mm", 0),
        )
    return "-"


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    """Main application window with tabs and 3D viewport."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout_data: dict | None = None
        self._scene_actors_by_group: dict[str, list[Any]] = {
            "deck": [],
            "boundary": [],
            "grid": [],
            "equipment": [],
            "equipment_label": [],
            "dimension": [],
            "measurement": [],
            "highlight": [],
        }
        self._measurement_result = None
        self._measure_engine: MeasurementEngine | None = None
        self._project_path: str | None = None
        self._highlight_actor: Any = None
        self._first_render = True
        self._show_dimensions = True
        # added
        self._scene_layout_data: dict | None = None
        self._noise_preview_layouts: list[dict] = []
        self._noise_preview_step: int = 0

        self.setWindowTitle("Layout Viewer 3D  -  SeaTec3D")
        self.resize(1500, 900)
        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()

    # -- UI setup -----------------------------------------------------------

    def _setup_ui(self):
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(self._splitter)

        # Left: tabs
        self._tab_widget = QTabWidget()
        self._splitter.addWidget(self._tab_widget)

        # Import tab
        self._import_tab = ImportTab()
        self._import_tab.svg_loaded.connect(self._on_svg_loaded)
        self._tab_widget.addTab(self._import_tab, "Import")

        # Equipment tab
        self._equipment_tab = EquipmentTab()
        self._equipment_tab.row_selected.connect(self._on_equipment_selected)
        self._equipment_tab.equipment_changed.connect(self._on_equipment_edited)
        self._tab_widget.addTab(self._equipment_tab, "Equipment")

        # Edit tab (between Equipment and Measure) (added)
        self._edit_tab = EditTab()
        self._edit_tab.equipment_modified.connect(self._on_equipment_modified)
        self._edit_tab.noise_generation_requested.connect(
            self._on_generate_noise_sequence
        )
        self._edit_tab.noise_preview_requested.connect(
            self._on_noise_preview_requested
        )
        self._edit_tab.noise_preview_index_requested.connect(
            self._on_noise_preview_index_requested
        )        
        self._tab_widget.addTab(self._edit_tab, "Edit")

        # Measure tab
        self._measure_tab = MeasureTab()
        self._measure_tab.measurement_ready.connect(self._on_measurement_ready)
        self._measure_tab.measurement_cleared.connect(self._on_measurement_cleared)
        self._tab_widget.addTab(self._measure_tab, "Measure")

        # Right: 3D viewer
        self._plotter = pyvistaqt.QtInteractor(self._splitter)
        self._plotter.set_background("#1e1e2e")
        self._plotter.add_axes()
        self._splitter.addWidget(self._plotter)

        # Enable click-picking in the 3D scene
        try:
            self._plotter.enable_point_picking(
                callback=self._on_point_picked,
                left_clicking=True,
                show_point=False,
                show_message=False,
                picker="cell",
            )
        except Exception as exc:  # older pyvista variants fall back silently
            log.warning("point picking unavailable: %s", exc)

        # 40/60 split
        self._splitter.setSizes([450, 650])
        self._splitter.setStretchFactor(0, 2)
        self._splitter.setStretchFactor(1, 3)

    def _setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        act = QAction("Load SVG", self)
        act.triggered.connect(self._import_tab._on_load_svg)
        toolbar.addAction(act)

        act2 = QAction("Export JSON", self)
        act2.triggered.connect(self._on_export_json)
        toolbar.addAction(act2)

        toolbar.addSeparator()

        act_save = QAction("Save Project", self)
        act_save.triggered.connect(self._on_save_project)
        toolbar.addAction(act_save)

        act_load = QAction("Load Project", self)
        act_load.triggered.connect(self._on_load_project)
        toolbar.addAction(act_load)

        toolbar.addSeparator()

        # View presets
        for label, slot in [
            ("3D", self._view_3d),
            ("Plan (XY)", self._view_plan),
            ("Front (XZ)", self._view_front),
            ("Side (YZ)", self._view_side),
        ]:
            a = QAction(label, self)
            a.triggered.connect(slot)
            toolbar.addAction(a)

        toolbar.addSeparator()

        dims_act = QAction("Dims", self)
        dims_act.setCheckable(True)
        dims_act.setChecked(True)
        dims_act.toggled.connect(self._on_toggle_dims)
        toolbar.addAction(dims_act)

    def _setup_statusbar(self):
        self.statusBar().showMessage("Ready  -  Load an SVG to begin")
        self._status_info = QLabel("")
        self._status_info.setStyleSheet("color: #aaddaa; padding: 0 8px;")
        self.statusBar().addPermanentWidget(self._status_info)

    def _update_status_info(self):
        """Refresh the permanent right-side status-bar summary."""
        if not self._layout_data:
            self._status_info.setText("")
            return
        n = len(self._layout_data.get("equipment", []))
        bnd = self._layout_data.get("module_boundary") or {}
        w_m = (bnd.get("width_mm") or 0) / 1000.0
        l_m = (bnd.get("length_mm") or 0) / 1000.0
        scale = self._layout_data.get("scale_mm_per_pt") or 0
        self._status_info.setText(
            "%d equipment | Module: %.1f x %.1f m | Scale: %.2f mm/pt"
            % (n, w_m, l_m, scale)
        )

    # -- Data flow ----------------------------------------------------------

    def _on_svg_loaded(self, layout_data: dict):
        """Handle newly parsed SVG data."""
        self._apply_layout_data(layout_data)
        n = len(layout_data.get("equipment", []))
        self.statusBar().showMessage("Loaded %d equipment items" % n)

    # added 6
    def _current_scene_layout(self) -> dict | None:
        return self._scene_layout_data or self._layout_data

    def _clear_noise_preview(self):
        self._noise_preview_layouts = []
        self._noise_preview_step = 0
        self._scene_layout_data = self._layout_data
        self._edit_tab.set_noise_preview_state(0, 0)

    def _show_preview_step(self, step: int):
        """
        step:
            0 = clean layout
            1..N = noisy layouts
        """
        total = len(self._noise_preview_layouts)
        if total == 0:
            self._scene_layout_data = self._layout_data
            self._noise_preview_step = 0
            self._rebuild_scene(reset_camera=False)
            self._edit_tab.set_noise_preview_state(0, 0)
            return

        step = max(0, min(step, total))

        if step == self._noise_preview_step:
            if step == 0 and self._scene_layout_data is self._layout_data:
                return
            if step > 0 and self._scene_layout_data is self._noise_preview_layouts[step - 1]:
                return

        self._noise_preview_step = step

        if step == 0:
            self._scene_layout_data = self._layout_data
            self._rebuild_scene(reset_camera=False)
            self._edit_tab.set_noise_preview_state(0, total)
            self.statusBar().showMessage("Showing clean layout (step 0)")
            return

        self._scene_layout_data = self._noise_preview_layouts[step - 1]
        self._rebuild_scene(reset_camera=False)
        self._edit_tab.set_noise_preview_state(step, total)

        meta = self._scene_layout_data.get("noise_metadata", {})
        alpha = meta.get("alpha")
        if alpha is None:
            self.statusBar().showMessage(
                "Showing noisy step %d / %d" % (step, total)
            )
        else:
            self.statusBar().showMessage(
                "Showing noisy step %d / %d  (alpha=%.3f)"
                % (step, total, float(alpha))
            )

    def _on_noise_preview_requested(self, action: str):
        if not self._noise_preview_layouts:
            return

        if action == "next":
            self._show_preview_step(self._noise_preview_step + 1)
        elif action == "prev":
            self._show_preview_step(self._noise_preview_step - 1)

    def _on_noise_preview_index_requested(self, step: int):
        if not self._noise_preview_layouts:
            return
        self._show_preview_step(step)

    def _apply_layout_data(self, layout_data: dict):
        """Shared refresh path for SVG loads and project loads."""
        #added
        self._layout_data = layout_data
        self._scene_layout_data = layout_data
        self._noise_preview_layouts = []
        self._noise_preview_step = 0
        self._edit_tab.set_noise_preview_state(0, 0)

        self._measure_engine = MeasurementEngine(
            layout_data.get("module_boundary")
        )
        self._measure_tab.set_engine(self._measure_engine)
        self._measure_tab._clear_all()
        self._measurement_result = None
        self._equipment_tab.set_equipment(layout_data.get("equipment", []))
        self._edit_tab.set_layout_data(layout_data)
        self._rebuild_scene()
        self._update_status_info()
        self._tab_widget.setCurrentIndex(1)  # Equipment tab

    # Helpers
    def _clear_actor_groups(self, *groups: str):
        for group in groups:
            actors = self._scene_actors_by_group.get(group, [])
            for actor in actors:
                try:
                    self._plotter.remove_actor(actor)
                except Exception:
                    pass
            self._scene_actors_by_group[group] = []

        if "highlight" in groups:
            self._highlight_actor = None

    def _add_mesh_dicts(self, mesh_dicts: list[dict[str, Any]]):
        """Ajoute les mesh dicts en batchant les labels par groupe/couleur."""
        label_batches: dict[tuple[str, str], dict[str, list[Any]]] = {}

        for md in mesh_dicts:
            group = md.get("group", "misc")

            if "label" in md:
                color = md.get("color", "#cdd6f4")
                key = (group, color)
                batch = label_batches.setdefault(
                    key,
                    {"points": [], "labels": []},
                )
                batch["points"].append(md["position"])
                batch["labels"].append(md["label"])
                continue

            if "mesh" not in md:
                continue

            kwargs = {
                "color": md.get("color", "white"),
                "opacity": md.get("opacity", 1.0),
                "show_edges": False,
            }
            if md.get("style") == "wireframe":
                kwargs["style"] = "wireframe"
            if "line_width" in md:
                kwargs["line_width"] = md["line_width"]

            actor = self._plotter.add_mesh(md["mesh"], **kwargs)
            if actor is not None:
                self._scene_actors_by_group.setdefault(group, []).append(actor)

        for (group, color), batch in label_batches.items():
            actor = self._plotter.add_point_labels(
                batch["points"],
                batch["labels"],
                font_size=10,
                text_color=color,
                shape=None,
                render_points_as_spheres=False,
                point_size=0,
                always_visible=True,
            )
            if actor is not None:
                self._scene_actors_by_group.setdefault(group, []).append(actor)

    def _rebuild_measurement_group(self):
        self._clear_actor_groups("measurement")

        if self._measurement_result is None or not hasattr(self, "_builder"):
            return

        self._add_mesh_dicts(
            self._builder.build_measurement(self._measurement_result)
        )

    def _rebuild_dimension_group(self):
        """Rebuild uniquement les dimensions, sans refaire toute la scène."""
        self._clear_actor_groups("dimension")

        if not self._show_dimensions:
            return

        scene_layout = self._current_scene_layout()
        if not scene_layout:
            return

        dim_builder = SceneBuilder(scene_layout)
        dim_meshes = [
            md for md in dim_builder.build(show_dimensions=True)
            if md.get("group") == "dimension"
        ]
        self._add_mesh_dicts(dim_meshes)

    # -- Scene management ---------------------------------------------------

    def _rebuild_scene(self, reset_camera: bool = True):
        """Clear and rebuild the 3D scene from layout data."""
        self._clear_actor_groups(
            "deck",
            "boundary",
            "grid",
            "equipment",
            "equipment_label",
            "dimension",
            "measurement",
            "highlight",
        )

        scene_layout = self._current_scene_layout()
        if not scene_layout:
            self._plotter.render()
            return

        builder = SceneBuilder(scene_layout)
        mesh_dicts = builder.build(show_dimensions=self._show_dimensions)
        self._builder = builder

        self._add_mesh_dicts(mesh_dicts)

        if self._measurement_result is not None:
            self._rebuild_measurement_group()

        if reset_camera or self._first_render:
            self._plotter.reset_camera()
            self._first_render = False

        self._plotter.render()

    def _add_mesh_dict(self, md: dict[str, Any]) -> Any:
        """Add a mesh dict to the plotter, return the actor."""
        if "label" in md:
            return self._plotter.add_point_labels(
                [md["position"]],
                [md["label"]],
                font_size=10,
                text_color=md.get("color", "#cdd6f4"),
                shape=None,
                render_points_as_spheres=False,
                point_size=0,
                always_visible=True,
            )
        elif "mesh" in md:
            kwargs = {
                "color": md.get("color", "white"),
                "opacity": md.get("opacity", 1.0),
                "show_edges": False,
            }
            if md.get("style") == "wireframe":
                kwargs["style"] = "wireframe"
            if "line_width" in md:
                kwargs["line_width"] = md["line_width"]
            return self._plotter.add_mesh(md["mesh"], **kwargs)
        return None

    # -- Edits / toggles ----------------------------------------------------

    def _on_equipment_edited(self):
        """Sync table model edits back into layout data and rebuild scene."""
        if not self._layout_data:
            return
        if self._noise_preview_layouts:
            self._clear_noise_preview()
        self._layout_data["equipment"] = (
            self._equipment_tab.get_table_model().get_equipment_list()
        )
        self._edit_tab.set_layout_data(self._layout_data)
        self._rebuild_scene(reset_camera=False)
        self._update_status_info()
        self.statusBar().showMessage("Scene updated from edit")

    def _on_equipment_modified(self, tag: str):
        """Handle add / delete / rename / bulk moves from the Edit tab."""
        if not self._layout_data:
            return
        if self._noise_preview_layouts:
            self._clear_noise_preview()
        self._equipment_tab.set_equipment(
            self._layout_data.get("equipment", [])
        )
        self._edit_tab.set_layout_data(self._layout_data)
        self._rebuild_scene(reset_camera=False)
        self._update_status_info()
        if tag and tag != "__all__":
            self.statusBar().showMessage("Updated: %s" % tag)
        else:
            self.statusBar().showMessage("Layout modified")

    # -- 3D picking + measurement ------------------------------------------

    def _on_point_picked(self, point):
        """Callback from pyvista point picking; 'point' is (x,y,z) in metres."""
        if point is None:
            return
        try:
            x_m, y_m, z_m = float(point[0]), float(point[1]), float(point[2])
        except (TypeError, IndexError, ValueError):
            return
        self._handle_pick(x_m, y_m, z_m)

    def _handle_pick(self, x_m: float, y_m: float, z_m: float):
        """Route a 3D pick to equipment selection and measurement state.

        Equipment-row selection fires from any tab (useful for browsing).
        The pick-A/pick-B measurement state only advances when the user is
        on the Measure tab, so casual clicks elsewhere don't alter a
        measurement in progress.
        """
        if not hasattr(self, "_builder") or not self._measure_engine:
            return

        measure_active = (
            self._tab_widget.currentWidget() is self._measure_tab
        )

        tag = self._builder.find_tag_at_point(x_m, y_m, z_m)
        if tag:
            self._equipment_tab.select_row_by_tag(tag)
            self._edit_tab.select_tag(tag)
            if measure_active:
                scene_layout = self._current_scene_layout() or {}
                eq = next(
                    (e for e in scene_layout.get("equipment", [])
                     if e.get("tag") == tag),
                    None,
                )
                if eq is not None:
                    ref = self._measure_engine.make_ref_from_equipment(eq)
                    self._measure_tab.receive_pick(ref)
            return

        # Boundary edge only matters for measurement
        if not measure_active:
            return
        x_mm = x_m * 1000.0
        y_mm = y_m * 1000.0
        edge = self._measure_engine.identify_nearest_boundary(x_mm, y_mm)
        if edge:
            ref = self._measure_engine.make_ref_from_boundary(
                edge, x_mm, y_mm
            )
            self._measure_tab.receive_pick(ref)

    def _on_measurement_ready(self, result):
        """Render the newly computed measurement in the scene."""
        self._measurement_result = result

        if not hasattr(self, "_builder"):
            return

        self._rebuild_measurement_group()
        self._plotter.render()

        self.statusBar().showMessage(
            "Measure: %s <-> %s"
            % (result.ref_a.display_name, result.ref_b.display_name)
        )

    def _on_measurement_cleared(self):
        """Strip measurement overlay from the 3D scene."""
        self._clear_actor_groups("measurement")
        self._measurement_result = None
        self._plotter.render()

    def _on_toggle_dims(self, checked: bool):
        self._show_dimensions = checked
        if self._layout_data:
            self._rebuild_dimension_group()
            self._plotter.render()   

    # -- Equipment selection ------------------------------------------------

    def _on_equipment_selected(self, tag: str):
        """Fly camera to selected equipment and highlight it."""
        self._edit_tab.select_tag(tag)

        if not hasattr(self, "_builder"):
            return

        center = self._builder.get_equipment_center(tag)
        if not center:
            return

        self._clear_actor_groups("highlight")

        import pyvista as pv
        sphere = pv.Sphere(radius=0.4, center=center)
        self._highlight_actor = self._plotter.add_mesh(
            sphere,
            color="#ffff00",
            opacity=0.35,
            show_edges=False,
        )
        if self._highlight_actor is not None:
            self._scene_actors_by_group["highlight"].append(self._highlight_actor)

        self._plotter.camera.focal_point = center
        self._plotter.render()
        self.statusBar().showMessage("Selected: %s" % tag)

    # -- View presets -------------------------------------------------------

    def _view_3d(self):
        self._plotter.view_isometric()
        self._plotter.reset_camera()

    def _view_plan(self):
        self._plotter.view_xy()
        self._plotter.enable_parallel_projection()
        self._plotter.reset_camera()

    def _view_front(self):
        self._plotter.view_xz()
        self._plotter.reset_camera()

    def _view_side(self):
        self._plotter.view_yz()
        self._plotter.reset_camera()

    # -- Export -------------------------------------------------------------

    # added 2 methods
    def _suggest_noise_export_stem(self) -> str:
        svg_path = getattr(self._import_tab, "_svg_path", None)
        if svg_path:
            return Path(svg_path).stem.replace(" ", "_")
        if self._project_path:
            return Path(self._project_path).stem.replace(" ", "_")
        return "layout"

    def _on_generate_noise_sequence(self, params: dict):
        import noise_generator

        if not self._layout_data:
            self.statusBar().showMessage("Nothing loaded")
            return

        self._sync_edits_to_layout()

        out_dir = QFileDialog.getExistingDirectory(
            self,
            "Select output folder for noisy layouts",
            "",
        )
        if not out_dir:
            return

        try:
            layouts = noise_generator.generate_progressive_noisy_layouts(
                layout_data=self._layout_data,
                num_examples=int(params["num_examples"]),
                max_dx_mm=float(params["max_dx_mm"]),
                max_dy_mm=float(params["max_dy_mm"]),
                max_rot_deg=float(params["max_rot_deg"]),
                seed=params.get("seed"),
                clamp_to_boundary=bool(
                    params.get("clamp_to_boundary", True)
                ),
                noise_mode=str(params.get("noise_mode", "linear")),
            )

            written = noise_generator.save_noisy_layouts(
                layouts=layouts,
                output_dir=out_dir,
                base_name=self._suggest_noise_export_stem(),
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Noise generation error",
                str(exc),
            )
            return

        self._noise_preview_layouts = layouts
        self._noise_preview_step = 0

        if self._noise_preview_layouts:
            self._show_preview_step(1)
        else:
            self._edit_tab.set_noise_preview_state(0, 0)

        QMessageBox.information(
            self,
            "Noise generation complete",
            "Generated %d noisy layouts in:\n%s\n\n"
            "The first noisy example is now shown in the 3D viewer."
            % (len(written), out_dir),
        )

    def _sync_edits_to_layout(self):
        """Ensure in-flight table edits are reflected in self._layout_data."""
        if not self._layout_data:
            return
        self._layout_data["equipment"] = (
            self._equipment_tab.get_table_model().get_equipment_list()
        )

    def _on_export_json(self):
        if not self._layout_data:
            self.statusBar().showMessage("Nothing to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Layout JSON", "layout.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return

        self._sync_edits_to_layout()
        payload = dict(self._layout_data)
        payload["export_metadata"] = {
            "tool": "Layout Viewer 3D",
            "version": "0.3",
            "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        self.statusBar().showMessage("Exported: %s" % path)

    # -- Project save / load ------------------------------------------------

    def _on_save_project(self):
        if not self._layout_data:
            self.statusBar().showMessage("Nothing to save")
            return
        path = self._project_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Project", "layout.lv3d",
                "Layout Viewer 3D Project (*.lv3d);;All Files (*)"
            )
            if not path:
                return

        self._sync_edits_to_layout()
        doc = {
            "format": "lv3d",
            "version": 1,
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "layout_data": self._layout_data,
        }
        try:
            with open(path, "w") as f:
                json.dump(doc, f, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Save Project Error", str(exc))
            return
        self._project_path = path
        self.statusBar().showMessage("Saved project: %s" % path)

    def _on_load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Project", "",
            "Layout Viewer 3D Project (*.lv3d);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r") as f:
                doc = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, "Load Project Error", str(exc))
            return

        if doc.get("format") != "lv3d":
            QMessageBox.critical(
                self, "Load Project Error",
                "File is not a Layout Viewer 3D project (missing format tag)."
            )
            return

        layout_data = doc.get("layout_data")
        if not isinstance(layout_data, dict):
            QMessageBox.critical(
                self, "Load Project Error",
                "Project file has no 'layout_data' dict."
            )
            return

        self._project_path = path
        self._apply_layout_data(layout_data)
        self.statusBar().showMessage("Loaded project: %s" % path)
