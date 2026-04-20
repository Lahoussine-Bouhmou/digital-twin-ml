"""
scene_builder.py - Convert parsed SVG layout JSON into PyVista meshes.

Layer 1 module: all geometry generation logic lives here.
No UI code, no Qt imports. Pure PyVista + math.

Equipment type mapping:
  box               -> pv.Box
  vertical_vessel   -> pv.Cylinder (upright)
  horizontal_vessel -> pv.Cylinder (rotated) + sphere heads + box saddles
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pyvista as pv


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MM_TO_M = 0.001  # scene units = metres

# Colours
COLOR_BOX = "#4bacc6"
COLOR_VERT_VESSEL = "#00b050"
COLOR_HORIZ_VESSEL = "#c0504d"
COLOR_BOUNDARY = "#cccccc"
COLOR_GRID = "#555555"
COLOR_DIM_LINE = "#cc3333"
COLOR_DIM_TEXT = "#ff5555"
COLOR_SADDLE = "#888888"
COLOR_DECK = "#3a3a4a"

# Deck plate thickness (metres)
DECK_THICKNESS = 0.012


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
class SceneBuilder:
    """Build a list of mesh-dicts from a parsed layout JSON dict."""
    
    def __init__(self, layout: dict):
        self.layout = layout
        self.scale = MM_TO_M
        self.meshes: list[dict[str, Any]] = []
        self._tag_to_mesh: dict[str, dict] = {}

        # caches pour accélérer le picking / les bounds
        self._equipment_by_tag: dict[str, dict] = {}
        self._bounds_by_tag: dict[str, tuple] = {}
        self._index_layout()

    # ----- main entry point ------------------------------------------------

    def _index_layout(self):
        """Pré-indexe les équipements et leurs bounds."""
        self._equipment_by_tag.clear()
        self._bounds_by_tag.clear()

        for eq in self.layout.get("equipment", []):
            tag = eq.get("tag", "")
            if not tag:
                continue
            self._equipment_by_tag[tag] = eq
            self._bounds_by_tag[tag] = self._compute_equipment_bounds(eq)

    def _compute_equipment_bounds(self, eq: dict) -> tuple:
        """Calcule les bounds logiques complets d'un équipement en mm."""
        cx = eq.get("center_x_mm", 0)
        cy = eq.get("center_y_mm", 0)
        et = eq.get("equipment_type", "box")
        el = eq.get("elevation_mm", 0)

        if et == "box":
            hw = eq.get("width_mm", 0) / 2.0
            hd = eq.get("depth_mm", 0) / 2.0
            h = eq.get("height_mm", 0)
            zmin, zmax = el, el + h

        elif et == "vertical_vessel":
            r = eq.get("diameter_mm", 0) / 2.0
            hw, hd = r, r
            h = eq.get("height_mm", 0)
            zmin, zmax = el, el + h

        elif et == "horizontal_vessel":
            hl = eq.get("length_mm", 0) / 2.0
            r = eq.get("diameter_mm", 0) / 2.0
            rot = eq.get("rotation_deg", 0) or 0
            rad = math.radians(rot)
            hw = abs(hl * math.cos(rad)) + abs(r * math.sin(rad))
            hd = abs(hl * math.sin(rad)) + abs(r * math.cos(rad))
            saddle_h = eq.get("saddle_height_mm", round(r * 2 * 0.4))
            zmin, zmax = el, el + saddle_h + r * 2

        else:
            hw = eq.get("width_mm", 1000) / 2.0
            hd = eq.get("depth_mm", 1000) / 2.0
            zmin, zmax = el, el + eq.get("height_mm", 2000)

        return (cx - hw, cx + hw, cy - hd, cy + hd, zmin, zmax)

    def build(self, show_dimensions: bool = True) -> list[dict[str, Any]]:
        """Generate all meshes and return list of mesh dicts."""
        self.meshes.clear()
        self._tag_to_mesh.clear()
        self._index_layout()

        self._build_deck_plate()
        self._build_boundary()
        self._build_grid_lines()
        self._build_equipment()
        if show_dimensions:
            self._build_dimensions()

        return self.meshes

    def get_equipment_center(self, tag: str) -> tuple[float, float, float] | None:
        """Return world-space centre of an equipment item by tag."""
        md = self._tag_to_mesh.get(tag)
        if md and "mesh" in md:
            c = md["mesh"].center
            return (c[0], c[1], c[2])
        return None

    def get_equipment_bounds(self, tag: str) -> tuple | None:
        """Retourne les bounds logiques complets (xmin, xmax, ymin, ymax, zmin, zmax) en mm."""
        return self._bounds_by_tag.get(tag)

    def find_tag_at_point(self, x_m: float, y_m: float,
                          z_m: float = 0.0) -> str | None:
        """Return the equipment tag whose XY footprint contains the point,
        falling back to the closest footprint within 500 mm.
        """
        x_mm = x_m / self.scale
        y_mm = y_m / self.scale

        nearest_tag = None
        nearest_dist = float("inf")

        for tag, b in self._bounds_by_tag.items():
            xmin, xmax, ymin, ymax, _, _ = b

            if xmin <= x_mm <= xmax and ymin <= y_mm <= ymax:
                return tag

            cx = (xmin + xmax) / 2.0
            cy = (ymin + ymax) / 2.0
            d = math.hypot(cx - x_mm, cy - y_mm)

            if d < nearest_dist:
                nearest_dist = d
                nearest_tag = tag

        if nearest_tag is not None and nearest_dist <= 500:
            return nearest_tag
        return None

    # ----- deck plate ------------------------------------------------------

    def _build_deck_plate(self):
        bnd = self.layout.get("module_boundary", {})
        w = (bnd.get("width_mm") or 0) * self.scale
        l = (bnd.get("length_mm") or 0) * self.scale
        if w <= 0 or l <= 0:
            return
        deck = pv.Box(bounds=(0, w, 0, l, -DECK_THICKNESS, 0))
        self.meshes.append({
            "mesh": deck,
            "color": COLOR_DECK,
            "opacity": 0.35,
            "group": "deck",
        })

    # ----- module boundary -------------------------------------------------

    def _build_boundary(self):
        bnd = self.layout.get("module_boundary", {})
        w = (bnd.get("width_mm") or 0) * self.scale
        l = (bnd.get("length_mm") or 0) * self.scale
        if w <= 0 or l <= 0:
            return

        h = 0.3  # boundary marker height (metres)
        box = pv.Box(bounds=(0, w, 0, l, 0, h))
        self.meshes.append({
            "mesh": box,
            "color": COLOR_BOUNDARY,
            "opacity": 0.15,
            "style": "wireframe",
            "line_width": 1.5,
            "group": "boundary",
        })

    # ----- grid lines ------------------------------------------------------

    def _build_grid_lines(self):
        grids = self.layout.get("grid_lines", {})
        bnd = self.layout.get("module_boundary", {})
        w = (bnd.get("width_mm") or 0) * self.scale
        l = (bnd.get("length_mm") or 0) * self.scale
        if w <= 0 or l <= 0:
            return

        ext = 1.0  # 1m extension beyond boundary for labels

        for xl in grids.get("x_lines", []):
            x = xl["position_mm"] * self.scale
            line = pv.Line((x, -ext, 0), (x, l + ext, 0))
            self.meshes.append({
                "mesh": line,
                "color": COLOR_GRID,
                "opacity": 0.4,
                "line_width": 1.0,
                "group": "grid",
            })
            self.meshes.append({
                "label": xl["label"],
                "position": (x, l + ext + 0.3, 0),
                "group": "grid",
            })

        for yl in grids.get("y_lines", []):
            y = yl["position_mm"] * self.scale
            line = pv.Line((-ext, y, 0), (w + ext, y, 0))
            self.meshes.append({
                "mesh": line,
                "color": COLOR_GRID,
                "opacity": 0.4,
                "line_width": 1.0,
                "group": "grid",
            })
            self.meshes.append({
                "label": yl["label"],
                "position": (-ext - 0.5, y, 0),
                "group": "grid",
            })

    # ----- equipment -------------------------------------------------------

    def _build_equipment(self):
        for eq in self.layout.get("equipment", []):
            eq_type = eq.get("equipment_type", "box")
            if eq_type == "box":
                self._build_box(eq)
            elif eq_type == "vertical_vessel":
                self._build_vertical_vessel(eq)
            elif eq_type == "horizontal_vessel":
                self._build_horizontal_vessel(eq)
            else:
                self._build_box(eq)  # fallback

    def _build_box(self, eq: dict):
        cx = eq["center_x_mm"] * self.scale
        cy = eq["center_y_mm"] * self.scale
        w = eq.get("width_mm", 2000) * self.scale
        d = eq.get("depth_mm", 2000) * self.scale
        h = eq.get("height_mm", 2000) * self.scale
        el = eq.get("elevation_mm", 0) * self.scale
        rot = eq.get("rotation_deg", 0) or 0

        box = pv.Box(bounds=(
            cx - w / 2, cx + w / 2,
            cy - d / 2, cy + d / 2,
            el, el + h,
        ))
        if abs(rot) > 1e-6:
            box = box.rotate_z(rot, point=(cx, cy, el + h / 2))
        md = {
            "mesh": box,
            "color": COLOR_BOX,
            "opacity": 0.75,
            "group": "equipment",
            "tag": eq.get("tag", ""),
        }
        self.meshes.append(md)
        self._tag_to_mesh[eq.get("tag", "")] = md

        # Tag label above
        self.meshes.append({
            "label": eq.get("tag", ""),
            "position": (cx, cy, el + h + 0.2),
            "group": "equipment_label",
        })

    def _build_vertical_vessel(self, eq: dict):
        cx = eq["center_x_mm"] * self.scale
        cy = eq["center_y_mm"] * self.scale
        dia = eq.get("diameter_mm", 1000) * self.scale
        h = eq.get("height_mm", 2000) * self.scale
        el = eq.get("elevation_mm", 0) * self.scale
        r = dia / 2

        cyl = pv.Cylinder(
            center=(cx, cy, el + h / 2),
            direction=(0, 0, 1),
            radius=r,
            height=h,
            resolution=16,
            capping=True,
        )
        md = {
            "mesh": cyl,
            "color": COLOR_VERT_VESSEL,
            "opacity": 0.75,
            "group": "equipment",
            "tag": eq.get("tag", ""),
        }
        self.meshes.append(md)
        self._tag_to_mesh[eq.get("tag", "")] = md

        self.meshes.append({
            "label": eq.get("tag", ""),
            "position": (cx, cy, el + h + 0.3),
            "group": "equipment_label",
        })

    def _build_horizontal_vessel(self, eq: dict):
        cx = eq["center_x_mm"] * self.scale
        cy = eq["center_y_mm"] * self.scale
        length = eq.get("length_mm", 4000) * self.scale
        dia = eq.get("diameter_mm", 1500) * self.scale
        h_default = eq.get("height_mm", 2000) * self.scale
        el = eq.get("elevation_mm", 0) * self.scale
        rot = eq.get("rotation_deg", 0)
        r = dia / 2

        # Saddle height: default 40% of diameter
        saddle_h = eq.get("saddle_height_mm",
                          round(dia / self.scale * 0.4)) * self.scale
        vessel_cz = el + saddle_h + r

        # Determine vessel axis direction from rotation
        # 0 deg = along X, 90 deg = along Y
        rad = math.radians(rot)
        dx = math.cos(rad)
        dy = math.sin(rad)

        # Main cylinder body (along axis)
        cyl = pv.Cylinder(
            center=(cx, cy, vessel_cz),
            direction=(dx, dy, 0),
            radius=r,
            height=length - dia,  # shell length between heads
            resolution=16,
            capping=True,
        )
        md = {
            "mesh": cyl,
            "color": COLOR_HORIZ_VESSEL,
            "opacity": 0.75,
            "group": "equipment",
            "tag": eq.get("tag", ""),
        }
        self.meshes.append(md)
        self._tag_to_mesh[eq.get("tag", "")] = md

        # Hemispherical heads
        shell_half = (length - dia) / 2
        for sign in (-1, 1):
            hx = cx + sign * shell_half * dx
            hy = cy + sign * shell_half * dy
            head = pv.Sphere(radius=r, center=(hx, hy, vessel_cz),
                             theta_resolution=12, phi_resolution=12)
            self.meshes.append({
                "mesh": head,
                "color": COLOR_HORIZ_VESSEL,
                "opacity": 0.65,
                "group": "equipment",
            })

        # Saddles (two boxes under the vessel).
        # Saddle centres follow the rotated axis, but the boxes themselves
        # stay axis-aligned -- a sketching-tool approximation that avoids
        # rotated-bounds math for visually small supports.
        saddle_thin = dia * 0.15   # along vessel axis
        saddle_wide = dia * 0.8    # perpendicular to vessel axis
        saddle_offset = shell_half * 0.6  # 60% of half-length from centre

        is_along_y = abs(dy) > abs(dx)
        if is_along_y:
            box_w, box_d = saddle_wide, saddle_thin
        else:
            box_w, box_d = saddle_thin, saddle_wide

        for sign in (-1, 1):
            sx = cx + sign * saddle_offset * dx
            sy = cy + sign * saddle_offset * dy
            saddle = pv.Box(bounds=(
                sx - box_w / 2, sx + box_w / 2,
                sy - box_d / 2, sy + box_d / 2,
                el, el + saddle_h,
            ))
            self.meshes.append({
                "mesh": saddle,
                "color": COLOR_SADDLE,
                "opacity": 0.8,
                "group": "equipment",
            })

        self.meshes.append({
            "label": eq.get("tag", ""),
            "position": (cx, cy, vessel_cz + r + 0.3),
            "group": "equipment_label",
        })

    # ----- dimensions ------------------------------------------------------

    def _build_dimensions(self):
        """Render dimension annotations as red lines + tick marks + labels.

        Resolves from_ref/to_ref strings into world-space points, places the
        line outside the module on a fixed perpendicular offset (Visio
        convention), draws ticks at each end, and emits the value label
        at the midpoint.
        """
        dims = self.layout.get("dimensions", [])
        if not dims:
            return

        bnd = self.layout.get("module_boundary", {})
        mod_w_mm = bnd.get("width_mm") or 0
        mod_l_mm = bnd.get("length_mm") or 0

        tag_to_eq = {
            eq.get("tag", ""): eq for eq in self.layout.get("equipment", [])
        }

        # Fallback perpendicular offsets used only when the parser didn't
        # record a real position for a dimension (e.g. synthetic dims).
        H_PERP_Y_FALLBACK = -1000
        V_PERP_X_FALLBACK = mod_w_mm + 1000

        z_dim = 0.05  # slightly above deck

        for dm in dims:
            direction = dm.get("direction", "")
            if direction not in ("horizontal", "vertical"):
                continue

            # Preferred path: parser gave us real-world endpoints + perp.
            if "start_mm" in dm and "end_mm" in dm and "perp_mm" in dm:
                s_mm = dm["start_mm"]
                e_mm = dm["end_mm"]
                perp = dm["perp_mm"]
                if direction == "horizontal":
                    p1_x_mm, p1_y_mm = s_mm, perp
                    p2_x_mm, p2_y_mm = e_mm, perp
                else:
                    p1_x_mm, p1_y_mm = perp, s_mm
                    p2_x_mm, p2_y_mm = perp, e_mm
            else:
                # Fallback: resolve via tag refs and a fixed outside offset.
                if direction == "horizontal":
                    h_perp, v_perp = H_PERP_Y_FALLBACK, V_PERP_X_FALLBACK
                else:
                    h_perp, v_perp = H_PERP_Y_FALLBACK, V_PERP_X_FALLBACK
                endpoints = self._resolve_dim_endpoints(
                    dm, tag_to_eq, mod_w_mm, mod_l_mm,
                    h_perp, v_perp,
                )
                if endpoints is None:
                    continue
                (p1_x_mm, p1_y_mm), (p2_x_mm, p2_y_mm), _ = endpoints

            p1 = (p1_x_mm * self.scale, p1_y_mm * self.scale, z_dim)
            p2 = (p2_x_mm * self.scale, p2_y_mm * self.scale, z_dim)

            # Main dimension line
            self.meshes.append({
                "mesh": pv.Line(p1, p2),
                "color": COLOR_DIM_LINE,
                "opacity": 1.0,
                "line_width": 2.0,
                "group": "dimension",
            })

            # Perpendicular tick marks (0.15 m total)
            tick_half = 0.075
            if direction == "horizontal":
                t1a = (p1[0], p1[1] - tick_half, z_dim)
                t1b = (p1[0], p1[1] + tick_half, z_dim)
                t2a = (p2[0], p2[1] - tick_half, z_dim)
                t2b = (p2[0], p2[1] + tick_half, z_dim)
            else:
                t1a = (p1[0] - tick_half, p1[1], z_dim)
                t1b = (p1[0] + tick_half, p1[1], z_dim)
                t2a = (p2[0] - tick_half, p2[1], z_dim)
                t2b = (p2[0] + tick_half, p2[1], z_dim)

            for a, b in ((t1a, t1b), (t2a, t2b)):
                self.meshes.append({
                    "mesh": pv.Line(a, b),
                    "color": COLOR_DIM_LINE,
                    "opacity": 1.0,
                    "line_width": 2.0,
                    "group": "dimension",
                })

            # Value label at midpoint
            mid_x = (p1[0] + p2[0]) / 2
            mid_y = (p1[1] + p2[1]) / 2
            self.meshes.append({
                "label": str(int(dm.get("value_mm", 0))),
                "position": (mid_x, mid_y, z_dim + 0.1),
                "color": COLOR_DIM_TEXT,
                "group": "dimension",
            })

    def _resolve_dim_endpoints(self, dm, tag_to_eq, mod_w_mm, mod_l_mm,
                               h_perp_y, v_perp_x):
        """Resolve a dimension's from_ref/to_ref into two (x_mm, y_mm) points.

        Returns (p1, p2, direction) or None if unresolvable.
        For horizontal dims, both points share y=h_perp_y; only x differs.
        For vertical dims, both points share x=v_perp_x; only y differs.
        """
        direction = dm.get("direction", "")
        if direction not in ("horizontal", "vertical"):
            return None

        from_ref = dm.get("from_ref", "")
        to_ref = dm.get("to_ref", "")

        a = self._resolve_ref_position(
            from_ref, direction, tag_to_eq, mod_w_mm, mod_l_mm, is_from=True,
        )
        b = self._resolve_ref_position(
            to_ref, direction, tag_to_eq, mod_w_mm, mod_l_mm, is_from=False,
        )
        if a is None or b is None:
            return None

        # If both endpoints landed on "boundary", use 0 and module extent
        if from_ref == "boundary" and to_ref == "boundary":
            if direction == "horizontal":
                a, b = 0, mod_w_mm
            else:
                a, b = 0, mod_l_mm

        # If only one is boundary, place it at the side opposite the other
        elif from_ref == "boundary":
            if direction == "horizontal":
                a = 0 if b > mod_w_mm / 2 else mod_w_mm
            else:
                a = 0 if b > mod_l_mm / 2 else mod_l_mm
        elif to_ref == "boundary":
            if direction == "horizontal":
                b = 0 if a > mod_w_mm / 2 else mod_w_mm
            else:
                b = 0 if a > mod_l_mm / 2 else mod_l_mm

        if direction == "horizontal":
            return ((a, h_perp_y), (b, h_perp_y), direction)
        else:
            return ((v_perp_x, a), (v_perp_x, b), direction)

    def _resolve_ref_position(self, ref, direction, tag_to_eq,
                              mod_w_mm, mod_l_mm, is_from):
        """Return a single coordinate (mm) along the dim axis for a ref token.

        Returns the position along the direction axis (x for horizontal
        dims, y for vertical). Returns None if the tag is unknown.
        """
        if ref == "boundary":
            # Caller patches boundary positions after both refs are resolved.
            return 0

        # ref like "TAG_left", "TAG_right", "TAG_top", "TAG_bottom", "TAG_center"
        if "_" not in ref:
            return None
        tag, _, side = ref.rpartition("_")
        eq = tag_to_eq.get(tag)
        if eq is None:
            return None

        cx = eq.get("center_x_mm", 0)
        cy = eq.get("center_y_mm", 0)
        w = eq.get("width_mm") or eq.get("diameter_mm") or 0
        d = eq.get("depth_mm") or eq.get("diameter_mm") or 0

        if direction == "horizontal":
            if side == "left":
                return cx - w / 2
            if side == "right":
                return cx + w / 2
            if side == "center":
                return cx
        else:  # vertical
            if side == "bottom":
                return cy - d / 2
            if side == "top":
                return cy + d / 2
            if side == "center":
                return cy
        return None

    # ----- measurement visualisation ---------------------------------------

    def build_measurement(self, result) -> list[dict[str, Any]]:
        """Build PyVista mesh dicts for measurement dimension lines.

        result: MeasurementResult with endpoints in mm.
        Returns a list of mesh dicts tagged group='measurement'.
        """
        meshes: list[dict[str, Any]] = []
        s = self.scale
        z = 0.15  # above deck and dim overlays

        # X distance line (red)
        if result.line_x:
            (x1, y1), (x2, y2) = result.line_x
            if abs(x2 - x1) > 1:
                line = pv.Line((x1 * s, y1 * s, z), (x2 * s, y2 * s, z))
                meshes.append({
                    "mesh": line, "color": "#ff3333",
                    "line_width": 2.5, "group": "measurement",
                })
                tick_h = 0.15
                for tx in (x1, x2):
                    tick = pv.Line(
                        (tx * s, y1 * s - tick_h, z),
                        (tx * s, y1 * s + tick_h, z),
                    )
                    meshes.append({
                        "mesh": tick, "color": "#ff3333",
                        "line_width": 2.0, "group": "measurement",
                    })
                mx = (x1 + x2) / 2.0 * s
                meshes.append({
                    "label": "X: %d mm" % abs(round(result.dx_edge)),
                    "position": (mx, y1 * s, z + 0.15),
                    "color": "#ff5555",
                    "group": "measurement",
                })

        # Y distance line (blue)
        if result.line_y:
            (x1, y1), (x2, y2) = result.line_y
            if abs(y2 - y1) > 1:
                line = pv.Line((x1 * s, y1 * s, z), (x2 * s, y2 * s, z))
                meshes.append({
                    "mesh": line, "color": "#3388ff",
                    "line_width": 2.5, "group": "measurement",
                })
                tick_h = 0.15
                for ty in (y1, y2):
                    tick = pv.Line(
                        (x1 * s - tick_h, ty * s, z),
                        (x1 * s + tick_h, ty * s, z),
                    )
                    meshes.append({
                        "mesh": tick, "color": "#3388ff",
                        "line_width": 2.0, "group": "measurement",
                    })
                my = (y1 + y2) / 2.0 * s
                meshes.append({
                    "label": "Y: %d mm" % abs(round(result.dy_edge)),
                    "position": (x1 * s, my, z + 0.15),
                    "color": "#55aaff",
                    "group": "measurement",
                })

        # Direct line (green) -- only when both X and Y components exist
        if (result.line_direct and result.dx_edge > 1
                and result.dy_edge > 1):
            (x1, y1), (x2, y2) = result.line_direct
            line = pv.Line((x1 * s, y1 * s, z), (x2 * s, y2 * s, z))
            meshes.append({
                "mesh": line, "color": "#33cc66",
                "line_width": 1.5, "group": "measurement",
            })
            mx = (x1 + x2) / 2.0 * s
            my = (y1 + y2) / 2.0 * s
            meshes.append({
                "label": "D: %d mm" % round(result.direct),
                "position": (mx, my, z + 0.3),
                "color": "#55dd88",
                "group": "measurement",
            })

        return meshes
