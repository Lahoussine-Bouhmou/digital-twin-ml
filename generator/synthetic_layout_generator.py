from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union


# ============================================================
# Data structures
# ============================================================

@dataclass
class EquipmentTypeSpec:
    name: str
    category: str
    width_range_mm: tuple[int, int]
    length_range_mm: tuple[int, int]
    height_range_mm: tuple[int, int]
    count_range: tuple[int, int]
    allowed_angles_deg: list[int]
    wall_clearance_mm: int
    preferred_zones: list[str] = field(default_factory=lambda: ["center"])
    aspect_bias: str = "any"   # "horizontal", "vertical", "any"


@dataclass
class PlacedEquipment:
    tag: str
    type_name: str
    category: str
    center_x_mm: float
    center_y_mm: float
    width_mm: float
    length_mm: float
    height_mm: float
    rotation_deg: float
    wall_clearance_mm: float
    preferred_zones: list[str]

    def polygon(self) -> Polygon:
        rect = box(
            -self.width_mm / 2.0,
            -self.length_mm / 2.0,
            self.width_mm / 2.0,
            self.length_mm / 2.0,
        )
        rect = affinity.rotate(rect, self.rotation_deg, origin=(0, 0), use_radians=False)
        rect = affinity.translate(rect, xoff=self.center_x_mm, yoff=self.center_y_mm)
        return rect


# ============================================================
# Config v0
# ============================================================

DEFAULT_SPECS = [
    EquipmentTypeSpec(
        name="LPU",  # large process unit
        category="large_process",
        width_range_mm=(5000, 12000),
        length_range_mm=(2500, 5000),
        height_range_mm=(2000, 4500),
        count_range=(1, 3),
        allowed_angles_deg=[0, 90],
        wall_clearance_mm=1200,
        preferred_zones=["north", "center", "south"],
        aspect_bias="horizontal",
    ),
    EquipmentTypeSpec(
        name="VES",
        category="vessel",
        width_range_mm=(1800, 3500),
        length_range_mm=(1800, 3500),
        height_range_mm=(2500, 6000),
        count_range=(1, 4),
        allowed_angles_deg=[0, 45, 90, 135],
        wall_clearance_mm=1000,
        preferred_zones=["south", "east", "west"],
        aspect_bias="any",
    ),
    EquipmentTypeSpec(
        name="UTL",
        category="utility",
        width_range_mm=(1800, 4500),
        length_range_mm=(1200, 3000),
        height_range_mm=(1800, 3500),
        count_range=(1, 4),
        allowed_angles_deg=[0, 90],
        wall_clearance_mm=800,
        preferred_zones=["east", "west", "center"],
        aspect_bias="horizontal",
    ),
    EquipmentTypeSpec(
        name="CTL",
        category="control",
        width_range_mm=(1200, 2800),
        length_range_mm=(1200, 2800),
        height_range_mm=(1800, 2800),
        count_range=(1, 2),
        allowed_angles_deg=[0, 90],
        wall_clearance_mm=1200,
        preferred_zones=["northwest", "northeast"],
        aspect_bias="any",
    ),
    EquipmentTypeSpec(
        name="HAZ",
        category="hazardous",
        width_range_mm=(1500, 3500),
        length_range_mm=(1500, 3500),
        height_range_mm=(1800, 3200),
        count_range=(1, 3),
        allowed_angles_deg=[0, 45, 90, 135],
        wall_clearance_mm=1500,
        preferred_zones=["southwest", "southeast"],
        aspect_bias="any",
    ),
    EquipmentTypeSpec(
        name="SRV",
        category="service",
        width_range_mm=(1000, 2200),
        length_range_mm=(1000, 2200),
        height_range_mm=(1500, 2500),
        count_range=(1, 4),
        allowed_angles_deg=[0, 90],
        wall_clearance_mm=700,
        preferred_zones=["center", "east", "west"],
        aspect_bias="any",
    ),
]

# Distance minimale entre catégories
PAIRWISE_MIN_DIST_MM = {
    ("large_process", "large_process"): 1800,
    ("large_process", "vessel"): 1800,
    ("large_process", "utility"): 1500,
    ("large_process", "control"): 3500,
    ("large_process", "hazardous"): 3000,
    ("large_process", "service"): 1200,

    ("vessel", "vessel"): 1400,
    ("vessel", "utility"): 1200,
    ("vessel", "control"): 3000,
    ("vessel", "hazardous"): 2500,
    ("vessel", "service"): 1200,

    ("utility", "utility"): 1000,
    ("utility", "control"): 2500,
    ("utility", "hazardous"): 2200,
    ("utility", "service"): 900,

    ("control", "control"): 1500,
    ("control", "hazardous"): 4500,
    ("control", "service"): 1200,

    ("hazardous", "hazardous"): 2500,
    ("hazardous", "service"): 1800,

    ("service", "service"): 800,
}

SCENARIO_TEMPLATES = [
    {
        "name": "compact_module",
        "module_w_range_mm": (18000, 26000),
        "module_l_range_mm": (16000, 24000),
        "corridor_width_mm": 1800,
        "equipment_counts": {
            "LPU": (1, 2),
            "VES": (1, 3),
            "UTL": (1, 3),
            "CTL": (1, 1),
            "HAZ": (1, 2),
            "SRV": (1, 3),
        },
    },
    {
        "name": "medium_process_module",
        "module_w_range_mm": (22000, 32000),
        "module_l_range_mm": (18000, 28000),
        "corridor_width_mm": 2200,
        "equipment_counts": {
            "LPU": (2, 3),
            "VES": (2, 4),
            "UTL": (2, 4),
            "CTL": (1, 2),
            "HAZ": (1, 2),
            "SRV": (2, 4),
        },
    },
]


# ============================================================
# Generator
# ============================================================

class StrongSyntheticLayoutGenerator:
    def __init__(self, specs=None, pairwise_rules=None, templates=None, seed: int = 42):
        self.specs = specs or DEFAULT_SPECS
        self.spec_by_name = {s.name: s for s in self.specs}
        self.pairwise_rules = pairwise_rules or PAIRWISE_MIN_DIST_MM
        self.templates = templates or SCENARIO_TEMPLATES
        self.rng = random.Random(seed)

    # ------------------------------
    # Utility geometry
    # ------------------------------
    def _pair_min_dist(self, cat_a: str, cat_b: str) -> float:
        key = tuple(sorted((cat_a, cat_b)))
        return float(self.pairwise_rules.get(key, 800))

    def _make_boundary(self, width_mm: float, length_mm: float) -> Polygon:
        return box(0, 0, width_mm, length_mm)

    def _make_zones(self, width_mm: float, length_mm: float) -> dict[str, Polygon]:
        w = width_mm
        l = length_mm
        zones = {
            "west": box(0, 0, 0.35 * w, l),
            "east": box(0.65 * w, 0, w, l),
            "south": box(0, 0, w, 0.35 * l),
            "north": box(0, 0.65 * l, w, l),
            "center": box(0.30 * w, 0.30 * l, 0.70 * w, 0.70 * l),
            "northwest": box(0, 0.60 * l, 0.40 * w, l),
            "northeast": box(0.60 * w, 0.60 * l, w, l),
            "southwest": box(0, 0, 0.40 * w, 0.40 * l),
            "southeast": box(0.60 * w, 0, w, 0.40 * l),
        }
        return zones

    def _make_corridors(self, width_mm: float, length_mm: float, corridor_width_mm: float):
        # Un couloir horizontal et un vertical, volontairement simples mais utiles
        cx = width_mm / 2.0
        cy = length_mm / 2.0
        cw = corridor_width_mm

        horizontal = box(0, cy - cw / 2.0, width_mm, cy + cw / 2.0)
        vertical = box(cx - cw / 2.0, 0, cx + cw / 2.0, length_mm)
        return [horizontal, vertical]

    def _sample_dimensions(self, spec: EquipmentTypeSpec):
        w = self.rng.randint(*spec.width_range_mm)
        l = self.rng.randint(*spec.length_range_mm)
        h = self.rng.randint(*spec.height_range_mm)

        if spec.aspect_bias == "horizontal" and l > w:
            w, l = l, w
        elif spec.aspect_bias == "vertical" and w > l:
            w, l = l, w

        return float(w), float(l), float(h)

    def _sample_angle(self, spec: EquipmentTypeSpec):
        return float(self.rng.choice(spec.allowed_angles_deg))

    def _sample_point_in_zone(self, zone: Polygon):
        minx, miny, maxx, maxy = zone.bounds
        for _ in range(100):
            x = self.rng.uniform(minx, maxx)
            y = self.rng.uniform(miny, maxy)
            p = Point(x, y)
            if zone.contains(p):
                return x, y
        return zone.centroid.x, zone.centroid.y

    def _tag(self, spec_name: str, idx: int) -> str:
        return f"{spec_name}-{idx:03d}"

    # ------------------------------
    # Energy / validity
    # ------------------------------
    def _wall_clearance_penalty(self, obj: PlacedEquipment, boundary: Polygon) -> float:
        inner = boundary.buffer(-obj.wall_clearance_mm)
        poly = obj.polygon()

        if inner.is_empty:
            return 1e9
        if poly.within(inner):
            return 0.0

        # forte pénalité si l’objet n’est pas dans la zone intérieure
        diff_area = poly.difference(inner).area
        return 1000.0 + 0.1 * diff_area

    def _corridor_penalty(self, obj: PlacedEquipment, corridors: list[Polygon]) -> float:
        poly = obj.polygon()
        penalty = 0.0
        for c in corridors:
            inter = poly.intersection(c)
            if not inter.is_empty:
                penalty += 2000.0 + 0.2 * inter.area
        return penalty

    def _zone_penalty(self, obj: PlacedEquipment, zones: dict[str, Polygon]) -> float:
        c = Point(obj.center_x_mm, obj.center_y_mm)
        for z in obj.preferred_zones:
            if z in zones and zones[z].contains(c):
                return 0.0
        return 500.0

    def _pair_penalty(self, a: PlacedEquipment, b: PlacedEquipment) -> float:
        pa = a.polygon()
        pb = b.polygon()

        if pa.intersects(pb):
            inter_area = pa.intersection(pb).area
            if inter_area > 1e-6:
                return 5e5 + 2.0 * inter_area

        dist = pa.distance(pb)
        req = self._pair_min_dist(a.category, b.category)
        if dist >= req:
            return 0.0

        missing = req - dist
        return 1000.0 + 3.0 * missing

    def _layout_energy(
        self,
        objects: list[PlacedEquipment],
        boundary: Polygon,
        corridors: list[Polygon],
        zones: dict[str, Polygon],
    ) -> float:
        e = 0.0
        for obj in objects:
            e += self._wall_clearance_penalty(obj, boundary)
            e += self._corridor_penalty(obj, corridors)
            e += self._zone_penalty(obj, zones)

            # très grosse pénalité si hors module
            if not obj.polygon().within(boundary):
                outside_area = obj.polygon().difference(boundary).area
                e += 1e6 + outside_area

        for i in range(len(objects)):
            for j in range(i + 1, len(objects)):
                e += self._pair_penalty(objects[i], objects[j])

        return e

    def _is_valid(
        self,
        objects: list[PlacedEquipment],
        boundary: Polygon,
        corridors: list[Polygon],
        zones: dict[str, Polygon],
    ) -> bool:
        return self._layout_energy(objects, boundary, corridors, zones) < 1e-6

    # ------------------------------
    # Construction
    # ------------------------------
    def _sample_equipment_list(self, template: dict[str, Any]) -> list[EquipmentTypeSpec]:
        chosen: list[EquipmentTypeSpec] = []
        for spec_name, count_range in template["equipment_counts"].items():
            spec = self.spec_by_name[spec_name]
            lo, hi = count_range
            n = self.rng.randint(lo, hi)
            chosen.extend([spec] * n)

        # placer d’abord les plus gros
        self.rng.shuffle(chosen)
        chosen.sort(
            key=lambda s: (s.width_range_mm[1] * s.length_range_mm[1]),
            reverse=True,
        )
        return chosen

    def _best_candidate_for_object(
        self,
        spec: EquipmentTypeSpec,
        tag: str,
        already: list[PlacedEquipment],
        boundary: Polygon,
        corridors: list[Polygon],
        zones: dict[str, Polygon],
        n_candidates: int = 80,
    ) -> PlacedEquipment | None:
        best_obj = None
        best_energy = float("inf")

        candidate_zones = [zones[z] for z in spec.preferred_zones if z in zones]
        if not candidate_zones:
            candidate_zones = [boundary]

        for _ in range(n_candidates):
            zone = self.rng.choice(candidate_zones)
            cx, cy = self._sample_point_in_zone(zone)
            w, l, h = self._sample_dimensions(spec)
            angle = self._sample_angle(spec)

            cand = PlacedEquipment(
                tag=tag,
                type_name=spec.name,
                category=spec.category,
                center_x_mm=cx,
                center_y_mm=cy,
                width_mm=w,
                length_mm=l,
                height_mm=h,
                rotation_deg=angle,
                wall_clearance_mm=spec.wall_clearance_mm,
                preferred_zones=list(spec.preferred_zones),
            )

            e = self._layout_energy(already + [cand], boundary, corridors, zones)
            if e < best_energy:
                best_energy = e
                best_obj = cand

                if e < 1e-6:
                    return cand

        return best_obj

    def _construct_layout(
        self,
        specs_to_place: list[EquipmentTypeSpec],
        boundary: Polygon,
        corridors: list[Polygon],
        zones: dict[str, Polygon],
    ) -> list[PlacedEquipment]:
        placed: list[PlacedEquipment] = []
        counters: dict[str, int] = {}

        for spec in specs_to_place:
            counters.setdefault(spec.name, 0)
            counters[spec.name] += 1
            tag = self._tag(spec.name, counters[spec.name])

            cand = self._best_candidate_for_object(
                spec=spec,
                tag=tag,
                already=placed,
                boundary=boundary,
                corridors=corridors,
                zones=zones,
                n_candidates=120,
            )
            if cand is None:
                raise RuntimeError("Failed to place object.")
            placed.append(cand)

        return placed

    # ------------------------------
    # Local repair / optimization
    # ------------------------------
    def _perturb_object(self, obj: PlacedEquipment, width_mm: float, length_mm: float) -> PlacedEquipment:
        new = PlacedEquipment(**asdict(obj))

        move_scale = max(width_mm, length_mm) * 0.04
        new.center_x_mm += self.rng.uniform(-move_scale, move_scale)
        new.center_y_mm += self.rng.uniform(-move_scale, move_scale)

        if self.rng.random() < 0.35:
            new.rotation_deg = self.rng.choice([obj.rotation_deg, 0, 45, 90, 135])

        return new

    def _repair_layout(
        self,
        objects: list[PlacedEquipment],
        boundary: Polygon,
        corridors: list[Polygon],
        zones: dict[str, Polygon],
        iters: int = 1200,
    ) -> list[PlacedEquipment]:
        current = [PlacedEquipment(**asdict(o)) for o in objects]
        current_e = self._layout_energy(current, boundary, corridors, zones)

        width_mm = boundary.bounds[2] - boundary.bounds[0]
        length_mm = boundary.bounds[3] - boundary.bounds[1]

        temperature = 2500.0

        for _ in range(iters):
            idx = self.rng.randrange(len(current))
            trial = [PlacedEquipment(**asdict(o)) for o in current]
            trial[idx] = self._perturb_object(trial[idx], width_mm, length_mm)

            trial_e = self._layout_energy(trial, boundary, corridors, zones)
            delta = trial_e - current_e

            if delta <= 0 or self.rng.random() < math.exp(-delta / max(temperature, 1e-6)):
                current = trial
                current_e = trial_e

            temperature *= 0.995

            if current_e < 1e-6:
                break

        return current

    # ------------------------------
    # Public API
    # ------------------------------
    def generate_layout(self, max_restarts: int = 25) -> dict:
        template = self.rng.choice(self.templates)

        for restart in range(max_restarts):
            width_mm = self.rng.randint(*template["module_w_range_mm"])
            length_mm = self.rng.randint(*template["module_l_range_mm"])
            boundary = self._make_boundary(width_mm, length_mm)
            zones = self._make_zones(width_mm, length_mm)
            corridors = self._make_corridors(width_mm, length_mm, template["corridor_width_mm"])

            specs_to_place = self._sample_equipment_list(template)

            try:
                placed = self._construct_layout(specs_to_place, boundary, corridors, zones)
                placed = self._repair_layout(placed, boundary, corridors, zones)

                energy = self._layout_energy(placed, boundary, corridors, zones)
                if energy < 1e-3:
                    return self._to_layout_json(
                        placed=placed,
                        width_mm=width_mm,
                        length_mm=length_mm,
                        template_name=template["name"],
                        corridors=corridors,
                    )

            except Exception:
                pass

        raise RuntimeError("Failed to generate a valid layout after several restarts.")

    def _to_layout_json(
        self,
        placed: list[PlacedEquipment],
        width_mm: int,
        length_mm: int,
        template_name: str,
        corridors: list[Polygon],
    ) -> dict:
        equipment = []
        for obj in placed:
            equipment.append(
                {
                    "tag": obj.tag,
                    "type_name": obj.type_name,
                    "category": obj.category,
                    "center_x_mm": int(round(obj.center_x_mm)),
                    "center_y_mm": int(round(obj.center_y_mm)),
                    "width_mm": int(round(obj.width_mm)),
                    "length_mm": int(round(obj.length_mm)),
                    "height_mm": int(round(obj.height_mm)),
                    "rotation_deg": float(obj.rotation_deg),
                }
            )

        corridor_boxes = []
        for c in corridors:
            minx, miny, maxx, maxy = c.bounds
            corridor_boxes.append(
                {
                    "x_min_mm": int(round(minx)),
                    "y_min_mm": int(round(miny)),
                    "x_max_mm": int(round(maxx)),
                    "y_max_mm": int(round(maxy)),
                }
            )

        return {
            "source_dataset": "synthetic_v0_rules_based",
            "generator_version": "v0_strong",
            "template_name": template_name,
            "module_boundary": {
                "width_mm": width_mm,
                "length_mm": length_mm,
            },
            "equipment": equipment,
            "reserved_corridors": corridor_boxes,
        }

    def generate_dataset(self, n: int, output_dir: str | Path):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest = []
        for i in range(n):
            layout = self.generate_layout()
            file_id = f"synthetic_{i:06d}"
            out_path = output_dir / f"{file_id}.json"

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(layout, f, indent=2)

            manifest.append(
                {
                    "file_id": file_id,
                    "path": out_path.name,
                    "template_name": layout["template_name"],
                    "n_objects": len(layout["equipment"]),
                    "module_boundary": layout["module_boundary"],
                }
            )

            if (i + 1) % 100 == 0:
                print(f"Generated {i + 1} / {n}")

        with open(output_dir / "_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)


def main():
    gen = StrongSyntheticLayoutGenerator(seed=42)
    gen.generate_dataset(
        n=20,
        output_dir="generator/synthetic_layouts_v0/train",
    )


if __name__ == "__main__":
    main()