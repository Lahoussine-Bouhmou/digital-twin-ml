# CLAUDE.md - Layout Viewer 3D (Phase 91)

## Project Overview

**Layout Viewer 3D** is a standalone PySide6 + PyVista tool that parses 2D Visio-exported SVG layout drawings and renders them as interactive 3D scenes. It is part of the SeaTec3D offshore engineering platform but runs independently.

**Purpose:** Bridge between 2D sketching (Visio) and 3D engineering visualization. Engineers upload an SVG plan view and optionally an Excel equipment list; the tool generates a calibrated 3D scene with real-world mm coordinates. This is NOT a final 3D model -- it is an intermediate sketching/communication tool.

## File Structure

```
Phase91_Layout_Viewer/
    CLAUDE.md                # Project context for Claude Code
    tool/
        __init__.py          # Package marker (can be empty)
        __main__.py          # python -m tool entry point
        main.py              # Entry point, QApplication, dark QSS theme
        main_window.py       # QMainWindow: QSplitter(tabs | PyVista 3D)
        scene_builder.py     # Layer 1: JSON dict -> PyVista meshes
        svg_layout_parser.py # Layer 1: Visio SVG -> JSON dict
        measurement_engine.py # (Session 3) Layer 1: distance measurement math
    Example01.svg            # Test SVG: 3x compressors + 3x vertical vessels
    Example02.svg            # Test SVG: horizontal vessel shapes (stadium/capsule)
```

## How to Run

```powershell
conda activate openusd
cd C:\path\layout\Phase91_Layout_Viewer
$env:QT_PLUGIN_PATH = ""
python tool/main.py
```

If PySide6 DLL conflict persists, use a separate conda env:
```
conda activate layout3d
python tool/main.py
```

## Architecture

### Data Flow
```
SVG file --(svg_layout_parser.py)--> JSON dict --(scene_builder.py)--> PyVista meshes
                                         |
Excel file (optional) --merge into JSON--+
                                         |
                                    main_window.py
                                    +-- ImportTab (left, load files)
                                    +-- EquipmentTab (left, editable table)
                                    +-- pyvistaqt.QtInteractor (right, 3D view)
```

### Layer 1 Principle
All engineering/geometry logic lives in `svg_layout_parser.py` and `scene_builder.py`. UI code in `main_window.py` only orchestrates -- no calculations, no coordinate math.

### Import Convention
All imports are flat sibling imports (NOT package imports):
```python
from scene_builder import SceneBuilder      # YES
from svg_layout_parser import SvgLayoutParser  # YES
# from layout_viewer.scene_builder import ...  # NO - breaks folder naming
```
`main.py` adds its own directory to `sys.path` to make this work.

## Key Classes

### SvgLayoutParser (svg_layout_parser.py)
- Parses Visio-exported SVG files
- Classifies shapes: `<rect>` -> box, `<ellipse>` -> vertical_vessel, `<path>` with 2 arcs -> horizontal_vessel (stadium)
- Extracts equipment tags from `<desc>`, `<text>`, Visio `v:ud` custom properties
- Calibrates SVG-pts-to-mm scale using dimension annotation arrows (corrects for marker setback: start=9.33pts, end=9.42pts, total=18.75pts)
- Verified scale: 35.28 mm/pt on Example01.svg
- Optional Excel merge via openpyxl (matches on equipment tag column)
- Output: JSON dict with module_boundary, grid_lines, equipment[], dimensions[], parser_warnings[]

### SceneBuilder (scene_builder.py)
- Converts parsed JSON dict into list of PyVista mesh dicts
- Equipment type mapping:
  - `box` -> pv.Box (width x depth x height)
  - `vertical_vessel` -> pv.Cylinder (upright, capped)
  - `horizontal_vessel` -> pv.Cylinder + 2x pv.Sphere heads + 2x pv.Box saddles
- Also builds: deck plate, boundary wireframe, grid lines with labels
- All coordinates in metres (JSON is mm, scale by 0.001)
- Colors: boxes=#4bacc6, vert_vessels=#00b050, horiz_vessels=#c0504d, saddles=#888888

### MainWindow (main_window.py)
- QSplitter: left=QTabWidget(40%), right=pyvistaqt.QtInteractor(60%)
- ImportTab: Load SVG button, Load Excel button, parse summary, warnings list
- EquipmentTab: QTableView backed by EquipmentTableModel (QAbstractTableModel)
  - Defaulted cells (height_mm, weight_kg) highlighted dark yellow, editable
  - Row selection emits tag -> camera flies to equipment + highlight sphere
- Toolbar: Load SVG, Export JSON, view presets (3D, Plan XY, Front XZ, Side YZ)
- Dark theme background: #1e1e2e (Catppuccin Mocha)

## JSON Schema (parser output)

```json
{
  "source": "Example01.svg",
  "units": "mm",
  "coordinate_system": "origin bottom-left, X-right, Y-up",
  "scale_mm_per_pt": 35.28,
  "module_boundary": { "width_mm": 25000, "length_mm": 21550 },
  "grid_lines": {
    "x_lines": [{"label": "1", "position_mm": 0}, ...],
    "y_lines": [{"label": "A", "position_mm": 0}, ...]
  },
  "equipment": [
    {
      "tag": "K-3170-A",
      "svg_shape": "rect",
      "equipment_type": "box",
      "center_x_mm": 10475,
      "center_y_mm": 2970,
      "width_mm": 13650,
      "depth_mm": 4000,
      "height_mm": 2000,       // default
      "weight_kg": 1000,       // default
      "rotation_deg": 0.0,
      "elevation_mm": 0,
      "data_source": "svg_geometry",
      "defaults_applied": ["height_mm", "weight_kg", "elevation_mm"]
    }
  ],
  "dimensions": [
    { "value_mm": 3648, "direction": "horizontal", "from_ref": "boundary", "to_ref": "K-3170-A_left" }
  ],
  "parser_warnings": []
}
```

## Measurement Engine Architecture (Session 3)

The measurement tool follows a pick-pick-measure flow:

```
3D click -> find_tag_at_point() or identify_nearest_boundary()
         -> MeasurementRef (equipment or boundary edge)
         -> state machine (slot A, then slot B)
         -> MeasurementEngine.measure(ref_a, ref_b)
         -> MeasurementResult (dx_edge, dy_edge, direct + line endpoints)
         -> scene_builder.build_measurement() -> visual dimension lines in 3D
```

Distance types:
- dx_edge: horizontal gap between nearest X-facing edges (mm)
- dy_edge: vertical gap between nearest Y-facing edges (mm)
- direct: straight-line center-to-center (mm)

Visualisation colors: red=X dimension, blue=Y dimension, green=direct line.
All measurement geometry at z=0.15m (above deck and dim overlays).

## Development Conventions

- **Pure ASCII only** in all .py files -- no Unicode characters (em-dashes, arrows, box-drawing). Windows cp1252 encoding constraint.
- **No package-style imports** -- use flat sibling imports only.
- **Layer 1 separation** -- geometry/engineering logic in parser and builder, never in UI.
- **Default values** -- height_mm=2000, weight_kg=1000, elevation_mm=0. Always tracked in `defaults_applied` list.
- **Test with Example01.svg** (6 equipment: 3 rect compressors K-3170-A/B/C + 3 ellipse vessels VZ-3170-A/B/C on 25000x21550mm module).
- **Test with Example02.svg** (2 horizontal vessels with stadium path shapes, no dimensions).

## Session History

### Session 1 (COMPLETED)
- Created svg_layout_parser.py with full Visio SVG parsing pipeline
- Created scene_builder.py with box, vertical_vessel, horizontal_vessel mesh generation
- Created main_window.py with ImportTab, EquipmentTab, PyVista viewer
- Created main.py with dark theme QSS and DLL conflict workaround
- Verified: 6 equipment items parsed, 22 mesh dicts generated, scale 35.28 mm/pt
- Verified: Example02.svg horizontal vessels detected (stadium path with 2 arcs)

### Session 2 (COMPLETED)
Goals achieved:
1. Dimension overlays in 3D scene (red lines + value labels, togglable via toolbar)
2. Equipment table editing triggers scene rebuild (edit height -> box grows in 3D)
3. Excel equipment list merge with flexible column header matching
4. Horizontal vessel rotation handling in scene_builder
5. Parser robustness: handles SVGs without dimensions using Visio page properties
6. Dimension toggle checkbox in toolbar

### Session 3 (NEXT)
Goals:
1. Click-picking in 3D viewport -> select row in equipment table
2. Interactive distance measurement tool (PRIORITY):
   - Click two references (equipment or boundary edge)
   - Show X, Y, and direct distances in GUI panel
   - Draw dimension lines in 3D scene (red=X, blue=Y, green=direct)
   - Edge-to-edge and center-to-center modes
3. Export JSON with user edits preserved + export metadata
4. Save/Load project (.lv3d files)
5. Status bar: permanent equipment count + module dimensions

### Future Development (deferred)
- STEP export via CadQuery subprocess (step_exporter.py)
- Copilot dock widget (copilot_widget.py)
- Full keyboard shortcuts
- About dialog
