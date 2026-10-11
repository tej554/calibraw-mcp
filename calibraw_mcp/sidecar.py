"""CalibRaw sidecar serialization and deserialization conforming to CalibRaw Schema Version 1.

Specification:
- File naming: `<raw_path>.calibraw` (e.g., `IMG_4755.CR3.calibraw`)
- Format string: "CalibRaw edit sidecar"
- Schema version: 1
- Non-destructive perceptual adjustments: exposure, contrast, highlights, shadows, whites,
  blacks, temperature, tint, saturation, vibrance, clarity, dehaze, texture, sharpen,
  vignette, sigmoid, tone curves, HSL, color grading, geometry, and lens profiling.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FORMAT_IDENTIFIER = "CalibRaw edit sidecar"
SCHEMA_VERSION = 1
SIDECAR_SUFFIX = ".calibraw"
MAX_POINT_CURVE_POINTS = 16


def sidecar_path_for_raw(raw_path: str | Path) -> Path:
    """Returns the companion sidecar path `<raw_path>.calibraw`."""
    p = Path(raw_path).resolve()
    if p.name.lower().endswith(SIDECAR_SUFFIX):
        return p
    return p.with_name(p.name + SIDECAR_SUFFIX)


def default_point_curve(linear: bool = True) -> Dict[str, Any]:
    """16 slots conforming to CalibRaw PointCurve struct."""
    if linear:
        points = [[0.0, 0.0], [1.0, 1.0]] + [[1.0, 1.0]] * 14
        return {"points": points, "len": 2}
    return {"points": [[1.0, 1.0]] * 16, "len": 2}


def create_point_curve(coords: List[Tuple[float, float] | List[float]]) -> Dict[str, Any]:
    """Generates a valid CalibRaw PointCurve from a list of (x, y) coordinates."""
    if not coords or len(coords) < 2:
        return default_point_curve(linear=True)
    
    clamped_coords = []
    for pt in coords[:MAX_POINT_CURVE_POINTS]:
        x = max(0.0, min(1.0, float(pt[0])))
        y = max(0.0, min(1.0, float(pt[1])))
        clamped_coords.append([round(x, 4), round(y, 4)])
    
    length = len(clamped_coords)
    # Pad to 16 slots with [1.0, 1.0] as required by CalibRaw deserializer
    slots = clamped_coords + [[1.0, 1.0]] * (MAX_POINT_CURVE_POINTS - length)
    return {"points": slots, "len": length}


def default_sigmoid_params() -> Dict[str, Any]:
    return {
        "contrast": 1.5,
        "skew": 0.0,
        "display_white_target": 100.0,
        "display_black_target": 0.0152,
        "color_processing": "PerChannel",
        "hue_preservation": 100.0,
    }


def default_color_grading() -> Dict[str, Any]:
    return {
        "shadows": {"hue": 0.0, "saturation": 0.0, "luminance": 0.0},
        "midtones": {"hue": 0.0, "saturation": 0.0, "luminance": 0.0},
        "highlights": {"hue": 0.0, "saturation": 0.0, "luminance": 0.0},
        "global": {"hue": 0.0, "saturation": 0.0, "luminance": 0.0},
        "blending": 50.0,
        "balance": 0.0,
    }


def default_exposure_params() -> Dict[str, Any]:
    return {
        "black_point": 0.0,
        "exposure": 0.0,
        "contrast": 0.0,
        "sigmoid": default_sigmoid_params(),
        "temperature": 0.0,
        "tint": 0.0,
        "hue": 0.0,
        "saturation": 0.0,
        "vibrance": 0.0,
        "tone_curve": default_point_curve(),
        "tone_curve_red": default_point_curve(),
        "tone_curve_green": default_point_curve(),
        "tone_curve_blue": default_point_curve(),
        "chroma_denoise": 0.0,
        "luminance_denoise": 0.0,
        "denoise_detail": 50.0,
        "denoise_quality": "balanced",
        "ai_denoise_enabled": False,
        "demosaic_mode": "Reference",
        "dual_threshold": 20.0,
        "frequency_chroma": 1.0,
        "ca_red": 0.0,
        "ca_blue": 0.0,
        "highlight_method": "InpaintOpposed",
        "highlight_clip": 1.0,
        "highlight_reconstruction": 1.0,
        "highlights": 0.0,
        "shadows": 0.0,
        "whites": 0.0,
        "blacks": 0.0,
        "texture": 0.0,
        "clarity": 0.0,
        "dehaze": 0.0,
        "sharpen_amount": 40.0,
        "sharpen_radius": 1.0,
        "sharpen_detail": 25.0,
        "sharpen_masking": 0.0,
        "halation_amount": 0.0,
        "grain_amount": 0.0,
        "glow_amount": 0.0,
        "glow_radius": 50.0,
        "glow_threshold": 60.0,
        "vignette_amount": 0.0,
        "vignette_midpoint": 50.0,
        "vignette_roundness": 0.0,
        "vignette_feather": 50.0,
        "vignette_highlights": 0.0,
        "hsl_hue": [0.0] * 8,
        "hsl_saturation": [0.0] * 8,
        "hsl_luminance": [0.0] * 8,
        "point_colors": [],
        "color_grading": default_color_grading(),
    }


def default_geometry() -> Dict[str, Any]:
    return {
        "crop": [0.0, 0.0, 1.0, 1.0],
        "aspect_ratio": "original",
        "quarter_turns": 0,
        "rotation_degrees": 0.0,
        "flip_horizontal": False,
        "flip_vertical": False,
        "horizontal_transform": 0.0,
        "vertical_transform": 0.0,
    }


def default_lens() -> Dict[str, Any]:
    return {
        "enabled": False,
        "maker": "",
        "model": "",
    }


def default_masks() -> Dict[str, Any]:
    return {
        "masks": [],
        "global_effects": [],
        "selected_mask": None,
        "selected_component": None,
    }


def default_review() -> Dict[str, Any]:
    return {
        "flag": "unflagged",
        "rating": 0,
    }


def default_sidecar() -> Dict[str, Any]:
    """Generates the full default CalibRaw sidecar document."""
    return {
        "format": FORMAT_IDENTIFIER,
        "schema_version": SCHEMA_VERSION,
        "edits": {
            "exposure": default_exposure_params(),
            "geometry": default_geometry(),
            "masks": default_masks(),
            "lens": default_lens(),
            "ai_masks_need_update": False,
        },
        "review": default_review(),
        "editing_time_ms": 0,
    }


def load_sidecar(raw_path: str | Path) -> Tuple[Dict[str, Any], bool]:
    """Loads existing `.calibraw` sidecar or returns default state.
    
    Returns:
        (document_dict, file_existed_bool)
    """
    sc_path = sidecar_path_for_raw(raw_path)
    if not sc_path.exists():
        return default_sidecar(), False

    with open(sc_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    if doc.get("format") != FORMAT_IDENTIFIER:
        raise ValueError(f"Invalid format identifier: {doc.get('format')}")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema version: {doc.get('schema_version')}")

    # Ensure baseline structure is populated
    merged = default_sidecar()
    if "edits" in doc and isinstance(doc["edits"], dict):
        edits = doc["edits"]
        if "exposure" in edits and isinstance(edits["exposure"], dict):
            merged["edits"]["exposure"].update(edits["exposure"])
        if "geometry" in edits and isinstance(edits["geometry"], dict):
            merged["edits"]["geometry"].update(edits["geometry"])
        if "lens" in edits and isinstance(edits["lens"], dict):
            merged["edits"]["lens"].update(edits["lens"])
        if "masks" in edits and isinstance(edits["masks"], dict):
            merged["edits"]["masks"].update(edits["masks"])
        if "ai_masks_need_update" in edits:
            merged["edits"]["ai_masks_need_update"] = edits["ai_masks_need_update"]
    if "review" in doc and isinstance(doc["review"], dict):
        merged["review"].update(doc["review"])
    if "editing_time_ms" in doc:
        merged["editing_time_ms"] = doc["editing_time_ms"]

    return merged, True


def save_sidecar(raw_path: str | Path, document: Dict[str, Any]) -> Path:
    """Atomically writes `.calibraw` JSON document beside the raw file."""
    sc_path = sidecar_path_for_raw(raw_path)
    sc_path.parent.mkdir(parents=True, exist_ok=True)

    # Validate mandatory header
    document["format"] = FORMAT_IDENTIFIER
    document["schema_version"] = SCHEMA_VERSION

    # Write atomically via temp file in the same directory
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(sc_path.parent),
        prefix=f".{sc_path.name}.tmp-",
    )
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, sc_path)
    return sc_path


def apply_adjustments_to_document(
    document: Dict[str, Any],
    adjustments: Dict[str, Any],
) -> Dict[str, Any]:
    """Merges flat or nested perceptual adjustments into the sidecar document."""
    exp = document["edits"]["exposure"]
    geom = document["edits"]["geometry"]
    lens = document["edits"]["lens"]
    review = document["review"]

    for key, value in adjustments.items():
        if value is None:
            continue

        # Top-level exposure fields
        if key in exp:
            if isinstance(exp[key], dict) and isinstance(value, dict):
                exp[key].update(value)
            elif isinstance(exp[key], list) and isinstance(value, list):
                # Ensure 8-element HSL arrays or tone curves
                if key.startswith("hsl_") and len(value) == 8:
                    exp[key] = [float(v) for v in value]
                else:
                    exp[key] = value
            elif isinstance(exp[key], bool):
                exp[key] = bool(value)
            elif isinstance(exp[key], (int, float)):
                exp[key] = float(value)
            else:
                exp[key] = value

        # Tone Curve point list helpers: e.g. tone_curve=[[0,0], [0.5, 0.45], [1,1]]
        elif key in ("tone_curve_points", "curve"):
            if isinstance(value, list):
                exp["tone_curve"] = create_point_curve(value)
        elif key == "tone_curve_red_points":
            if isinstance(value, list):
                exp["tone_curve_red"] = create_point_curve(value)
        elif key == "tone_curve_green_points":
            if isinstance(value, list):
                exp["tone_curve_green"] = create_point_curve(value)
        elif key == "tone_curve_blue_points":
            if isinstance(value, list):
                exp["tone_curve_blue"] = create_point_curve(value)

        # Point Colors system
        elif key == "point_colors" and isinstance(value, list):
            from .masks import build_point_color
            exp["point_colors"] = [
                build_point_color(**pc) if isinstance(pc, dict) and "sample_hsl" not in pc else pc
                for pc in value
            ][:8]

        # White balance helpers (Kelvin conversion)
        elif key == "temperature_kelvin":
            from .white_balance import temperature_offset_from_kelvin
            exp["temperature"] = temperature_offset_from_kelvin(5500.0, float(value))

        # Geometry controls
        elif key in geom:
            geom[key] = value
        elif key == "crop_rect" and isinstance(value, list) and len(value) == 4:
            geom["crop"] = [float(v) for v in value]
        elif key == "rotation":
            geom["rotation_degrees"] = float(value)
        elif key in ("flip_h", "flip_horizontal"):
            geom["flip_horizontal"] = bool(value)
        elif key in ("flip_v", "flip_vertical"):
            geom["flip_vertical"] = bool(value)
        elif key == "quarter_turns":
            geom["quarter_turns"] = int(value) % 4
        elif key == "aspect_ratio":
            geom["aspect_ratio"] = str(value)

        # Lens controls
        elif key in lens:
            lens[key] = value
        elif key == "lens_correction_enabled":
            lens["enabled"] = bool(value)

        # Masks and Global Effects
        elif key == "masks" and isinstance(value, list):
            masks_obj = document["edits"].setdefault("masks", default_masks())
            masks_obj["masks"] = value
        elif key == "global_effects" and isinstance(value, list):
            masks_obj = document["edits"].setdefault("masks", default_masks())
            masks_obj["global_effects"] = value

        # Review / Culling
        elif key in review:
            review[key] = value
        elif key == "rating":
            review["rating"] = max(0, min(5, int(value)))
        elif key == "flag":
            review["flag"] = str(value).lower()

        # Sigmoid convenience shortcuts
        elif key == "sigmoid_contrast":
            exp["sigmoid"]["contrast"] = float(value)
        elif key == "sigmoid_skew":
            exp["sigmoid"]["skew"] = float(value)
        elif key == "sigmoid_hue_preservation":
            exp["sigmoid"]["hue_preservation"] = float(value)
        elif key == "color_processing":
            exp["sigmoid"]["color_processing"] = str(value)

    return document
