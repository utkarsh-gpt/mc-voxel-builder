#!/usr/bin/env python3
"""Build a Minecraft Java block-colour dataset for voxel-to-block mapping.

Reads the official client jar (or a pre-extracted assets tree) for a given
release, uses blockstate and model JSON to resolve each in-scope block's face
textures, and writes per-face / overall colour statistics.

Canonical averages are computed in OKLab (then converted back to sRGB, CIELAB
and OKLCh). That avoids the dark bias of naïve sRGB means and keeps gradient
interpolation perceptually even.

Usage:
    python3 block_colors.py
    python3 block_colors.py --jar raw/client-26.3.jar --out .
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Version / tints
# ---------------------------------------------------------------------------

MC_VERSION = "26.3"
CLIENT_SHA1 = "e877b6a07acd633fb3bb475002175cec036e7b87"
CLIENT_URL = (
    "https://piston-data.mojang.com/v1/objects/"
    f"{CLIENT_SHA1}/client.jar"
)
MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

# Official default plains biome tints (Java Edition). Hardcoded by the game
# rather than sampled from the colormap PNG.
TINTS = {
    "grass": (0x91, 0xBD, 0x59),
    "foliage": (0x77, 0xAB, 0x2F),
    "birch_leaves": (0x80, 0xA7, 0x55),
    "spruce_leaves": (0x61, 0x99, 0x61),
    "lily_pad": (0x20, 0x80, 0x30),
    "dry_foliage": (0xA3, 0x73, 0x46),  # plains dry-foliage colormap sample
}

# Light levels for included light-emitting full blocks (Java wiki, 26.3).
# Furnaces etc. are stored unlit (0) with light_level_lit set separately.
LIGHT_LEVELS = {
    "glowstone": 15,
    "sea_lantern": 15,
    "shroomlight": 15,
    "ochre_froglight": 15,
    "verdant_froglight": 15,
    "pearlescent_froglight": 15,
    "jack_o_lantern": 15,
    "crying_obsidian": 10,
    "magma_block": 3,
    "sculk_catalyst": 6,
}
LIGHT_LEVEL_LIT = {
    "furnace": 13,
    "blast_furnace": 13,
    "smoker": 13,
}

GRAVITY_BLOCKS = {
    "sand", "red_sand", "gravel",
    "suspicious_sand", "suspicious_gravel",
}

DYE_COLORS = (
    "white", "orange", "magenta", "light_blue", "yellow", "lime", "pink",
    "gray", "light_gray", "cyan", "purple", "blue", "brown", "green", "red",
    "black",
)

WOOD_TYPES = (
    "pale_oak", "dark_oak", "poplar", "mangrove", "cherry", "bamboo",
    "crimson", "warped", "acacia", "spruce", "birch", "jungle", "oak",
)

# ---------------------------------------------------------------------------
# Colour science
# ---------------------------------------------------------------------------

def srgb8_to_linear(c: np.ndarray) -> np.ndarray:
    x = c / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb8(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    a = np.where(
        x <= 0.0031308,
        12.92 * x,
        1.055 * np.power(x, 1 / 2.4) - 0.055,
    )
    return np.clip(np.rint(a * 255.0), 0, 255).astype(np.int32)


def linear_to_xyz(lin: np.ndarray) -> np.ndarray:
    # sRGB D65 matrix (IEC 61966-2-1)
    m = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ], dtype=np.float64)
    return lin @ m.T


def xyz_to_linear(xyz: np.ndarray) -> np.ndarray:
    m = np.array([
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ], dtype=np.float64)
    return xyz @ m.T


# D65 white point (CIE 1931 2°)
_XN, _YN, _ZN = 0.95047, 1.00000, 1.08883
_DELTA = 6 / 29
_DELTA_C3 = _DELTA ** 3


def _lab_f(t: np.ndarray) -> np.ndarray:
    return np.where(
        t > _DELTA_C3,
        np.cbrt(t),
        t / (3 * _DELTA ** 2) + 4 / 29,
    )


def _lab_f_inv(t: np.ndarray) -> np.ndarray:
    return np.where(
        t > _DELTA,
        t ** 3,
        3 * _DELTA ** 2 * (t - 4 / 29),
    )


def xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    x, y, z = xyz[..., 0] / _XN, xyz[..., 1] / _YN, xyz[..., 2] / _ZN
    fx, fy, fz = _lab_f(x), _lab_f(y), _lab_f(z)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)
    return np.stack([L, a, b], axis=-1)


def lab_to_xyz(lab: np.ndarray) -> np.ndarray:
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    x = _XN * _lab_f_inv(fx)
    y = _YN * _lab_f_inv(fy)
    z = _ZN * _lab_f_inv(fz)
    return np.stack([x, y, z], axis=-1)


def srgb8_to_lab(rgb: np.ndarray) -> np.ndarray:
    return xyz_to_lab(linear_to_xyz(srgb8_to_linear(rgb)))


def lab_to_srgb8(lab: np.ndarray) -> np.ndarray:
    return linear_to_srgb8(xyz_to_linear(lab_to_xyz(lab)))


# OKLab, Björn Ottosson (https://bottosson.github.io/posts/oklab/)
# M1 here is the linear-sRGB → LMS matrix (not the XYZ → LMS matrix).
_M1_SRGB = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
], dtype=np.float64)
_M2 = np.array([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050, 0.4505937099],
    [0.0259040371, 0.7827717662, -0.8086757660],
], dtype=np.float64)
_M1_SRGB_INV = np.linalg.inv(_M1_SRGB)
_M2_INV = np.linalg.inv(_M2)


def linear_to_oklab(lin: np.ndarray) -> np.ndarray:
    lms = lin @ _M1_SRGB.T
    lms_c = np.sign(lms) * np.cbrt(np.abs(lms))
    return lms_c @ _M2.T


def oklab_to_linear(ok: np.ndarray) -> np.ndarray:
    lms_c = ok @ _M2_INV.T
    lms = lms_c ** 3
    return lms @ _M1_SRGB_INV.T


def srgb8_to_oklab(rgb: np.ndarray) -> np.ndarray:
    return linear_to_oklab(srgb8_to_linear(rgb))


def oklab_to_srgb8(ok: np.ndarray) -> np.ndarray:
    return linear_to_srgb8(oklab_to_linear(ok))


def oklab_to_oklch(ok: np.ndarray) -> np.ndarray:
    L, a, b = ok[..., 0], ok[..., 1], ok[..., 2]
    C = np.sqrt(a * a + b * b)
    h = (np.degrees(np.arctan2(b, a)) + 360.0) % 360.0
    h = np.where(C < 1e-8, np.nan, h)
    return np.stack([L, C, h], axis=-1)


def hex_from_rgb(rgb) -> str:
    r, g, b = (int(x) for x in np.clip(np.rint(rgb), 0, 255))
    return f"#{r:02X}{g:02X}{b:02X}"


def rgb_from_hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ciede2000(lab1, lab2, kL=1.0, kC=1.0, kH=1.0) -> float:
    """CIEDE2000 colour difference of two CIE L*a*b* colours."""
    L1, a1, b1 = [float(x) for x in lab1]
    L2, a2, b2 = [float(x) for x in lab2]
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    Cbar = (C1 + C2) / 2.0
    C7 = Cbar ** 7
    G = 0.5 * (1.0 - math.sqrt(C7 / (C7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    def _hp(ap, b, Cp):
        if Cp == 0:
            return 0.0
        h = math.degrees(math.atan2(b, ap))
        return h + 360.0 if h < 0 else h

    h1p, h2p = _hp(a1p, b1, C1p), _hp(a2p, b2, C2p)
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2.0))
    Lbarp = (L1 + L2) / 2.0
    Cbarp = (C1p + C2p) / 2.0
    if C1p * C2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbarp = (h1p + h2p) / 2.0
    elif h1p + h2p < 360:
        hbarp = (h1p + h2p + 360) / 2.0
    else:
        hbarp = (h1p + h2p - 360) / 2.0
    T = (
        1
        - 0.17 * math.cos(math.radians(hbarp - 30))
        + 0.24 * math.cos(math.radians(2 * hbarp))
        + 0.32 * math.cos(math.radians(3 * hbarp + 6))
        - 0.20 * math.cos(math.radians(4 * hbarp - 63))
    )
    dtheta = 30 * math.exp(-(((hbarp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbarp ** 7 / (Cbarp ** 7 + 25 ** 7))
    Sl = 1 + (0.015 * (Lbarp - 50) ** 2) / math.sqrt(20 + (Lbarp - 50) ** 2)
    Sc = 1 + 0.045 * Cbarp
    Sh = 1 + 0.015 * Cbarp * T
    Rt = -math.sin(math.radians(2 * dtheta)) * Rc
    return math.sqrt(
        (dLp / (kL * Sl)) ** 2
        + (dCp / (kC * Sc)) ** 2
        + (dHp / (kH * Sh)) ** 2
        + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh))
    )


def _selftest_color():
    white = srgb8_to_lab(np.array([255, 255, 255], dtype=np.float64))
    assert abs(white[0] - 100) < 0.02, white
    assert abs(white[1]) < 0.05 and abs(white[2]) < 0.05, white
    d = ciede2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485))
    assert abs(d - 2.0425) < 0.001, d
    okw = srgb8_to_oklab(np.array([255, 255, 255], dtype=np.float64))
    assert abs(okw[0] - 1.0) < 0.002, okw
    sample = np.array([207, 213, 214], dtype=np.float64)
    back = lab_to_srgb8(srgb8_to_lab(sample))
    assert np.max(np.abs(back - sample)) <= 1, back
    back = oklab_to_srgb8(srgb8_to_oklab(sample))
    assert np.max(np.abs(back - sample)) <= 1, back

# ---------------------------------------------------------------------------
# Texture I/O
# ---------------------------------------------------------------------------

def norm_tex_path(ref: str) -> str | None:
    if not ref or ref.startswith("#"):
        return None
    ref = ref.replace("minecraft:", "")
    if ref.startswith("block/"):
        ref = ref[len("block/"):]
    if ref.startswith("textures/block/"):
        ref = ref[len("textures/block/"):]
    return ref


def load_mcmeta(path: Path) -> dict | None:
    meta = path.with_name(path.name + ".mcmeta")
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text())
    except json.JSONDecodeError:
        return None


def frame_indices_and_weights(img_h: int, img_w: int, mcmeta: dict | None):
    n_natural = img_h // img_w if img_w and img_h >= img_w and img_h % img_w == 0 else 1
    if not mcmeta or "animation" not in mcmeta:
        return [0], [1.0], n_natural == 1 and img_h == img_w
    anim = mcmeta["animation"]
    frametime = int(anim.get("frametime", 1))
    frames = anim.get("frames")
    if not frames:
        idxs = list(range(n_natural))
        weights = [frametime] * len(idxs)
    else:
        idxs, weights = [], []
        for fr in frames:
            if isinstance(fr, int):
                idxs.append(fr)
                weights.append(frametime)
            elif isinstance(fr, dict):
                idxs.append(int(fr.get("index", 0)))
                weights.append(int(fr.get("time", frametime)))
    return idxs, weights, False


def load_texture_rgba(tex_dir: Path, name: str) -> tuple[np.ndarray, dict]:
    """Return a time-averaged RGBA uint8 image (one frame's size) plus meta."""
    path = tex_dir / f"{name}.png"
    if not path.exists():
        raise FileNotFoundError(name)
    img = Image.open(path).convert("RGBA")
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    mcmeta = load_mcmeta(path)
    idxs, weights, is_static = frame_indices_and_weights(h, w, mcmeta)
    if is_static or (h == w and (not mcmeta or "animation" not in (mcmeta or {}))):
        meta = {"animated": False, "frame_count": 1, "path": f"minecraft:block/{name}"}
        return arr, meta
    fw = w
    frames, ws = [], []
    for i, wt in zip(idxs, weights):
        y0 = i * fw
        if y0 + fw > h:
            continue
        frames.append(arr[y0:y0 + fw, :, :])
        ws.append(wt)
    if not frames:
        return arr[: min(h, w), :w, :], {
            "animated": False, "frame_count": 1, "path": f"minecraft:block/{name}"
        }
    stack = np.stack(frames, axis=0).astype(np.float64)
    wts = np.array(ws, dtype=np.float64)[:, None, None]
    wsum = wts.sum()
    lin = srgb8_to_linear(stack[..., :3])
    lin_avg = (lin * wts[..., None]).sum(axis=0) / wsum
    a_avg = (stack[..., 3] * wts).sum(axis=0) / wsum
    out = np.empty(frames[0].shape, dtype=np.uint8)
    out[..., :3] = linear_to_srgb8(lin_avg)
    out[..., 3] = np.clip(np.rint(a_avg), 0, 255).astype(np.uint8)
    meta = {
        "animated": True,
        "frame_count": len(frames),
        "unique_frame_indices": sorted(set(idxs)),
        "interpolate": bool((mcmeta or {}).get("animation", {}).get("interpolate", False)),
        "path": f"minecraft:block/{name}",
        "average": "time-weighted linear RGB across animation frames",
    }
    return out, meta


def apply_tint(rgba: np.ndarray, tint_rgb) -> np.ndarray:
    out = rgba.copy()
    tr, tg, tb = tint_rgb
    out[..., 0] = np.clip(out[..., 0].astype(np.uint16) * tr // 255, 0, 255).astype(np.uint8)
    out[..., 1] = np.clip(out[..., 1].astype(np.uint16) * tg // 255, 0, 255).astype(np.uint8)
    out[..., 2] = np.clip(out[..., 2].astype(np.uint16) * tb // 255, 0, 255).astype(np.uint8)
    return out


def alpha_composite(base: np.ndarray, over: np.ndarray) -> np.ndarray:
    if over.shape != base.shape:
        over_img = Image.fromarray(over, "RGBA").resize(
            (base.shape[1], base.shape[0]), Image.Resampling.NEAREST
        )
        over = np.asarray(over_img)
    src = over.astype(np.float64) / 255.0
    dst = base.astype(np.float64) / 255.0
    ao = src[..., 3:4]
    ad = dst[..., 3:4]
    out_a = ao + ad * (1 - ao)
    out_rgb = src[..., :3] * ao + dst[..., :3] * ad * (1 - ao)
    with np.errstate(invalid="ignore"):
        out_rgb = np.divide(out_rgb, out_a, out=np.zeros_like(out_rgb), where=out_a > 1e-8)
    out = np.empty_like(base)
    out[..., :3] = np.clip(np.rint(out_rgb * 255.0), 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(np.rint(out_a[..., 0] * 255.0), 0, 255).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------
# Model / blockstate resolution
# ---------------------------------------------------------------------------

def strip_ns(s: str) -> str:
    return s.split(":", 1)[1] if ":" in s else s


def model_filename(ref: str) -> str:
    ref = strip_ns(ref)
    if ref.startswith("block/"):
        ref = ref[len("block/"):]
    return ref


class AssetIndex:
    def __init__(self, root: Path):
        self.root = root
        self.models = root / "assets/minecraft/models/block"
        self.blockstates = root / "assets/minecraft/blockstates"
        self.textures = root / "assets/minecraft/textures/block"
        self.lang_path = root / "assets/minecraft/lang/en_us.json"
        self._model_cache: dict[str, dict] = {}
        self._lang = None
        self._tex_cache: dict[str, tuple[np.ndarray, dict]] = {}

    def lang(self) -> dict:
        if self._lang is None:
            self._lang = json.loads(self.lang_path.read_text()) if self.lang_path.exists() else {}
        return self._lang

    def display_name(self, block_id: str) -> str:
        key = f"block.minecraft.{block_id}"
        return self.lang().get(key, block_id.replace("_", " ").title())

    def load_model(self, ref: str) -> dict:
        name = model_filename(ref)
        if name not in self._model_cache:
            path = self.models / f"{name}.json"
            self._model_cache[name] = json.loads(path.read_text()) if path.exists() else {}
        return self._model_cache[name]

    def flatten_model(self, ref: str) -> dict:
        textures: dict[str, str] = {}
        elements = None
        parent_chain = []
        cur = ref
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            data = self.load_model(cur)
            if not data:
                break
            parent_chain.append(model_filename(cur))
            for k, v in (data.get("textures") or {}).items():
                textures.setdefault(k, v)
            if elements is None and "elements" in data:
                elements = data["elements"]
            cur = data.get("parent")

        def resolve(val, depth=0):
            if not isinstance(val, str):
                return val
            if val.startswith("#") and depth < 12:
                key = val[1:]
                if key in textures and textures[key] != val:
                    return resolve(textures[key], depth + 1)
            return val

        resolved = {k: resolve(v) for k, v in textures.items()}
        return {"textures": resolved, "elements": elements or [], "parents": parent_chain}

    def texture(self, name: str) -> tuple[np.ndarray, dict]:
        if name not in self._tex_cache:
            self._tex_cache[name] = load_texture_rgba(self.textures, name)
        return self._tex_cache[name]


def resolve_tex_ref(textures: dict, ref: str) -> str | None:
    if not ref:
        return None
    depth = 0
    while isinstance(ref, str) and ref.startswith("#") and depth < 12:
        ref = textures.get(ref[1:])
        depth += 1
    return norm_tex_path(ref) if isinstance(ref, str) else None


def elements_are_full_cube(elements: list) -> bool:
    for el in elements:
        fr = el.get("from", [0, 0, 0])
        to = el.get("to", [0, 0, 0])
        lo = [min(fr[i], to[i]) for i in range(3)]
        hi = [max(fr[i], to[i]) for i in range(3)]
        spans = [hi[i] - lo[i] for i in range(3)]
        if all(s >= 14.0 for s in spans) and all(lo[i] <= 1.5 and hi[i] >= 14.5 for i in range(3)):
            return True
    return False


def parent_suggests_cube(parents: list[str]) -> bool:
    cube_roots = {
        "cube", "cube_all", "cube_all_inner_faces", "cube_bottom_top",
        "cube_bottom_top_inner_faces", "cube_column", "cube_column_horizontal",
        "cube_column_mirrored", "cube_column_uv_locked_x", "cube_column_uv_locked_y",
        "cube_column_uv_locked_z", "cube_directional", "cube_mirrored",
        "cube_mirrored_all", "cube_north_west_mirrored", "cube_north_west_mirrored_all",
        "cube_top", "orientable", "orientable_vertical", "orientable_with_bottom",
        "template_glazed_terracotta", "template_command_block",
        "template_cube_bottom_top_indented", "leaves",
    }
    return any(p in cube_roots for p in parents)


PREFERRED_STATE = {
    "axis": "y",
    "snowy": "false",
    "lit": "false",
    "powered": "false",
    "open": "false",
    "occupied": "false",
    "inverted": "false",
    "enabled": "true",
    "triggered": "false",
    "extended": "false",
    "unstable": "false",
    "waterlogged": "false",
    "hanging": "false",
    "berries": "false",
    "bloom": "false",
    "signal_fire": "false",
    "in_wall": "false",
    "ominous": "false",
    "crafting": "false",
    "has_book": "false",
    "has_record": "false",
    "has_bottle_0": "false",
    "has_bottle_1": "false",
    "has_bottle_2": "false",
    "disarmed": "false",
    "half": "bottom",
    "type": "bottom",
    "face": "wall",
    "attachment": "floor",
    "charges": "0",
    "power": "0",
    "level": "0",
    "moisture": "0",
    "age": "0",
    "hatch": "0",
    "bites": "0",
    "honey_level": "0",
    "delay": "1",
    "eggs": "1",
    "layers": "1",
    "part": "foot",
    "shape": "straight",
    "orientation": "north_up",
    "creaking_heart_state": "dormant",
    "trial_spawner_state": "inactive",
    "sculk_sensor_phase": "inactive",
    "vault_state": "inactive",
    "thickness": "base",
    "vertical_direction": "up",
    "tilt": "none",
    "leaves": "none",
    "mode": "data",
    "instrument": "harp",
}

FACE_BOOLS = ("down", "up", "north", "south", "east", "west")
SLOT_RE = re.compile(r"^slot_\d+_occupied$")


def parse_variant_key(key: str) -> dict[str, str]:
    if not key:
        return {}
    out = {}
    for part in key.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def score_state(props: dict[str, str]) -> tuple:
    score = 0
    for k, v in props.items():
        if k in PREFERRED_STATE:
            score += 0 if v == PREFERRED_STATE[k] else 3
        elif k == "facing":
            score += {"up": 0, "north": 1, "south": 2, "west": 3, "east": 4, "down": 5}.get(v, 6)
        elif k in FACE_BOOLS:
            score += 0 if v == "true" else 2
        elif SLOT_RE.match(k):
            score += 0 if v == "false" else 2
        else:
            if v in {"false", "0", "none", "bottom", "inactive", "dormant"}:
                score += 0
            else:
                score += 1
    return (score, len(props), ",".join(f"{k}={props[k]}" for k in sorted(props)))


def pick_variant_model(blockstate: dict) -> tuple[str | None, dict]:
    if "variants" in blockstate:
        variants = blockstate["variants"]
        if "" in variants:
            val = variants[""]
            if isinstance(val, list):
                val = val[0]
            return val.get("model"), {}
        best = None
        for key, val in variants.items():
            props = parse_variant_key(key)
            sc = score_state(props)
            if best is None or sc < best[0]:
                if isinstance(val, list):
                    val = val[0]
                best = (sc, val.get("model"), props)
        if best:
            return best[1], best[2]
    return None, {}


def inventory_model_name(block_id: str) -> str:
    return f"{block_id}_inventory"

# ---------------------------------------------------------------------------
# Scope: include / exclude
# ---------------------------------------------------------------------------

TECHNICAL = {
    "air", "cave_air", "void_air", "barrier", "structure_block", "structure_void",
    "jigsaw", "command_block", "chain_command_block", "repeating_command_block",
    "light", "spawner", "trial_spawner", "test_block", "test_instance_block",
    "end_portal", "end_gateway", "nether_portal", "end_portal_frame",
    "moving_piston", "piston_head", "fire", "soul_fire", "water", "lava",
    "bubble_column", "powder_snow", "frosted_ice", "piston", "sticky_piston",
}

SPECIAL_UTILITY = {
    "beacon", "conduit", "respawn_anchor", "vault", "decorated_pot",
    "dragon_egg", "heavy_core", "dried_ghast", "copper_golem_statue",
    "ender_chest", "chest", "trapped_chest", "copper_chest",
    "exposed_copper_chest", "weathered_copper_chest", "oxidized_copper_chest",
    "waxed_copper_chest", "waxed_exposed_copper_chest",
    "waxed_weathered_copper_chest", "waxed_oxidized_copper_chest",
}

REDSTONE_COMPONENTS = {
    "redstone_block", "redstone_lamp", "redstone_ore", "deepslate_redstone_ore",
    "redstone_torch", "redstone_wall_torch", "redstone_wire",
    "repeater", "comparator", "observer", "dispenser", "dropper", "hopper",
    "crafter", "target", "daylight_detector", "lever", "tripwire", "tripwire_hook",
    "calibrated_sculk_sensor", "sculk_sensor", "sculk_shrieker",
    "copper_bulb", "exposed_copper_bulb", "weathered_copper_bulb",
    "oxidized_copper_bulb", "waxed_copper_bulb", "waxed_exposed_copper_bulb",
    "waxed_weathered_copper_bulb", "waxed_oxidized_copper_bulb",
}

PLANT_CROSS_OR_CROP = {
    "short_grass", "tall_grass", "fern", "large_fern", "dead_bush", "bush",
    "short_dry_grass", "tall_dry_grass", "red_shrub", "firefly_bush",
    "hanging_roots", "pale_hanging_moss", "glow_lichen", "resin_clump",
    "leaf_litter", "wildflowers", "pink_petals", "cactus_flower",
    "spore_blossom", "sweet_berry_bush", "cave_vines", "cave_vines_plant",
    "twisting_vines", "twisting_vines_plant", "weeping_vines", "weeping_vines_plant",
    "vine", "lily_pad", "seagrass", "tall_seagrass", "kelp", "kelp_plant",
    "sugar_cane", "cactus", "bamboo", "bamboo_sapling", "cocoa",
    "nether_wart", "wheat", "carrots", "potatoes", "beetroots",
    "melon_stem", "attached_melon_stem", "pumpkin_stem", "attached_pumpkin_stem",
    "pitcher_crop", "pitcher_plant", "torchflower", "torchflower_crop",
    "brown_mushroom", "red_mushroom", "crimson_fungus", "warped_fungus",
    "crimson_roots", "warped_roots", "nether_sprouts", "chorus_plant",
    "chorus_flower", "big_dripleaf", "big_dripleaf_stem", "small_dripleaf",
    "azalea", "flowering_azalea", "mangrove_roots", "shelf_mushroom",
    "frogspawn", "sniffer_egg", "turtle_egg", "sea_pickle",
    "open_eyeblossom", "closed_eyeblossom",
}

FLOWER_NAMES = {
    "dandelion", "poppy", "blue_orchid", "allium", "azure_bluet",
    "red_tulip", "orange_tulip", "white_tulip", "pink_tulip",
    "oxeye_daisy", "cornflower", "lily_of_the_valley", "wither_rose",
    "golden_dandelion",
    "sunflower", "lilac", "rose_bush", "peony",
}

SUFFIX_EXCLUDES = [
    (re.compile(r"_stairs$"), "stairs"),
    (re.compile(r"_fence_gate$"), "fence_gate"),
    (re.compile(r"_fence$"), "fence"),
    (re.compile(r"_wall$"), "wall"),
    (re.compile(r"_pane$"), "pane"),
    (re.compile(r"_door$"), "door"),
    (re.compile(r"_button$"), "button"),
    (re.compile(r"_pressure_plate$"), "pressure_plate"),
    (re.compile(r"_sign$"), "sign"),
    (re.compile(r"_hanging_sign$"), "sign"),
    (re.compile(r"_banner$"), "banner"),
    (re.compile(r"_head$"), "head"),
    (re.compile(r"_skull$"), "skull"),
    (re.compile(r"_bed$"), "bed"),
    (re.compile(r"_carpet$"), "carpet"),
    (re.compile(r"_sapling$"), "sapling"),
    (re.compile(r"_propagule$"), "sapling"),
    (re.compile(r"_candle$"), "candle"),
    (re.compile(r"_candle_cake$"), "candle"),
    (re.compile(r"_wall_fan$"), "coral_fan"),
    (re.compile(r"_fan$"), "coral_fan"),
    (re.compile(r"_rail$"), "rail"),
    (re.compile(r"^potted_"), "potted_plant"),
    (re.compile(r"_grate$"), "grate"),
    (re.compile(r"_bars$"), "bars"),
    (re.compile(r"_chain$"), "chain"),
    (re.compile(r"_statue$"), "statue"),
    (re.compile(r"^infested_"), "infested"),
    (re.compile(r"(^|_)shulker_box$"), "shulker_box"),
    (re.compile(r"_leaves$"), "leaves"),
    (re.compile(r"_coral$"), "coral_plant"),
    (re.compile(r"^dead_.+_coral$"), "coral_plant"),
]

NONFULL_UTILITY = {
    "anvil", "chipped_anvil", "damaged_anvil", "grindstone", "stonecutter",
    "lectern", "composter", "cauldron", "water_cauldron", "lava_cauldron",
    "powder_snow_cauldron", "hopper", "brewing_stand", "enchanting_table",
    "bell", "end_rod", "lightning_rod", "exposed_lightning_rod",
    "weathered_lightning_rod", "oxidized_lightning_rod",
    "waxed_lightning_rod", "waxed_exposed_lightning_rod",
    "waxed_weathered_lightning_rod", "waxed_oxidized_lightning_rod",
    "iron_bars", "iron_chain", "chain", "ladder", "scaffolding",
    "pointed_dripstone", "amethyst_cluster", "large_amethyst_bud",
    "medium_amethyst_bud", "small_amethyst_bud", "flower_pot", "cake",
    "dirt_path", "farmland", "snow", "cobweb", "iron_door",
    "lever", "tripwire_hook", "string",
    "sulfur_spike", "heavy_core",
    "activator_rail", "detector_rail", "powered_rail", "rail",
    "sculk_vein", "glow_lichen",
    "campfire", "soul_campfire",
}

GLASS_RE = re.compile(r"glass")
TORCH_RE = re.compile(r"torch")
LANTERN_RE = re.compile(r"(?<!sea_)(?<!jack_o_)lantern")
CANDLE_RE = re.compile(r"candle")


def shape_from_id(block_id: str) -> str | None:
    if block_id.endswith("_slab"):
        return "slab"
    if block_id.endswith("_trapdoor"):
        return "trapdoor"
    if block_id.endswith("_shelf") and block_id != "chiseled_bookshelf":
        return "shelf"
    return None


def exclusion_reason(block_id: str) -> str | None:
    if block_id in TECHNICAL:
        return "technical"
    if block_id in SPECIAL_UTILITY:
        return "special_utility"
    if block_id in REDSTONE_COMPONENTS:
        return "redstone"
    if block_id in PLANT_CROSS_OR_CROP or block_id in FLOWER_NAMES:
        return "plant"
    if block_id in NONFULL_UTILITY:
        return "non_full"
    if GLASS_RE.search(block_id):
        return "glass"
    if TORCH_RE.search(block_id):
        return "torch"
    if LANTERN_RE.search(block_id):
        return "lantern"
    if CANDLE_RE.search(block_id):
        return "candle"
    if block_id.endswith("_coral") or block_id.endswith("_coral_fan"):
        if "coral_block" not in block_id:
            return "plant"
    for rx, reason in SUFFIX_EXCLUDES:
        if rx.search(block_id):
            if reason == "coral_plant" and "coral_block" in block_id:
                continue
            if reason == "leaves":
                return "leaves"
            return reason
    return None


def classify_family(block_id: str, shape: str) -> dict:
    dye = next((d for d in DYE_COLORS if block_id.startswith(d + "_")), None)
    wood = next((w for w in WOOD_TYPES if (
        block_id.startswith(w + "_") or block_id.startswith("stripped_" + w + "_")
        or block_id in {
            f"{w}_wood", f"stripped_{w}_wood", f"{w}_log", f"stripped_{w}_log",
            f"{w}_stem", f"stripped_{w}_stem", f"{w}_hyphae", f"stripped_{w}_hyphae",
            f"{w}_planks", f"{w}_mosaic", f"{w}_shelf", f"{w}_trapdoor",
            f"{w}_slab", f"{w}_block", f"stripped_{w}_block",
        }
    )), None)

    def fam(family, subfamily=None):
        return {"family": family, "subfamily": subfamily, "dye_color": dye, "wood_type": wood}

    if "froglight" in block_id:
        return fam("froglight")
    if "glazed_terracotta" in block_id:
        return fam("glazed_terracotta")
    if "concrete_powder" in block_id:
        return fam("concrete_powder")
    if "concrete" in block_id:
        return fam("concrete")
    if re.search(r"(^|_)terracotta$", block_id):
        return fam("terracotta")
    if re.search(r"(^|_)wool(_slab)?$", block_id):
        return fam("wool")
    if wood and shape == "shelf":
        return fam("wood", "shelf")
    if wood and shape == "trapdoor":
        return fam("wood", "trapdoor")
    if wood and "mosaic" in block_id:
        return fam("wood", "mosaic")
    if wood and any(x in block_id for x in ("_log", "_stem", "_hyphae", "_wood", "_block")):
        sub = "stripped" if block_id.startswith("stripped_") else "log"
        if "_planks" in block_id:
            sub = "planks"
        elif block_id.endswith("_wood") or block_id.endswith("_hyphae"):
            sub = "wood" if not block_id.startswith("stripped_") else "stripped_wood"
        elif "_log" in block_id or "_stem" in block_id or block_id.endswith("_block"):
            sub = "stripped_log" if block_id.startswith("stripped_") else "log"
        return fam("wood", sub)
    if wood or block_id.endswith("_planks"):
        return fam("wood", "planks" if ("plank" in block_id or shape in {"slab", "trapdoor"}) else None)
    if "copper" in block_id:
        stage = "copper"
        for s in ("oxidized", "weathered", "exposed"):
            if s in block_id:
                stage = s
                break
        sub = "waxed" if "waxed" in block_id else "unwaxed"
        if "ore" in block_id:
            return fam("ore")
        if "cut" in block_id:
            kind = "cut"
        elif "chiseled" in block_id:
            kind = "chiseled"
        elif "trapdoor" in block_id:
            kind = "trapdoor"
        else:
            kind = "block"
        return fam("copper", f"{sub}_{stage}_{kind}")
    if block_id in {
        "barrel", "bee_nest", "beehive", "blast_furnace", "bookshelf",
        "cartography_table", "chiseled_bookshelf", "crafting_table",
        "fletching_table", "furnace", "jukebox", "lodestone", "loom",
        "note_block", "smithing_table", "smoker", "tnt",
    }:
        return fam("utility")
    if block_id in {"nether_wart_block", "warped_wart_block"}:
        return fam("organic")
    if block_id == "creaking_heart" or block_id == "petrified_oak_slab":
        return fam("wood", "other")
    if "smooth_stone" in block_id:
        return fam("stone")
    if "sulfur" in block_id:
        return fam("sulfur")
    if "cinnabar" in block_id:
        return fam("cinnabar")
    if "resin" in block_id:
        return fam("resin")
    if "deepslate" in block_id and "ore" in block_id:
        return fam("ore", "deepslate")
    if block_id.endswith("_ore") or block_id == "ancient_debris":
        return fam("ore")
    if "deepslate" in block_id:
        return fam("deepslate")
    if "blackstone" in block_id or "gilded_blackstone" in block_id:
        return fam("blackstone")
    if "basalt" in block_id:
        return fam("basalt")
    if "tuff" in block_id:
        return fam("tuff")
    if "prismarine" in block_id or block_id == "sea_lantern":
        return fam("prismarine")
    if "red_sandstone" in block_id or block_id == "red_sand":
        return fam("red_sandstone")
    if "sandstone" in block_id or block_id in {"sand", "suspicious_sand"}:
        return fam("sandstone")
    if "nether_brick" in block_id or "red_nether" in block_id:
        return fam("nether_brick")
    if "end_stone" in block_id:
        return fam("end_stone")
    if "purpur" in block_id:
        return fam("purpur")
    if "quartz" in block_id:
        return fam("quartz")
    if "amethyst" in block_id:
        return fam("amethyst")
    if "mud" in block_id:
        return fam("mud")
    if "stone_brick" in block_id or "cobble" in block_id:
        return fam("stone")
    if "brick" in block_id:
        return fam("brick")
    if "moss_block" in block_id or block_id in {"moss_block", "pale_moss_block"}:
        return fam("moss")
    if "sculk" in block_id:
        return fam("sculk")
    if "ice" in block_id:
        return fam("ice")
    if "snow" in block_id:
        return fam("snow")
    if "dripstone" in block_id:
        return fam("dripstone")
    if "andesite" in block_id:
        return fam("andesite")
    if "diorite" in block_id:
        return fam("diorite")
    if "granite" in block_id:
        return fam("granite")
    if "calcite" in block_id:
        return fam("calcite")
    if block_id.startswith("stone"):
        return fam("stone")
    if block_id in {
        "iron_block", "gold_block", "diamond_block", "emerald_block",
        "lapis_block", "coal_block", "netherite_block",
        "raw_iron_block", "raw_gold_block", "raw_copper_block",
    }:
        return fam("mineral")
    if "coral_block" in block_id:
        return fam("coral")
    if "nylium" in block_id or block_id in {
        "dirt", "coarse_dirt", "rooted_dirt", "podzol", "mycelium",
        "grass_block", "clay", "gravel", "suspicious_gravel",
        "soul_sand", "soul_soil", "netherrack",
    }:
        return fam("soil")
    if "mushroom" in block_id:
        return fam("mushroom")
    if block_id in {"melon", "pumpkin", "carved_pumpkin", "jack_o_lantern"}:
        return fam("gourd")
    if block_id in {
        "hay_block", "dried_kelp_block", "honeycomb_block",
        "bone_block", "slime_block", "honey_block", "sponge", "wet_sponge",
    }:
        return fam("organic")
    if "shroomlight" in block_id or "glowstone" in block_id or "magma" in block_id:
        return fam("light")
    if "obsidian" in block_id or block_id == "bedrock":
        return fam("obsidian")
    if "trapdoor" in block_id:
        return fam("metal" if any(x in block_id for x in ("iron", "copper")) else "wood", "trapdoor")
    return fam("other")


def tint_for_block(block_id: str, texture_name: str | None, tintindex) -> tuple[str | None, tuple | None]:
    if tintindex is None:
        return None, None
    if block_id == "birch_leaves" or (texture_name and "birch_leaves" in texture_name):
        return "birch_leaves", TINTS["birch_leaves"]
    if block_id == "spruce_leaves" or (texture_name and "spruce_leaves" in texture_name):
        return "spruce_leaves", TINTS["spruce_leaves"]
    if "leaves" in block_id or (texture_name and "leaves" in (texture_name or "")):
        return "foliage", TINTS["foliage"]
    if block_id == "lily_pad":
        return "lily_pad", TINTS["lily_pad"]
    if "leaf_litter" in block_id or "dry_foliage" in (texture_name or ""):
        return "dry_foliage", TINTS["dry_foliage"]
    return "grass", TINTS["grass"]

# ---------------------------------------------------------------------------
# Face gathering + stats
# ---------------------------------------------------------------------------

def gather_face_layers(flat: dict) -> dict[str, list]:
    """Map cube face -> list of (texture_name, tintindex) in draw order."""
    layers: dict[str, list] = defaultdict(list)
    textures = flat["textures"]
    for el in flat["elements"]:
        for face, info in (el.get("faces") or {}).items():
            tex = resolve_tex_ref(textures, info.get("texture", ""))
            if not tex:
                continue
            layers[face].append((tex, info.get("tintindex")))
    return layers


def render_face(assets: AssetIndex, layers: list, block_id: str) -> tuple[np.ndarray | None, dict]:
    canvas = None
    meta = {"textures": [], "animated": False, "tinted": False, "tint_type": None}
    for tex, tintindex in layers:
        try:
            rgba, tmeta = assets.texture(tex)
        except FileNotFoundError:
            continue
        tint_type, tint = tint_for_block(block_id, tex, tintindex)
        if tint is not None:
            rgba = apply_tint(rgba, tint)
            meta["tinted"] = True
            meta["tint_type"] = tint_type
        meta["textures"].append(tmeta["path"])
        if tmeta.get("animated"):
            meta["animated"] = True
            meta["frame_count"] = tmeta.get("frame_count")
        if canvas is None:
            canvas = rgba
        else:
            canvas = alpha_composite(canvas, rgba)
    return canvas, meta


def kmeans_oklab(points: np.ndarray, k: int, rng: np.random.Generator, n_init=6, n_iter=25):
    n = len(points)
    if n == 0:
        return np.zeros((0, 3)), np.zeros((0,), dtype=int)
    k = min(k, n)
    best_inertia, best_centers, best_labels = None, None, None
    for _ in range(n_init):
        centers = [points[int(rng.integers(0, n))]]
        dist = np.full(n, np.inf)
        for _c in range(1, k):
            d = ((points - centers[-1]) ** 2).sum(axis=1)
            dist = np.minimum(dist, d)
            p = dist / (dist.sum() + 1e-12)
            centers.append(points[int(rng.choice(n, p=p))])
        centers = np.stack(centers, axis=0)
        labels = np.zeros(n, dtype=int)
        for _it in range(n_iter):
            d = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            labels = d.argmin(axis=1)
            new = centers.copy()
            for j in range(k):
                mask = labels == j
                if mask.any():
                    new[j] = points[mask].mean(axis=0)
            if np.allclose(new, centers):
                centers = new
                break
            centers = new
        inertia = ((points - centers[labels]) ** 2).sum()
        if best_inertia is None or inertia < best_inertia:
            best_inertia, best_centers, best_labels = inertia, centers, labels
    return best_centers, best_labels


def busyness_label(l_std: float, spatial: float) -> str:
    if l_std < 2.0 and spatial < 3.0:
        return "flat"
    if l_std < 6.0:
        return "smooth"
    if l_std < 15.0:
        return "textured"
    return "noisy"


def analyze_rgba(rgba: np.ndarray, rng: np.random.Generator) -> dict | None:
    a = rgba[..., 3]
    opaque = a > 0
    n_vis = int(opaque.sum())
    if n_vis == 0:
        return None
    rgb = rgba[..., :3][opaque].astype(np.float64)
    n_zero = int((a == 0).sum())
    n_part = int(((a > 0) & (a < 255)).sum())

    lab = srgb8_to_lab(rgb)
    ok = srgb8_to_oklab(rgb)
    lin = srgb8_to_linear(rgb)

    ok_mean = ok.mean(axis=0)
    lab_of_ok = srgb8_to_lab(oklab_to_srgb8(ok_mean).astype(np.float64))
    lab_mean = lab.mean(axis=0)
    srgb_naive = rgb.mean(axis=0)
    lin_mean = lin.mean(axis=0)
    srgb_of_lin = linear_to_srgb8(lin_mean)
    srgb_of_ok = oklab_to_srgb8(ok_mean)
    lch = oklab_to_oklch(ok_mean)

    l = lab[..., 0]
    l_std = float(l.std(ddof=0))

    lab_img = np.zeros(rgba.shape[:2] + (3,), dtype=np.float64)
    vis_img = np.zeros(rgba.shape[:2], dtype=bool)
    ys, xs = np.nonzero(opaque)
    lab_img[ys, xs] = lab
    vis_img[ys, xs] = True
    diffs = []
    Lmap = lab_img[..., 0]
    h, w = Lmap.shape
    for dy, dx in ((0, 1), (1, 0)):
        a_ = vis_img[: h - dy, : w - dx]
        b_ = vis_img[dy:, dx:]
        both = a_ & b_
        if both.any():
            diffs.append(np.abs(Lmap[: h - dy, : w - dx][both] - Lmap[dy:, dx:][both]))
    spatial = float(np.concatenate(diffs).mean()) if diffs else 0.0

    unique = {tuple(p) for p in rgb.astype(np.uint8)}
    k = 3 if n_vis >= 12 else (2 if n_vis >= 4 else 1)
    centers, labels = kmeans_oklab(ok, k, rng)
    clusters = []
    for j, c in enumerate(centers):
        frac = float((labels == j).mean()) if len(labels) else 0
        if frac < 0.05 and k > 1:
            continue
        rgb_c = oklab_to_srgb8(c)
        lab_c = srgb8_to_lab(rgb_c.astype(np.float64))
        clusters.append({
            "hex": hex_from_rgb(rgb_c),
            "srgb": [int(x) for x in rgb_c],
            "oklab": [round(float(x), 4) for x in c],
            "lab": [round(float(x), 3) for x in lab_c],
            "fraction": round(frac, 4),
        })
    merged = []
    for cl in sorted(clusters, key=lambda c: -c["fraction"]):
        found = False
        for m in merged:
            if ciede2000(cl["lab"], m["lab"]) < 6:
                m["fraction"] = round(m["fraction"] + cl["fraction"], 4)
                found = True
                break
        if not found:
            merged.append(cl)
    merged = sorted(merged, key=lambda c: -c["fraction"])[:3]
    sfrac = sum(c["fraction"] for c in merged) or 1.0
    for c in merged:
        c["fraction"] = round(c["fraction"] / sfrac, 4)

    hue = None if (isinstance(lch, np.ndarray) and np.isnan(lch[2])) else float(lch[2])
    if hue is not None and math.isnan(hue):
        hue = None
    chroma = float(lch[1])
    return {
        "srgb": [int(x) for x in srgb_of_ok],
        "hex": hex_from_rgb(srgb_of_ok),
        "srgb_naive": [int(x) for x in np.clip(np.rint(srgb_naive), 0, 255)],
        "hex_naive": hex_from_rgb(srgb_naive),
        "srgb_linear_mean": [int(x) for x in srgb_of_lin],
        "hex_linear_mean": hex_from_rgb(srgb_of_lin),
        "lab": [round(float(x), 3) for x in lab_mean],
        "lab_of_oklab_mean": [round(float(x), 3) for x in lab_of_ok],
        "oklab": [round(float(x), 4) for x in ok_mean],
        "oklch": {
            "L": round(float(lch[0]), 4),
            "C": round(chroma, 4),
            "h": None if hue is None else round(hue, 2),
        },
        "brightness_L": round(float(lab_mean[0]), 3),
        "hue_deg": None if hue is None else round(hue, 2),
        "chroma": round(chroma, 4),
        "l_stddev": round(l_std, 3),
        "spatial_contrast": round(spatial, 3),
        "busyness": busyness_label(l_std, spatial),
        "unique_opaque_colours": len(unique),
        "visible_pixels": n_vis,
        "transparent_pixels": n_zero,
        "translucent_pixels": n_part,
        "has_cutout": n_zero > 0,
        "has_translucency": n_part > 0,
        "partially_transparent": n_zero > 0 or n_part > 0,
        "dominant_colours": merged,
        "_oklab": ok_mean,
        "_lab": lab_of_ok,
        "_rgba": rgba,
    }


def combine_overall(face_stats: dict, weights: dict) -> dict | None:
    acc = np.zeros(3, dtype=np.float64)
    wsum = 0.0
    any_cutout = False
    any_trans = False
    for face, w in weights.items():
        st = face_stats.get(face)
        if not st:
            continue
        acc += st["_oklab"] * w
        wsum += w
        any_cutout = any_cutout or st["has_cutout"]
        any_trans = any_trans or st["has_translucency"]
    if wsum == 0:
        return None
    ok_mean = acc / wsum
    srgb = oklab_to_srgb8(ok_mean)
    lab = srgb8_to_lab(srgb.astype(np.float64))
    lch = oklab_to_oklch(ok_mean)
    hue = float(lch[2])
    if math.isnan(hue):
        hue = None
    lstd = 0.0
    spat = 0.0
    for face, w in weights.items():
        st = face_stats.get(face)
        if st:
            lstd += st["l_stddev"] * w
            spat += st["spatial_contrast"] * w
    lstd /= wsum
    spat /= wsum
    return {
        "srgb": [int(x) for x in srgb],
        "hex": hex_from_rgb(srgb),
        "lab": [round(float(x), 3) for x in lab],
        "oklab": [round(float(x), 4) for x in ok_mean],
        "oklch": {
            "L": round(float(lch[0]), 4),
            "C": round(float(lch[1]), 4),
            "h": None if hue is None else round(hue, 2),
        },
        "brightness_L": round(float(lab[0]), 3),
        "hue_deg": None if hue is None else round(hue, 2),
        "chroma": round(float(lch[1]), 4),
        "l_stddev": round(lstd, 3),
        "spatial_contrast": round(spat, 3),
        "busyness": busyness_label(lstd, spat),
        "has_cutout": any_cutout,
        "has_translucency": any_trans,
        "partially_transparent": any_cutout or any_trans,
        "_oklab": ok_mean,
        "_lab": lab,
    }


def public_stats(st: dict) -> dict:
    return {k: v for k, v in st.items() if not k.startswith("_")}


def max_face_delta(face_stats: dict, faces: list[str]) -> float:
    labs = [face_stats[f]["_lab"] for f in faces if f in face_stats]
    best = 0.0
    for i in range(len(labs)):
        for j in range(i + 1, len(labs)):
            best = max(best, ciede2000(labs[i], labs[j]))
    return best

# ---------------------------------------------------------------------------
# Build dataset
# ---------------------------------------------------------------------------

def extract_assets(jar: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    want = (
        "assets/minecraft/textures/block/",
        "assets/minecraft/models/block/",
        "assets/minecraft/blockstates/",
        "assets/minecraft/textures/colormap/",
        "assets/minecraft/lang/en_us.json",
        "assets/minecraft/items/",
        "version.json",
    )
    with zipfile.ZipFile(jar) as zf:
        for info in zf.infolist():
            n = info.filename
            if n == "version.json" or any(n.startswith(p) for p in want):
                zf.extract(info, dest)


def process_block(block_id: str, assets: AssetIndex, rng: np.random.Generator) -> tuple[dict | None, dict]:
    reason = exclusion_reason(block_id)
    shape_hint = shape_from_id(block_id)
    bs_path = assets.blockstates / f"{block_id}.json"
    if not bs_path.exists():
        return None, {"id": block_id, "included": False, "reason": "no_blockstate"}
    blockstate = json.loads(bs_path.read_text())

    model_ref = None
    state_used = {}
    inv = inventory_model_name(block_id)
    if (assets.models / f"{inv}.json").exists() and "multipart" in blockstate:
        model_ref = f"minecraft:block/{inv}"
        state_used = {"_source": "inventory_model"}
    else:
        model_ref, state_used = pick_variant_model(blockstate)
        if model_ref is None and "multipart" in blockstate:
            for part in blockstate["multipart"]:
                when = part.get("when")
                if not when:
                    apply = part["apply"]
                    if isinstance(apply, list):
                        apply = apply[0]
                    model_ref = apply.get("model")
                    state_used = {"_source": "multipart_unconditional"}
                    break
            if model_ref is None:
                for part in blockstate["multipart"]:
                    apply = part.get("apply")
                    if isinstance(apply, list):
                        apply = apply[0]
                    m = (apply or {}).get("model", "")
                    if m.endswith("_shelf") and "unpowered" not in m and "inventory" not in m:
                        when = part.get("when") or {}
                        if not isinstance(when, dict) or when.get("facing", "north") == "north":
                            model_ref = m
                            state_used = when if isinstance(when, dict) else {}
                            break

    log = {"id": block_id, "model": model_ref, "state": state_used}

    if reason:
        log.update({"included": False, "reason": reason})
        return None, log

    if not model_ref:
        log.update({"included": False, "reason": "no_model"})
        return None, log

    flat = assets.flatten_model(model_ref)
    is_cube = elements_are_full_cube(flat["elements"]) or (
        not flat["elements"] and parent_suggests_cube(flat["parents"])
    )

    shape = shape_hint
    if shape is None:
        if is_cube:
            shape = "full_block"
        else:
            log.update({"included": False, "reason": "non_full", "parents": flat["parents"]})
            return None, log

    layers = gather_face_layers(flat)
    face_rgba, face_meta, face_stats = {}, {}, {}
    for face, ly in layers.items():
        rgba, meta = render_face(assets, ly, block_id)
        if rgba is None:
            continue
        st = analyze_rgba(rgba, rng)
        if st is None:
            continue
        face_rgba[face] = rgba
        face_meta[face] = meta
        face_stats[face] = st

    if not face_stats:
        texmap = flat["textures"]
        aliases = {
            "up": ["up", "top", "end", "all", "texture", "particle"],
            "down": ["down", "bottom", "end", "all", "texture", "particle"],
            "north": ["north", "side", "front", "all", "texture", "particle"],
        }
        for face, keys in aliases.items():
            name = None
            for k in keys:
                if k in texmap:
                    name = resolve_tex_ref(texmap, texmap[k]) or norm_tex_path(texmap[k])
                    if name:
                        break
            if not name:
                continue
            try:
                rgba, tmeta = assets.texture(name)
            except FileNotFoundError:
                continue
            st = analyze_rgba(rgba, rng)
            if st:
                face_stats[face] = st
                face_meta[face] = {
                    "textures": [tmeta["path"]],
                    "animated": tmeta.get("animated", False),
                    "tinted": False,
                    "tint_type": None,
                }
                face_rgba[face] = rgba

    for f in ("south", "east", "west"):
        if f not in face_stats and "north" in face_stats:
            face_stats[f] = face_stats["north"]
            face_meta[f] = face_meta.get("north", {})

    if not face_stats:
        log.update({"included": False, "reason": "no_texture"})
        return None, log

    top_k = "up" if "up" in face_stats else None
    bot_k = "down" if "down" in face_stats else None
    side_keys = [k for k in ("north", "east", "south", "west") if k in face_stats]

    weights = {}
    if top_k:
        weights[top_k] = 1.0
    if bot_k:
        weights[bot_k] = 1.0
    if side_keys:
        w = 4.0 / len(side_keys)
        for k in side_keys:
            weights[k] = w
    overall = combine_overall(face_stats, weights) or public_stats(next(iter(face_stats.values())))
    if "_oklab" not in overall:
        overall["_oklab"] = srgb8_to_oklab(np.array(overall["srgb"], dtype=np.float64))
        overall["_lab"] = srgb8_to_lab(np.array(overall["srgb"], dtype=np.float64))

    side_stat = None
    if side_keys:
        side_stat = combine_overall({k: face_stats[k] for k in side_keys}, {k: 1.0 for k in side_keys})
    elif top_k:
        side_stat = face_stats[top_k]

    top_stat = face_stats.get("up") or side_stat or next(iter(face_stats.values()))
    bot_stat = face_stats.get("down") or top_stat

    faces_delta = max_face_delta(
        face_stats, [k for k in ("up", "down", "north", "east", "south", "west") if k in face_stats]
    )
    sides_delta = max_face_delta(face_stats, side_keys)
    faces_differ = faces_delta > 5.0
    sides_differ = sides_delta > 5.0

    family = classify_family(block_id, shape)
    tinted = any(m.get("tinted") for m in face_meta.values())
    tint_types = sorted({m.get("tint_type") for m in face_meta.values() if m.get("tint_type")})
    animated = any(m.get("animated") for m in face_meta.values())

    thumb_key = side_keys[0] if side_keys else (top_k or next(iter(face_rgba), None))
    thumb = face_rgba.get(thumb_key) if thumb_key else None

    light = int(LIGHT_LEVELS.get(block_id, 0))
    rec = {
        "id": block_id,
        "display_name": assets.display_name(block_id),
        "shape": shape,
        **family,
        "emits_light": light > 0,
        "light_level": light,
        "gravity": block_id in GRAVITY_BLOCKS or block_id.endswith("_concrete_powder"),
        "biome_tinted": tinted,
        "tint_type": tint_types[0] if tint_types else None,
        "faces_differ": faces_differ,
        "sides_differ": sides_differ,
        "face_delta_e00": round(faces_delta, 2),
        "side_delta_e00": round(sides_delta, 2),
        "animated": animated,
        "partially_transparent": overall.get("partially_transparent", False),
        "has_cutout": overall.get("has_cutout", False),
        "has_translucency": overall.get("has_translucency", False),
        "model": model_ref,
        "state": {k: v for k, v in state_used.items() if not str(k).startswith("_")} if isinstance(state_used, dict) else {},
        "textures": {
            "top": list(dict.fromkeys((face_meta.get("up") or {}).get("textures", []))),
            "side": list(dict.fromkeys((face_meta.get(side_keys[0]) if side_keys else {}).get("textures", []) if side_keys else [])),
            "bottom": list(dict.fromkeys((face_meta.get("down") or {}).get("textures", []))),
        },
        "overall": public_stats(overall),
        "faces": {
            "top": public_stats(top_stat),
            "side": public_stats(side_stat) if side_stat else public_stats(top_stat),
            "bottom": public_stats(bot_stat),
        },
        "_lab": overall["_lab"],
        "_oklab": overall["_oklab"],
        "_thumb": thumb,
    }
    if block_id in LIGHT_LEVEL_LIT:
        rec["light_level_lit"] = LIGHT_LEVEL_LIT[block_id]
    src = side_stat or top_stat
    rec["dominant_colours"] = (src or {}).get("dominant_colours") or []
    rec["l_stddev"] = (src or overall).get("l_stddev")
    rec["spatial_contrast"] = (src or overall).get("spatial_contrast")
    rec["busyness"] = (src or overall).get("busyness")
    log.update({"included": True, "reason": None, "shape": shape, "family": family["family"]})
    return rec, log


def nearest_neighbours(records: list[dict], k=5) -> None:
    n = len(records)
    labs = [r["_lab"] for r in records]
    for i, rec in enumerate(records):
        dists = []
        for j in range(n):
            if i == j:
                continue
            dists.append((ciede2000(labs[i], labs[j]), records[j]["id"], records[j]["overall"]["hex"]))
        dists.sort(key=lambda t: t[0])
        rec["nearest"] = [
            {"id": d[1], "hex": d[2], "delta_e00": round(d[0], 3)}
            for d in dists[:k]
        ]


def thin_ramp(items: list[dict], target=10, min_de=2.5) -> list[dict]:
    if len(items) <= target:
        out = []
        for it in items:
            if out and ciede2000(out[-1]["_lab"], it["_lab"]) < min_de:
                continue
            out.append(it)
        return out
    Ls = [it["overall"]["brightness_L"] for it in items]
    lo, hi = min(Ls), max(Ls)
    if hi - lo < 1e-6:
        return items[:1]
    chosen, used = [], set()
    for t in np.linspace(lo, hi, target):
        best = None
        for i, it in enumerate(items):
            if i in used:
                continue
            d = abs(it["overall"]["brightness_L"] - t)
            if best is None or d < best[0]:
                best = (d, i, it)
        if best and best[1] not in used:
            if chosen and ciede2000(chosen[-1]["_lab"], best[2]["_lab"]) < min_de:
                continue
            chosen.append(best[2])
            used.add(best[1])
    return chosen


def build_gradient_chains(records: list[dict]) -> list[dict]:
    chains = []
    full = [r for r in records if r["shape"] == "full_block"]
    by_id = {r["id"]: r for r in records}

    def add_chain(name, desc, items, kind):
        if len(items) < 3:
            return
        items = sorted(items, key=lambda r: r["overall"]["brightness_L"])
        steps = [round(ciede2000(a["_lab"], b["_lab"]), 2) for a, b in zip(items, items[1:])]
        chains.append({
            "id": name,
            "kind": kind,
            "description": desc,
            "blocks": [r["id"] for r in items],
            "hexes": [r["overall"]["hex"] for r in items],
            "L_star": [r["overall"]["brightness_L"] for r in items],
            "step_delta_e00": steps,
            "max_step_delta_e00": max(steps) if steps else 0,
            "span_delta_e00": round(ciede2000(items[0]["_lab"], items[-1]["_lab"]), 2) if len(items) > 1 else 0,
        })

    by_fam = defaultdict(list)
    for r in full:
        by_fam[r["family"]].append(r)
    for fam, items in sorted(by_fam.items()):
        if fam in {"other", "copper"}:
            continue
        add_chain(f"family_{fam}_L", f"{fam} full blocks sorted by lightness", items, "family_lightness")
        th = thin_ramp(items, target=min(8, len(items)), min_de=3.0)
        if len(th) >= 3 and len(th) < len(items):
            add_chain(f"family_{fam}_smooth", f"{fam} thinned smoothness ramp", th, "family_smooth")

    for name, ids, desc in (
        ("copper_oxidation",
         ["copper_block", "exposed_copper", "weathered_copper", "oxidized_copper"],
         "Unwaxed copper blocks, oxidation order"),
        ("cut_copper_oxidation",
         ["cut_copper", "exposed_cut_copper", "weathered_cut_copper", "oxidized_cut_copper"],
         "Unwaxed cut copper, oxidation order"),
    ):
        items = [by_id[i] for i in ids if i in by_id]
        if len(items) >= 3:
            steps = [round(ciede2000(a["_lab"], b["_lab"]), 2) for a, b in zip(items, items[1:])]
            chains.append({
                "id": name,
                "kind": "oxidation",
                "description": desc,
                "blocks": [r["id"] for r in items],
                "hexes": [r["overall"]["hex"] for r in items],
                "L_star": [r["overall"]["brightness_L"] for r in items],
                "step_delta_e00": steps,
                "max_step_delta_e00": max(steps) if steps else 0,
                "span_delta_e00": round(ciede2000(items[0]["_lab"], items[-1]["_lab"]), 2),
            })

    grey = [r for r in full if (r["overall"].get("chroma") or 0) < 0.03]
    add_chain("greyscale_all", "Low-chroma full blocks sorted by lightness", grey, "greyscale")
    th = thin_ramp(grey, target=12, min_de=3.5)
    add_chain("greyscale_smooth", "Thinned greyscale ramp for smooth gradients", th, "greyscale_smooth")

    buckets = [
        ("red", 350, 20), ("orange", 20, 55), ("yellow", 55, 95),
        ("green", 95, 160), ("cyan", 160, 210), ("blue", 210, 265),
        ("purple", 265, 310), ("magenta_pink", 310, 350),
    ]

    def in_bucket(h, lo, hi):
        if h is None:
            return False
        return lo <= h < hi if lo <= hi else (h >= lo or h < hi)

    for name, lo, hi in buckets:
        items = [
            r for r in full
            if (r["overall"].get("chroma") or 0) >= 0.03
            and in_bucket(r["overall"].get("hue_deg"), lo, hi)
        ]
        add_chain(f"hue_{name}_L", f"Full blocks in the {name} hue band, by lightness", items, "hue_lightness")
        th = thin_ramp(items, target=8, min_de=4.0)
        add_chain(f"hue_{name}_smooth", f"Thinned {name} ramp", th, "hue_smooth")

    for fam, suffix in (
        ("wool", "_wool"),
        ("concrete", "_concrete"),
        ("concrete_powder", "_concrete_powder"),
        ("terracotta", "_terracotta"),
        ("glazed_terracotta", "_glazed_terracotta"),
    ):
        items = [by_id[f"{d}{suffix}"] for d in DYE_COLORS if f"{d}{suffix}" in by_id]
        coloured = [r for r in items if r["overall"].get("hue_deg") is not None]
        coloured.sort(key=lambda r: r["overall"]["hue_deg"])
        if len(coloured) >= 8:
            steps = [round(ciede2000(a["_lab"], b["_lab"]), 2) for a, b in zip(coloured, coloured[1:])]
            chains.append({
                "id": f"{fam}_hue_wheel",
                "kind": "dye_hue_wheel",
                "description": f"Dyed {fam} blocks ordered by hue (not lightness)",
                "blocks": [r["id"] for r in coloured],
                "hexes": [r["overall"]["hex"] for r in coloured],
                "L_star": [r["overall"]["brightness_L"] for r in coloured],
                "step_delta_e00": steps,
                "max_step_delta_e00": max(steps) if steps else 0,
                "span_delta_e00": None,
            })

    planks = [r for r in full if r["family"] == "wood" and r.get("subfamily") == "planks"]
    add_chain("wood_planks_L", "Wood planks sorted by lightness", planks, "family_lightness")
    return chains


def attach_chain_refs(records: list[dict], chains: list[dict]) -> None:
    by_id = {r["id"]: r for r in records}
    for r in records:
        r["gradient_chains"] = []
    for ch in chains:
        ids = ch["blocks"]
        for i, bid in enumerate(ids):
            rec = by_id.get(bid)
            if not rec:
                continue
            rec["gradient_chains"].append({
                "chain": ch["id"],
                "index": i,
                "prev": ids[i - 1] if i else None,
                "next": ids[i + 1] if i + 1 < len(ids) else None,
            })

# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def load_font(size: int):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def thumb_from_rgba(rgba: np.ndarray, size: int) -> Image.Image:
    im = Image.fromarray(rgba, "RGBA")
    return im.resize((size, size), Image.Resampling.NEAREST).convert("RGBA")


def draw_swatch_sheet(records: list[dict], path: Path) -> None:
    def sort_key(r):
        h = r["overall"].get("hue_deg")
        c = r["overall"].get("chroma") or 0
        L = r["overall"].get("brightness_L") or 0
        if c < 0.03 or h is None:
            return (0, L, r["id"])
        return (1, h, L, r["id"])

    items = sorted(records, key=sort_key)
    cols = 12
    thumb = 32
    sw = 32
    pad = 6
    label_h = 28
    cell_w = 118
    cell_h = max(thumb, sw) + label_h + pad * 2
    rows = math.ceil(len(items) / cols) if items else 1
    header = 64
    W = cols * cell_w + pad
    H = header + rows * cell_h + pad
    img = Image.new("RGB", (W, H), (18, 18, 20))
    draw = ImageDraw.Draw(img)
    font = load_font(11)
    font_h = load_font(18)
    title = (
        f"Minecraft {MC_VERSION} block colours  ·  {len(items)} blocks  ·  "
        "OKLab mean  ·  sorted grey→hue→lightness"
    )
    draw.text((12, 16), title, fill=(235, 235, 230), font=font_h)
    draw.text(
        (12, 40),
        "Left: face texture (side, or top if no side).  Right: canonical average colour.",
        fill=(160, 160, 158),
        font=font,
    )
    checker = (40, 40, 44)
    for i, rec in enumerate(items):
        r, c = divmod(i, cols)
        x = pad + c * cell_w
        y = header + r * cell_h
        bg = Image.new("RGBA", (thumb, thumb), checker + (255,))
        if rec.get("_thumb") is not None:
            bg.alpha_composite(thumb_from_rgba(rec["_thumb"], thumb))
        img.paste(bg.convert("RGB"), (x + pad, y + pad))
        hexv = rec["overall"]["hex"]
        col = rgb_from_hex(hexv)
        draw.rectangle(
            [x + pad + thumb + pad, y + pad, x + pad + thumb + pad + sw - 1, y + pad + sw - 1],
            fill=col,
        )
        name = rec["id"]
        if len(name) > 22:
            name = name[:21] + "…"
        draw.text((x + pad, y + pad + thumb + 2), name, fill=(210, 210, 205), font=font)
        draw.text((x + pad, y + pad + thumb + 12), hexv, fill=(140, 140, 136), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)


def draw_gradient_chart(records: list[dict], chains: list[dict], path: Path) -> None:
    want = [
        "greyscale_smooth", "wood_planks_L", "family_terracotta_smooth",
        "family_concrete_L", "family_wool_L", "copper_oxidation",
        "cut_copper_oxidation", "family_stone_smooth", "family_deepslate_smooth",
        "family_sandstone_smooth", "hue_orange_smooth", "hue_green_smooth",
        "hue_blue_smooth", "wool_hue_wheel", "terracotta_hue_wheel",
    ]
    by_id = {r["id"]: r for r in records}
    ch_by = {c["id"]: c for c in chains}
    rows = [ch_by[k] for k in want if k in ch_by and len(ch_by[k]["blocks"]) >= 3]
    if len(rows) < 6:
        for c in chains:
            if c not in rows and c["kind"] in {
                "family_smooth", "oxidation", "greyscale_smooth", "dye_hue_wheel"
            }:
                rows.append(c)
            if len(rows) >= 12:
                break

    thumb = 44
    pad = 8
    header = 70
    row_h = thumb + 48 + pad
    maxn = max((len(c["blocks"]) for c in rows), default=8)
    W = max(1400, pad * 2 + 280 + maxn * (thumb + 8))
    H = header + len(rows) * row_h + pad
    img = Image.new("RGB", (W, H), (18, 18, 20))
    draw = ImageDraw.Draw(img)
    font = load_font(12)
    font_s = load_font(10)
    font_h = load_font(20)
    draw.text((14, 14), f"Sample gradient ramps  ·  Minecraft {MC_VERSION}", fill=(235, 235, 230), font=font_h)
    draw.text(
        (14, 42),
        "Each cell is texture + average colour. Family ramps are sorted by CIELAB L*; "
        "copper is oxidation order; dye wheels are hue order.",
        fill=(160, 160, 158),
        font=font,
    )
    for ri, ch in enumerate(rows):
        y = header + ri * row_h
        draw.text((14, y), ch["id"], fill=(230, 230, 225), font=font)
        desc = ch.get("description", "")
        extra = ""
        if ch.get("step_delta_e00"):
            extra = f"  ·  max step ΔE00 {ch['max_step_delta_e00']}"
        draw.text((14, y + 16), desc + extra, fill=(150, 150, 148), font=font_s)
        x = 280
        for bid, hx in zip(ch["blocks"], ch["hexes"]):
            rec = by_id.get(bid)
            if rec is not None and rec.get("_thumb") is not None:
                t = thumb_from_rgba(rec["_thumb"], thumb)
                bg = Image.new("RGBA", (thumb, thumb), (40, 40, 44, 255))
                bg.alpha_composite(t)
                img.paste(bg.convert("RGB"), (x, y))
            col = rgb_from_hex(hx)
            draw.rectangle([x, y + thumb, x + thumb - 1, y + thumb + 12], fill=col)
            label = bid.replace("_", "\n")
            # two-line wrap on underscores already; if still long, shrink
            draw.multiline_text((x, y + thumb + 14), label, fill=(200, 200, 196), font=font_s, spacing=0)
            x += thumb + 8
    img.save(path, "PNG", optimize=True)


# Values published by MCBI (mcbi.ai) for Minecraft 26.3, OKLab mean of visible
# pixels, measured from game textures on 2026-09-21. Used only to check
# agreement; not copied into the dataset.
PUBLISHED_HEX = {
    # Independently confirmed against MCBI 26.3 OKLab means (https://mcbi.ai/block/<id>).
    # These are citations for agreement only; our dataset is computed from the client jar.
    "white_concrete": {"hex": "#CFD5D6", "source": "MCBI 26.3 (OKLab mean)"},
    "black_concrete": {"hex": "#080A0F", "source": "MCBI 26.3 (OKLab mean)"},
    "oak_planks": {"hex": "#A2824E", "source": "MCBI 26.3 (OKLab mean)"},
    "white_wool": {"hex": "#EAECED", "source": "MCBI 26.3 (OKLab mean)"},
    "stone": {"hex": "#7D7D7D", "source": "MCBI 26.3 (OKLab mean)"},
    "cobblestone": {"hex": "#7F7F7F", "source": "MCBI 26.3 (OKLab mean)"},
    "glowstone": {"hex": "#AB8154", "source": "MCBI 26.3 (OKLab mean)"},
    "terracotta": {"hex": "#985E44", "source": "MCBI 26.3 (OKLab mean)"},
}


def try_fetch_more_published() -> None:
    """Best-effort: pull a handful of MCBI block pages for agreement checks."""
    try:
        import urllib.request
    except ImportError:
        return
    ids = [
        "white_concrete", "black_concrete", "orange_concrete", "oak_planks",
        "spruce_planks", "stone", "cobblestone", "glowstone", "white_wool",
        "terracotta", "grass_block",
    ]
    ua = {"User-Agent": "mc-blocks-dataset/1.0 (local research; colour cross-check)"}
    for bid in ids:
        if bid in PUBLISHED_HEX and bid != "white_concrete":
            continue
        url = f"https://mcbi.ai/block/{bid}"
        try:
            req = urllib.request.Request(url, headers=ua)
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", "replace")
        except Exception:
            continue
        hexes = re.findall(r"#[0-9A-Fa-f]{6}", html)
        if not hexes:
            continue
        counts = {}
        for h in hexes:
            hu = h.upper()
            if hu in {"#FFFFFF", "#000000"}:
                continue
            counts[hu] = counts.get(hu, 0) + 1
        if not counts:
            continue
        best = max(counts, key=counts.get)
        if counts[best] >= 2:
            PUBLISHED_HEX.setdefault(
                bid,
                {"hex": best, "source": f"MCBI page {url} (most frequent hex, best-effort)"},
            )


def crosscheck(records: list[dict]) -> list[dict]:
    by_id = {r["id"]: r for r in records}
    out = []
    for bid, info in PUBLISHED_HEX.items():
        rec = by_id.get(bid)
        if not rec:
            out.append({"id": bid, "published": info, "ours": None, "note": "not in dataset"})
            continue
        our = rec["overall"]["hex"]
        pub = info["hex"]
        d = ciede2000(
            srgb8_to_lab(np.array(rgb_from_hex(our), dtype=np.float64)),
            srgb8_to_lab(np.array(rgb_from_hex(pub), dtype=np.float64)),
        )
        out.append({
            "id": bid,
            "published_hex": pub,
            "published_source": info["source"],
            "our_hex": our,
            "delta_e00": round(d, 3),
            "agree": d < 1.0,
        })
    return out


CSV_COLUMNS = [
    "id", "display_name", "shape", "family", "subfamily", "dye_color", "wood_type",
    "emits_light", "light_level", "gravity", "biome_tinted", "tint_type",
    "faces_differ", "sides_differ", "face_delta_e00", "partially_transparent",
    "has_cutout", "has_translucency", "animated", "busyness", "l_stddev",
    "spatial_contrast",
    "overall_hex", "overall_r", "overall_g", "overall_b",
    "overall_lab_L", "overall_lab_a", "overall_lab_b",
    "overall_oklab_L", "overall_oklab_a", "overall_oklab_b",
    "overall_oklch_L", "overall_oklch_C", "overall_oklch_h",
    "brightness_L", "lightness_rank", "lightness_percentile", "hue_deg", "chroma",
    "top_hex", "side_hex", "bottom_hex",
    "top_lab_L", "side_lab_L", "bottom_lab_L",
    "dominant_hex_1", "dominant_pct_1", "dominant_hex_2", "dominant_pct_2",
    "dominant_hex_3", "dominant_pct_3",
    "nearest_1_id", "nearest_1_dE", "nearest_2_id", "nearest_2_dE",
    "nearest_3_id", "nearest_3_dE", "nearest_4_id", "nearest_4_dE",
    "nearest_5_id", "nearest_5_dE",
    "texture_top", "texture_side", "texture_bottom",
]


def flatten_csv_row(rec: dict) -> dict:
    ov = rec["overall"]
    lab, ok, lch = ov["lab"], ov["oklab"], ov["oklch"]
    dom = rec.get("dominant_colours") or []
    near = rec.get("nearest") or []
    row = {
        "id": rec["id"],
        "display_name": rec["display_name"],
        "shape": rec["shape"],
        "family": rec["family"],
        "subfamily": rec.get("subfamily") or "",
        "dye_color": rec.get("dye_color") or "",
        "wood_type": rec.get("wood_type") or "",
        "emits_light": rec["emits_light"],
        "light_level": rec["light_level"],
        "gravity": rec["gravity"],
        "biome_tinted": rec["biome_tinted"],
        "tint_type": rec.get("tint_type") or "",
        "faces_differ": rec["faces_differ"],
        "sides_differ": rec["sides_differ"],
        "face_delta_e00": rec["face_delta_e00"],
        "partially_transparent": rec["partially_transparent"],
        "has_cutout": rec["has_cutout"],
        "has_translucency": rec["has_translucency"],
        "animated": rec["animated"],
        "busyness": rec.get("busyness") or "",
        "l_stddev": rec.get("l_stddev"),
        "spatial_contrast": rec.get("spatial_contrast"),
        "overall_hex": ov["hex"],
        "overall_r": ov["srgb"][0],
        "overall_g": ov["srgb"][1],
        "overall_b": ov["srgb"][2],
        "overall_lab_L": lab[0],
        "overall_lab_a": lab[1],
        "overall_lab_b": lab[2],
        "overall_oklab_L": ok[0],
        "overall_oklab_a": ok[1],
        "overall_oklab_b": ok[2],
        "overall_oklch_L": lch["L"],
        "overall_oklch_C": lch["C"],
        "overall_oklch_h": lch["h"] if lch["h"] is not None else "",
        "brightness_L": rec["brightness_L"],
        "lightness_rank": rec["lightness_rank"],
        "lightness_percentile": rec["lightness_percentile"],
        "hue_deg": ov.get("hue_deg") if ov.get("hue_deg") is not None else "",
        "chroma": ov.get("chroma"),
        "top_hex": rec["faces"]["top"]["hex"],
        "side_hex": rec["faces"]["side"]["hex"],
        "bottom_hex": rec["faces"]["bottom"]["hex"],
        "top_lab_L": rec["faces"]["top"].get("brightness_L"),
        "side_lab_L": rec["faces"]["side"].get("brightness_L"),
        "bottom_lab_L": rec["faces"]["bottom"].get("brightness_L"),
        "texture_top": " ".join(rec["textures"].get("top") or []),
        "texture_side": " ".join(rec["textures"].get("side") or []),
        "texture_bottom": " ".join(rec["textures"].get("bottom") or []),
    }
    for i in range(3):
        if i < len(dom):
            row[f"dominant_hex_{i+1}"] = dom[i]["hex"]
            row[f"dominant_pct_{i+1}"] = dom[i]["fraction"]
        else:
            row[f"dominant_hex_{i+1}"] = ""
            row[f"dominant_pct_{i+1}"] = ""
    for i in range(5):
        if i < len(near):
            row[f"nearest_{i+1}_id"] = near[i]["id"]
            row[f"nearest_{i+1}_dE"] = near[i]["delta_e00"]
        else:
            row[f"nearest_{i+1}_id"] = ""
            row[f"nearest_{i+1}_dE"] = ""
    return row


def strip_private(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jar", type=Path, default=here / "raw" / "client-26.3.jar")
    ap.add_argument("--assets", type=Path, default=here / "assets")
    ap.add_argument("--out", type=Path, default=here)
    ap.add_argument("--skip-fetch-crosscheck", action="store_true")
    args = ap.parse_args()

    _selftest_color()

    assets_root = args.assets
    needed = assets_root / "assets/minecraft/blockstates"
    if not needed.exists():
        if not args.jar.exists():
            raise SystemExit(
                f"No assets at {needed} and no client jar at {args.jar}.\n"
                f"Download the official {MC_VERSION} client (sha1 {CLIENT_SHA1}) from:\n"
                f"  {CLIENT_URL}\n"
                f"via the version manifest {MANIFEST_URL}"
            )
        print(f"Extracting assets from {args.jar} …")
        extract_assets(args.jar, assets_root)

    assets = AssetIndex(assets_root)
    block_ids = sorted(p.stem for p in assets.blockstates.glob("*.json"))
    rng = np.random.default_rng(26_0003)

    records = []
    logs = []
    for bid in block_ids:
        rec, log = process_block(bid, assets, rng)
        logs.append(log)
        if rec is not None:
            records.append(rec)

    ordered = sorted(records, key=lambda r: (r["overall"]["brightness_L"], r["id"]))
    n = len(ordered)
    for i, rec in enumerate(ordered, start=1):
        rec["lightness_rank"] = i
        rec["lightness_percentile"] = round(100.0 * (i - 1) / max(n - 1, 1), 2)
        rec["brightness_L"] = rec["overall"]["brightness_L"]

    nearest_neighbours(records, k=5)
    chains = build_gradient_chains(records)
    attach_chain_refs(records, chains)

    if not args.skip_fetch_crosscheck:
        try_fetch_more_published()
    xcheck = crosscheck(records)

    excluded = [l for l in logs if not l.get("included")]
    reason_counts = defaultdict(int)
    reason_examples = defaultdict(list)
    for l in excluded:
        r = l.get("reason") or "unknown"
        reason_counts[r] += 1
        if len(reason_examples[r]) < 8:
            reason_examples[r].append(l["id"])

    shape_counts = defaultdict(int)
    family_counts = defaultdict(int)
    for rec in records:
        shape_counts[rec["shape"]] += 1
        family_counts[rec["family"]] += 1

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "minecraft_version": MC_VERSION,
        "client_sha1": CLIENT_SHA1,
        "client_url": CLIENT_URL,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "blockstate_count": len(block_ids),
        "included_count": len(records),
        "excluded_count": len(excluded),
        "shape_counts": dict(shape_counts),
        "family_counts": dict(sorted(family_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "excluded_reason_counts": dict(sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "excluded_reason_examples": dict(reason_examples),
        "tints": {k: hex_from_rgb(v) for k, v in TINTS.items()},
        "averaging": (
            "Canonical colours are the OKLab mean of visible (alpha>0) pixels, "
            "converted back to sRGB, CIELAB and OKLCh. Animated textures are "
            "first time-averaged in linear RGB. Face overall colour is the "
            "OKLab mean of top + bottom + four sides (weights 1+1+4). "
            "Naïve sRGB means are stored on each face as hex_naive for comparison."
        ),
        "distance": "CIEDE2000 in CIELAB (D65, 2°) on the Lab of the OKLab-mean colour.",
        "notes": [
            "Textures and models are © Mojang Studios, extracted from the official client for analysis. They are not redistributed as a resource pack.",
            "Redstone ore is excluded with other redstone components, even though it is a natural ore.",
            "Leaf blocks are excluded as plants, even though builders often use them.",
            "Chests, shulker boxes, signs, beds, vaults, spawners, beacons and respawn anchors are excluded as entity/special utility blocks.",
            "Copper bulbs and redstone lamps are excluded as redstone-controlled lights; glowstone, sea lanterns, shroomlights, froglights, magma, crying obsidian, jack o'lanterns and sculk catalysts are included.",
        ],
    }

    payload = {
        "meta": meta,
        "blocks": [strip_private(r) for r in sorted(records, key=lambda r: r["id"])],
        "gradient_chains": chains,
        "crosscheck": xcheck,
    }
    json_path = out_dir / "blocks.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    csv_path = out_dir / "blocks.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for rec in sorted(records, key=lambda r: r["id"]):
            w.writerow(flatten_csv_row(rec))

    excl_path = out_dir / "excluded.json"
    excl_path.write_text(json.dumps({
        "count": len(excluded),
        "by_reason": dict(reason_counts),
        "examples": dict(reason_examples),
        "blocks": [
            {"id": l["id"], "reason": l.get("reason")}
            for l in sorted(excluded, key=lambda x: (x.get("reason") or "", x["id"]))
        ],
    }, indent=2) + "\n")

    swatch_path = out_dir / "swatches.png"
    grad_path = out_dir / "gradients.png"
    print("Drawing swatch sheet …")
    draw_swatch_sheet(records, swatch_path)
    print("Drawing gradient chart …")
    draw_gradient_chart(records, chains, grad_path)

    print()
    print(f"Minecraft {MC_VERSION}  client sha1 {CLIENT_SHA1}")
    print(f"Blockstates: {len(block_ids)}")
    print(f"Included:    {len(records)}  {dict(shape_counts)}")
    print(f"Excluded:    {len(excluded)}")
    for r, c in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {r:20s} {c:4d}  e.g. {', '.join(reason_examples[r][:5])}")
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {excl_path}")
    print(f"Wrote {swatch_path}")
    print(f"Wrote {grad_path}")
    print("Cross-check:")
    for row in xcheck:
        print(" ", row)


if __name__ == "__main__":
    main()
