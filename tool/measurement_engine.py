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
        self.mod_w = (module_boundary or {}).get("width_mm", 0) or 0
        self.mod_l = (module_boundary or {}).get("length_mm", 0) or 0

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
        """Build MeasurementRef for a boundary edge."""
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
        """Given a click point, determine the nearest boundary edge."""
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

        Edge-to-edge distances are always nearest-edge to nearest-edge,
        clamped to 0 when the two bounding boxes overlap on that axis
        (i.e. the smallest possible edge-to-edge distance). Axes with
        zero clearance emit no dimension line.
        """
        r = MeasurementResult(ref_a, ref_b)

        r.dx_center = abs(ref_b.center_x - ref_a.center_x)
        r.dy_center = abs(ref_b.center_y - ref_a.center_y)
        r.direct = math.sqrt(r.dx_center ** 2 + r.dy_center ** 2)

        # Nearest-edge gap on X (negative means overlap -> clamp to 0)
        if ref_a.center_x <= ref_b.center_x:
            raw_dx = ref_b.x_min - ref_a.x_max
            x1, x2 = ref_a.x_max, ref_b.x_min
        else:
            raw_dx = ref_a.x_min - ref_b.x_max
            x1, x2 = ref_b.x_max, ref_a.x_min
        r.dx_edge = max(0.0, raw_dx)

        # Nearest-edge gap on Y
        if ref_a.center_y <= ref_b.center_y:
            raw_dy = ref_b.y_min - ref_a.y_max
            y1, y2 = ref_a.y_max, ref_b.y_min
        else:
            raw_dy = ref_a.y_min - ref_b.y_max
            y1, y2 = ref_b.y_max, ref_a.y_min
        r.dy_edge = max(0.0, raw_dy)

        y_mid = (ref_a.center_y + ref_b.center_y) / 2.0
        x_mid = (ref_a.center_x + ref_b.center_x) / 2.0

        # Only emit a line for axes with positive clearance
        if r.dx_edge > 0:
            r.line_x = ((x1, y_mid), (x2, y_mid))
        if r.dy_edge > 0:
            r.line_y = ((x_mid, y1), (x_mid, y2))

        # Direct line drawn only when both axes have clearance
        if r.dx_edge > 0 and r.dy_edge > 0:
            r.line_direct = (
                (ref_a.center_x, ref_a.center_y),
                (ref_b.center_x, ref_b.center_y),
            )

        return r
