# Session 3 Prompt - Layout Viewer 3D

Read CLAUDE.md first for full project context. Sessions 1 and 2 are complete.

## Objective

Implement Session 3: 3D click-picking, interactive distance measurement tool, JSON export with edits, and Save/Load project. The priority feature is the measurement capability -- engineers click two items (equipment or boundary edge) and instantly see X, Y, and total distances both in the GUI panel and as dimension lines in the 3D scene.

## Tasks

### Task 3A: Click-picking in 3D viewport -> select equipment table row

**File: scene_builder.py** -- add methods

1. Add `find_tag_at_point(self, x, y, z) -> str | None`:
   - For each equipment in `self._tag_to_mesh`, get the mesh bounds
   - Check if point (x, y) is inside or within 0.5m of the bounding box XY footprint
   - Return the tag of the closest equipment, or None

2. Add `get_equipment_bounds(self, tag) -> tuple | None`:
   - Return (xmin, xmax, ymin, ymax, zmin, zmax) in metres from the stored mesh
   - Returns None if tag not found

**File: main_window.py** -- enable picking

1. After creating the plotter in `_setup_ui()`, enable cell picking:
   ```python
   self._plotter.enable_cell_picking(
       callback=self._on_cell_picked,
       through=False,
       show=False,
       show_message=False,
   )
   ```
   If `enable_cell_picking` is not available in the installed pyvistaqt version, use the alternative:
   ```python
   self._plotter.iren.add_observer("LeftButtonPressEvent", self._on_left_click)
   ```
   Then in the handler, use `self._plotter.picked_point` to get the 3D coordinates.

2. Implement the pick handler:
   - Get the picked 3D point (x, y, z) in metres
   - Call `self._builder.find_tag_at_point(x, y, z)`
   - If a tag is found, select the corresponding row in the equipment table
   - Feed the pick into the measurement state machine (Task 3B)

3. In `EquipmentTab`, add `select_row_by_tag(self, tag: str)`:
   - Iterate rows, find matching tag
   - Set selection programmatically and scroll to make it visible

### Task 3B: Interactive distance measurement tool (PRIORITY FEATURE)

Engineers need to click two references and see the distance. The references can be:
- An equipment item (clicked on in 3D)
- A boundary edge (clicked near the module boundary in 3D)

The tool must show X distance, Y distance, and direct distance. Measurement lines must appear visually in the 3D scene.

#### File: measurement_engine.py (NEW FILE -- Layer 1)

All measurement math lives here. No UI, no PyVista. Coordinates in mm.

```python
"""
measurement_engine.py - Distance measurement between layout references.
Layer 1 module: pure geometry, no UI, no PyVista.
All coordinates in mm (matching the layout JSON).
"""

import math


class MeasurementRef:
    """A pickable reference point/edge on the layout."""

    def __init__(self, ref_type, tag=None, edge=None,
                 center_x=0, center_y=0,
                 x_min=0, x_max=0, y_min=0, y_max=0):
        self.ref_type = ref_type   # "equipment" or "boundary"
        self.tag = tag             # equipment tag or None
        self.edge = edge           # "left","right","bottom","top" or None
        self.center_x = center_x   # centre in mm
        self.center_y = center_y
        self.x_min = x_min         # bounding box edges in mm
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max

    @property
    def display_name(self):
        if self.ref_type == "equipment":
            return self.tag or "Equipment"
        return "Boundary (%s)" % (self.edge or "?")


class MeasurementResult:
    """Result of a distance measurement between two references."""

    def __init__(self, ref_a, ref_b):
        self.ref_a = ref_a
        self.ref_b = ref_b
        self.dx_edge = 0.0     # X edge-to-edge gap in mm (positive=separated)
        self.dy_edge = 0.0     # Y edge-to-edge gap in mm
        self.dx_center = 0.0   # X center-to-center in mm
        self.dy_center = 0.0   # Y center-to-center in mm
        self.direct = 0.0      # straight-line center-to-center in mm
        # Line endpoints for 3D visualisation (mm coordinates)
        self.line_x = None     # ((x1,y1), (x2,y2)) for X dimension line
        self.line_y = None     # ((x1,y1), (x2,y2)) for Y dimension line
        self.line_direct = None  # ((x1,y1), (x2,y2)) for direct line


class MeasurementEngine:
    """Compute distances between two MeasurementRef objects."""

    def __init__(self, module_boundary):
        self.mod_w = (module_boundary or {}).get("width_mm", 0)
        self.mod_l = (module_boundary or {}).get("length_mm", 0)

    def make_ref_from_equipment(self, eq):
        """Build MeasurementRef from an equipment dict.

        Works for box (width_mm, depth_mm), vertical_vessel (diameter_mm),
        and horizontal_vessel (length_mm, diameter_mm, rotation_deg).
        """
        cx = eq["center_x_mm"]
        cy = eq["center_y_mm"]
        et = eq.get("equipment_type", "box")

        if et == "box":
            hw = eq.get("width_mm", 0) / 2.0
            hd = eq.get("depth_mm", 0) / 2.0
        elif et == "vertical_vessel":
            r = eq.get("diameter_mm", 0) / 2.0
            hw, hd = r, r
        elif et == "horizontal_vessel":
            hl = eq.get("length_mm", 0) / 2.0
            r = eq.get("diameter_mm", 0) / 2.0
            rot = eq.get("rotation_deg", 0)
            # Approximate axis-aligned bounding box
            rad = math.radians(rot)
            hw = abs(hl * math.cos(rad)) + abs(r * math.sin(rad))
            hd = abs(hl * math.sin(rad)) + abs(r * math.cos(rad))
        else:
            hw = eq.get("width_mm", 1000) / 2.0
            hd = eq.get("depth_mm", 1000) / 2.0

        return MeasurementRef(
            ref_type="equipment", tag=eq.get("tag", "?"),
            center_x=cx, center_y=cy,
            x_min=cx - hw, x_max=cx + hw,
            y_min=cy - hd, y_max=cy + hd,
        )

    def make_ref_from_boundary(self, edge, click_x_mm=0, click_y_mm=0):
        """Build MeasurementRef for a boundary edge.

        The click position is used to place the non-measured coordinate
        so the dimension line starts at a sensible location.
        """
        if edge == "left":
            return MeasurementRef(
                "boundary", edge=edge,
                center_x=0, center_y=click_y_mm,
                x_min=0, x_max=0, y_min=0, y_max=self.mod_l)
        elif edge == "right":
            return MeasurementRef(
                "boundary", edge=edge,
                center_x=self.mod_w, center_y=click_y_mm,
                x_min=self.mod_w, x_max=self.mod_w,
                y_min=0, y_max=self.mod_l)
        elif edge == "bottom":
            return MeasurementRef(
                "boundary", edge=edge,
                center_x=click_x_mm, center_y=0,
                x_min=0, x_max=self.mod_w, y_min=0, y_max=0)
        elif edge == "top":
            return MeasurementRef(
                "boundary", edge=edge,
                center_x=click_x_mm, center_y=self.mod_l,
                x_min=0, x_max=self.mod_w,
                y_min=self.mod_l, y_max=self.mod_l)
        return None

    def identify_nearest_boundary(self, x_mm, y_mm, threshold_mm=1500):
        """Given a click point, determine the nearest boundary edge.

        Returns "left", "right", "bottom", "top", or None.
        """
        distances = {
            "left": abs(x_mm),
            "right": abs(self.mod_w - x_mm),
            "bottom": abs(y_mm),
            "top": abs(self.mod_l - y_mm),
        }
        nearest = min(distances, key=distances.get)
        if distances[nearest] <= threshold_mm:
            return nearest
        return None

    def measure(self, ref_a, ref_b):
        """Compute all distances between two references.

        Edge-to-edge logic:
        - For two equipment items or equipment-to-boundary:
          dx_edge = gap between nearest X-facing edges
          dy_edge = gap between nearest Y-facing edges
          (positive = clear gap, negative = overlapping)

        Line endpoints:
        - line_x: horizontal at Y midpoint of the two refs
        - line_y: vertical at X midpoint of the two refs
        - line_direct: center to center (shown when dx and dy are both nonzero)
        """
        r = MeasurementResult(ref_a, ref_b)

        # Center-to-center
        r.dx_center = abs(ref_b.center_x - ref_a.center_x)
        r.dy_center = abs(ref_b.center_y - ref_a.center_y)
        r.direct = math.sqrt(r.dx_center**2 + r.dy_center**2)

        # Edge-to-edge X: gap between nearest horizontal edges
        # If A is left of B: gap = B.x_min - A.x_max
        # If B is left of A: gap = A.x_min - B.x_max
        # Take the positive interpretation (gap between outer edges)
        if ref_a.center_x <= ref_b.center_x:
            r.dx_edge = ref_b.x_min - ref_a.x_max
        else:
            r.dx_edge = ref_a.x_min - ref_b.x_max

        # Edge-to-edge Y
        if ref_a.center_y <= ref_b.center_y:
            r.dy_edge = ref_b.y_min - ref_a.y_max
        else:
            r.dy_edge = ref_a.y_min - ref_b.y_max

        # For boundary refs, the edge-to-edge is simpler:
        # The boundary has zero width, so x_min == x_max
        # The formula above already handles this correctly.

        # Dimension line endpoints (mm)
        y_mid = (ref_a.center_y + ref_b.center_y) / 2.0
        x_mid = (ref_a.center_x + ref_b.center_x) / 2.0

        # X line: horizontal, connecting the nearest X edges
        if ref_a.center_x <= ref_b.center_x:
            x1 = ref_a.x_max
            x2 = ref_b.x_min
        else:
            x1 = ref_b.x_max
            x2 = ref_a.x_min
        r.line_x = ((x1, y_mid), (x2, y_mid))

        # Y line: vertical, connecting the nearest Y edges
        if ref_a.center_y <= ref_b.center_y:
            y1 = ref_a.y_max
            y2 = ref_b.y_min
        else:
            y1 = ref_b.y_max
            y2 = ref_a.y_min
        r.line_y = ((x_mid, y1), (x_mid, y2))

        # Direct line: center to center
        r.line_direct = (
            (ref_a.center_x, ref_a.center_y),
            (ref_b.center_x, ref_b.center_y),
        )

        return r
```

#### File: scene_builder.py -- add measurement visualisation

Add method `build_measurement(self, result) -> list[dict]`:

```python
def build_measurement(self, result):
    """Build PyVista mesh dicts for measurement dimension lines.

    Args:
        result: MeasurementResult with line endpoints in mm

    Returns:
        list of mesh dicts (lines + labels) with group="measurement"
    """
    meshes = []
    s = self.scale  # MM_TO_M = 0.001
    z = 0.15  # measurement lines above deck and dim overlays

    # X distance line (red)
    if result.line_x:
        (x1, y1), (x2, y2) = result.line_x
        if abs(x2 - x1) > 1:  # only draw if meaningful gap
            line = pv.Line((x1*s, y1*s, z), (x2*s, y2*s, z))
            meshes.append({"mesh": line, "color": "#ff3333",
                           "line_width": 2.5, "group": "measurement"})
            # Tick marks at both ends
            tick_h = 0.15  # metres
            for tx in [x1, x2]:
                tick = pv.Line((tx*s, y1*s - tick_h, z),
                               (tx*s, y1*s + tick_h, z))
                meshes.append({"mesh": tick, "color": "#ff3333",
                               "line_width": 2.0, "group": "measurement"})
            # Label
            mx = (x1 + x2) / 2.0 * s
            label = "%d" % abs(round(result.dx_edge))
            meshes.append({"label": "X: " + label + " mm",
                           "position": (mx, y1*s, z + 0.15),
                           "group": "measurement"})

    # Y distance line (blue)
    if result.line_y:
        (x1, y1), (x2, y2) = result.line_y
        if abs(y2 - y1) > 1:
            line = pv.Line((x1*s, y1*s, z), (x2*s, y2*s, z))
            meshes.append({"mesh": line, "color": "#3388ff",
                           "line_width": 2.5, "group": "measurement"})
            tick_h = 0.15
            for ty in [y1, y2]:
                tick = pv.Line((x1*s - tick_h, ty*s, z),
                               (x1*s + tick_h, ty*s, z))
                meshes.append({"mesh": tick, "color": "#3388ff",
                               "line_width": 2.0, "group": "measurement"})
            my = (y1 + y2) / 2.0 * s
            label = "%d" % abs(round(result.dy_edge))
            meshes.append({"label": "Y: " + label + " mm",
                           "position": (x1*s, my, z + 0.15),
                           "group": "measurement"})

    # Direct line (green dashed -- use thin line since PyVista
    # does not support dashed lines natively)
    if result.line_direct and result.dx_edge > 1 and result.dy_edge > 1:
        (x1, y1), (x2, y2) = result.line_direct
        line = pv.Line((x1*s, y1*s, z), (x2*s, y2*s, z))
        meshes.append({"mesh": line, "color": "#33cc66",
                       "line_width": 1.5, "group": "measurement"})
        mx = (x1 + x2) / 2.0 * s
        my = (y1 + y2) / 2.0 * s
        label = "%d" % round(result.direct)
        meshes.append({"label": "D: " + label + " mm",
                       "position": (mx, my, z + 0.3),
                       "group": "measurement"})

    return meshes
```

#### File: main_window.py -- MeasureTab + pick state machine

Add class `MeasureTab(QWidget)`:

```
+------------------------------------------+
| Distance Measurement                      |
|                                          |
| Pick A: [ K-3170-A            ] [Clear]  |
| Pick B: [ Boundary (left)     ] [Clear]  |
|                                          |
| Mode: (o) Edge-to-Edge  ( ) Center      |
|                                          |
| Results:                                 |
| +--------------------------------------+ |
| |  X distance:   3,648 mm             | |
| |  Y distance:       0 mm             | |
| |  Direct:       3,648 mm             | |
| +--------------------------------------+ |
|                                          |
| [Clear All]                              |
+------------------------------------------+
```

Pick state machine in MeasureTab:
- State: `_pick_slot` = "A" or "B"
- When `receive_pick(ref: MeasurementRef)` is called:
  - If `_pick_slot == "A"`: store as ref_a, display name, advance to "B"
  - If `_pick_slot == "B"`: store as ref_b, display name, compute measurement
- When measurement is computed, emit `measurement_ready = Signal(object)` with the MeasurementResult
- "Clear A" resets ref_a and goes back to slot A
- "Clear B" resets ref_b
- "Clear All" resets both

The MainWindow connects:
- 3D pick handler -> determines if equipment or boundary -> creates MeasurementRef -> sends to MeasureTab
- MeasureTab.measurement_ready -> MainWindow adds visualisation meshes to scene
- MeasureTab clear signals -> MainWindow removes measurement meshes

Integration in MainWindow._on_cell_picked or equivalent pick handler:
```python
def _handle_pick(self, x_m, y_m, z_m):
    """Process a 3D pick at world coordinates (metres)."""
    if not hasattr(self, "_builder"):
        return

    x_mm = x_m * 1000.0
    y_mm = y_m * 1000.0

    # Try equipment first
    tag = self._builder.find_tag_at_point(x_m, y_m, z_m)
    if tag:
        # Select in table
        self._equipment_tab.select_row_by_tag(tag)
        # Build measurement ref
        eq = next((e for e in self._layout_data["equipment"]
                   if e["tag"] == tag), None)
        if eq:
            ref = self._measure_engine.make_ref_from_equipment(eq)
            self._measure_tab.receive_pick(ref)
        return

    # Try boundary
    edge = self._measure_engine.identify_nearest_boundary(x_mm, y_mm)
    if edge:
        ref = self._measure_engine.make_ref_from_boundary(
            edge, x_mm, y_mm)
        self._measure_tab.receive_pick(ref)
```

### Task 3C: Export JSON with user edits

**File: main_window.py** -- method `_on_export_json()`

1. Sync table edits back into layout_data before export
2. Add export metadata (tool name, version, timestamp)

### Task 3D: Save/Load project

**File: main_window.py**

1. "Save Project" toolbar action -> saves `.lv3d` file (JSON with different extension)
2. "Load Project" toolbar action -> loads `.lv3d` and restores state
3. Remember path in `self._project_path` for quick re-save

### Task 3E: Status bar enrichment

**File: main_window.py**

After loading SVG or editing equipment, show permanent info on the right side of the status bar:
```
"6 equipment | Module: 25.0 x 21.6 m | Scale: 35.28 mm/pt"
```

## Future Development (NOT for this session)

- STEP export via CadQuery subprocess (step_exporter.py)
- Copilot dock widget (copilot_widget.py)
- Full keyboard shortcuts (1/2/3/4 for views, Ctrl+O, Ctrl+E)
- About dialog

## Testing

After implementation, verify:

1. `python tool/main.py` launches without errors
2. Load Example01.svg -> 6 items in table + 3D scene
3. Click a box in 3D -> corresponding row highlights in equipment table
4. Click near the left boundary, then click K-3170-A -> X distance shows ~3648 mm
5. Click VZ-3170-A, then click VZ-3170-B -> Y distance shows ~6975 mm
6. Click K-3170-A then right boundary -> X distance shows gap to right edge
7. Red X dimension line and blue Y dimension line appear in 3D scene
8. Green direct line appears when measurement has both X and Y components
9. "Clear All" removes measurement lines from 3D scene
10. Edge-to-Edge vs Center mode changes the displayed values
11. Export JSON -> file contains user edits + export metadata
12. Save Project -> Load Project -> state fully restored
13. Status bar shows "6 equipment | Module: 25.0 x 21.6 m"

## Constraints

- Pure ASCII only in all .py files
- Flat sibling imports only (from xxx import Yyy)
- No engineering/measurement logic in main_window.py -- all math in measurement_engine.py
- All new code must work on Windows 11 with conda openusd environment
- Test with both Example01.svg and Example02.svg

## Files to create/modify

| File | Action |
|------|--------|
| measurement_engine.py | CREATE: Layer 1 distance computation (MeasurementRef, MeasurementResult, MeasurementEngine) |
| scene_builder.py | MODIFY: add `find_tag_at_point()`, `get_equipment_bounds()`, `build_measurement()` |
| main_window.py | MODIFY: add 3D picking, MeasureTab, save/load project, status bar, export JSON with edits |
