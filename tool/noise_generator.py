"""
noise_generator.py - Batch generation of progressive noisy layouts.

The generated sequence is progressive:
    x_1, x_2, ..., x_N
where each step is a stronger perturbation of the same clean base layout.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import equipment_editor


def _clip_abs(value: float, max_abs: float) -> float:
    if max_abs <= 0:
        return 0.0
    return max(-max_abs, min(max_abs, value))


def _sample_diffusion_component(
    rng: random.Random,
    alpha: float,
    max_abs: float,
) -> float:
    """
    Diffusion-like noise:
    fresh Gaussian noise at each step, with std increasing with alpha.
    Then clipped to [-max_abs, max_abs].
    """
    if max_abs <= 0:
        return 0.0

    sigma = alpha * float(max_abs)
    value = rng.gauss(0.0, sigma)
    return _clip_abs(value, float(max_abs))


def generate_progressive_noisy_layouts(
    layout_data: dict,
    num_examples: int,
    max_dx_mm: float,
    max_dy_mm: float,
    max_rot_deg: float,
    seed: int | None = None,
    clamp_to_boundary: bool = True,
    noise_mode: str = "linear",   # "linear" or "diffusion"
) -> list[dict]:
    """
    Generate N noisy copies of the input layout.

    Modes
    -----
    linear:
        One target perturbation per equipment is sampled once,
        then scaled with alpha=t/N.

    diffusion:
        Fresh Gaussian noise is sampled independently for each equipment
        and each step, with std increasing with alpha=t/N.
    """
    if num_examples <= 0:
        return []

    base_layout = copy.deepcopy(layout_data)
    boundary = base_layout.get("module_boundary") or {}
    equipment = base_layout.get("equipment", [])

    rng = random.Random(seed)
    noise_mode = (noise_mode or "linear").strip().lower()

    if noise_mode not in {"linear", "diffusion"}:
        raise ValueError(f"Unsupported noise_mode: {noise_mode}")

    # Used only for linear mode
    noise_targets: dict[str, dict[str, float]] = {}
    if noise_mode == "linear":
        for eq in equipment:
            tag = eq.get("tag")
            if not tag:
                continue
            noise_targets[tag] = {
                "dx_mm": rng.uniform(-float(max_dx_mm), float(max_dx_mm)),
                "dy_mm": rng.uniform(-float(max_dy_mm), float(max_dy_mm)),
                "rot_deg": rng.uniform(-float(max_rot_deg), float(max_rot_deg)),
            }

    outputs: list[dict] = []

    for step_idx in range(1, num_examples + 1):
        alpha = step_idx / float(num_examples)
        layout_copy = copy.deepcopy(base_layout)

        applied_noise: dict[str, dict[str, float]] = {}

        for eq in layout_copy.get("equipment", []):
            tag = eq.get("tag")
            if not tag:
                continue

            if noise_mode == "linear":
                target = noise_targets[tag]
                dx = alpha * target["dx_mm"]
                dy = alpha * target["dy_mm"]
                drot = alpha * target["rot_deg"]

            else:  # diffusion
                dx = _sample_diffusion_component(rng, alpha, float(max_dx_mm))
                dy = _sample_diffusion_component(rng, alpha, float(max_dy_mm))
                drot = _sample_diffusion_component(rng, alpha, float(max_rot_deg))

            equipment_editor.apply_noise(
                eq,
                dx_mm=dx,
                dy_mm=dy,
                drot_deg=drot,
                boundary=boundary if clamp_to_boundary else None,
            )

            applied_noise[tag] = {
                "dx_mm": round(dx, 6),
                "dy_mm": round(dy, 6),
                "rot_deg": round(drot, 6),
            }

        oob = equipment_editor.check_out_of_bounds(layout_copy)
        coll = equipment_editor.check_collisions(layout_copy)

        layout_copy["noise_metadata"] = {
            "generator": "progressive_layout_noise_v2",
            "noise_mode": noise_mode,
            "step_index": step_idx,
            "num_examples": num_examples,
            "alpha": round(alpha, 6),
            "seed": seed,
            "max_dx_mm": float(max_dx_mm),
            "max_dy_mm": float(max_dy_mm),
            "max_rot_deg": float(max_rot_deg),
            "clamp_to_boundary": bool(clamp_to_boundary),
            "num_out_of_bounds": len(oob),
            "out_of_bounds_tags": list(oob),
            "num_collisions": len(coll),
            "collision_pairs": [list(pair) for pair in coll],
        }

        # Useful later if you want the model to predict the applied noise
        layout_copy["noise_applied"] = applied_noise

        outputs.append(layout_copy)

    return outputs


def save_noisy_layouts(
    layouts: list[dict],
    output_dir: str | Path,
    base_name: str = "layout",
) -> list[Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_base = str(base_name).strip().replace(" ", "_") or "layout"
    pad = max(3, len(str(len(layouts))))

    written_files: list[Path] = []
    manifest_items: list[dict] = []

    for idx, layout in enumerate(layouts, start=1):
        filename = f"{safe_base}_noise_{idx:0{pad}d}.json"
        path = out_dir / filename

        with open(path, "w", encoding="utf-8") as f:
            json.dump(layout, f, indent=2)

        written_files.append(path)

        meta = layout.get("noise_metadata", {})
        manifest_items.append({
            "file": filename,
            "step_index": meta.get("step_index"),
            "alpha": meta.get("alpha"),
            "noise_mode": meta.get("noise_mode"),
            "num_collisions": meta.get("num_collisions"),
            "num_out_of_bounds": meta.get("num_out_of_bounds"),
        })

    manifest_path = out_dir / f"{safe_base}_manifest.json"
    manifest = {
        "base_name": safe_base,
        "num_layouts": len(layouts),
        "files": manifest_items,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return written_files