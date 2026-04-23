from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datasets import load_dataset
from tqdm import tqdm
from shapely.affinity import rotate, translate
from shapely.geometry import Point, Polygon, box

try:
    import pulp
except Exception:
    pulp = None


# ============================================================
# Basic helpers
# ============================================================

def mm(v_meters: float) -> int:
    return int(round(float(v_meters) * 1000.0))


def wrap_deg(angle_deg: float) -> float:
    return ((float(angle_deg) + 180.0) % 360.0) - 180.0


def quat_to_yaw_deg(q: list[float]) -> float:
    """
    SSR-3DFRONT rotation = quaternion [x, y, z, w]
    Extract yaw around the vertical axis.
    """
    x, y, z, w = map(float, q)
    siny_cosp = 2.0 * (w * y + x * z)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw_rad = math.atan2(siny_cosp, cosy_cosp)
    return wrap_deg(math.degrees(yaw_rad))


def largest_polygon(geom):
    if geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)
    return None


# ============================================================
# Room geometry
# ============================================================

def build_room_polygon_xz(bounds_bottom: list[list[float]]) -> Polygon:
    """
    Build the original room polygon from scene["bounds_bottom"] projected to XZ.
    """
    pts = [(float(p[0]), float(p[2])) for p in bounds_bottom]
    if len(pts) < 3:
        raise ValueError("Room boundary has fewer than 3 points.")

    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)

    poly = largest_polygon(poly)
    if poly is None or poly.area <= 1e-12:
        raise ValueError("Invalid room polygon after cleanup.")

    return poly


def angle_of_longest_edge(rect: Polygon) -> float:
    """
    Returns the angle (degrees) of the longest edge of a rectangle polygon.
    Used as the local orientation of the room.
    """
    coords = list(rect.exterior.coords)[:-1]
    if len(coords) != 4:
        raise ValueError("Minimum rotated rectangle is not a 4-corner polygon.")

    best_len = -1.0
    best_angle = 0.0

    for i in range(4):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % 4]
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length > best_len:
            best_len = length
            best_angle = math.degrees(math.atan2(dy, dx))

    return wrap_deg(best_angle)


def make_room_local_frame(room_poly_world: Polygon):
    """
    Compute the minimum rotated rectangle of the room, then define a local frame
    in which that rectangle becomes axis-aligned and starts at (0, 0).

    Returns:
      rect_world
      room_angle_deg
      room_width_m
      room_length_m
      to_local_geom(geom)
      to_local_point(x, y)
    """
    rect_world = room_poly_world.minimum_rotated_rectangle
    rect_world = largest_polygon(rect_world.buffer(0))
    if rect_world is None or rect_world.area <= 1e-12:
        raise ValueError("Failed to compute minimum rotated rectangle.")

    room_angle_deg = angle_of_longest_edge(rect_world)

    rect_rot = rotate(rect_world, -room_angle_deg, origin=(0.0, 0.0), use_radians=False)
    minx, miny, maxx, maxy = rect_rot.bounds

    room_width_m = maxx - minx
    room_length_m = maxy - miny

    if room_width_m <= 1e-12 or room_length_m <= 1e-12:
        raise ValueError("Degenerate local room rectangle.")

    def to_local_geom(geom):
        g = rotate(geom, -room_angle_deg, origin=(0.0, 0.0), use_radians=False)
        g = translate(g, xoff=-minx, yoff=-miny)
        return g

    def to_local_point(x: float, y: float) -> tuple[float, float]:
        p = Point(float(x), float(y))
        q = to_local_geom(p)
        return float(q.x), float(q.y)

    return rect_world, room_angle_deg, room_width_m, room_length_m, to_local_geom, to_local_point


# ============================================================
# Object geometry
# ============================================================

def footprint_polygon_xz(size: list[float], pos: list[float], rot_q: list[float]) -> tuple[Polygon, float]:
    """
    Build exact oriented footprint in XZ plane.
    size = [width, height, depth]
    pos  = [x, y, z]
    """
    w = float(size[0])
    d = float(size[2])
    x = float(pos[0])
    z = float(pos[2])

    if w <= 0.0 or d <= 0.0:
        raise ValueError("Non-positive footprint size.")

    yaw_deg = quat_to_yaw_deg(rot_q)

    rect = box(-w / 2.0, -d / 2.0, w / 2.0, d / 2.0)
    rect = rotate(rect, yaw_deg, origin=(0.0, 0.0), use_radians=False)
    rect = translate(rect, xoff=x, yoff=z)
    rect = largest_polygon(rect.buffer(0))

    if rect is None or rect.area <= 1e-12:
        raise ValueError("Invalid object footprint polygon.")

    return rect, yaw_deg


def polygon_to_mm_coords(poly: Polygon) -> list[list[int]]:
    coords = list(poly.exterior.coords)
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [[mm(x), mm(y)] for x, y in coords]


def object_fully_inside_room(room_rect_local: Polygon, obj_poly_local: Polygon, eps_area: float) -> bool:
    """
    Strict inside test:
    any area outside the room rectangle -> reject object
    """
    outside = obj_poly_local.difference(room_rect_local)
    return outside.is_empty or float(outside.area) <= eps_area


def aabb_may_overlap(
    a_bounds: tuple[float, float, float, float],
    b_bounds: tuple[float, float, float, float],
) -> bool:
    ax1, ay1, ax2, ay2 = a_bounds
    bx1, by1, bx2, by2 = b_bounds
    return not (ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1)


# ============================================================
# Candidate object
# ============================================================

@dataclass
class Candidate:
    source_index: int
    source_jid: str | None
    room_type: str | None

    center_x_local_m: float
    center_y_local_m: float
    width_m: float
    length_m: float
    rotation_local_deg: float

    bottom_y_m: float
    top_y_m: float
    area_m2: float

    score: float = 0.0

    poly_local: Polygon = field(repr=False, compare=False, default=None)
    bounds_local: tuple[float, float, float, float] = field(repr=False, compare=False, default=None)


def candidate_score(area_m2: float, bottom_y_m: float) -> float:
    """
    Deterministic score for conflict resolution.

    We strongly prefer larger footprints.
    We slightly prefer lower objects.
    """
    return 1000.0 * area_m2 - 10.0 * bottom_y_m


# ============================================================
# Conflict graph + selection
# ============================================================

def exact_intersection_area(a: Candidate, b: Candidate) -> float:
    if not aabb_may_overlap(a.bounds_local, b.bounds_local):
        return 0.0
    inter = a.poly_local.intersection(b.poly_local)
    if inter.is_empty:
        return 0.0
    return float(inter.area)


def build_conflicts(
    candidates: list[Candidate],
    eps_intersection_m2: float,
) -> tuple[list[tuple[int, int]], float]:
    conflicts: list[tuple[int, int]] = []
    max_intersection = 0.0

    n = len(candidates)
    for i in range(n):
        for j in range(i + 1, n):
            inter_area = exact_intersection_area(candidates[i], candidates[j])
            max_intersection = max(max_intersection, inter_area)
            if inter_area > eps_intersection_m2:
                conflicts.append((i, j))

    return conflicts, max_intersection


def greedy_select(candidates: list[Candidate], conflicts: list[tuple[int, int]]) -> list[int]:
    neighbors: dict[int, set[int]] = {i: set() for i in range(len(candidates))}
    for i, j in conflicts:
        neighbors[i].add(j)
        neighbors[j].add(i)

    order = sorted(
        range(len(candidates)),
        key=lambda i: (-candidates[i].score, candidates[i].source_index),
    )

    selected: list[int] = []
    selected_set: set[int] = set()

    for i in order:
        if all(j not in selected_set for j in neighbors[i]):
            selected.append(i)
            selected_set.add(i)

    return sorted(selected)


def exact_select_with_ilp(
    candidates: list[Candidate],
    conflicts: list[tuple[int, int]],
    time_limit_s: int,
) -> list[int]:
    if pulp is None:
        return greedy_select(candidates, conflicts)

    problem = pulp.LpProblem("strict_clean_layout_selection", pulp.LpMaximize)

    x = {
        i: pulp.LpVariable(f"x_{i}", lowBound=0, upBound=1, cat="Binary")
        for i in range(len(candidates))
    }

    problem += pulp.lpSum(candidates[i].score * x[i] for i in range(len(candidates)))

    for i, j in conflicts:
        problem += x[i] + x[j] <= 1

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_s)
    status = problem.solve(solver)
    status_str = pulp.LpStatus.get(status, "Unknown")

    if status_str not in {"Optimal", "Not Solved", "Undefined", "Integer Feasible"}:
        return greedy_select(candidates, conflicts)

    selected = []
    for i in range(len(candidates)):
        val = pulp.value(x[i])
        if val is not None and val > 0.5:
            selected.append(i)

    if not selected:
        return greedy_select(candidates, conflicts)

    return sorted(selected)


# ============================================================
# Scene conversion
# ============================================================

def convert_scene(
    example: dict[str, Any],
    keep_jid: bool,
    min_area_m2: float,
    min_rectangularity: float,
    eps_inside_m2: float,
    eps_intersection_m2: float,
    min_kept_objects: int,
    min_keep_ratio: float,
    ilp_time_limit_s: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    scene = example["scene"]
    bounds_bottom = scene["bounds_bottom"]
    objects = scene["objects"]

    stats = {
        "file_id": example.get("file_id"),
        "room_type": example.get("room_type"),
        "n_original_objects": len(objects),
        "n_rejected_invalid_geom": 0,
        "n_rejected_small": 0,
        "n_rejected_outside_room": 0,
        "n_candidates": 0,
        "n_conflicts_before": 0,
        "max_pair_intersection_m2_before": 0.0,
        "n_kept_objects": 0,
        "keep_ratio": 0.0,
        "rectangularity": 0.0,
        "selection_method": "ilp" if pulp is not None else "greedy_fallback",
        "reject_reason": None,
    }

    try:
        room_poly_world = build_room_polygon_xz(bounds_bottom)
    except Exception as e:
        stats["reject_reason"] = f"invalid_room_polygon: {e}"
        return None, stats

    try:
        (
            room_rect_world,
            room_angle_deg,
            room_width_m,
            room_length_m,
            to_local_geom,
            to_local_point,
        ) = make_room_local_frame(room_poly_world)
    except Exception as e:
        stats["reject_reason"] = f"invalid_min_rotated_rectangle: {e}"
        return None, stats

    rectangularity = float(room_poly_world.area) / float(room_rect_world.area)
    stats["rectangularity"] = rectangularity

    if rectangularity < min_rectangularity:
        stats["reject_reason"] = "room_not_rectangular_enough"
        return None, stats

    room_rect_local = box(0.0, 0.0, room_width_m, room_length_m)

    candidates: list[Candidate] = []

    for idx, obj in enumerate(objects, start=1):
        try:
            obj_poly_world, obj_yaw_world_deg = footprint_polygon_xz(
                obj["size"],
                obj["pos"],
                obj["rot"],
            )
        except Exception:
            stats["n_rejected_invalid_geom"] += 1
            continue

        area_m2 = float(obj_poly_world.area)
        if area_m2 < min_area_m2:
            stats["n_rejected_small"] += 1
            continue

        obj_poly_local = to_local_geom(obj_poly_world)
        obj_poly_local = largest_polygon(obj_poly_local.buffer(0))
        if obj_poly_local is None or obj_poly_local.area <= 1e-12:
            stats["n_rejected_invalid_geom"] += 1
            continue

        if not object_fully_inside_room(room_rect_local, obj_poly_local, eps_area=eps_inside_m2):
            stats["n_rejected_outside_room"] += 1
            continue

        pos = obj["pos"]
        size = obj["size"]

        cx_local, cy_local = to_local_point(float(pos[0]), float(pos[2]))
        rot_local_deg = wrap_deg(obj_yaw_world_deg - room_angle_deg)

        bottom_y_m = float(pos[1]) - float(size[1]) / 2.0
        top_y_m = float(pos[1]) + float(size[1]) / 2.0

        cand = Candidate(
            source_index=idx,
            source_jid=obj.get("jid"),
            room_type=example.get("room_type"),
            center_x_local_m=cx_local,
            center_y_local_m=cy_local,
            width_m=float(size[0]),
            length_m=float(size[2]),
            rotation_local_deg=rot_local_deg,
            bottom_y_m=bottom_y_m,
            top_y_m=top_y_m,
            area_m2=float(obj_poly_local.area),
            poly_local=obj_poly_local,
            bounds_local=tuple(map(float, obj_poly_local.bounds)),
        )
        cand.score = candidate_score(area_m2=cand.area_m2, bottom_y_m=cand.bottom_y_m)
        candidates.append(cand)

    stats["n_candidates"] = len(candidates)

    if not candidates:
        stats["reject_reason"] = "no_candidates"
        return None, stats

    conflicts, max_inter_before = build_conflicts(
        candidates=candidates,
        eps_intersection_m2=eps_intersection_m2,
    )
    stats["n_conflicts_before"] = len(conflicts)
    stats["max_pair_intersection_m2_before"] = max_inter_before

    selected_idx = exact_select_with_ilp(
        candidates=candidates,
        conflicts=conflicts,
        time_limit_s=ilp_time_limit_s,
    )
    selected = [candidates[i] for i in selected_idx]

    stats["n_kept_objects"] = len(selected)
    stats["keep_ratio"] = len(selected) / max(1, len(candidates))

    if len(selected) < min_kept_objects:
        stats["reject_reason"] = "too_few_kept_objects"
        return None, stats

    if stats["keep_ratio"] < min_keep_ratio:
        stats["reject_reason"] = "keep_ratio_too_low"
        return None, stats

    # Final hard verification: no kept object may be outside the room
    for c in selected:
        if not object_fully_inside_room(room_rect_local, c.poly_local, eps_area=eps_inside_m2):
            stats["reject_reason"] = "residual_object_outside_room_after_selection"
            return None, stats

    # Final hard verification: zero overlap among kept objects
    residual_conflicts, residual_max_inter = build_conflicts(
        candidates=selected,
        eps_intersection_m2=eps_intersection_m2,
    )
    if residual_conflicts:
        stats["reject_reason"] = f"residual_overlap_after_selection(max={residual_max_inter:.12f})"
        return None, stats

    selected = sorted(
        selected,
        key=lambda c: (c.center_x_local_m, c.center_y_local_m, c.source_index),
    )

    equipment = []
    for out_idx, c in enumerate(selected, start=1):
        item = {
            "tag": f"OBJ_{out_idx:04d}",
            "type_name": "generic_object",
            "center_x_mm": mm(c.center_x_local_m),
            "center_y_mm": mm(c.center_y_local_m),
            "width_mm": max(1, mm(c.width_m)),
            "length_mm": max(1, mm(c.length_m)),
            "rotation_deg": float(c.rotation_local_deg),
            "source_room_type": c.room_type,
            "source_bottom_y_m": float(c.bottom_y_m),
            "source_top_y_m": float(c.top_y_m),
            "selection_score": float(c.score),
        }
        if keep_jid:
            item["source_jid"] = c.source_jid
        equipment.append(item)

    out = {
        "source_dataset": "SSR-3DFRONT",
        "file_id": example.get("file_id"),
        "room_type": example.get("room_type"),
        "n_objects_before_cleaning": len(objects),
        "n_objects_after_cleaning": len(equipment),
        "splits": example.get("splits", []),
        "module_boundary": {
            "width_mm": mm(room_width_m),
            "length_mm": mm(room_length_m),
        },
        "boundary_polygon_mm": [
            [0, 0],
            [mm(room_width_m), 0],
            [mm(room_width_m), mm(room_length_m)],
            [0, mm(room_length_m)],
        ],
        "equipment": equipment,
        "cleaning": {
            "rule": "strict_zero_overlap_and_strict_inside_minimum_rotated_rectangle",
            "room_angle_deg_world": float(room_angle_deg),
            "rectangularity": float(rectangularity),
            "min_area_m2": float(min_area_m2),
            "min_rectangularity": float(min_rectangularity),
            "eps_inside_m2": float(eps_inside_m2),
            "eps_intersection_m2": float(eps_intersection_m2),
            "selection_method": stats["selection_method"],
            "n_candidates": stats["n_candidates"],
            "n_conflicts_before": stats["n_conflicts_before"],
            "max_pair_intersection_m2_before": stats["max_pair_intersection_m2_before"],
            "keep_ratio": stats["keep_ratio"],
        },
    }

    return out, stats


# ============================================================
# Export split
# ============================================================

def export_split(
    split_name: str,
    output_root: Path,
    keep_jid: bool,
    min_area_m2: float,
    min_rectangularity: float,
    eps_inside_m2: float,
    eps_intersection_m2: float,
    min_kept_objects: int,
    min_keep_ratio: float,
    ilp_time_limit_s: int,
):
    ds = load_dataset("gradient-spaces/SSR-3DFRONT", split=split_name)

    split_dir = output_root / split_name
    split_dir.mkdir(parents=True, exist_ok=True)

    manifest_clean = []
    manifest_rejected = []

    for i, ex in enumerate(tqdm(ds, desc=f"Converting {split_name}")):
        layout, stats = convert_scene(
            example=ex,
            keep_jid=keep_jid,
            min_area_m2=min_area_m2,
            min_rectangularity=min_rectangularity,
            eps_inside_m2=eps_inside_m2,
            eps_intersection_m2=eps_intersection_m2,
            min_kept_objects=min_kept_objects,
            min_keep_ratio=min_keep_ratio,
            ilp_time_limit_s=ilp_time_limit_s,
        )

        file_id = ex.get("file_id") or f"{split_name}_{i:06d}"

        if layout is None:
            manifest_rejected.append(stats)
            continue

        out_path = split_dir / f"{file_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(layout, f, indent=2)

        manifest_clean.append({
            "file_id": file_id,
            "path": out_path.name,
            "room_type": ex.get("room_type"),
            "n_objects_before_cleaning": layout["n_objects_before_cleaning"],
            "n_objects_after_cleaning": layout["n_objects_after_cleaning"],
            "rectangularity": layout["cleaning"]["rectangularity"],
            "keep_ratio": layout["cleaning"]["keep_ratio"],
            "n_conflicts_before": layout["cleaning"]["n_conflicts_before"],
            "max_pair_intersection_m2_before": layout["cleaning"]["max_pair_intersection_m2_before"],
        })

    with open(split_dir / "_manifest_clean.json", "w", encoding="utf-8") as f:
        json.dump(manifest_clean, f, indent=2)

    with open(split_dir / "_manifest_rejected.json", "w", encoding="utf-8") as f:
        json.dump(manifest_rejected, f, indent=2)

    summary = {
        "split": split_name,
        "n_clean": len(manifest_clean),
        "n_rejected": len(manifest_rejected),
        "clean_ratio": len(manifest_clean) / max(1, len(manifest_clean) + len(manifest_rejected)),
        "selection_method": "ilp" if pulp is not None else "greedy_fallback",
        "params": {
            "min_area_m2": min_area_m2,
            "min_rectangularity": min_rectangularity,
            "eps_inside_m2": eps_inside_m2,
            "eps_intersection_m2": eps_intersection_m2,
            "min_kept_objects": min_kept_objects,
            "min_keep_ratio": min_keep_ratio,
            "ilp_time_limit_s": ilp_time_limit_s,
        },
    }

    with open(split_dir / "_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--keep_jid", action="store_true")

    parser.add_argument("--min_area_m2", type=float, default=0.04)
    parser.add_argument("--min_rectangularity", type=float, default=0.85)
    parser.add_argument("--eps_inside_m2", type=float, default=1e-9)
    parser.add_argument("--eps_intersection_m2", type=float, default=1e-9)
    parser.add_argument("--min_kept_objects", type=int, default=3)
    parser.add_argument("--min_keep_ratio", type=float, default=0.50)
    parser.add_argument("--ilp_time_limit_s", type=int, default=20)

    parser.add_argument(
        "--splits",
        nargs="+",
        default=["train", "validation", "test"],
        help="HF splits to export",
    )
    args = parser.parse_args()

    out_root = Path(args.output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    split_name_map = {
        "train": "train",
        "validation": "val",
        "val": "val",
        "test": "test",
    }

    for split in args.splits:
        hf_split = split_name_map[split]
        export_split(
            split_name=hf_split,
            output_root=out_root,
            keep_jid=args.keep_jid,
            min_area_m2=args.min_area_m2,
            min_rectangularity=args.min_rectangularity,
            eps_inside_m2=args.eps_inside_m2,
            eps_intersection_m2=args.eps_intersection_m2,
            min_kept_objects=args.min_kept_objects,
            min_keep_ratio=args.min_keep_ratio,
            ilp_time_limit_s=args.ilp_time_limit_s,
        )


if __name__ == "__main__":
    main()