"""CalibRaw settings transfer and batch copy engine.

Port of ``crates/calibraw-core/src/sidecar/transfer.rs`` and ``adjustment_groups.rs``.
Handles selective category merging/replacement between images and batch propagation.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .masks import MANUAL_MASK_KINDS, default_local_adjustments
from .sidecar import default_exposure_params, default_geometry, default_lens, default_masks, default_sidecar, load_sidecar, save_sidecar

ADJUSTMENT_GROUPS = [
    "light",
    "tone_curve",
    "color",
    "color_grading",
    "detail",
    "effects",
    "color_mixer",
]

GROUP_FIELDS = {
    "light": ["exposure", "contrast", "highlights", "shadows", "whites", "blacks"],
    "tone_curve": ["tone_curve", "tone_curve_red", "tone_curve_green", "tone_curve_blue"],
    "color": ["temperature", "tint", "hue", "saturation", "vibrance"],
    "color_grading": ["color_grading"],
    "detail": [
        "luminance_denoise", "chroma_denoise", "denoise_detail", "denoise_quality",
        "ai_denoise_enabled", "sharpen_amount", "sharpen_radius", "sharpen_detail",
        "sharpen_masking",
    ],
    "effects": [
        "texture", "clarity", "dehaze", "halation_amount", "grain_amount",
        "glow_amount", "glow_radius", "glow_threshold", "vignette_amount",
        "vignette_midpoint", "vignette_roundness", "vignette_feather", "vignette_highlights",
    ],
    "color_mixer": ["hsl_hue", "hsl_saturation", "hsl_luminance", "point_colors"],
}

RAW_PROCESSING_FIELDS = [
    "black_point", "sigmoid", "demosaic_mode", "dual_threshold",
    "frequency_chroma", "ca_red", "ca_blue", "highlight_method",
    "highlight_clip", "highlight_reconstruction",
]


def default_edit_selection(all_categories: bool = True) -> Dict[str, Any]:
    """Returns an EditSelection dictionary matching CalibRaw's schema."""
    if all_categories:
        return {
            "adjustment_groups": list(ADJUSTMENT_GROUPS),
            "raw_processing": True,
            "geometry": True,
            "camera_profile": True,
            "masks": True,
            "ai_masks": True,
            "lens_correction": True,
        }
    return {
        "adjustment_groups": [],
        "raw_processing": False,
        "geometry": False,
        "camera_profile": False,
        "masks": False,
        "ai_masks": False,
        "lens_correction": False,
    }


def normalize_selection(selection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalizes a partial selection dict or shortcut category names."""
    base = default_edit_selection(all_categories=False)
    if selection is None:
        return default_edit_selection(all_categories=True)

    # If user provided a list of category strings: ["light", "masks", "geometry"]
    if isinstance(selection, (list, set, tuple)):
        sel_list = [str(s).lower() for s in selection]
        if "adjustments" in sel_list or "all" in sel_list:
            base["adjustment_groups"] = list(ADJUSTMENT_GROUPS)
            base["raw_processing"] = True
        for g in ADJUSTMENT_GROUPS:
            if g in sel_list:
                if g not in base["adjustment_groups"]:
                    base["adjustment_groups"].append(g)
        for cat in ("geometry", "camera_profile", "masks", "ai_masks", "lens_correction", "raw_processing"):
            if cat in sel_list:
                base[cat] = True
        return base

    # If user passed "adjustments": true shortcut
    if selection.get("adjustments"):
        base["adjustment_groups"] = list(ADJUSTMENT_GROUPS)
        base["raw_processing"] = True

    # Adjustment groups subset
    if "adjustment_groups" in selection:
        groups = selection["adjustment_groups"]
        if isinstance(groups, list):
            base["adjustment_groups"] = [g.lower() for g in groups if g.lower() in ADJUSTMENT_GROUPS]
        elif groups is True:
            base["adjustment_groups"] = list(ADJUSTMENT_GROUPS)

    # Booleans
    for key in ("raw_processing", "geometry", "camera_profile", "masks", "ai_masks", "lens_correction"):
        if key in selection:
            base[key] = bool(selection[key])

    return base


def transfer_edits(
    destination: Dict[str, Any],
    source: Dict[str, Any],
    selection: Optional[Dict[str, Any]] = None,
    paste_mode: str = "merge",  # "merge" or "replace"
) -> Dict[str, Any]:
    """Copies selected categories from `source` to `destination` sidecar document.

    Port of ``transfer_edits`` in ``transfer.rs``.
    """
    sel = normalize_selection(selection)
    dest = copy.deepcopy(destination)
    src_edits = source.get("edits", {})
    dest_edits = dest.setdefault("edits", {})

    if paste_mode.lower() == "replace":
        # Reset destination to default first
        fresh = default_sidecar()
        dest["edits"] = fresh["edits"]
        dest_edits = dest["edits"]

    # 1. Transfer Exposure adjustment groups
    src_exp = src_edits.get("exposure", {})
    dest_exp = dest_edits.setdefault("exposure", default_exposure_params())

    for group in sel.get("adjustment_groups", []):
        fields = GROUP_FIELDS.get(group, [])
        for field in fields:
            if field in src_exp:
                dest_exp[field] = copy.deepcopy(src_exp[field])

    # 2. Transfer Raw Processing
    if sel.get("raw_processing"):
        for field in RAW_PROCESSING_FIELDS:
            if field in src_exp:
                dest_exp[field] = copy.deepcopy(src_exp[field])

    # 3. Transfer Geometry
    if sel.get("geometry"):
        if "geometry" in src_edits:
            dest_edits["geometry"] = copy.deepcopy(src_edits["geometry"])

    # 4. Transfer Lens correction
    if sel.get("lens_correction"):
        if "lens" in src_edits:
            dest_edits["lens"] = copy.deepcopy(src_edits["lens"])

    # 5. Transfer Camera Profile
    if sel.get("camera_profile"):
        if "camera_profile" in src_edits:
            dest_edits["camera_profile"] = copy.deepcopy(src_edits["camera_profile"])

    # 6. Transfer Masks
    inc_manual = sel.get("masks", False)
    inc_ai = sel.get("ai_masks", False)

    if inc_manual or inc_ai:
        src_masks_obj = src_edits.get("masks", default_masks())
        dest_masks_obj = dest_edits.setdefault("masks", default_masks())

        # Copy global effects if manual masks selected
        if inc_manual and "global_effects" in src_masks_obj:
            dest_masks_obj.setdefault("global_effects", []).extend(
                copy.deepcopy(src_masks_obj["global_effects"])
            )

        # Filter and append local masks
        src_local_masks = src_masks_obj.get("masks", [])
        transferred_masks = []
        needs_ai_update = False

        for mask in src_local_masks:
            m_copy = copy.deepcopy(mask)
            filtered_components = []
            for comp in m_copy.get("components", []):
                kind = comp.get("kind", "Brush")
                is_manual = kind in MANUAL_MASK_KINDS
                if (is_manual and inc_manual) or (not is_manual and inc_ai):
                    filtered_components.append(comp)
                    if not is_manual:
                        needs_ai_update = True
            if filtered_components:
                m_copy["components"] = filtered_components
                transferred_masks.append(m_copy)

        dest_masks_obj.setdefault("masks", []).extend(transferred_masks)
        # Cap masks to MAX_LOCAL_MASKS
        dest_masks_obj["masks"] = dest_masks_obj["masks"][:32]
        if needs_ai_update:
            dest_edits["ai_masks_need_update"] = True

    return dest


def copy_settings_batch(
    source_path: Union[str, Path],
    target_paths: List[Union[str, Path]],
    selection: Optional[Dict[str, Any]] = None,
    paste_mode: str = "merge",
) -> Dict[str, Any]:
    """Applies adjustments from source_path to multiple target images."""
    src_doc, src_existed = load_sidecar(source_path)
    if not src_existed:
        raise FileNotFoundError(f"Source sidecar not found for {source_path}")

    sel = normalize_selection(selection)
    results = []

    for tgt in target_paths:
        t_path = Path(tgt).resolve()
        try:
            dest_doc, _ = load_sidecar(t_path)
            updated = transfer_edits(dest_doc, src_doc, sel, paste_mode=paste_mode)
            saved = save_sidecar(t_path, updated)
            results.append({
                "target": str(t_path),
                "sidecar": str(saved),
                "status": "success",
            })
        except Exception as exc:
            results.append({
                "target": str(t_path),
                "status": "error",
                "error": str(exc),
            })

    successful_count = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "success",
        "source": str(source_path),
        "total_targets": len(target_paths),
        "updated_targets": successful_count,
        "paste_mode": paste_mode,
        "selection": sel,
        "details": results,
    }
