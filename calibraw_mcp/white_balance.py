"""White-balance math that mirrors CalibRaw's sidecar semantics.

CalibRaw stores white balance in the sidecar as *offsets* from the as-shot
white balance, not as absolute values:

- ``temperature``: mired offset, ``1e6/base_K - 1e6/target_K``, clamped to
  +/-500 (``GLOBAL_TEMPERATURE_LIMIT`` in ``basicadj.rs``). Positive = warmer.
- ``tint``: offset scaled by 100 (``WHITE_BALANCE_TINT_OFFSET_SCALE``),
  limited to +/-219.1. Positive = magenta, negative = green.

The as-shot colour temperature is estimated from the camera's white-balance
multipliers and colour matrix (McCamy CCT approximation).
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

MIN_TEMPERATURE_KELVIN = 1901.0
MAX_TEMPERATURE_KELVIN = 25000.0
GLOBAL_TEMPERATURE_LIMIT = 500.0
MIN_WHITE_BALANCE_TINT = 0.135
MAX_WHITE_BALANCE_TINT = 2.326
WHITE_BALANCE_TINT_OFFSET_SCALE = 100.0
GLOBAL_TINT_OFFSET_LIMIT = (MAX_WHITE_BALANCE_TINT - MIN_WHITE_BALANCE_TINT) * WHITE_BALANCE_TINT_OFFSET_SCALE
DEFAULT_AS_SHOT_KELVIN = 5500.0

# Generic illuminant presets (Kelvin) used when a camera-specific preset is not requested.
ILLUMINANT_PRESETS_K: Dict[str, float] = {
    "daylight": 5500.0,
    "sunny": 5500.0,
    "cloudy": 6500.0,
    "overcast": 6500.0,
    "shade": 7500.0,
    "tungsten": 2850.0,
    "incandescent": 2850.0,
    "fluorescent": 3800.0,
    "flash": 5500.0,
    "candlelight": 1950.0,
    "golden_hour": 3500.0,
    "blue_hour": 9000.0,
}

WB_DATABASE_CANDIDATES = [
    Path(__file__).resolve().parent / "wb_presets.json",
    Path(__file__).resolve().parent.parent / "CalibRaw" / "data" / "wb_presets.json",
]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def clamp_kelvin(kelvin: float) -> float:
    return _clamp(float(kelvin), MIN_TEMPERATURE_KELVIN, MAX_TEMPERATURE_KELVIN)


def temperature_offset_from_kelvin(base_kelvin: float, target_kelvin: float) -> float:
    """Port of ``temperature_offset_from_kelvin`` from ``basicadj.rs``."""
    base = clamp_kelvin(base_kelvin)
    target = clamp_kelvin(target_kelvin)
    return _clamp(1e6 / base - 1e6 / target, -GLOBAL_TEMPERATURE_LIMIT, GLOBAL_TEMPERATURE_LIMIT)


def temperature_kelvin_from_offset(base_kelvin: float, offset_mired: float) -> float:
    """Port of ``temperature_kelvin_from_offset`` from ``basicadj.rs``."""
    base_mired = 1e6 / clamp_kelvin(base_kelvin)
    return clamp_kelvin(1e6 / max(base_mired - float(offset_mired), 1.0))


def clamp_temperature_offset(value: float) -> float:
    return _clamp(float(value), -GLOBAL_TEMPERATURE_LIMIT, GLOBAL_TEMPERATURE_LIMIT)


def clamp_tint_offset(value: float) -> float:
    return _clamp(float(value), -GLOBAL_TINT_OFFSET_LIMIT, GLOBAL_TINT_OFFSET_LIMIT)


def looks_like_kelvin(value: float) -> bool:
    """A 'temperature' outside the mired-offset range is almost certainly Kelvin."""
    return abs(float(value)) > GLOBAL_TEMPERATURE_LIMIT and MIN_TEMPERATURE_KELVIN <= abs(float(value)) <= MAX_TEMPERATURE_KELVIN


# ---------------------------------------------------------------------------
# Colour-temperature estimation
# ---------------------------------------------------------------------------

def _mccamy_cct(x: float, y: float) -> float:
    n = (x - 0.3320) / (0.1858 - y)
    return 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.3 * n + 5520.33


def cct_from_camera_multipliers(multipliers: List[float], cam_xyz: np.ndarray) -> Optional[float]:
    """Estimate the illuminant CCT neutralised by camera WB ``multipliers``.

    ``cam_xyz`` is LibRaw's ``rgb_xyz_matrix`` (XYZ -> camera, rows = camera channels).
    """
    try:
        mul = np.asarray(multipliers[:3], dtype=np.float64)
        if np.any(mul <= 0) or not np.all(np.isfinite(mul)):
            return None
        neutral_cam = 1.0 / mul
        neutral_cam /= neutral_cam[1]
        matrix = np.asarray(cam_xyz, dtype=np.float64)[:3, :3]
        if not np.any(matrix):
            return None
        xyz = np.linalg.solve(matrix, neutral_cam)
        total = float(xyz.sum())
        if total <= 0:
            return None
        x, y = xyz[0] / total, xyz[1] / total
        cct = _mccamy_cct(x, y)
        if not math.isfinite(cct) or not (MIN_TEMPERATURE_KELVIN <= cct <= MAX_TEMPERATURE_KELVIN):
            return None
        return float(cct)
    except Exception:
        return None


@lru_cache(maxsize=64)
def estimate_as_shot_kelvin(raw_path: str) -> Tuple[float, str]:
    """Returns (kelvin, method). Falls back to 5500K for non-RAW files."""
    try:
        import rawpy

        with rawpy.imread(raw_path) as raw:
            cct = cct_from_camera_multipliers(list(raw.camera_whitebalance), np.array(raw.rgb_xyz_matrix))
            if cct:
                return round(cct, 0), "camera_matrix_mccamy"
    except Exception:
        pass
    return DEFAULT_AS_SHOT_KELVIN, "default_5500K"


def planckian_rgb_white(kelvin: float) -> np.ndarray:
    """Linear-sRGB colour of a blackbody / daylight illuminant, normalised to Y=1."""
    t = clamp_kelvin(kelvin)
    # Kim et al. (2002) cubic spline approximation of the Planckian locus in CIE xy.
    if t <= 4000:
        x = -0.2661239e9 / t ** 3 - 0.2343589e6 / t ** 2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t ** 3 + 2.1070379e6 / t ** 2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x ** 3 - 1.34811020 * x ** 2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x ** 3 - 1.37418593 * x ** 2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x ** 3 - 5.87338670 * x ** 2 + 3.75112997 * x - 0.37001483
    xyz = np.array([x / y, 1.0, (1.0 - x - y) / y])
    xyz_to_srgb = np.array([
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ])
    rgb = xyz_to_srgb @ xyz
    rgb = np.clip(rgb, 1e-4, None)
    return rgb / (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2])


def wb_channel_gains(base_kelvin: float, temperature_offset: float, tint_offset: float) -> np.ndarray:
    """Linear-sRGB channel gains that re-balance an as-shot image to the new WB."""
    target_k = temperature_kelvin_from_offset(base_kelvin, temperature_offset)
    gains = planckian_rgb_white(base_kelvin) / planckian_rgb_white(target_k)
    tint_ratio = 1.0 + clamp_tint_offset(tint_offset) / WHITE_BALANCE_TINT_OFFSET_SCALE
    gains[1] /= max(tint_ratio, MIN_WHITE_BALANCE_TINT)
    luminance = 0.2126 * gains[0] + 0.7152 * gains[1] + 0.0722 * gains[2]
    return (gains / luminance).astype(np.float32)


# ---------------------------------------------------------------------------
# Camera preset database (darktable-derived, shipped with CalibRaw)
# ---------------------------------------------------------------------------

def _normalized_camera_name(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


@lru_cache(maxsize=1)
def _load_wb_database() -> Dict[Tuple[str, str], List[Dict]]:
    for candidate in WB_DATABASE_CANDIDATES:
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            catalog: Dict[Tuple[str, str], List[Dict]] = {}
            for maker in data.get("wb_presets", []):
                maker_key = _normalized_camera_name(maker.get("maker", ""))
                for model in maker.get("models", []):
                    presets = [
                        {"name": p["name"], "channels": p["channels"]}
                        for p in model.get("presets", [])
                        if all(isinstance(v, (int, float)) and v > 0 for v in p["channels"][:3])
                    ]
                    catalog[(maker_key, _normalized_camera_name(model.get("model", "")))] = presets
            return catalog
    return {}


def camera_wb_presets(camera_maker: str, camera_model: str) -> List[Dict]:
    return list(_load_wb_database().get(
        (_normalized_camera_name(camera_maker or ""), _normalized_camera_name(camera_model or "")), []
    ))


def camera_preset_kelvin(raw_path: str, preset: Dict) -> Optional[float]:
    try:
        import rawpy

        with rawpy.imread(raw_path) as raw:
            return cct_from_camera_multipliers(preset["channels"], np.array(raw.rgb_xyz_matrix))
    except Exception:
        return None
