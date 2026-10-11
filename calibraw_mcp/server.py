"""CalibRaw MCP Server — Professional RAW darkroom grading, sidecars, and rendering engine.

Provides full coverage of CalibRaw capabilities:
1. Develop Sliders & JSON Sidecar Management (read, update, reset, inspect)
2. Photographic & Cinema Presets (Portra, Golden Hour, Teal & Orange, Monochrome, etc.)
3. Native Preset Standard (.calibraw-preset with category masking)
4. EXIF & RAW Sensor Metadata Extraction
5. CalibRaw White Balance Engine (Mired offsets, Kelvin conversion, Camera presets)
6. Masking & Local Adjustments (Radial, Linear, Brush, AI Subject/Sky, Color/Luminance ranges)
7. Global Creative Effects (Fog, Smoke, Light Rays, Glow, Neon, Halation, Grain, Lens Blur)
8. Point Color System (Eyedropper targeted color sampling & selective shifts)
9. High-Fidelity Rendering & Image Export (JPEG 4:4:4, PNG, TIFF with Planckian WB & Sigmoid curves)
10. Batch Processing & Settings Transfer across multiple photos
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP

from .exporter import export_image as render_and_export
from .masks import (
    MAX_LOCAL_MASKS,
    MAX_POINT_COLORS,
    build_effect_component,
    build_local_mask,
    build_point_color,
    summarize_mask,
)
from .metadata import get_image_metadata, is_raw_file
from .native_presets import (
    apply_native_preset_to_image,
    list_native_presets as scan_native_presets,
    load_native_preset,
    save_native_preset,
)
from .presets import PRESETS, find_preset
from .sidecar import (
    FORMAT_IDENTIFIER,
    SCHEMA_VERSION,
    SIDECAR_SUFFIX,
    apply_adjustments_to_document,
    default_masks,
    default_sidecar,
    load_sidecar,
    save_sidecar,
    sidecar_path_for_raw,
)
from .transfer import copy_settings_batch, normalize_selection
from .white_balance import (
    ILLUMINANT_PRESETS_K,
    camera_wb_presets,
    estimate_as_shot_kelvin,
    temperature_kelvin_from_offset,
    temperature_offset_from_kelvin,
)

mcp = FastMCP("CalibRawMCP")


def _resolve_raw_path(image_path: str) -> Path:
    p = Path(image_path)
    if p.exists():
        return p.resolve()

    search_roots = [
        Path.cwd(),
        Path.cwd().parent,
    ]
    env_dir = os.environ.get("CALIBRAW_PHOTOS_DIR")
    if env_dir:
        search_roots.append(Path(env_dir))
    seen_roots = set()
    for root in search_roots:
        resolved_root = root.resolve()
        if resolved_root in seen_roots or not resolved_root.exists():
            continue
        seen_roots.add(resolved_root)

        direct_cand = resolved_root / p
        if direct_cand.exists():
            return direct_cand.resolve()

        try:
            for match in resolved_root.rglob(p.name):
                if any(part in match.parts for part in (".git", "target", ".cargo")):
                    continue
                return match.resolve()
        except Exception:
            pass

    sc = sidecar_path_for_raw(p)
    if sc.exists():
        return sc.resolve()

    raise FileNotFoundError(f"Image or sidecar not found: {image_path}")


# ===========================================================================
# 1. Core Sidecar Reading & Updating Tools
# ===========================================================================

@mcp.tool()
def read_image_edits(image_path: str) -> str:
    """Reads current perceptual slider values, tone curves, and grading state from the .calibraw sidecar.

    Args:
        image_path: Path to the RAW file (e.g. 'IMG_4755.CR3') or its .calibraw sidecar.

    Returns:
        JSON string containing active sliders, color grading, curves, masks, and metadata.
    """
    raw_path = _resolve_raw_path(image_path)
    doc, existed = load_sidecar(raw_path)
    sc_path = sidecar_path_for_raw(raw_path)

    exp = doc["edits"]["exposure"]
    geom = doc["edits"]["geometry"]
    lens = doc["edits"]["lens"]
    masks_obj = doc["edits"].get("masks", {})
    review = doc["review"]

    # Calculate active Kelvin estimate
    base_k, _ = estimate_as_shot_kelvin(str(raw_path))
    temp_offset = float(exp.get("temperature", 0.0))
    current_kelvin = round(temperature_kelvin_from_offset(base_k, temp_offset), 0)

    # Summarize active masks
    local_masks = masks_obj.get("masks", [])
    summarized_masks = [summarize_mask(i, m) for i, m in enumerate(local_masks)]

    summary = {
        "image_path": str(raw_path),
        "sidecar_path": str(sc_path),
        "sidecar_exists": existed,
        "format": doc.get("format", FORMAT_IDENTIFIER),
        "schema_version": doc.get("schema_version", SCHEMA_VERSION),
        "white_balance": {
            "temperature_mired_offset": round(temp_offset, 1),
            "tint_offset": round(exp.get("tint", 0.0), 1),
            "as_shot_kelvin_base": base_k,
            "effective_kelvin": current_kelvin,
        },
        "basic_adjustments": {
            "exposure": round(exp.get("exposure", 0.0), 3),
            "contrast": round(exp.get("contrast", 0.0), 2),
            "highlights": round(exp.get("highlights", 0.0), 2),
            "shadows": round(exp.get("shadows", 0.0), 2),
            "whites": round(exp.get("whites", 0.0), 2),
            "blacks": round(exp.get("blacks", 0.0), 2),
            "vibrance": round(exp.get("vibrance", 0.0), 2),
            "saturation": round(exp.get("saturation", 0.0), 2),
        },
        "detail_and_effects": {
            "texture": round(exp.get("texture", 0.0), 2),
            "clarity": round(exp.get("clarity", 0.0), 2),
            "dehaze": round(exp.get("dehaze", 0.0), 2),
            "sharpen_amount": round(exp.get("sharpen_amount", 40.0), 2),
            "sharpen_radius": round(exp.get("sharpen_radius", 1.0), 2),
            "sharpen_masking": round(exp.get("sharpen_masking", 0.0), 2),
            "grain_amount": round(exp.get("grain_amount", 0.0), 2),
            "halation_amount": round(exp.get("halation_amount", 0.0), 2),
            "vignette_amount": round(exp.get("vignette_amount", 0.0), 2),
        },
        "sigmoid": exp.get("sigmoid", {}),
        "tone_curve_points": exp.get("tone_curve", {}).get("points", [])[: exp.get("tone_curve", {}).get("len", 2)],
        "color_grading": exp.get("color_grading", {}),
        "hsl_saturation": exp.get("hsl_saturation", [0.0] * 8),
        "hsl_luminance": exp.get("hsl_luminance", [0.0] * 8),
        "point_colors_count": len(exp.get("point_colors", [])),
        "masks": summarized_masks,
        "global_effects": [e.get("effect") for e in masks_obj.get("global_effects", [])],
        "geometry": geom,
        "lens": lens,
        "review": review,
    }
    return json.dumps(summary, indent=2)


@mcp.tool()
def update_image_edits(image_path: str, adjustments: Dict[str, Any] | str) -> str:
    """Merges perceptual modifications into the .calibraw sidecar for immediate GPU rendering.

    Supported adjustment keys:
      - Exposure / Tone: exposure (-5.0..+5.0), contrast (-100..+100), highlights (-100..+100),
        shadows (-100..+100), whites (-100..+100), blacks (-100..+100)
      - White Balance: temperature (-500..+500 mired offset), temperature_kelvin (e.g. 5600),
        tint (-219..+219), vibrance (-100..+100), saturation (-100..+100)
      - Detail: texture (-100..+100), clarity (-100..+100), dehaze (-100..+100),
        sharpen_amount (0..150), sharpen_radius (0.5..3.0), sharpen_masking (0..100)
      - Effects: grain_amount (0..100), halation_amount (0..100), vignette_amount (-100..+100)
      - Sigmoid: sigmoid_contrast (0.5..3.0), sigmoid_skew (-1.0..1.0), sigmoid_hue_preservation (0..100)
      - Curves: tone_curve_points (list of [x, y]), tone_curve_red_points, etc.
      - Color grading: color_grading (dict with shadows, midtones, highlights wheels)
      - HSL: hsl_hue, hsl_saturation, hsl_luminance (8-element float arrays)
      - Point Color: point_colors (list of sampled color shift dicts)
      - Geometry: rotation (degrees), crop_rect ([x0, y0, x1, y1]), quarter_turns (0..3), flip_h, flip_v
      - Review: rating (0..5), flag ('unflagged'|'picked'|'rejected')

    Args:
        image_path: Path to the RAW photo.
        adjustments: Dictionary or JSON string of adjustments to merge.

    Returns:
        JSON string confirming updated settings and saved sidecar file location.
    """
    raw_path = _resolve_raw_path(image_path)
    if isinstance(adjustments, str):
        try:
            adjustments = json.loads(adjustments)
        except Exception as err:
            raise ValueError(f"Could not parse adjustments JSON string: {err}")

    doc, _ = load_sidecar(raw_path)
    updated_doc = apply_adjustments_to_document(doc, adjustments)
    saved_path = save_sidecar(raw_path, updated_doc)

    return json.dumps({
        "status": "success",
        "message": f"Successfully updated CalibRaw sidecar for {raw_path.name}",
        "sidecar_file": str(saved_path),
        "applied_adjustments": adjustments,
    }, indent=2)


@mcp.tool()
def reset_image_edits(image_path: str) -> str:
    """Resets the image sidecar back to default neutral scene-referred settings."""
    raw_path = _resolve_raw_path(image_path)
    fresh_doc = default_sidecar()
    saved_path = save_sidecar(raw_path, fresh_doc)

    return json.dumps({
        "status": "success",
        "message": f"Reset sidecar to default scene-referred settings for {raw_path.name}",
        "sidecar_file": str(saved_path),
    }, indent=2)


@mcp.tool()
def get_sidecar_json(image_path: str) -> str:
    """Returns the raw JSON content of the .calibraw sidecar for live inspection or frontend display."""
    raw_path = _resolve_raw_path(image_path)
    doc, _ = load_sidecar(raw_path)
    return json.dumps(doc, indent=2)


# ===========================================================================
# 2. RAW & Metadata Inspection Tools
# ===========================================================================

@mcp.tool()
def get_image_info(image_path: str) -> str:
    """Extracts camera model, lens, ISO, shutter speed, aperture, and as-shot white balance metadata.

    Args:
        image_path: Path to the RAW or raster image.

    Returns:
        JSON string containing camera maker, model, lens, EXIF settings, and RAW dimensions.
    """
    raw_path = _resolve_raw_path(image_path)
    meta = get_image_metadata(raw_path)
    return json.dumps(meta, indent=2)


# ===========================================================================
# 3. White Balance & Temperature Engine
# ===========================================================================

@mcp.tool()
def set_white_balance(
    image_path: str,
    kelvin: Optional[float] = None,
    tint: Optional[float] = None,
    preset: Optional[str] = None,
) -> str:
    """Sets white balance using absolute Kelvin, tint offset, or camera illuminant presets.

    CalibRaw calculates the mired offset from the photo's as-shot CCT.
    Available presets: 'Daylight', 'Cloudy', 'Shade', 'Tungsten', 'Fluorescent', 'Flash', etc.

    Args:
        image_path: Path to the RAW photo.
        kelvin: Target color temperature in Kelvin (1901K to 25000K).
        tint: Green/Magenta tint offset (-219.0 to +219.0).
        preset: Named white balance preset (e.g. 'daylight', 'tungsten', 'cloudy').

    Returns:
        JSON string showing base CCT, calculated mired offset, and updated values.
    """
    raw_path = _resolve_raw_path(image_path)
    base_k, method = estimate_as_shot_kelvin(str(raw_path))

    target_k = kelvin
    if preset:
        key = preset.strip().lower()
        if key in ILLUMINANT_PRESETS_K:
            target_k = ILLUMINANT_PRESETS_K[key]
        else:
            meta = get_image_metadata(raw_path)
            maker = meta.get("camera_make", "")
            model = meta.get("camera_model", "")
            cam_presets = camera_wb_presets(maker, model)
            match = next((p for p in cam_presets if p["name"].lower() == key), None)
            if match:
                from .white_balance import camera_preset_kelvin
                k = camera_preset_kelvin(str(raw_path), match)
                if k:
                    target_k = k

    if target_k is None and tint is None:
        return json.dumps({
            "status": "error",
            "message": "Specify at least one of kelvin, tint, or preset.",
        }, indent=2)

    doc, _ = load_sidecar(raw_path)
    exp = doc["edits"]["exposure"]

    applied_changes = {}
    if target_k is not None:
        mired_offset = temperature_offset_from_kelvin(base_k, float(target_k))
        exp["temperature"] = round(mired_offset, 2)
        applied_changes["target_kelvin"] = target_k
        applied_changes["temperature_mired_offset"] = exp["temperature"]

    if tint is not None:
        exp["tint"] = round(float(tint), 1)
        applied_changes["tint"] = exp["tint"]

    saved_path = save_sidecar(raw_path, doc)

    return json.dumps({
        "status": "success",
        "image_path": str(raw_path),
        "as_shot_base_kelvin": base_k,
        "as_shot_method": method,
        "applied": applied_changes,
        "sidecar_file": str(saved_path),
    }, indent=2)


# ===========================================================================
# 4. Masking & Local Adjustments
# ===========================================================================

@mcp.tool()
def add_mask(
    image_path: str,
    kind: str,
    name: Optional[str] = None,
    adjustments: Optional[Dict[str, Any]] = None,
    geometry: Optional[Dict[str, Any]] = None,
    opacity: float = 1.0,
    invert: bool = False,
) -> str:
    """Adds a local adjustment mask (Radial, Linear, Subject, Background, Sky, ColorRange, etc.).

    Supported mask kinds:
      - 'Radial': Radial gradient (geometry: center=[x,y], radius=[rx,ry], feather=0.55)
      - 'Linear': Linear gradient (geometry: start=[x,y], end=[x,y], feather=1.0)
      - 'Subject', 'Background', 'Sky': On-device local AI masks
      - 'ColorRange': Eyedropper sampled color range (geometry: sample=[r,g,b], tolerance=0.18)
      - 'LuminanceRange': Tonal range selection (geometry: low=0.2, high=0.8)
      - 'DepthRange': Scene depth slice (geometry: near=0.0, far=0.5)

    Supported local adjustments: exposure, contrast, highlights, shadows, whites, blacks,
    temperature, tint, saturation, texture, clarity, dehaze.

    Args:
        image_path: Path to the RAW photo.
        kind: Mask kind (Radial, Linear, Subject, Background, Sky, ColorRange, LuminanceRange).
        name: Optional custom label for the mask.
        adjustments: Dictionary of local slider adjustments for this mask.
        geometry: Shape/coordinate parameters.
        opacity: Mask opacity 0.0 to 1.0 (default 1.0).
        invert: Whether to invert the mask (default False).

    Returns:
        JSON string confirming added mask and updated mask count.
    """
    raw_path = _resolve_raw_path(image_path)
    doc, _ = load_sidecar(raw_path)

    masks_obj = doc["edits"].setdefault("masks", default_masks())
    current_masks = masks_obj.setdefault("masks", [])

    if len(current_masks) >= MAX_LOCAL_MASKS:
        return json.dumps({
            "status": "error",
            "message": f"Maximum of {MAX_LOCAL_MASKS} local masks reached.",
        }, indent=2)

    new_mask = build_local_mask(
        kind=kind,
        name=name,
        geometry=geometry,
        adjustments=adjustments,
        opacity=opacity,
        invert=invert,
        number=len(current_masks) + 1,
    )

    current_masks.append(new_mask)
    if new_mask.get("components", [{}])[0].get("kind") in ("Subject", "Background", "Sky", "Object"):
        doc["edits"]["ai_masks_need_update"] = True

    saved_path = save_sidecar(raw_path, doc)

    return json.dumps({
        "status": "success",
        "message": f"Added {new_mask['name']} ({kind}) to {raw_path.name}",
        "total_masks": len(current_masks),
        "mask": summarize_mask(len(current_masks) - 1, new_mask),
        "sidecar_file": str(saved_path),
    }, indent=2)


@mcp.tool()
def list_masks(image_path: str) -> str:
    """Lists all active local masks, their components, and local adjustments."""
    raw_path = _resolve_raw_path(image_path)
    doc, _ = load_sidecar(raw_path)
    masks = doc["edits"].get("masks", {}).get("masks", [])
    summarized = [summarize_mask(i, m) for i, m in enumerate(masks)]
    return json.dumps({
        "image_path": str(raw_path),
        "total_masks": len(masks),
        "masks": summarized,
    }, indent=2)


@mcp.tool()
def remove_mask(image_path: str, mask_index: int) -> str:
    """Removes a local adjustment mask by its index."""
    raw_path = _resolve_raw_path(image_path)
    doc, _ = load_sidecar(raw_path)

    masks = doc["edits"].get("masks", {}).get("masks", [])
    if mask_index < 0 or mask_index >= len(masks):
        return json.dumps({
            "status": "error",
            "message": f"Mask index {mask_index} out of range (0..{len(masks)-1}).",
        }, indent=2)

    removed = masks.pop(mask_index)
    saved_path = save_sidecar(raw_path, doc)

    return json.dumps({
        "status": "success",
        "message": f"Removed mask '{removed.get('name')}' from {raw_path.name}",
        "remaining_masks": len(masks),
        "sidecar_file": str(saved_path),
    }, indent=2)


@mcp.tool()
def add_global_effect(
    image_path: str,
    effect: str,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Adds a creative atmospheric effect across the entire photo.

    Available effects:
      - 'Fog': Volumetric atmosphere (settings: amount, density, softness, depth_enabled)
      - 'Smoke': Organic haze (settings: amount, density, scale)
      - 'LightRays': Volumetric sunlight rays (settings: amount, length, source=[x,y], spread)
      - 'Glow': Highlight diffusion/bloom (settings: amount, radius, core)
      - 'Neon': Cyberpunk edge radiance (settings: amount, color=[r,g,b])
      - 'LensBlur': Optical depth-of-field bokeh (settings: amount, radius)
      - 'TiltShift': Miniature focus band (settings: amount, radius, angle, focus_width)
      - 'Halation': Analog film highlight glow (settings: amount, radius)
      - 'Grain': Photographic film silver grain (settings: amount, size, roughness)

    Args:
        image_path: Path to the RAW photo.
        effect: Effect name (Fog, Smoke, LightRays, Glow, Neon, LensBlur, TiltShift, Halation, Grain).
        settings: Effect parameters dictionary.

    Returns:
        JSON string confirming effect added.
    """
    raw_path = _resolve_raw_path(image_path)
    doc, _ = load_sidecar(raw_path)

    masks_obj = doc["edits"].setdefault("masks", default_masks())
    effects_list = masks_obj.setdefault("global_effects", [])

    comp = build_effect_component(effect, settings)
    effects_list.append(comp)
    saved_path = save_sidecar(raw_path, doc)

    return json.dumps({
        "status": "success",
        "message": f"Added global effect '{effect}' to {raw_path.name}",
        "total_global_effects": len(effects_list),
        "effect": comp,
        "sidecar_file": str(saved_path),
    }, indent=2)


# ===========================================================================
# 5. Point Color System
# ===========================================================================

@mcp.tool()
def add_point_color(
    image_path: str,
    sample_rgb: Optional[List[float]] = None,
    hue_shift: float = 0.0,
    saturation_shift: float = 0.0,
    luminance_shift: float = 0.0,
    range: float = 50.0,
) -> str:
    """Applies an eyedropper targeted color shift (Point Color).

    Args:
        image_path: Path to the RAW photo.
        sample_rgb: Sampled color [R, G, B] in range 0.0 to 1.0 (or 0..255).
        hue_shift: Hue rotation (-100.0 to +100.0).
        saturation_shift: Saturation boost/cut (-100.0 to +100.0).
        luminance_shift: Luminance boost/cut (-100.0 to +100.0).
        range: Width of affected color range (0.0 to 100.0, default 50.0).

    Returns:
        JSON string confirming point color added.
    """
    raw_path = _resolve_raw_path(image_path)
    doc, _ = load_sidecar(raw_path)

    exp = doc["edits"]["exposure"]
    pcs = exp.setdefault("point_colors", [])

    if len(pcs) >= MAX_POINT_COLORS:
        return json.dumps({
            "status": "error",
            "message": f"Maximum of {MAX_POINT_COLORS} Point Colors reached.",
        }, indent=2)

    new_pc = build_point_color(
        sample_rgb=sample_rgb or [0.5, 0.5, 0.5],
        hue_shift=hue_shift,
        saturation_shift=saturation_shift,
        luminance_shift=luminance_shift,
        range=range,
    )
    pcs.append(new_pc)
    saved_path = save_sidecar(raw_path, doc)

    return json.dumps({
        "status": "success",
        "message": f"Added Point Color to {raw_path.name}",
        "total_point_colors": len(pcs),
        "point_color": new_pc,
        "sidecar_file": str(saved_path),
    }, indent=2)


# ===========================================================================
# 6. Presets (Curated & Native .calibraw-preset)
# ===========================================================================

@mcp.tool()
def apply_preset(image_path: str, preset_name: str) -> str:
    """Applies a curated film curve and color grading matrix to the .calibraw sidecar.

    Available Presets:
      - 'Kodak Portra 400': Analog skin tones, lifted shadows, gentle film compression.
      - 'Golden Hour Warmth': Sunset warmth, amber midtones, soft gold highlights.
      - 'Dramatic Sky Recovery': Highlight and sky recovery, deep blue saturation.
      - 'Moody Teal & Orange': Blockbuster separation with teal shadows & warm skin tones.
      - 'Clean Portrait CAT16': Bradford CAT16 studio portrait look, edge-masked sharpening.
      - 'Monochrome Fine Art': Deep silver B&W conversion, tactile analog grain.
    """
    raw_path = _resolve_raw_path(image_path)
    preset = find_preset(preset_name)
    if not preset:
        valid_presets = [p["name"] for p in PRESETS.values()]
        return json.dumps({
            "status": "error",
            "message": f"Preset '{preset_name}' not found. Available: {valid_presets}",
        }, indent=2)

    doc, _ = load_sidecar(raw_path)
    updated_doc = apply_adjustments_to_document(doc, preset["adjustments"])
    saved_path = save_sidecar(raw_path, updated_doc)

    return json.dumps({
        "status": "success",
        "preset_applied": preset["name"],
        "category": preset.get("category", "General"),
        "description": preset["description"],
        "sidecar_file": str(saved_path),
    }, indent=2)


@mcp.tool()
def list_presets() -> str:
    """Lists all available photographic and cinema grading presets in CalibRaw MCP."""
    catalog = []
    for key, p in PRESETS.items():
        catalog.append({
            "key": key,
            "name": p["name"],
            "category": p.get("category", "General"),
            "description": p["description"],
            "sample_adjustments": list(p["adjustments"].keys()),
        })
    return json.dumps({"presets": catalog}, indent=2)


@mcp.tool()
def apply_native_preset(image_path: str, preset_path: str) -> str:
    """Applies an official CalibRaw .calibraw-preset file with selective category masking."""
    raw_path = _resolve_raw_path(image_path)
    res = apply_native_preset_to_image(raw_path, preset_path)
    return json.dumps(res, indent=2)


@mcp.tool()
def export_native_preset(
    image_path: str,
    preset_name: str,
    output_path: Optional[str] = None,
    group: str = "User Presets",
    categories: Optional[List[str]] = None,
) -> str:
    """Exports current photo adjustments as an official reusable .calibraw-preset file.

    Args:
        image_path: Source RAW photo.
        preset_name: Title of the preset.
        output_path: Destination .calibraw-preset file path (defaults to User Presets folder).
        group: Preset category group (default 'User Presets').
        categories: Categories to include: ['light', 'tone_curve', 'color', 'color_grading',
                    'detail', 'effects', 'color_mixer', 'geometry', 'masks', 'lens_correction'].
    """
    raw_path = _resolve_raw_path(image_path)
    doc, _ = load_sidecar(raw_path)

    out_file = Path(output_path) if output_path else Path.home() / ".config" / "calibraw" / "presets" / f"{preset_name}.calibraw-preset"
    saved = save_native_preset(
        output_path=out_file,
        name=preset_name,
        edits=doc["edits"],
        selection=normalize_selection(categories) if categories else None,
        group=group,
    )

    return json.dumps({
        "status": "success",
        "preset_file": str(saved),
        "preset_name": preset_name,
        "group": group,
    }, indent=2)


@mcp.tool()
def list_native_presets(preset_directory: Optional[str] = None) -> str:
    """Lists all official .calibraw-preset files discovered on disk."""
    dirs = [Path(preset_directory)] if preset_directory else None
    presets = scan_native_presets(dirs)
    return json.dumps({"native_presets": presets, "count": len(presets)}, indent=2)


# ===========================================================================
# 7. Batch Processing & Settings Transfer
# ===========================================================================

@mcp.tool()
def copy_settings(
    source_image: str,
    target_images: List[str],
    categories: Optional[List[str]] = None,
    paste_mode: str = "merge",
) -> str:
    """Propagates develop settings from a source image to multiple target photos.

    Categories:
      - 'adjustments' or 'all': All develop slider groups
      - Specific groups: 'light', 'tone_curve', 'color', 'color_grading', 'detail', 'effects', 'color_mixer'
      - Non-slider categories: 'geometry', 'masks', 'ai_masks', 'lens_correction', 'raw_processing'

    Args:
        source_image: Path to source photo with developed settings.
        target_images: List of target photo paths to update.
        categories: List of category strings to copy (defaults to all adjustments).
        paste_mode: 'merge' (keeps existing unaffected settings) or 'replace' (resets target first).

    Returns:
        JSON string reporting batch operation results.
    """
    src_path = _resolve_raw_path(source_image)
    resolved_targets = [_resolve_raw_path(t) for t in target_images]

    result = copy_settings_batch(
        source_path=src_path,
        target_paths=resolved_targets,
        selection=categories,
        paste_mode=paste_mode,
    )
    return json.dumps(result, indent=2)


# ===========================================================================
# 8. High-Fidelity Image Export
# ===========================================================================

@mcp.tool()
def export_image(
    image_path: str,
    output_path: Optional[str] = None,
    format: str = "jpeg",
    quality: int = 95,
    max_dimension: Optional[int] = None,
    use_darktable_cli: bool = False,
) -> str:
    """Renders and exports a full-fidelity master image applying all active .calibraw edits.

    Demosaics RAW with Planckian white balance, Sigmoid tone mapping, highlight/shadow
    recovery LUT, clarity, vibrance, sharpness, and saves pristine 4:4:4 JPEGs or lossless PNGs.

    Args:
        image_path: Source RAW photo (e.g. 'IMG_4755.CR3').
        output_path: Destination output file path (defaults to Exports folder).
        format: 'jpeg', 'png', or 'tiff' (default 'jpeg').
        quality: JPEG export quality 1-100 (default 95).
        max_dimension: Longest edge pixel constraint (optional).
        use_darktable_cli: Use Darktable CLI for scene-referred base demosaicing if available.

    Returns:
        JSON string with output file path, dimensions, and file size.
    """
    raw_path = _resolve_raw_path(image_path)
    res = render_and_export(
        image_path=raw_path,
        output_path=output_path,
        format=format,
        quality=quality,
        max_dimension=max_dimension,
        use_darktable_cli=use_darktable_cli,
    )
    return json.dumps(res, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
