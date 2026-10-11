"""CalibRaw high-fidelity image export engine.

Renders full-resolution images from RAW (.CR3, .NEF, .ARW, .DNG) or raster formats
by applying all active adjustments from the companion .calibraw sidecar:
- White balance channel gains (Planckian daylight/tungsten CCT rebalancing)
- Linear exposure EV scaling
- Sigmoid & contrast tone curves
- Shadow/highlight/whites/blacks recovery LUT
- Clarity & texture (local micro-contrast)
- Vibrance & saturation
- Sharpening with edge masking
- Vignette falloff
- Geometry crop & rotation
- Optional Darktable CLI scene-referred demosaic bridge
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .metadata import is_raw_file
from .sidecar import load_sidecar, sidecar_path_for_raw
from .white_balance import estimate_as_shot_kelvin, wb_channel_gains

import os

def find_darktable_cli() -> Optional[Path]:
    """Finds darktable-cli executable across operating systems."""
    env_path = os.getenv("DARKTABLE_CLI")
    if env_path and Path(env_path).exists():
        return Path(env_path).resolve()
    which = shutil.which("darktable-cli")
    if which:
        return Path(which).resolve()
    candidates = [
        Path(r"C:\Program Files\darktable\bin\darktable-cli.exe"),
        Path("/usr/bin/darktable-cli"),
        Path("/usr/local/bin/darktable-cli"),
        Path("/Applications/darktable.app/Contents/MacOS/darktable-cli"),
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


def _build_shadow_highlight_lut(
    highlights: float = 0.0,
    shadows: float = 0.0,
    whites: float = 0.0,
    blacks: float = 0.0,
) -> np.ndarray:
    """Builds an 8-bit LUT for highlights, shadows, whites, and blacks."""
    lut = np.arange(256, dtype=np.float32)

    # Whites & blacks shift endpoints
    white_point = 255.0 * (1.0 - whites / 200.0)
    black_point = 255.0 * (-blacks / 200.0)
    lut = (lut - black_point) / max(1.0, (white_point - black_point)) * 255.0

    # Highlights: pull down top end
    hl = highlights / 100.0
    mask_hl = lut / 255.0
    lut = lut - hl * (mask_hl ** 2) * 80.0

    # Shadows: lift bottom end
    sh = shadows / 100.0
    mask_sh = 1.0 - lut / 255.0
    lut = lut + sh * (mask_sh ** 2) * 80.0

    return np.clip(lut, 0, 255).astype(np.uint8)


def _apply_vignette(
    img: Image.Image,
    amount: float,
    midpoint: float = 50.0,
    feather: float = 50.0,
    roundness: float = 0.0,
) -> Image.Image:
    """Applies perceptual vignette falloff."""
    if abs(amount) < 1.0:
        return img
    w, h = img.size
    y_idx, x_idx = np.ogrid[:h, :w]
    cx, cy = w / 2.0, h / 2.0

    # Aspect ratio adjustment based on roundness (-100 = rectangle, 0 = oval, +100 = circle)
    aspect = (w / h) if roundness > 0 else 1.0
    dist = np.sqrt(((x_idx - cx) / cx * aspect) ** 2 + ((y_idx - cy) / cy) ** 2)

    # Falloff mapping
    mid = max(0.05, midpoint / 100.0)
    edge = np.clip((dist - mid) / max(0.05, feather / 100.0), 0.0, 1.0) ** 1.5

    arr = np.array(img, dtype=np.float32)
    factor = abs(amount) / 100.0
    if amount < 0:
        multiplier = 1.0 - edge * factor
    else:
        multiplier = 1.0 + edge * factor * 0.5

    arr = arr * multiplier[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _apply_clarity(img: Image.Image, clarity: float) -> Image.Image:
    if abs(clarity) < 1.0:
        return img
    amount = abs(clarity) / 100.0
    if clarity > 0:
        return img.filter(ImageFilter.UnsharpMask(radius=30, percent=int(amount * 75), threshold=2))
    else:
        return img.filter(ImageFilter.GaussianBlur(radius=amount * 3))


def _apply_vibrance(img: Image.Image, vibrance: float) -> Image.Image:
    if abs(vibrance) < 1.0:
        return img
    arr = np.array(img, dtype=np.float32) / 255.0
    hsv_like_sat = arr.max(axis=2) - arr.min(axis=2)
    boost = (vibrance / 100.0) * (1.0 - hsv_like_sat[..., None])
    grey = arr.mean(axis=2, keepdims=True)
    arr = arr + (arr - grey) * boost
    return Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8))


def _apply_sigmoid(arr: np.ndarray, contrast: float = 1.5) -> np.ndarray:
    """Applies a smooth sigmoid tone curve in normalized [0, 1] space."""
    if abs(contrast - 1.0) < 0.05:
        return arr
    # Centered logistic sigmoid
    k = max(0.5, min(3.5, contrast))
    x = arr - 0.5
    y = 1.0 / (1.0 + np.exp(-4.0 * k * x))
    # Normalize back to [0, 1]
    y_min = 1.0 / (1.0 + np.exp(2.0 * k))
    y_max = 1.0 / (1.0 + np.exp(-2.0 * k))
    return np.clip((y - y_min) / (y_max - y_min), 0.0, 1.0)


def render_calibraw_image(
    source_path: Union[str, Path],
    sidecar_doc: Optional[Dict[str, Any]] = None,
    use_darktable_base: bool = False,
    max_dimension: Optional[int] = None,
) -> Image.Image:
    """Renders a fully graded image from source file and .calibraw document."""
    src = Path(source_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {src}")

    if sidecar_doc is None:
        sidecar_doc, _ = load_sidecar(src)

    exp = sidecar_doc.get("edits", {}).get("exposure", {})
    geom = sidecar_doc.get("edits", {}).get("geometry", {})

    img: Image.Image

    # 1. Base Demosaic
    if is_raw_file(src):
        # If darktable is requested and available, use darktable-cli to produce a clean base
        dt_bin = find_darktable_cli()
        if use_darktable_base and dt_bin:
            temp_dt_export = src.parent / f".tmp_{src.stem}_dt_base.jpg"
            cmd = [
                str(dt_bin),
                src.as_posix(),
                temp_dt_export.as_posix(),
                "--hq", "true",
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if res.returncode == 0 and temp_dt_export.exists():
                    img = Image.open(temp_dt_export).convert("RGB")
                    temp_dt_export.unlink(missing_ok=True)
                else:
                    img = _demosaic_rawpy(src, exp)
            except Exception:
                img = _demosaic_rawpy(src, exp)
        else:
            img = _demosaic_rawpy(src, exp)
    else:
        img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")

    # 2. Tone LUT: Highlights, Shadows, Whites, Blacks
    hl = float(exp.get("highlights", 0.0))
    sh = float(exp.get("shadows", 0.0))
    wh = float(exp.get("whites", 0.0))
    bl = float(exp.get("blacks", 0.0))
    if any([hl, sh, wh, bl]):
        lut = _build_shadow_highlight_lut(hl, sh, wh, bl)
        arr = np.array(img)
        img = Image.fromarray(lut[arr])

    # 3. Sigmoid Tone Mapping
    sig_contrast = float(exp.get("sigmoid", {}).get("contrast", 1.5))
    if sig_contrast > 1.05 or sig_contrast < 0.95:
        arr_f = np.array(img, dtype=np.float32) / 255.0
        arr_f = _apply_sigmoid(arr_f, sig_contrast)
        img = Image.fromarray((arr_f * 255.0).astype(np.uint8))

    # 4. Global Contrast & Exposure fine adjustment
    contrast = float(exp.get("contrast", 0.0))
    if contrast != 0.0:
        factor = 1.0 + contrast / 100.0
        img = ImageEnhance.Contrast(img).enhance(max(0.0, factor))

    # 5. Presence: Texture, Clarity, Dehaze
    clarity = float(exp.get("clarity", 0.0))
    if clarity != 0.0:
        img = _apply_clarity(img, clarity)

    # 6. Color: Saturation & Vibrance
    sat = float(exp.get("saturation", 0.0))
    if sat != 0.0:
        factor = 1.0 + sat / 100.0
        img = ImageEnhance.Color(img).enhance(max(0.0, factor))

    vibrance = float(exp.get("vibrance", 0.0))
    if vibrance != 0.0:
        img = _apply_vibrance(img, vibrance)

    # 7. Sharpening
    sharpen_amount = float(exp.get("sharpen_amount", 40.0))
    if sharpen_amount > 10.0:
        radius = float(exp.get("sharpen_radius", 1.0))
        masking = int(exp.get("sharpen_masking", 0.0))
        percent = int(sharpen_amount * 1.5)
        img = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=masking))

    # 8. Geometry: Rotation and Crop
    rot = float(geom.get("rotation_degrees", 0.0))
    if abs(rot) > 0.05:
        img = img.rotate(-rot, expand=True, resample=Image.BICUBIC)

    crop = geom.get("crop", [0.0, 0.0, 1.0, 1.0])
    if len(crop) == 4 and (crop[0] > 0 or crop[1] > 0 or crop[2] < 1 or crop[3] < 1):
        w, h = img.size
        box = (
            int(crop[0] * w),
            int(crop[1] * h),
            int(crop[2] * w),
            int(crop[3] * h),
        )
        if box[2] > box[0] and box[3] > box[1]:
            img = img.crop(box)

    # 9. Vignette
    vignette = float(exp.get("vignette_amount", 0.0))
    if abs(vignette) > 1.0:
        img = _apply_vignette(
            img,
            vignette,
            midpoint=float(exp.get("vignette_midpoint", 50.0)),
            feather=float(exp.get("vignette_feather", 50.0)),
            roundness=float(exp.get("vignette_roundness", 0.0)),
        )

    # 10. Max dimension resize if requested
    if max_dimension and max(img.size) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    return img


def _demosaic_rawpy(src: Path, exp: Dict[str, Any]) -> Image.Image:
    """High-fidelity demosaic using rawpy with camera WB and Planckian gains."""
    import rawpy

    ev = float(exp.get("exposure", 0.0))
    linear_exp_mult = 2.0 ** ev

    with rawpy.imread(str(src)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            output_color=rawpy.ColorSpace.sRGB,
            no_auto_bright=False,  # Calibrated white-point normalization
            exp_shift=linear_exp_mult,
            bright=1.0,
            output_bps=8,
            demosaic_algorithm=rawpy.DemosaicAlgorithm.DHT,
        )

    # Apply White Balance offset if specified
    temp_offset = float(exp.get("temperature", 0.0))
    tint_offset = float(exp.get("tint", 0.0))
    if abs(temp_offset) > 0.5 or abs(tint_offset) > 0.5:
        base_k, _ = estimate_as_shot_kelvin(str(src))
        gains = wb_channel_gains(base_k, temp_offset, tint_offset)
        rgb_f = rgb.astype(np.float32)
        rgb_f[..., 0] = np.clip(rgb_f[..., 0] * gains[0], 0, 255)
        rgb_f[..., 1] = np.clip(rgb_f[..., 1] * gains[1], 0, 255)
        rgb_f[..., 2] = np.clip(rgb_f[..., 2] * gains[2], 0, 255)
        rgb = rgb_f.astype(np.uint8)

    return Image.fromarray(rgb)


def export_image(
    image_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    format: str = "jpeg",
    quality: int = 95,
    max_dimension: Optional[int] = None,
    use_darktable_cli: bool = False,
) -> Dict[str, Any]:
    """Renders and exports an image with all active CalibRaw sidecar edits."""
    src = Path(image_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source image not found: {src}")

    # Determine output path
    fmt = format.lower()
    if fmt in ("jpg", "jpeg"):
        ext = ".jpg"
    elif fmt == "png":
        ext = ".png"
    elif fmt in ("tif", "tiff"):
        ext = ".tif"
    else:
        ext = ".jpg"

    if output_path:
        out_p = Path(output_path).resolve()
        if not out_p.suffix:
            out_p = out_p.with_suffix(ext)
    else:
        out_dir = src.parent.parent / "Exports" if src.parent.name in ("Originals", "originals") else src.parent / "Exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_p = out_dir / f"{src.stem}_CalibRaw{ext}"

    out_p.parent.mkdir(parents=True, exist_ok=True)

    # Render image
    rendered = render_calibraw_image(
        source_path=src,
        use_darktable_base=use_darktable_cli,
        max_dimension=max_dimension,
    )

    # Save
    save_kwargs: Dict[str, Any] = {}
    if ext == ".jpg":
        save_kwargs = {
            "format": "JPEG",
            "quality": max(1, min(100, quality)),
            "optimize": True,
            "subsampling": 0,  # 4:4:4 chroma subsampling for photographic fidelity
        }
    elif ext == ".png":
        save_kwargs = {"format": "PNG", "optimize": True}
    elif ext == ".tif":
        save_kwargs = {"format": "TIFF"}

    rendered.save(out_p, **save_kwargs)

    size_mb = round(out_p.stat().st_size / (1024 * 1024), 2)
    return {
        "status": "success",
        "source": str(src),
        "output_path": str(out_p),
        "format": ext[1:].upper(),
        "dimensions": [rendered.width, rendered.height],
        "size_mb": size_mb,
        "engine": "CalibRaw High-Fidelity Rendering Pipeline",
    }
