"""Builders for CalibRaw local masks, global effects and point colours.

Serialized layouts follow ``calibraw-core/src/pipeline/masks*.rs`` and
``point_color.rs`` (serde external tagging: unit variants are strings,
struct variants are ``{"Variant": {...}}``).
"""

from __future__ import annotations

import colorsys
import copy
from typing import Any, Dict, List, Optional

from .sidecar import create_point_curve, default_color_grading, default_point_curve

MAX_LOCAL_MASKS = 32
MAX_EFFECT_COMPONENTS = 12
MAX_MASK_COMPONENTS = 64
MAX_POINT_COLORS = 8

MASK_KINDS = [
    "Brush", "Fullscreen", "Radial", "Linear", "Path", "Subject", "Background", "Sky",
    "Object", "LuminanceRange", "ColorRange", "DepthRange",
]
MANUAL_MASK_KINDS = {"Brush", "Fullscreen", "Radial", "Linear", "Path"}
AI_MASK_KINDS = {"Subject", "Background", "Sky", "Object", "DepthRange"}
COMBINE_MODES = ["Add", "Subtract", "Intersect"]
MASK_EFFECTS = [
    "Adjustment", "Blur", "LensBlur", "MotionBlur", "RadialBlur", "TiltShift", "Glow", "LightRays",
    "Neon", "EdgeGlow", "Pixelate", "Fog", "Smoke", "Grain", "Halation", "Vignette",
]
_EFFECT_SETTINGS_KEY = {
    "Blur": "blur", "LensBlur": "lens_blur", "MotionBlur": "motion_blur", "RadialBlur": "radial_blur",
    "TiltShift": "tilt_shift", "Glow": "glow", "LightRays": "light_rays", "Neon": "neon",
    "EdgeGlow": "edge_glow", "Pixelate": "pixelate", "Fog": "fog", "Smoke": "smoke",
    "Grain": "grain", "Halation": "halation", "Vignette": "vignette",
}
_KIND_LABELS = {
    "Brush": "Brush", "Fullscreen": "Fullscreen", "Radial": "Radial Gradient",
    "Linear": "Linear Gradient", "Path": "Freeform / Path", "Subject": "Select Subject",
    "Background": "Select Background", "Sky": "Select Sky", "Object": "Select Object",
    "LuminanceRange": "Luminance Range", "ColorRange": "Color Range", "DepthRange": "Depth Range",
}

LOCAL_ADJUSTMENT_SCALARS = [
    "exposure", "contrast", "highlights", "shadows", "whites", "blacks", "temperature", "tint",
    "hue", "saturation", "texture", "clarity", "dehaze", "halation_amount",
]


def _canonical(value: str, options: List[str], what: str) -> str:
    key = str(value).replace(" ", "").replace("_", "").replace("-", "").lower()
    for option in options:
        if option.lower() == key:
            return option
    aliases = {"radialgradient": "Radial", "lineargradient": "Linear", "gradient": "Linear",
               "luminance": "LuminanceRange", "color": "ColorRange", "colour": "ColorRange",
               "depth": "DepthRange", "freeform": "Path", "person": "Subject", "global": "Fullscreen"}
    if key in aliases and aliases[key] in options:
        return aliases[key]
    raise ValueError(f"Unknown {what} '{value}'. Valid: {options}")


def canonical_kind(kind: str) -> str:
    return _canonical(kind, MASK_KINDS, "mask kind")


def canonical_effect(effect: str) -> str:
    return _canonical(effect, MASK_EFFECTS, "effect")


def default_local_adjustments() -> Dict[str, Any]:
    adj: Dict[str, Any] = {k: 0.0 for k in LOCAL_ADJUSTMENT_SCALARS}
    adj.update({
        "tone_curve": default_point_curve(),
        "tone_curve_red": default_point_curve(),
        "tone_curve_green": default_point_curve(),
        "tone_curve_blue": default_point_curve(),
        "hsl_hue": [0.0] * 8,
        "hsl_saturation": [0.0] * 8,
        "hsl_luminance": [0.0] * 8,
        "point_colors": [],
        "color_grading": default_color_grading(),
    })
    return adj


def default_geometry_for_kind(kind: str) -> Any:
    """Port of ``MaskGeometry::for_kind``."""
    if kind == "Fullscreen":
        return "Fullscreen"
    if kind == "Brush":
        return {"Brush": {"size": 0.055, "feather": 0.55, "opacity_enabled": False, "opacity": 1.0,
                          "overlap_enabled": True, "dabs": []}}
    if kind == "Radial":
        return {"Radial": {"center": [0.5, 0.5], "radius": [0.22, 0.16], "rotation": 0.0,
                           "feather": 0.55, "initialized": True}}
    if kind == "Linear":
        return {"Linear": {"start": [0.5, 0.0], "end": [0.5, 0.5], "feather": 1.0, "initialized": True}}
    if kind == "Path":
        return {"Path": {"points": [], "grow": 0.0, "feather": 0.0}}
    if kind in ("Subject", "Background", "Sky"):
        return {"Ai": {"mask": None, "grow": 0.0, "feather": 0.0}}
    if kind == "Object":
        return {"Object": {"mask": None, "grow": 0.0, "feather": 0.0, "brush_size": 0.055,
                           "edge_refine": 0.55, "strokes": []}}
    if kind == "LuminanceRange":
        return {"LuminanceRange": {"low": 0.2, "high": 0.8, "grow": 0.0, "feather": 0.15}}
    if kind == "ColorRange":
        return {"ColorRange": {"sample": [0.5, 0.5, 0.5], "tolerance": 0.18, "grow": 0.0,
                               "feather": 0.12, "sampled": True}}
    if kind == "DepthRange":
        return {"DepthRange": {"depth": None, "near": 0.0, "far": 0.5, "feather": 0.1, "far_feather": 0.1}}
    return "Placeholder"


def merge_geometry(geometry: Any, overrides: Optional[Dict[str, Any]]) -> Any:
    if not overrides or not isinstance(geometry, dict):
        return geometry
    variant = next(iter(geometry))
    body = dict(geometry[variant])
    for key, value in overrides.items():
        if key in ("dabs", "points", "strokes"):
            body[key] = value
        elif isinstance(value, (list, tuple)):
            body[key] = [float(v) for v in value]
        elif isinstance(value, bool):
            body[key] = value
        elif isinstance(value, (int, float)):
            body[key] = float(value)
        else:
            body[key] = value
    if variant in ("Radial", "Linear"):
        body["initialized"] = True
    if variant == "ColorRange" and "sample" in overrides:
        body["sampled"] = True
    return {variant: body}


def build_component(kind: str, combine: str = "Add", geometry: Optional[Dict[str, Any]] = None,
                    invert: bool = False, name: Optional[str] = None) -> Dict[str, Any]:
    kind = canonical_kind(kind)
    return {
        "name": name or _KIND_LABELS[kind],
        "enabled": True,
        "invert": bool(invert),
        "kind": kind,
        "combine": _canonical(combine, COMBINE_MODES, "combine mode"),
        "geometry": merge_geometry(default_geometry_for_kind(kind), geometry),
    }


def merge_local_adjustments(adjustments: Dict[str, Any], updates: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not updates:
        return adjustments
    for key, value in updates.items():
        if value is None:
            continue
        if key in LOCAL_ADJUSTMENT_SCALARS:
            adjustments[key] = float(value)
        elif key in ("hsl_hue", "hsl_saturation", "hsl_luminance") and len(value) == 8:
            adjustments[key] = [float(v) for v in value]
        elif key in ("tone_curve_points", "curve"):
            adjustments["tone_curve"] = create_point_curve(value)
        elif key in ("tone_curve_red_points", "tone_curve_green_points", "tone_curve_blue_points"):
            adjustments[key.replace("_points", "")] = create_point_curve(value)
        elif key == "color_grading" and isinstance(value, dict):
            grading = adjustments.setdefault("color_grading", default_color_grading())
            for wheel, wheel_value in value.items():
                if isinstance(wheel_value, dict) and isinstance(grading.get(wheel), dict):
                    grading[wheel].update({k: float(v) for k, v in wheel_value.items()})
                elif wheel in ("blending", "balance"):
                    grading[wheel] = float(wheel_value)
        elif key == "point_colors" and isinstance(value, list):
            adjustments["point_colors"] = [build_point_color(**pc) if "sample_hsl" not in pc else pc for pc in value][:MAX_POINT_COLORS]
    return adjustments


def build_local_mask(kind: str, name: Optional[str] = None, geometry: Optional[Dict[str, Any]] = None,
                     adjustments: Optional[Dict[str, Any]] = None, opacity: float = 1.0,
                     invert: bool = False, number: int = 1,
                     extra_components: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    components = [build_component(kind, "Add", geometry)]
    for comp in extra_components or []:
        components.append(build_component(comp.get("kind", "Fullscreen"), comp.get("combine", "Add"),
                                          comp.get("geometry"), comp.get("invert", False), comp.get("name")))
    return {
        "name": name or f"Mask {number}",
        "enabled": True,
        "invert": bool(invert),
        "effect": "Adjustment",
        "adjustments_enabled": True,
        "opacity": max(0.0, min(1.0, float(opacity))),
        "components": components[:MAX_MASK_COMPONENTS],
        "adjustments": merge_local_adjustments(default_local_adjustments(), adjustments),
    }


def build_effect_component(effect: str, settings: Optional[Dict[str, Any]] = None,
                           enabled: bool = True) -> Dict[str, Any]:
    effect = canonical_effect(effect)
    if effect == "Adjustment":
        raise ValueError("'Adjustment' is not a standalone effect; use add_mask instead.")
    component: Dict[str, Any] = {"effect": effect, "enabled": bool(enabled)}
    if settings:
        component["settings"] = {_EFFECT_SETTINGS_KEY[effect]: copy.deepcopy(settings)}
    return component


def build_point_color(sample_rgb: Optional[List[float]] = None, sample_hsl: Optional[List[float]] = None,
                      hue_shift: float = 0.0, saturation_shift: float = 0.0, luminance_shift: float = 0.0,
                      range: float = 50.0, **_: Any) -> Dict[str, Any]:
    """``sample_rgb`` in 0..1 sRGB (or 0..255). Mirrors ``PointColor::from_srgb``."""
    if sample_hsl is None:
        rgb = [float(v) for v in (sample_rgb or [0.5, 0.5, 0.5])][:3]
        if max(rgb) > 1.0:
            rgb = [v / 255.0 for v in rgb]
        h, l, s = colorsys.rgb_to_hls(*[max(0.0, min(1.0, v)) for v in rgb])
        sample_hsl = [h, s, l]

    def clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, float(v)))

    return {
        "sample_hsl": [float(sample_hsl[0]) % 1.0, clamp(sample_hsl[1], 0, 1), clamp(sample_hsl[2], 0, 1)],
        "hue_shift": clamp(hue_shift, -100, 100),
        "saturation_shift": clamp(saturation_shift, -100, 100),
        "luminance_shift": clamp(luminance_shift, -100, 100),
        "range": clamp(range, 0, 100),
        "hue_range": {"min": -0.125, "inner_min": -0.0625, "inner_max": 0.0625, "max": 0.125},
        "saturation_range": {"min": -0.5, "inner_min": -0.25, "inner_max": 0.25, "max": 0.5},
        "luminance_range": {"min": -0.5, "inner_min": -0.25, "inner_max": 0.25, "max": 0.5},
    }


def mask_uses_ai(mask: Dict[str, Any]) -> bool:
    return any(c.get("kind") not in MANUAL_MASK_KINDS | {"LuminanceRange", "ColorRange"}
               for c in mask.get("components", []))


def summarize_mask(index: int, mask: Dict[str, Any]) -> Dict[str, Any]:
    adj = mask.get("adjustments", {})
    active = {k: adj[k] for k in LOCAL_ADJUSTMENT_SCALARS if abs(float(adj.get(k, 0.0))) > 1e-6}
    return {
        "index": index,
        "name": mask.get("name"),
        "enabled": mask.get("enabled", True),
        "invert": mask.get("invert", False),
        "opacity": mask.get("opacity", 1.0),
        "components": [
            {"kind": c.get("kind"), "combine": c.get("combine"), "invert": c.get("invert", False),
             "geometry": c.get("geometry") if not isinstance(c.get("geometry"), dict) else
             {k: {kk: vv for kk, vv in v.items() if kk not in ("mask", "depth", "dabs", "strokes", "source")}
              for k, v in c["geometry"].items()}}
            for c in mask.get("components", [])
        ],
        "active_adjustments": active,
        "effects": [e.get("effect") for e in mask.get("effect_components", [])],
        "needs_ai_generation": mask_uses_ai(mask),
    }
