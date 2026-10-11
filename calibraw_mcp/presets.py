"""Curated CalibRaw perceptual grading presets.

Implements high-fidelity film emulations, dynamic range recoveries, and portrait grades
adhering strictly to CalibRaw Schema Version 1.
"""

from __future__ import annotations

from typing import Any, Dict

from .sidecar import create_point_curve

PRESETS: Dict[str, Dict[str, Any]] = {
    "kodak_portra_400": {
        "name": "Kodak Portra 400",
        "description": "Legendary analog portrait stock: creamy skin tones, soft lifted shadows, gentle highlight roll-off, and subtle organic halation.",
        "category": "Film Emulation",
        "adjustments": {
            "exposure": 0.15,
            "contrast": -4.0,
            "highlights": -18.0,
            "shadows": 14.0,
            "whites": -8.0,
            "blacks": 6.0,
            "temperature": 110.0,
            "tint": 3.0,
            "vibrance": 8.0,
            "saturation": -4.0,
            "texture": -3.0,
            "clarity": -2.0,
            "sigmoid_contrast": 1.45,
            "sigmoid_skew": 0.04,
            "sigmoid_hue_preservation": 96.0,
            "tone_curve": create_point_curve([
                [0.0, 0.04],    # Lifted black floor (film look)
                [0.25, 0.23],
                [0.50, 0.49],
                [0.75, 0.76],
                [1.0, 0.96],    # Soft compressed highlights
            ]),
            "color_grading": {
                "shadows": {"hue": 38.0, "saturation": 6.0, "luminance": 1.0},
                "midtones": {"hue": 32.0, "saturation": 5.0, "luminance": 0.0},
                "highlights": {"hue": 52.0, "saturation": 6.0, "luminance": -1.0},
                "global": {"hue": 0.0, "saturation": 0.0, "luminance": 0.0},
                "blending": 55.0,
                "balance": 5.0,
            },
            # HSL adjustments: Muted greens, flattering peachy skin (Orange/Red)
            # Order: [Red, Orange, Yellow, Green, Aqua, Blue, Purple, Magenta]
            "hsl_hue": [2.0, -2.0, -4.0, 15.0, 0.0, -5.0, 0.0, 0.0],
            "hsl_saturation": [5.0, 8.0, -8.0, -20.0, -10.0, -8.0, -5.0, 0.0],
            "hsl_luminance": [2.0, 6.0, 2.0, -4.0, 0.0, -4.0, 0.0, 0.0],
            "grain_amount": 16.0,
            "halation_amount": 12.0,
        },
    },

    "golden_hour_warmth": {
        "name": "Golden Hour Warmth",
        "description": "Rich sunset illumination: warm amber midtones, soft gold highlights, opened shadows, and gentle atmospheric contrast.",
        "category": "Atmospheric & Nature",
        "adjustments": {
            "exposure": 0.22,
            "contrast": 6.0,
            "highlights": -24.0,
            "shadows": 20.0,
            "whites": -10.0,
            "blacks": 4.0,
            "temperature": 480.0,
            "tint": -4.0,
            "vibrance": 18.0,
            "saturation": 4.0,
            "clarity": 6.0,
            "dehaze": 4.0,
            "sigmoid_contrast": 1.55,
            "sigmoid_skew": 0.02,
            "color_grading": {
                "shadows": {"hue": 30.0, "saturation": 12.0, "luminance": 2.0},
                "midtones": {"hue": 38.0, "saturation": 16.0, "luminance": 0.0},
                "highlights": {"hue": 46.0, "saturation": 22.0, "luminance": -1.0},
                "global": {"hue": 40.0, "saturation": 4.0, "luminance": 0.0},
                "blending": 50.0,
                "balance": 10.0,
            },
            "hsl_saturation": [10.0, 15.0, 20.0, -5.0, -10.0, -15.0, 0.0, 0.0],
            "vignette_amount": -14.0,
            "vignette_feather": 65.0,
            "glow_amount": 8.0,
            "glow_radius": 55.0,
        },
    },

    "dramatic_sky_recovery": {
        "name": "Dramatic Sky Recovery",
        "description": "Aggressive highlight and sky recovery: deepens overexposed clouds, pulls out shadow details, and intensifies blue sky saturation.",
        "category": "Landscape & HDR",
        "adjustments": {
            "exposure": -0.15,
            "contrast": 18.0,
            "highlights": -58.0,
            "shadows": 32.0,
            "whites": -30.0,
            "blacks": -8.0,
            "clarity": 22.0,
            "dehaze": 28.0,
            "texture": 12.0,
            "sigmoid_contrast": 1.62,
            "sigmoid_skew": -0.06,
            "tone_curve": create_point_curve([
                [0.0, 0.0],
                [0.20, 0.24],
                [0.50, 0.51],
                [0.80, 0.72],
                [1.0, 0.90],
            ]),
            # Deepen Cyan / Blue skies
            # Order: [Red, Orange, Yellow, Green, Aqua, Blue, Purple, Magenta]
            "hsl_hue": [0.0, 0.0, 0.0, 0.0, 5.0, -8.0, 0.0, 0.0],
            "hsl_saturation": [0.0, 5.0, 10.0, 10.0, 20.0, 26.0, 0.0, 0.0],
            "hsl_luminance": [0.0, 0.0, -5.0, -10.0, -22.0, -36.0, 0.0, 0.0],
        },
    },

    "moody_teal_orange": {
        "name": "Moody Teal & Orange",
        "description": "Hollywood blockbuster color separation: rich teal shadows and blacks paired with radiant warm orange skin and highlights.",
        "category": "Cinematic",
        "adjustments": {
            "exposure": 0.05,
            "contrast": 22.0,
            "highlights": -22.0,
            "shadows": 14.0,
            "whites": -6.0,
            "blacks": -10.0,
            "clarity": 14.0,
            "dehaze": 10.0,
            "temperature": 80.0,
            "tint": 2.0,
            "sigmoid_contrast": 1.65,
            "sigmoid_skew": 0.0,
            "color_grading": {
                "shadows": {"hue": 196.0, "saturation": 32.0, "luminance": -4.0},
                "midtones": {"hue": 28.0, "saturation": 14.0, "luminance": 0.0},
                "highlights": {"hue": 36.0, "saturation": 28.0, "luminance": 2.0},
                "global": {"hue": 0.0, "saturation": 0.0, "luminance": 0.0},
                "blending": 55.0,
                "balance": -8.0,
            },
            # Push warm colors towards orange, cool colors towards teal
            "hsl_hue": [10.0, -4.0, -18.0, 45.0, 10.0, -14.0, 0.0, 0.0],
            "hsl_saturation": [10.0, 18.0, 5.0, -28.0, 18.0, 22.0, -15.0, -10.0],
            "hsl_luminance": [-2.0, 4.0, 0.0, -6.0, -8.0, -12.0, 0.0, 0.0],
            "vignette_amount": -18.0,
            "vignette_midpoint": 45.0,
        },
    },

    "clean_portrait_cat16": {
        "name": "Clean Portrait CAT16",
        "description": "Bradford CAT16 adapted studio portrait look: clean natural skin tones, soft facial diffusion, eye clarity, and edge-masked sharpening.",
        "category": "Portrait & Commercial",
        "adjustments": {
            "exposure": 0.12,
            "contrast": -3.0,
            "highlights": -16.0,
            "shadows": 12.0,
            "whites": -6.0,
            "blacks": 2.0,
            "temperature": 40.0,
            "tint": 0.0,
            "texture": -8.0,        # Gentle organic skin micro-softening
            "clarity": -4.0,
            "sharpen_amount": 38.0,
            "sharpen_radius": 0.8,
            "sharpen_masking": 48.0,# Only edge transitions / hair / eyes sharpened
            "sigmoid_contrast": 1.48,
            "sigmoid_skew": 0.02,
            "color_grading": {
                "shadows": {"hue": 40.0, "saturation": 4.0, "luminance": 1.0},
                "midtones": {"hue": 25.0, "saturation": 4.0, "luminance": 0.0},
                "highlights": {"hue": 45.0, "saturation": 4.0, "luminance": 0.0},
                "global": {"hue": 0.0, "saturation": 0.0, "luminance": 0.0},
                "blending": 50.0,
                "balance": 0.0,
            },
            "hsl_saturation": [4.0, 6.0, -4.0, -12.0, -5.0, 0.0, 0.0, 0.0],
            "hsl_luminance": [2.0, 8.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0], # Luminous skin
        },
    },

    "monochrome_fine_art": {
        "name": "Monochrome Fine Art",
        "description": "Exhibition grade Black & White: rich silver midtones, deep velvety blacks, enhanced local structure, and tactile analog grain.",
        "category": "Black & White",
        "adjustments": {
            "exposure": 0.05,
            "contrast": 26.0,
            "highlights": -14.0,
            "shadows": 16.0,
            "whites": 12.0,
            "blacks": -14.0,
            "saturation": -100.0,   # Pure black and white
            "vibrance": -100.0,
            "clarity": 28.0,
            "texture": 18.0,
            "dehaze": 14.0,
            "sigmoid_contrast": 1.76,
            "sigmoid_skew": -0.04,
            "tone_curve": create_point_curve([
                [0.0, 0.0],
                [0.22, 0.17],       # Anchor deep contrast
                [0.50, 0.49],
                [0.78, 0.83],       # Radiant silver highlights
                [1.0, 1.0],
            ]),
            "grain_amount": 24.0,
            "vignette_amount": -20.0,
            "vignette_feather": 60.0,
            "vignette_roundness": 10.0,
        },
    },
}


def find_preset(query: str) -> Dict[str, Any] | None:
    """Finds a preset by exact key, name, or case-insensitive fuzzy match."""
    q_norm = query.strip().lower().replace(" ", "_").replace("-", "_")
    if q_norm in PRESETS:
        return PRESETS[q_norm]

    for key, p in PRESETS.items():
        if q_norm == key or q_norm in key:
            return p
        if query.strip().lower() in p["name"].lower():
            return p

    return None
