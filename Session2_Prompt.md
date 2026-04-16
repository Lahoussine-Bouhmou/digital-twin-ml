# Session 2 Prompt - Layout Viewer 3D

Read CLAUDE.md first for full project context.

## Objective
Implement Session 2 features for the Layout Viewer 3D tool. Session 1 (basic SVG parsing, 3D scene with boxes/cylinders, Qt window with tabs) is complete and working.

## Tasks

### Task 2A: Dimension overlays in 3D scene

**File: scene_builder.py** -- method `_build_dimensions()`

Currently this method is a stub (pass). Implement it:

1. For each dimension in `self.layout["dimensions"]`, build a 3D dimension line:
   - Red line (`#cc3333`) between the two reference points
   - Small perpendicular tick marks at both ends (0.15m tall)
   - Text label showing the value (e.g. "3648") positioned at midpoint
   - Use `pv.Line()` for lines, point labels for text

2. To resolve reference positions, add a method `_resolve_dim_endpoints(dim)`:
   - Parse `from_ref` and `to_ref` strings (e.g. "boundary", "K-3170-A_left", "VZ-3170-A_center")
   - "boundary" with horizontal direction -> x=0 (left) or x=module_width (right) 
   - "boundary" with vertical -> y=0 (bottom) or y=module_length (top)
   - "{tag}_left" -> equipment center_x - width/2
   - "{tag}_right" -> equipment center_x + width/2
   - "{tag}_center" -> equipment center_x or center_y
   - Place dimension lines at z=0.05m (just above deck)

3. Add `show_dimensions: bool = True` parameter to `build()` method. When False, skip dimension meshes. This will be toggled from the UI.

4. Tag all dimension mesh dicts with `"group": "dimension"`.

### Task 2B: Equipment table editing triggers rebuild

**File: main_window.py** -- class `EquipmentTab` and `MainWindow`

Currently, editing a default cell (e.g. changing height_mm from 2000 to 5000) updates the table model but does NOT rebuild the 3D scene.

1. In `EquipmentTableModel.setData()`, after updating the value, emit a custom signal `data_edited = Signal()`.

2. In `EquipmentTab`, connect `self._model.data_edited` to a new signal `equipment_changed = Signal()`.

3. In `MainWindow.__init__()`, connect `self._equipment_tab.equipment_changed` to a new method `_on_equipment_edited()`.

4. `_on_equipment_edited()` should:
   - Get the current equipment list from the table model: `self._equipment_tab.get_table_model().get_equipment_list()`
   - Update `self._layout_data["equipment"]` with this list
   - Call `self._rebuild_scene()`

### Task 2C: Dimension toggle in toolbar

**File: main_window.py**

1. Add a checkable QAction "Dims" to the toolbar (checked by default).
2. Store state in `self._show_dimensions = True`.
3. When toggled, set the flag and call `self._rebuild_scene()`.
4. Pass `show_dimensions=self._show_dimensions` to `SceneBuilder.build()`.

### Task 2D: Excel merge integration

**File: svg_layout_parser.py** -- method `_merge_excel()`

The current implementation expects specific column headers. Make it more flexible:

1. Add case-insensitive header matching with aliases:
   - tag: "tag", "equipment tag", "equipment_tag", "item", "tag number", "tag_number"
   - height: "height_mm", "height", "height (mm)", "h_mm", "tan-tan"
   - weight: "weight_kg", "weight", "weight (kg)", "dry weight", "operating weight", "dry weight (kg)", "operating weight (kg)", "weight (t)", "weight (mT)", "dry weight (t)", "operating weight (t)", "dry weight (mT)", "operating weight (mT)"
   - diameter: "diameter_mm", "diameter", "dia", "od", "dia (mm)", "id"
   - length: "length_mm", "length", "len", "length (mm)", "t/t", "tan to tan"
   - elevation: "elevation_mm", "elevation", "elev", "el", "elevation (mm)"

2. If height values appear to be in metres (all values < 50), auto-convert to mm and add warning.

3. After merge, update the summary in ImportTab and rebuild scene.

**File: main_window.py** -- `ImportTab._on_load_excel()`

Currently this re-parses the SVG. Change it to:
1. Keep the existing parsed layout data
2. Create a new parser instance just for the Excel merge
3. Call `_merge_excel()` on the existing equipment list directly
4. Emit `svg_loaded` signal with updated data to trigger table + scene refresh

### Task 2E: Horizontal vessel rotation in scene_builder

**File: scene_builder.py** -- method `_build_horizontal_vessel()`

Current implementation uses rotation_deg to orient the cylinder direction vector, but the saddle positions don't account for rotation correctly. Fix:

1. The saddle boxes should be offset along the vessel axis (rotated direction), not just along X.
2. Saddle depth should be perpendicular to the vessel axis.
3. For rotated saddles, use PyVista's `pv.Box().rotate_z(angle)` or compute rotated bounding boxes.

**Simpler approach:** Since saddles are small relative to the vessel, approximate them as:
- Compute saddle center positions along the vessel axis using the direction vector
- Create saddle boxes aligned to the global axes (no rotation) -- visually acceptable for a sketching tool
- This avoids complex rotated box math

### Task 2F: Parser robustness

**File: svg_layout_parser.py**

1. When no dimension annotations exist (like Example02.svg), use Visio's `v:drawingScale` and `v:pageScale` from `v:pageProperties` to compute the scale:
   ```
   scale = drawingScale / pageScale  (both in mm if metric)
   ```
   For Example02.svg: drawingScale=39.3701, pageScale=0.393701 -> scale_factor = 100 (1 SVG pt = 100 real units? No, these are in/mm conversion). Parse the drawingUnits attribute too.

2. Add a fallback: if neither dimensions nor page properties give a usable scale, default to scale=1.0 and warn "No scale calibration available; coordinates are in SVG points".

3. Handle the case where equipment shapes have no CSS class (Example02.svg uses class="st1" which is white fill, not colored). For shapes with Visio `ShapeClass=Equipment` metadata, treat them as equipment regardless of CSS fill color.

## Testing

After implementation, verify:

1. `python tool/main.py` launches without errors
2. Load Example01.svg -> 6 equipment items, dimension overlay lines visible in 3D
3. Toggle "Dims" off -> dimension lines disappear
4. Double-click height_mm cell for K-3170-A, change to 5000 -> the box grows taller in 3D
5. Load Example02.svg -> 2 horizontal vessels render (no dimensions, parser warns)
6. Click Plan (XY) -> top-down view shows correct layout

## Constraints

- Pure ASCII only in all .py files
- Flat sibling imports only (from xxx import Yyy, NOT from package.xxx)
- No engineering logic in main_window.py
- All new code must work on Windows 11 with conda layout3d environment
- Test with both Example01.svg and Example02.svg
