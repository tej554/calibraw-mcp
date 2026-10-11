"""RAW / raster metadata extraction (camera, lens, exposure, WB, dimensions)."""

from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Optional

RAW_EXTENSIONS = {
    ".cr3", ".cr2", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".raf", ".orf",
    ".rw2", ".pef", ".srw", ".3fr", ".iiq", ".x3f", ".erf", ".mos", ".kdc", ".rwl",
}
RASTER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}

_EXIF_TAGS = {
    0x010F: "camera_make",
    0x0110: "camera_model",
    0x0112: "orientation",
    0x0131: "software",
    0x013B: "artist",
}
_EXIF_IFD_TAGS = {
    0x829A: "exposure_time",
    0x829D: "f_number",
    0x8827: "iso",
    0x9003: "date_time_original",
    0x9204: "exposure_bias_ev",
    0x9209: "flash",
    0x920A: "focal_length_mm",
    0xA405: "focal_length_35mm",
    0xA434: "lens_model",
    0xA433: "lens_make",
    0xA431: "body_serial",
}


def is_raw_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in RAW_EXTENSIONS


def _to_python(value: Any) -> Any:
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", "ignore").strip("\x00 ").strip()
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            return float(value) if value.denominator else None
        if isinstance(value, tuple):
            return [_to_python(v) for v in value]
        if isinstance(value, str):
            return value.strip("\x00 ").strip()
        return value
    except Exception:
        return str(value)


def _exif_from_pil(image) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        exif = image.getexif()
    except Exception:
        return out
    for tag, key in _EXIF_TAGS.items():
        if tag in exif:
            out[key] = _to_python(exif[tag])
    try:
        sub = exif.get_ifd(0x8769)
        for tag, key in _EXIF_IFD_TAGS.items():
            if tag in sub:
                out[key] = _to_python(sub[tag])
    except Exception:
        pass
    return out


def _format_shutter(seconds: Optional[float]) -> Optional[str]:
    if not seconds:
        return None
    if seconds >= 1:
        return f"{seconds:g}s"
    frac = Fraction(seconds).limit_denominator(16000)
    return f"1/{round(frac.denominator / frac.numerator)}s" if frac.numerator else None


def get_image_metadata(image_path: str | Path) -> Dict[str, Any]:
    p = Path(image_path).resolve()
    info: Dict[str, Any] = {
        "path": str(p),
        "name": p.name,
        "type": "raw" if is_raw_file(p) else "raster",
        "file_size_mb": round(p.stat().st_size / (1024 * 1024), 2),
    }
    exif: Dict[str, Any] = {}

    if is_raw_file(p):
        import rawpy

        with rawpy.imread(str(p)) as raw:
            sizes = raw.sizes
            flip = sizes.flip
            width, height = sizes.width, sizes.height
            if flip in (5, 6):
                width, height = height, width
            info.update({
                "width": int(width),
                "height": int(height),
                "megapixels": round(width * height / 1e6, 1),
                "raw_sensor_size": [int(sizes.raw_width), int(sizes.raw_height)],
                "color_description": raw.color_desc.decode("ascii", "ignore"),
                "num_colors": int(raw.num_colors),
                "black_level_per_channel": [int(v) for v in raw.black_level_per_channel],
                "white_level": int(raw.white_level),
                "as_shot_wb_multipliers": [round(float(v), 5) for v in raw.camera_whitebalance],
                "daylight_wb_multipliers": [round(float(v), 5) for v in raw.daylight_whitebalance],
            })
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    from PIL import Image

                    with Image.open(io.BytesIO(thumb.data)) as preview:
                        exif = _exif_from_pil(preview)
                        info["embedded_preview_size"] = list(preview.size)
            except Exception:
                pass

        if not exif.get("camera_model"):
            try:
                import exifread

                with open(p, "rb") as handle:
                    tags = exifread.process_file(handle, details=False)
                mapping = {
                    "Image Make": "camera_make", "Image Model": "camera_model",
                    "EXIF ExposureTime": "exposure_time", "EXIF FNumber": "f_number",
                    "EXIF ISOSpeedRatings": "iso", "EXIF FocalLength": "focal_length_mm",
                    "EXIF LensModel": "lens_model", "EXIF DateTimeOriginal": "date_time_original",
                }
                for tag, key in mapping.items():
                    if tag in tags and key not in exif:
                        val = tags[tag].values
                        val = val[0] if isinstance(val, list) and val else val
                        exif[key] = _to_python(val) if not hasattr(val, "num") else (val.num / val.den if val.den else None)
            except Exception:
                pass

        from .white_balance import estimate_as_shot_kelvin

        kelvin, method = estimate_as_shot_kelvin(str(p))
        info["as_shot_kelvin_estimate"] = kelvin
        info["as_shot_kelvin_method"] = method
    else:
        from PIL import Image, ImageOps

        with Image.open(p) as img:
            upright = ImageOps.exif_transpose(img)
            info.update({
                "width": upright.width,
                "height": upright.height,
                "megapixels": round(upright.width * upright.height / 1e6, 1),
                "mode": img.mode,
            })
            exif = _exif_from_pil(img)

    info.update({k: v for k, v in exif.items() if v not in (None, "", [])})
    if "exposure_time" in info and isinstance(info["exposure_time"], (int, float)):
        info["shutter_speed"] = _format_shutter(float(info["exposure_time"]))
    if "f_number" in info and isinstance(info["f_number"], (int, float)):
        info["aperture"] = f"f/{float(info['f_number']):.1f}"
    if isinstance(info.get("iso"), list):
        info["iso"] = info["iso"][0] if info["iso"] else None
    return info
