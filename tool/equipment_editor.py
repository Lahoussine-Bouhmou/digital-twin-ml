"""
equipment_editor.py - Layer 1 edit operations on equipment dicts.

Pure geometry and data manipulation. No UI, no PyVista.
All coordinates in mm.

Rotation convention:
  rotation_deg is CCW in the XY plane.
  0 deg -> part's local +X axis aligned with world +X.
  90 deg -> part's local +X axis aligned with world +Y.
"""

from __future__ import annotations

import copy
import math
from typing import Iterable


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _half_extents(eq: dict) -> tuple[float, float]:
    """Return (half_width, half_depth) along the part's *local* X / Y axes.

    Local X matches the part's length / width direction; local Y matches
    depth / diameter. Rotation is applied by the caller.
    """
    et = eq.get("equipment_type", "box")
    if et == "box":
        return (eq.get("width_mm", 0) / 2.0, eq.get("depth_mm", 0) / 2.0)
    if et == "vertical_vessel":
        r = eq.get("diameter_mm", 0) / 2.0
        return (r, r)
    if et == "horizontal_vessel":
        return (
            eq.get("length_mm", 0) / 2.0,
            eq.get("diameter_mm", 0) / 2.0,
        )
    return (
        eq.get("width_mm", 1000) / 2.0,
        eq.get("depth_mm", 1000) / 2.0,
    )


def _rotate_point(px: float, py: float, cx: float, cy: float,
                  angle_deg: float) -> tuple[float, float]:
    """Rotate (px, py) CCW by angle_deg around pivot (cx, cy)."""
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    return (cx + c * dx - s * dy, cy + s * dx + c * dy)


def _axis_aligned_footprint(eq: dict) -> tuple[float, float, float, float]:
    """Return world-space (xmin, xmax, ymin, ymax) accounting for rotation."""
    cx = eq.get("center_x_mm", 0)
    cy = eq.get("center_y_mm", 0)
    hw, hd = _half_extents(eq)
    rot = eq.get("rotation_deg", 0)
    rad = math.radians(rot)
    c, s = abs(math.cos(rad)), abs(math.sin(rad))
    aabb_hw = hw * c + hd * s
    aabb_hd = hw * s + hd * c
    return (cx - aabb_hw, cx + aabb_hw, cy - aabb_hd, cy + aabb_hd)


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------

def move_absolute(eq: dict, x_mm: float | None = None,
                  y_mm: float | None = None,
                  z_mm: float | None = None) -> None:
    if x_mm is not None:
        eq["center_x_mm"] = int(round(x_mm))
    if y_mm is not None:
        eq["center_y_mm"] = int(round(y_mm))
    if z_mm is not None:
        eq["elevation_mm"] = int(round(z_mm))
        _strip_default(eq, "elevation_mm")


def move_relative(eq: dict, dx_mm: float = 0, dy_mm: float = 0,
                  dz_mm: float = 0) -> None:
    eq["center_x_mm"] = int(round(eq.get("center_x_mm", 0) + dx_mm))
    eq["center_y_mm"] = int(round(eq.get("center_y_mm", 0) + dy_mm))
    if dz_mm != 0:
        eq["elevation_mm"] = int(round(eq.get("elevation_mm", 0) + dz_mm))
        _strip_default(eq, "elevation_mm")


# ---------------------------------------------------------------------------
# Rotate
# ---------------------------------------------------------------------------

def rotate_around_center(eq: dict, delta_deg: float) -> None:
    eq["rotation_deg"] = _wrap_deg(eq.get("rotation_deg", 0) + delta_deg)


def rotate_around_pivot(eq: dict, pivot_x_mm: float, pivot_y_mm: float,
                        delta_deg: float) -> None:
    cx = eq.get("center_x_mm", 0)
    cy = eq.get("center_y_mm", 0)
    new_cx, new_cy = _rotate_point(cx, cy, pivot_x_mm, pivot_y_mm, delta_deg)
    eq["center_x_mm"] = int(round(new_cx))
    eq["center_y_mm"] = int(round(new_cy))
    eq["rotation_deg"] = _wrap_deg(eq.get("rotation_deg", 0) + delta_deg)


def rotate_around_corner(eq: dict, corner: str, delta_deg: float) -> None:
    px, py = get_corner_world(eq, corner)
    rotate_around_pivot(eq, px, py, delta_deg)


def _wrap_deg(deg: float) -> float:
    return round(deg % 360.0, 3)


# ---------------------------------------------------------------------------
# Corners and edges
# ---------------------------------------------------------------------------

_CORNER_LOCAL = {
    "bottom-left":  (-1, -1),
    "bottom-right": (+1, -1),
    "top-left":     (-1, +1),
    "top-right":    (+1, +1),
}


def get_corner_world(eq: dict, corner: str) -> tuple[float, float]:
    """World-space coords of the named corner in the part's local frame.

    The corner is fixed to the part: as rotation changes, the world
    position of "bottom-left" moves with the part.
    """
    if corner not in _CORNER_LOCAL:
        raise ValueError("unknown corner: %r" % corner)
    sx, sy = _CORNER_LOCAL[corner]
    hw, hd = _half_extents(eq)
    lx, ly = sx * hw, sy * hd
    cx = eq.get("center_x_mm", 0)
    cy = eq.get("center_y_mm", 0)
    rot = eq.get("rotation_deg", 0)
    wx, wy = _rotate_point(cx + lx, cy + ly, cx, cy, rot)
    return (wx, wy)


def get_edge_world(eq: dict, edge: str) -> float:
    """World-space X (for left/right) or Y (for top/bottom) of the edge.

    Uses the rotation-aware axis-aligned bounding box so alignment
    semantics feel natural when parts are rotated.
    """
    xmin, xmax, ymin, ymax = _axis_aligned_footprint(eq)
    if edge == "left":
        return xmin
    if edge == "right":
        return xmax
    if edge == "bottom":
        return ymin
    if edge == "top":
        return ymax
    raise ValueError("unknown edge: %r" % edge)


# ---------------------------------------------------------------------------
# Create / duplicate
# ---------------------------------------------------------------------------

_TYPE_REQUIRED = {
    "box": ("width_mm", "depth_mm", "height_mm"),
    "vertical_vessel": ("diameter_mm", "height_mm"),
    "horizontal_vessel": ("length_mm", "diameter_mm"),
}


def make_new_equipment(tag: str, eq_type: str,
                       center_x_mm: float, center_y_mm: float,
                       **dims) -> dict:
    """Build a fresh equipment dict with the project's default conventions."""
    if eq_type not in _TYPE_REQUIRED:
        raise ValueError("unknown equipment_type: %r" % eq_type)

    eq: dict = {
        "tag": tag,
        "svg_shape": "manual",
        "equipment_type": eq_type,
        "center_x_mm": int(round(center_x_mm)),
        "center_y_mm": int(round(center_y_mm)),
        "rotation_deg": float(dims.get("rotation_deg", 0.0)),
        "elevation_mm": int(round(dims.get("elevation_mm", 0))),
        "weight_kg": int(round(dims.get("weight_kg", 1000))),
        "data_source": "manual",
        "defaults_applied": [],
    }

    if eq_type == "box":
        eq["width_mm"] = int(round(dims.get("width_mm", 2000)))
        eq["depth_mm"] = int(round(dims.get("depth_mm", 2000)))
        eq["height_mm"] = int(round(dims.get("height_mm", 2000)))
    elif eq_type == "vertical_vessel":
        eq["diameter_mm"] = int(round(dims.get("diameter_mm", 1500)))
        eq["height_mm"] = int(round(dims.get("height_mm", 3000)))
    elif eq_type == "horizontal_vessel":
        eq["length_mm"] = int(round(dims.get("length_mm", 4000)))
        eq["diameter_mm"] = int(round(dims.get("diameter_mm", 1500)))
        eq["height_mm"] = int(round(dims.get("height_mm", 2000)))
        eq["saddle_height_mm"] = int(round(
            dims.get("saddle_height_mm", eq["diameter_mm"] * 0.4)
        ))

    return eq


def duplicate_equipment(eq: dict, offset_x_mm: float = 1000,
                        offset_y_mm: float = 0,
                        new_tag: str | None = None,
                        existing_tags: Iterable[str] = ()) -> dict:
    """Return a deep copy of eq shifted by (offset_x_mm, offset_y_mm)."""
    copy_eq = copy.deepcopy(eq)
    copy_eq["center_x_mm"] = int(round(copy_eq.get("center_x_mm", 0) + offset_x_mm))
    copy_eq["center_y_mm"] = int(round(copy_eq.get("center_y_mm", 0) + offset_y_mm))
    copy_eq["data_source"] = (copy_eq.get("data_source", "") + "+duplicate").lstrip("+")
    if new_tag:
        copy_eq["tag"] = new_tag
    else:
        copy_eq["tag"] = _auto_suffix_tag(
            copy_eq.get("tag", "EQ"), set(existing_tags)
        )
    return copy_eq


def _auto_suffix_tag(base: str, existing: set[str]) -> str:
    candidate = base + "-copy"
    if candidate not in existing:
        return candidate
    i = 2
    while True:
        candidate = "%s-copy%d" % (base, i)
        if candidate not in existing:
            return candidate
        i += 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_tag_unique(layout: dict, tag: str,
                        exclude_tag: str | None = None) -> bool:
    for eq in layout.get("equipment", []):
        existing = eq.get("tag", "")
        if existing == exclude_tag:
            continue
        if existing == tag:
            return False
    return True


def check_collisions(layout: dict) -> list[tuple[str, str]]:
    """Return pairs of tags whose axis-aligned footprints overlap."""
    items = [
        (eq.get("tag", ""), _axis_aligned_footprint(eq))
        for eq in layout.get("equipment", [])
        if eq.get("tag")
    ]
    pairs: list[tuple[str, str]] = []
    for i in range(len(items)):
        ta, (ax0, ax1, ay0, ay1) = items[i]
        for j in range(i + 1, len(items)):
            tb, (bx0, bx1, by0, by1) = items[j]
            if ax1 > bx0 and bx1 > ax0 and ay1 > by0 and by1 > ay0:
                pairs.append((ta, tb))
    return pairs


def check_out_of_bounds(layout: dict) -> list[str]:
    bnd = layout.get("module_boundary") or {}
    w = bnd.get("width_mm")
    l = bnd.get("length_mm")
    if not w or not l:
        return []
    out: list[str] = []
    for eq in layout.get("equipment", []):
        tag = eq.get("tag", "")
        if not tag:
            continue
        x0, x1, y0, y1 = _axis_aligned_footprint(eq)
        if x0 < 0 or y0 < 0 or x1 > w or y1 > l:
            out.append(tag)
    return out


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

def align_to(equipment_list: list[dict], ref_tag: str,
             target_tags: Iterable[str], edge: str) -> None:
    """Align each target to ref along the named edge.

    edge in {"left","right","top","bottom","h-center","v-center"}.
    Uses rotation-aware axis-aligned footprints.
    """
    ref = _find(equipment_list, ref_tag)
    if ref is None:
        return
    targets = [_find(equipment_list, t) for t in target_tags if t != ref_tag]
    targets = [t for t in targets if t is not None]
    if not targets:
        return

    if edge == "h-center":
        ref_x = ref["center_x_mm"]
        for t in targets:
            t["center_x_mm"] = int(round(ref_x))
        return
    if edge == "v-center":
        ref_y = ref["center_y_mm"]
        for t in targets:
            t["center_y_mm"] = int(round(ref_y))
        return

    ref_val = get_edge_world(ref, edge)
    for t in targets:
        cur = get_edge_world(t, edge)
        delta = ref_val - cur
        if edge in ("left", "right"):
            t["center_x_mm"] = int(round(t["center_x_mm"] + delta))
        else:  # top / bottom
            t["center_y_mm"] = int(round(t["center_y_mm"] + delta))


def _find(equipment_list: list[dict], tag: str) -> dict | None:
    for e in equipment_list:
        if e.get("tag") == tag:
            return e
    return None


def _strip_default(eq: dict, key: str) -> None:
    da = eq.get("defaults_applied")
    if isinstance(da, list) and key in da:
        da.remove(key)
