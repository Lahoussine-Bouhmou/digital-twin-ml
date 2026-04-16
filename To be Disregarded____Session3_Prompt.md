# Session 3 Prompt - Layout Viewer 3D

Read CLAUDE.md first for full project context. Sessions 1 and 2 are complete.

## Objective

Implement Session 3: 3D click-picking, JSON/STEP export, Save/Load project, and a copilot dock placeholder. This session makes the tool production-ready for engineer demos.

## Tasks

### Task 3A: Click-picking in 3D viewport -> select equipment table row

**File: main_window.py**

Currently clicking equipment in the 3D viewport does nothing. Implement pick-on-click:

1. In `_setup_ui()`, after creating the plotter, enable point picking:
   ```python
   self._plotter.enable_point_picking(
       callback=self._on_3d_pick,
       use_picker=True,
       show_message=False,
       show_point=False,
       picker="cell",
   )
   ```
   NOTE: `enable_point_picking` may not exist in all pyvistaqt versions. Alternative approach using `iren`:
   ```python
   self._plotter.iren.add_observer("LeftButtonPressEvent", self._on_left_click)
   ```

2. The preferred approach is to use `enable_cell_picking`:
   ```python
   self._plotter.enable_cell_picking(
       callback=self._on_cell_picked,
       through=False,
       show=False,
       show_message=False,
       color="yellow",
       style="wireframe",
   )
   ```

3. Implement `_on_cell_picked(self, cell)` or `_on_3d_pick(self, point)`:
   - Get the picked mesh from the callback
   - Find which equipment tag owns that mesh by checking `self._builder._tag_to_mesh`
   - If found, select the corresponding row in the equipment table
   - Highlight the equipment (reuse existing `_on_equipment_selected` logic)

4. In `SceneBuilder`, expose a method `find_tag_at_point(x, y, z) -> str | None`:
   - For each equipment mesh, check if the point is inside or near the mesh bounds
   - Return the tag of the closest equipment, or None
   - Use `mesh.bounds` for bounding-box hit testing (simpler than ray casting)

5. In `EquipmentTab`, add a public method `select_row_by_tag(tag: str)`:
   - Find the row index where tag matches
   - Set the table selection to that row
   - Scroll to make it visible

6. Wire it together: 3D pick -> find tag -> select table row -> highlight in 3D

### Task 3B: Export JSON with user edits preserved

**File: main_window.py** -- method `_on_export_json()`

The current implementation exports raw layout_data. Improve it:

1. Before export, sync the equipment table edits back into `self._layout_data`:
   ```python
   self._layout_data["equipment"] = (
       self._equipment_tab.get_table_model().get_equipment_list()
   )
   ```

2. Add metadata to the exported JSON:
   ```python
   export_data = dict(self._layout_data)
   export_data["export_info"] = {
       "tool": "Layout Viewer 3D",
       "version": "0.1.0",
       "exported_at": datetime.now().isoformat(),
   }
   ```

3. Add a "Save Project" toolbar action that saves to a `.lv3d` file (just JSON with a different extension) and remembers the path for quick re-save.

4. Add a "Load Project" toolbar action that loads a `.lv3d` file and restores the state (equipment table + 3D scene), bypassing SVG parsing.

### Task 3C: STEP export via subprocess to cq_export environment

**File: step_exporter.py (NEW FILE)**

Create a new module `step_exporter.py` that handles STEP export using the same subprocess pattern as the main SeaTec3D app:

1. The module should contain:
   ```python
   class StepExporter:
       def __init__(self, layout_data: dict):
           self.layout_data = layout_data
       
       def export(self, output_path: str, 
                  progress_callback=None) -> dict:
           """Export layout as STEP file via CadQuery subprocess."""
           ...
       
       def _find_cq_python(self) -> str | None:
           """Find cq_export conda env Python executable."""
           ...
       
       def _build_scene_dict(self) -> dict:
           """Convert layout JSON to scene_dict format for step_export_worker."""
           ...
   ```

2. `_find_cq_python()` search order:
   - `CQ_PYTHON` environment variable (user override)
   - `{conda_prefix}/../cq_export/python.exe` (sibling env)
   - `{USERPROFILE}/miniconda3/envs/cq_export/python.exe`
   - `{USERPROFILE}/anaconda3/envs/cq_export/python.exe`
   - `conda run -n cq_export python` as fallback

3. `_build_scene_dict()` converts the layout JSON equipment list into the format expected by `step_export_worker.py`:
   ```python
   scene_dict = {"equipment": {}, "structure": {}, "piping": {}}
   for eq in self.layout_data["equipment"]:
       tag = eq["tag"]
       eq_type = eq["equipment_type"]
       # Map to step_export_worker types:
       # box -> "Cubical Equipment"
       # vertical_vessel -> "Vertical Vessel"  
       # horizontal_vessel -> "Horizontal Vessel"
       scene_dict["equipment"][tag] = {
           "type": mapped_type,
           "params": {
               "pos": [cx_m, cy_m, el_m],
               "width": w_m, "length": d_m, "height": h_m,
               # or for vessels: "diameter": d_m, ...
           }
       }
   ```
   All dimensions convert from mm to metres (divide by 1000).

4. The export flow:
   - Write scene_dict to a temp JSON file
   - Find cq_export Python
   - Run: `{cq_python} step_export_worker.py {temp_json} {output_step}`
   - Parse stdout for JSON report
   - Return result dict with ok, solids count, errors

5. If cq_export is not found, return a clear error message telling the user to run `setup_cadquery_env.bat` or set `CQ_PYTHON` env var.

**File: main_window.py** -- add STEP export action

1. Add "Export STEP" to the toolbar.
2. On click: open file dialog for .step path, then call `StepExporter.export()`.
3. Show progress in status bar.
4. Show result dialog (success with solid count, or error with instructions).

### Task 3D: Copilot dock widget placeholder

**File: copilot_widget.py (NEW FILE)**

Create a QDockWidget placeholder for future copilot integration, following the pattern from the jacket_tool:

```python
class CopilotDock(QDockWidget):
    """Placeholder copilot chat dock widget."""
    
    model_mutations_ready = Signal(list)
    
    def __init__(self, parent=None):
        super().__init__("Co-pilot", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # API key section
        key_row = QHBoxLayout()
        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("Anthropic API key...")
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self._key_input)
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.clicked.connect(self._on_connect)
        key_row.addWidget(self._btn_connect)
        layout.addLayout(key_row)
        
        # Status
        self._status_label = QLabel("Not connected")
        self._status_label.setStyleSheet("color: #f38ba8;")
        layout.addWidget(self._status_label)
        
        # Chat display (read-only)
        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        layout.addWidget(self._chat_display)
        
        # Input row
        input_row = QHBoxLayout()
        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("Ask the co-pilot...")
        self._chat_input.returnPressed.connect(self._on_send)
        input_row.addWidget(self._chat_input)
        self._btn_send = QPushButton("Send")
        self._btn_send.clicked.connect(self._on_send)
        input_row.addWidget(self._btn_send)
        layout.addLayout(input_row)
        
        # Quick prompts
        qp_row = QHBoxLayout()
        for label, prompt in [
            ("Summary", "Summarize this layout"),
            ("Clearances", "Check equipment clearances"),
            ("Weights", "Show weight summary"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda p=prompt: self._send(p))
            qp_row.addWidget(btn)
        layout.addLayout(qp_row)
        
        self.setWidget(widget)
    
    def _on_connect(self):
        key = self._key_input.text().strip()
        if key:
            self._status_label.setText("Connected (placeholder)")
            self._status_label.setStyleSheet("color: #a6e3a1;")
            self._append_message("system", 
                "Co-pilot connected. Full integration coming in Phase 92.")
    
    def _on_send(self):
        msg = self._chat_input.text().strip()
        if not msg:
            return
        self._chat_input.clear()
        self._send(msg)
    
    def _send(self, msg):
        self._append_message("user", msg)
        # Placeholder response
        self._append_message("assistant",
            "Co-pilot integration is a placeholder in this version. "
            "Full Anthropic API integration planned for Phase 92.")
    
    def _append_message(self, role, text):
        color_map = {
            "user": "#89b4fa",
            "assistant": "#cdd6f4", 
            "system": "#a6adc8",
            "error": "#f38ba8",
        }
        color = color_map.get(role, "#cdd6f4")
        prefix = {"user": "You", "assistant": "Co-pilot",
                  "system": "System", "error": "Error"}.get(role, "")
        self._chat_display.append(
            '<span style="color:%s"><b>%s:</b> %s</span>' % (color, prefix, text)
        )
```

**File: main_window.py** -- integrate copilot dock

1. In `_setup_toolbar()`, add a separator then a checkable "Co-pilot" action.
2. Add method `_toggle_copilot()`:
   ```python
   def _toggle_copilot(self):
       if not hasattr(self, "_copilot_dock"):
           from copilot_widget import CopilotDock
           self._copilot_dock = CopilotDock(self)
           self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, 
                              self._copilot_dock)
       else:
           self._copilot_dock.setVisible(
               not self._copilot_dock.isVisible())
   ```

### Task 3E: Toolbar polish and keyboard shortcuts

**File: main_window.py**

1. Add keyboard shortcuts:
   - `Ctrl+O` -> Load SVG
   - `Ctrl+S` -> Save Project
   - `Ctrl+Shift+S` -> Export JSON
   - `Ctrl+E` -> Export STEP
   - `1` -> 3D view
   - `2` -> Plan (XY) view
   - `3` -> Front (XZ) view
   - `4` -> Side (YZ) view

2. Add toolbar separators between logical groups:
   - File group: Load SVG | Save | Load Project
   - Export group: Export JSON | Export STEP
   - View group: 3D | Plan | Front | Side | Dims toggle
   - Tools group: Co-pilot toggle

3. Add an "About" action in the toolbar or menu bar showing:
   - "Layout Viewer 3D v0.1.0"
   - "Part of SeaTec3D - Offshore Engineering Platform"
   - "Session 3 build"

### Task 3F: Status bar enrichment

**File: main_window.py**

1. Show permanent info in the status bar:
   - Left: last action message (existing)
   - Right: equipment count and module dimensions (permanent widgets)
   
2. After loading SVG or editing equipment, update the permanent status:
   ```
   "6 equipment | Module: 25.0 x 21.6 m | Scale: 35.28 mm/pt"
   ```

3. During STEP export, show progress:
   ```
   "Exporting STEP... 3/6 solids built"
   ```

## Testing

After implementation, verify:

1. `python tool/main.py` launches without errors
2. Load Example01.svg -> 6 items in table + 3D scene
3. Click a box in 3D -> corresponding row highlights in equipment table
4. Click a row in table -> camera flies to equipment in 3D (already works from Session 1)
5. Edit height_mm in table -> 3D scene updates (from Session 2)
6. Export JSON -> file contains user edits + export metadata
7. Save Project (.lv3d) -> Load Project -> state fully restored
8. Export STEP -> either succeeds with solid count or shows clear "cq_export not found" message
9. Co-pilot toggle -> dock appears/disappears on right side
10. Keyboard shortcut `2` -> switches to plan view
11. Status bar shows "6 equipment | Module: 25.0 x 21.6 m"

## Constraints

- Pure ASCII only in all .py files
- Flat sibling imports only (from xxx import Yyy)
- No engineering logic in main_window.py or copilot_widget.py
- STEP exporter must handle "cq_export not found" gracefully (no crash)
- All new code must work on Windows 11 with conda openusd environment
- Test with both Example01.svg and Example02.svg

## Files to create/modify

| File | Action |
|------|--------|
| main_window.py | MODIFY: add 3D picking, save/load project, STEP export action, copilot toggle, shortcuts, status bar |
| scene_builder.py | MODIFY: add `find_tag_at_point()` method |
| step_exporter.py | CREATE: STEP export via CadQuery subprocess |
| copilot_widget.py | CREATE: QDockWidget placeholder with chat UI |
