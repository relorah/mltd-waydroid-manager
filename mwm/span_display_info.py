# SPDX-License-Identifier: MIT
"""Read-only display inventory for the experimental Gamescope span page."""
import json
import math
import re
from pathlib import Path

EDID_HEADER = bytes.fromhex("00ffffffffffff00")

def parse_edid(data):
    """Read safe, human-facing EDID fields; retain no serial number."""
    if len(data) < 128 or data[:8] != EDID_HEADER or sum(data[:128]) % 256:
        return None
    width_cm, height_cm = data[21], data[22]
    physical = (width_cm * 10, height_cm * 10) if 10 <= width_cm <= 300 and 10 <= height_cm <= 200 else None
    code = (data[8] << 8) | data[9]
    vendor = "".join(chr(((code >> shift) & 31) + 64) for shift in (10, 5, 0)) if code else ""
    product = int.from_bytes(data[10:12], "little")
    model = ""
    for offset in range(54, 126, 18):
        block = data[offset:offset + 18]
        if len(block) == 18 and block[:3] == b"\x00\x00\x00" and block[3] == 0xFC:
            model = block[5:18].decode("ascii", errors="replace").replace("\x00", "").replace("\n", " ").strip()
            break
    label = model or (f"{vendor} {product:04X}".strip() if vendor else "EDID monitor")
    return {"physical_mm": physical, "vendor": vendor, "product_code": product, "model": label}

def edid_physical_mm(data):
    info = parse_edid(data)
    return info["physical_mm"] if info else None

def read_edid_info(output_name, drm_root=Path("/sys/class/drm")):
    if not output_name or not re.fullmatch(r"[A-Za-z0-9._-]+", output_name):
        return None
    try:
        candidates = sorted(Path(drm_root).glob(f"card*-{output_name}/edid"))
    except OSError:
        return None
    for path in candidates:
        try:
            value = parse_edid(path.read_bytes())
        except OSError:
            continue
        if value:
            return value
    return None

def read_edid_mm(output_name, drm_root=Path("/sys/class/drm")):
    info = read_edid_info(output_name, drm_root)
    return info["physical_mm"] if info else None

def _rotation_quarter_turn(rotation):
    if isinstance(rotation, str):
        value = rotation.strip().lower()
        if value in ("left", "right", "90", "270"):
            return True
        if value in ("none", "normal", "inverted", "180", "0", ""):
            return False
        try:
            rotation = int(value, 0)
        except ValueError:
            return False
    try:
        value = int(rotation)
    except (TypeError, ValueError):
        return False
    # KScreen's Output::Rotation flags: None=1, Left=2, Inverted=4, Right=8.
    return value in (2, 8)

def logical_rect(output):
    size = output.get("size") or {}
    pos = output.get("pos") or {}
    scale = float(output.get("scale", 1))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid output scale")
    width = round(float(size["width"]) / scale)
    height = round(float(size["height"]) / scale)
    if _rotation_quarter_turn(output.get("rotation", 1)):
        width, height = height, width
    x, y = int(pos.get("x", 0)), int(pos.get("y", 0))
    if min(width, height) <= 0:
        raise ValueError("Invalid output dimensions")
    return x, y, width, height

def union_bounds(outputs):
    rects = [logical_rect(o) for o in outputs if o.get("enabled") and o.get("connected")]
    if len(rects) < 2:
        raise ValueError("Span Displays requires two enabled connected outputs")
    x = min(r[0] for r in rects); y = min(r[1] for r in rects)
    right = max(r[0] + r[2] for r in rects); bottom = max(r[1] + r[3] for r in rects)
    width, height = right - x, bottom - y
    if not 320 <= width <= 16384 or not 320 <= height <= 8192:
        raise ValueError("Unsupported display canvas")
    return dict(x=x, y=y, width=width, height=height)

def inventory(payload, drm_root=Path("/sys/class/drm")):
    data = json.loads(payload) if isinstance(payload, (str, bytes, bytearray)) else payload
    outputs = []
    for item in data.get("outputs", []):
        o = dict(item)
        edid = read_edid_info(o.get("name"), drm_root)
        o["edid_info"] = edid
        o["physical_mm"] = edid["physical_mm"] if edid else None
        try:
            o["logical_rect"] = logical_rect(o)
        except (ValueError, TypeError, KeyError, OverflowError):
            o["logical_rect"] = None
        modes = o.get("modes", [])
        active = next((m for m in modes if str(m.get("id")) == str(o.get("currentModeId", o.get("modeId")))), None)
        o["refresh_hz"] = active.get("refreshRate") if active else None
        outputs.append(o)
    return outputs


def physical_scale_plan(outputs, preserve_reference=False):
    """Recommend equal physical size per logical pixel without changing displays.

    Anchor the lowest density output at 100%; EDID millimetres are approximate.
    Use diagonal density to reduce centimetre rounding error in EDID dimensions.
    """
    active = [o for o in outputs if o.get("enabled") and o.get("connected")]
    if len(active) < 2:
        raise ValueError("Two active displays are required")
    densities = []
    for o in active:
        mm = o.get("physical_mm")
        size = o.get("size") or {}
        if not mm or len(mm) != 2 or any(not math.isfinite(float(v)) or float(v) <= 0 for v in mm):
            raise ValueError("Physical size unavailable for " + str(o.get("name")))
        w, h = float(size["width"]), float(size["height"])
        if not all(math.isfinite(v) and v > 0 for v in (w, h)):
            raise ValueError("Invalid display dimensions")
        densities.append(math.hypot(w, h) / math.hypot(*mm))
    reference = min(densities)
    reference_scale = float(active[densities.index(reference)].get("scale", 1)) if preserve_reference else 1.0
    if not math.isfinite(reference_scale) or not 1 <= reference_scale <= 3:
        raise ValueError("Unsupported reference scale")
    result = []
    for o, density in zip(active, densities):
        exact = density / reference * reference_scale
        scale = max(1.0, round(exact * 20) / 20)
        if scale > 3:
            raise ValueError("Recommended scale exceeds 300%")
        rect = logical_rect(dict(o, scale=scale))
        result.append(dict(name=o.get("name"), scale=scale,
                           exact_scale=exact, logical_width=rect[2], logical_height=rect[3],
                           residual_percent=(scale / exact - 1) * 100))
    return result


def matched_scale_layout(outputs, alignment="bottom"):
    """Match side-by-side monitors while preserving the reference's UI size."""
    if alignment not in ("top", "center", "bottom"):
        raise ValueError("Invalid monitor alignment")
    active = sorted([o for o in outputs if o.get("enabled") and o.get("connected")],
                    key=lambda o: logical_rect(o)[0])
    plan = physical_scale_plan(active, preserve_reference=True)
    rects = [logical_rect(o) for o in active]
    if any(_rotation_quarter_turn(o.get("rotation", 1)) for o in active):
        raise ValueError("Use OS display settings for rotated monitors")
    for left, right in zip(rects, rects[1:]):
        if right[0] < left[0] + left[2] - 2 or min(left[1]+left[3], right[1]+right[3]) <= max(left[1], right[1]):
            raise ValueError("Automatic matching requires side-by-side monitors")
    x, y = min(r[0] for r in rects), min(r[1] for r in rects)
    height = max(o["logical_height"] for o in plan)
    for item in plan:
        offset = height-item["logical_height"]
        item["x"], item["y"] = x, y + (round(offset/2) if alignment == "center" else offset if alignment == "bottom" else 0)
        x += item["logical_width"]
    return plan
