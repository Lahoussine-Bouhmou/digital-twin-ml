from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import transforms
from matplotlib.patches import Polygon, Rectangle


def load_layout_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def draw_boundary(layout: dict, ax):
    boundary = layout.get("module_boundary", {})
    room_w = float(boundary.get("width_mm", 1.0))
    room_l = float(boundary.get("length_mm", 1.0))

    poly = layout.get("boundary_polygon_mm", [])
    if poly:
        ax.add_patch(
            Polygon(
                poly,
                closed=True,
                fill=False,
                linewidth=2.0,
                edgecolor="black",
            )
        )
    else:
        ax.add_patch(
            Rectangle(
                (0, 0),
                room_w,
                room_l,
                fill=False,
                linewidth=2.0,
                edgecolor="black",
            )
        )

    return room_w, room_l


def draw_equipment(layout: dict, ax, show_labels: bool = False):
    for obj in layout.get("equipment", []):
        cx = float(obj.get("center_x_mm", 0.0))
        cy = float(obj.get("center_y_mm", 0.0))
        w = float(obj.get("width_mm", 1.0))
        l = float(obj.get("length_mm", 1.0))
        angle = float(obj.get("rotation_deg", 0.0))

        rect = Rectangle(
            (cx - w / 2.0, cy - l / 2.0),
            w,
            l,
            fill=False,
            linewidth=1.2,
            edgecolor="tab:blue",
        )
        t = transforms.Affine2D().rotate_deg_around(cx, cy, angle) + ax.transData
        rect.set_transform(t)
        ax.add_patch(rect)

        if show_labels:
            label = obj.get("tag", "")
            ax.text(
                cx,
                cy,
                label,
                fontsize=6,
                ha="center",
                va="center",
            )


def build_title(layout: dict, fallback_name: str) -> str:
    file_id = layout.get("file_id", fallback_name)
    room_type = layout.get("room_type", "unknown")
    n_before = layout.get("n_objects_before_cleaning", layout.get("n_objects", "?"))
    n_after = layout.get("n_objects_after_cleaning", len(layout.get("equipment", [])))

    cleaning = layout.get("cleaning", {})
    rectangularity = cleaning.get("rectangularity", None)
    keep_ratio = cleaning.get("keep_ratio", None)

    parts = [
        str(file_id),
        f"room_type={room_type}",
        f"objs={n_after}/{n_before}",
    ]

    if rectangularity is not None:
        parts.append(f"rect={rectangularity:.3f}")
    if keep_ratio is not None:
        parts.append(f"keep={keep_ratio:.3f}")

    return " | ".join(parts)


def draw_layout(layout: dict, ax=None, title: str | None = None, show_labels: bool = False):
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 8))

    room_w, room_l = draw_boundary(layout, ax)
    draw_equipment(layout, ax, show_labels=show_labels)

    ax.set_xlim(0, room_w)
    ax.set_ylim(0, room_l)
    ax.set_aspect("equal")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_title(title or build_title(layout, "layout"))
    ax.grid(True, alpha=0.3)

    return ax


def list_json_files(data_root: Path, split: str) -> list[Path]:
    split_dir = data_root / split
    if not split_dir.exists():
        raise FileNotFoundError(f"Split directory not found: {split_dir}")
    files = [p for p in split_dir.glob("*.json") if not p.name.startswith("_")]
    return sorted(files)


def save_single(input_json: Path, output_png: Path, show_labels: bool):
    layout = load_layout_json(input_json)

    fig, ax = plt.subplots(figsize=(8, 8))
    draw_layout(
        layout,
        ax=ax,
        title=build_title(layout, input_json.stem),
        show_labels=show_labels,
    )
    fig.tight_layout()

    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {output_png}")


def save_grid(data_root: Path, split: str, n: int, output_png: Path, seed: int, show_labels: bool):
    files = list_json_files(data_root, split=split)
    if not files:
        raise ValueError(f"No json files found in {data_root / split}")

    rng = random.Random(seed)
    chosen = rng.sample(files, k=min(n, len(files)))

    cols = min(3, len(chosen))
    rows = math.ceil(len(chosen) / cols)

    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 5 * rows))
    if hasattr(axes, "flatten"):
        axes = axes.flatten()
    else:
        axes = [axes]

    for ax, path in zip(axes, chosen):
        layout = load_layout_json(path)
        draw_layout(
            layout,
            ax=ax,
            title=build_title(layout, path.stem),
            show_labels=show_labels,
        )

    for ax in axes[len(chosen):]:
        ax.axis("off")

    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {output_png}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_json", type=str, default=None, help="Path to one converted layout json")
    parser.add_argument("--data_root", type=str, default=None, help="Root folder containing train/ val/ test/")
    parser.add_argument("--split", type=str, default="train")
    parser.add_argument("--n", type=int, default=6, help="Number of layouts for grid mode")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--show_labels", action="store_true")
    parser.add_argument("--output_png", type=str, required=True)

    args = parser.parse_args()
    output_png = Path(args.output_png)

    if args.input_json:
        save_single(Path(args.input_json), output_png=output_png, show_labels=args.show_labels)
    else:
        if not args.data_root:
            raise ValueError("Provide either --input_json or --data_root")
        save_grid(
            Path(args.data_root),
            split=args.split,
            n=args.n,
            output_png=output_png,
            seed=args.seed,
            show_labels=args.show_labels,
        )


if __name__ == "__main__":
    main()