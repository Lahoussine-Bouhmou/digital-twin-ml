from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from datasets import load_dataset


def quat_to_rotmat(q):
    """
    Quaternion [x, y, z, w] -> rotation matrix 3x3
    """
    q = np.asarray(q, dtype=np.float64)
    n = np.linalg.norm(q)
    if n == 0:
        return np.eye(3)
    q = q / n
    x, y, z, w = q

    return np.array([
        [1 - 2 * (y * y + z * z),     2 * (x * y - z * w),     2 * (x * z + y * w)],
        [    2 * (x * y + z * w), 1 - 2 * (x * x + z * z),     2 * (y * z - x * w)],
        [    2 * (x * z - y * w),     2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def box_corners(size, pos, quat):
    """
    size = [width, height, depth]
    pos  = [x, y, z]
    quat = [x, y, z, w]
    Returns 8 oriented box corners in world coordinates.
    """
    sx, sy, sz = map(float, size)
    px, py, pz = map(float, pos)

    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0

    local = np.array([
        [-hx, -hy, -hz],
        [ hx, -hy, -hz],
        [ hx,  hy, -hz],
        [-hx,  hy, -hz],
        [-hx, -hy,  hz],
        [ hx, -hy,  hz],
        [ hx,  hy,  hz],
        [-hx,  hy,  hz],
    ], dtype=np.float64)

    R = quat_to_rotmat(quat)
    world = local @ R.T
    world += np.array([px, py, pz], dtype=np.float64)
    return world


def add_box_edges(fig, corners, name="", color="black", width=3):
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]

    for a, b in edges:
        xs = [corners[a, 0], corners[b, 0]]
        ys = [corners[a, 2], corners[b, 2]]  # Z displayed as plot Y
        zs = [corners[a, 1], corners[b, 1]]  # Y(height) displayed as plot Z

        fig.add_trace(go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="lines",
            line=dict(color=color, width=width),
            name=name,
            showlegend=False,
            hoverinfo="skip",
        ))


def add_floor_polygon(fig, bounds_bottom, color="royalblue", width=5):
    pts = np.asarray(bounds_bottom, dtype=np.float64)
    if len(pts) == 0:
        return
    pts_closed = np.vstack([pts, pts[0]])

    # dataset: [x, y, z]
    # display: x <- x, y <- z, z <- y(height)
    fig.add_trace(go.Scatter3d(
        x=pts_closed[:, 0],
        y=pts_closed[:, 2],
        z=pts_closed[:, 1],
        mode="lines",
        line=dict(color=color, width=width),
        name="floor_boundary",
        showlegend=True,
    ))


def find_example_by_file_id(ds, file_id: str):
    wanted = Path(file_id).stem  # enlève ".json" si présent
    for ex in ds:
        if str(ex.get("file_id")) == wanted:
            return ex
    raise ValueError(f"file_id introuvable dans ce split: {wanted}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", type=str, default="train", choices=["train", "val", "test"])
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--file_id", type=str, default=None,
                        help="Ex: 685804c9-...-6869f22ff98a.json ou sans .json")
    parser.add_argument("--max_objects", type=int, default=40)
    parser.add_argument("--output_html", type=str, required=True)
    parser.add_argument("--floor_only", action="store_true")
    parser.add_argument("--floor_y_tol", type=float, default=0.12,
                        help="Keep only objects whose bottom is near the floor when --floor_only is used")
    parser.add_argument("--min_footprint_m2", type=float, default=0.0,
                        help="Optional footprint filter in m²")
    args = parser.parse_args()

    ds = load_dataset("gradient-spaces/SSR-3DFRONT", split=args.split)

    if args.file_id is not None:
        ex = find_example_by_file_id(ds, args.file_id)
    else:
        ex = ds[args.index]

    scene = ex["scene"]
    objects = scene["objects"]
    bounds_bottom = scene.get("bounds_bottom", [])

    fig = go.Figure()
    add_floor_polygon(fig, bounds_bottom)

    shown = 0
    skipped = 0

    for i, obj in enumerate(objects):
        size = obj["size"]      # [w, h, d]
        pos = obj["pos"]        # [x, y, z]
        rot = obj["rot"]        # quaternion [x, y, z, w]

        footprint = float(size[0]) * float(size[2])
        bottom_y = float(pos[1]) - float(size[1]) / 2.0

        if footprint < args.min_footprint_m2:
            skipped += 1
            continue

        if args.floor_only and bottom_y > args.floor_y_tol:
            skipped += 1
            continue

        corners = box_corners(size=size, pos=pos, quat=rot)
        name = obj.get("jid", f"obj_{i}")
        add_box_edges(fig, corners, name=name)

        shown += 1
        if shown >= args.max_objects:
            break

    title = (
        f"SSR-3DFRONT | split={args.split} | "
        f"file_id={ex.get('file_id')} | room_type={ex.get('room_type')} | "
        f"shown={shown} | skipped={skipped}"
    )

    fig.update_layout(
        title=title,
        scene=dict(
            xaxis_title="X (m)",
            yaxis_title="Z (m)",
            zaxis_title="Y (m, height)",
            aspectmode="data",
        ),
        margin=dict(l=0, r=0, b=0, t=40),
    )

    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_html))
    print(f"Saved: {output_html}")
    print(f"Loaded file_id: {ex.get('file_id')}")


if __name__ == "__main__":
    main()