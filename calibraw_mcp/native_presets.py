"""CalibRaw native preset manager (.calibraw-preset).

Conforms strictly to CalibRaw's native preset file format:
- Format string: "CalibRaw preset"
- Schema version: 1
- File suffix: ".calibraw-preset"
- Category masking via EditSelection (AdjustmentGroupSet + raw/geometry/masks/lens flags).
- Portable mask filtering (omits per-image brush rasters/depth).
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .sidecar import default_sidecar, load_sidecar, save_sidecar
from .transfer import default_edit_selection, normalize_selection, transfer_edits

PRESET_FORMAT = "CalibRaw preset"
PRESET_SCHEMA_VERSION = 1
PRESET_SUFFIX = ".calibraw-preset"
DEFAULT_PRESET_GROUP = "User Presets"
MAX_PRESET_NAME_CHARS = 64
MAX_PRESET_BYTES = 4 * 1024 * 1024

USER_PRESETS_DIR = (
    Path(os.getenv("APPDATA", "")) / "calibraw" / "presets"
    if os.name == "nt" and os.getenv("APPDATA")
    else Path.home() / ".config" / "calibraw" / "presets"
)


def _standard_preset_directories() -> List[Path]:
    dirs = [USER_PRESETS_DIR, Path.cwd() / "presets", Path.cwd()]
    env_dir = os.getenv("CALIBRAW_PRESETS_DIR")
    if env_dir:
        dirs.insert(0, Path(env_dir))
    return [d.resolve() for d in dirs if d.exists()]


def _resolve_preset_path(path_or_name: str | Path, search_dir: Optional[Path] = None) -> Path:
    p = Path(path_or_name)
    if p.exists() and p.is_file():
        return p.resolve()

    name = p.name
    if not name.lower().endswith(PRESET_SUFFIX):
        name = name + PRESET_SUFFIX

    candidates = []
    if search_dir:
        candidates.append(search_dir / name)
    for d in _standard_preset_directories():
        candidates.append(d / name)

    for cand in candidates:
        if cand.exists():
            return cand.resolve()

    # Search in directories
    for root in _standard_preset_directories():
        try:
            for match in root.rglob(f"*{name}"):
                return match.resolve()
        except Exception:
            pass

    raise FileNotFoundError(f"Native preset not found: {path_or_name}")


def create_native_preset_document(
    name: str,
    edits: Dict[str, Any],
    selection: Optional[Dict[str, Any]] = None,
    group: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds a PresetDocument matching ``crates/calibraw-core/src/presets.rs``."""
    name = str(name).strip()
    if not name:
        raise ValueError("Preset name cannot be empty")
    if len(name) > MAX_PRESET_NAME_CHARS:
        name = name[:MAX_PRESET_NAME_CHARS]

    group = str(group or DEFAULT_PRESET_GROUP).strip() or DEFAULT_PRESET_GROUP
    sel = normalize_selection(selection)

    # Capture only selected categories into a clean default state
    captured_doc = default_sidecar()
    source_wrap = {"edits": edits if "exposure" in edits else edits.get("edits", {})}
    transferred = transfer_edits(captured_doc, source_wrap, sel, paste_mode="replace")

    # Clean up non-portable mask elements (rasters, scene depth)
    masks_obj = transferred["edits"].get("masks", {})
    if "scene_depth" in masks_obj:
        masks_obj["scene_depth"] = None
    transferred["edits"]["ai_masks_need_update"] = False

    return {
        "format": PRESET_FORMAT,
        "schema_version": PRESET_SCHEMA_VERSION,
        "name": name,
        "group": group,
        "selection": sel,
        "edits": transferred["edits"],
    }


def load_native_preset(preset_path: str | Path) -> Dict[str, Any]:
    """Loads and validates a ``.calibraw-preset`` file."""
    p = _resolve_preset_path(preset_path)
    size = p.stat().st_size
    if size > MAX_PRESET_BYTES:
        raise ValueError(f"Preset file is {size} bytes, exceeds 4MB limit.")

    with open(p, "r", encoding="utf-8") as f:
        doc = json.load(f)

    if doc.get("format") != PRESET_FORMAT:
        raise ValueError(f"Not a valid CalibRaw preset: format is '{doc.get('format')}'")
    if doc.get("schema_version") != PRESET_SCHEMA_VERSION:
        raise ValueError(f"Unsupported preset schema version: {doc.get('schema_version')}")

    return doc


def save_native_preset(
    output_path: str | Path,
    name: str,
    edits: Dict[str, Any],
    selection: Optional[Dict[str, Any]] = None,
    group: Optional[str] = None,
) -> Path:
    """Atomically saves a ``.calibraw-preset`` file."""
    doc = create_native_preset_document(name, edits, selection, group)
    out_p = Path(output_path).resolve()
    if not out_p.name.lower().endswith(PRESET_SUFFIX):
        out_p = out_p.with_name(out_p.name + PRESET_SUFFIX)

    out_p.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(out_p.parent),
        prefix=f".{out_p.name}.tmp-",
    )
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, out_p)
    return out_p


def apply_native_preset_to_image(
    image_path: str | Path,
    preset_path_or_doc: Union[str, Path, Dict[str, Any]],
) -> Dict[str, Any]:
    """Applies a native preset to an image's .calibraw sidecar using category masking."""
    if isinstance(preset_path_or_doc, (str, Path)):
        preset_doc = load_native_preset(preset_path_or_doc)
    else:
        preset_doc = preset_path_or_doc

    image_path = Path(image_path).resolve()
    dest_doc, _ = load_sidecar(image_path)

    selection = preset_doc.get("selection", default_edit_selection(True))
    preset_edits = {"edits": preset_doc.get("edits", {})}

    updated_doc = transfer_edits(dest_doc, preset_edits, selection, paste_mode="merge")
    saved_path = save_sidecar(image_path, updated_doc)

    return {
        "status": "success",
        "image_path": str(image_path),
        "sidecar_path": str(saved_path),
        "preset_name": preset_doc.get("name"),
        "preset_group": preset_doc.get("group"),
        "selection_applied": selection,
    }


def list_native_presets(preset_dirs: Optional[List[Union[str, Path]]] = None) -> List[Dict[str, Any]]:
    """Discovers all `.calibraw-preset` files across standard directories."""
    dirs = _standard_preset_directories()
    if preset_dirs:
        dirs = [Path(d) for d in preset_dirs] + dirs

    presets = []
    seen_paths = set()

    for d in dirs:
        if not d.exists():
            continue
        for p in d.rglob(f"*{PRESET_SUFFIX}"):
            res = p.resolve()
            if res in seen_paths:
                continue
            seen_paths.add(res)
            try:
                doc = load_native_preset(res)
                presets.append({
                    "name": doc.get("name", p.stem),
                    "group": doc.get("group", DEFAULT_PRESET_GROUP),
                    "path": str(res),
                    "selection": doc.get("selection", {}),
                    "size_bytes": res.stat().st_size,
                })
            except Exception:
                pass

    return presets
