#!/usr/bin/env python3
"""Detailed-parts / stamped pipeline: same stages as the original photo-to-Minecraft path, with facade orientation
and blueprint part stamping inserted after voxelize, before materials and mc_map.

Original (README):
  photo -> cut-out -> sheets -> mesh -> paint -> shape fit -> materials -> noise -> mc_map

This runner (stamped):
  photo -> cut-out -> sheets -> mesh
       -> voxelize (plain fal grid) -> orient facade onto +z
       -> stamp_parts (only listed blueprint parts, as structure)
       -> optional resize to W×H×D
       -> materials (limestone / roof / openings from geometry + stamp masks)
       -> noise (lightweight, same schema as noise_measure)
       -> mc_map (WINDOW_KIT off: openings are already carved)

Cathedral is the first subject with a stamper + blueprint
(`specs/detailed-parts-cathedral.md` -> `art/final/meta/cathedral_blueprint.json`).

usage:
  python run_stamped.py cathedral [--grid 80] [--size 45,80,84]
  python run_stamped.py cathedral --skip-sheet --skip-mesh --mesh out/cathedral_lowpoly.glb --size 45,80,84
  python run_stamped.py cathedral --parts rose,portal_main,portal_side,front_window

Outputs (alias = NAME_stamped):
  out/NAME_stamped/                 grey renders, part checks, voxels json
  art/final/NAME_stamped_voxels_textured.json
  art/final/meta/NAME_stamped_*.json
  art/final/NAME_stamped_mc_blocks.json + schematics/
"""
import argparse, json, os, collections, shutil, urllib.request
import numpy as np
from scipy import ndimage

import fal_shape, orient, stamp_parts as SP, mc_map, blueprint as BP


ALIAS = "{n}_stamped"
BASES = {
    "cathedral": {"limestone": "#c9a46a", "roof_slate": "#4a4f57", "window_dark": "#2e2a2a"},
}
WINDOW_PARTS = ("rose", "portal_main", "portal_side", "front_window", "gallery_arcade", "aisle_window",
                "aisle_window_left", "clerestory_window", "clerestory_window_left", "apse_window",
                "belfry_opening", "front_gable")


def ensure_dirs():
    for p in ("out", "art/final", "art/final/meta", "art/final/schematics", "ortho", "refs"):
        os.makedirs(p, exist_ok=True)


def stage_sheet(n, skip):
    """1-2. cut-out + drawing sheets (original ortho_verify path). Reuses an existing verify pick when --skip-sheet."""
    if skip:
        for p in (f"out/{n}_verify.json", f"art/final/meta/{n}_views.json"):
            if os.path.exists(p):
                V = json.load(open(p)); print("sheet: reuse", p, "chosen", V.get("chosen")); return V
        # ortho views alone are enough for orient + mesh reuse
        for tag in ("_v3", "_v2", "_v1", ""):
            if os.path.exists(f"ortho/{n}{tag}_right.png"):
                print("sheet: reuse ortho tag", tag or "(none)"); return {"chosen": tag, "views_used": ["front", "right", "back", "top"]}
        raise SystemExit(f"sheet: --skip-sheet but no verify json or ortho/{n}_*_right.png")
    import gen_refs
    if not os.path.exists(f"refs/{n}_fal_in.png"):
        print("sheet: gen_refs.prep", n); gen_refs.prep(n)
    import ortho_verify
    print("sheet: ortho_verify", n)
    # ortho_verify is CLI-driven; call the same way the original does
    import subprocess, sys
    r = subprocess.run([sys.executable, "ortho_verify.py", n], check=False)
    if r.returncode: raise SystemExit(f"ortho_verify failed ({r.returncode})")
    return json.load(open(f"out/{n}_verify.json"))


def stage_mesh(n, skip, mesh_path, faces):
    """3. Hyper3D lowpoly mesh (original ortho_lowpoly path)."""
    if mesh_path and os.path.exists(mesh_path):
        print("mesh: reuse", mesh_path); return mesh_path
    glb = f"out/{n}_lowpoly.glb"
    if skip and os.path.exists(glb):
        print("mesh: reuse", glb); return glb
    if skip:
        # try recorded URL
        meta = f"art/final/meta/{n}_mesh.json"
        if os.path.exists(meta):
            urllib.request.urlretrieve(json.load(open(meta))["url"], glb)
            print("mesh: re-downloaded", glb); return glb
        raise SystemExit(f"mesh: --skip-mesh but no {glb}")
    import subprocess, sys
    print("mesh: ortho_lowpoly", n, "faces", faces)
    r = subprocess.run([sys.executable, "ortho_lowpoly.py", n, "--faces", str(faces)], check=False)
    if r.returncode: raise SystemExit(f"ortho_lowpoly failed ({r.returncode})")
    return glb


def stage_voxels(glb, grid, n, sheet_tag):
    """Voxelize at `grid`, then flip so the facade (spires) sits on +z."""
    print("voxels: fal_shape.voxelize", glb, "grid", grid)
    d = fal_shape.voxelize(glb, grid)
    W, H, D = d["size"]; occ = np.zeros((W, H, D), bool)
    for v in d["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    right = f"ortho/{n}{sheet_tag}_right.png" if sheet_tag else f"ortho/{n}_right.png"
    if not os.path.exists(right):
        # fall back to any right elevation for this subject
        cands = [f"ortho/{n}_v3_right.png", f"ortho/{n}_v2_right.png", f"ortho/{n}_right.png"]
        right = next((p for p in cands if os.path.exists(p)), None)
    if orient.facade_flip(occ, right):
        d = orient.flip_voxel_dict(d); occ = orient.flip_occ(occ).copy()
        d["orientation"] = "flipped 180 about y (facade was on -z)"
    d["name"] = f"{n}_stamped_g{grid}"
    p = f"out/{n}_stamped_g{grid}.json"; json.dump(d, open(p, "w"))
    print("voxels:", occ.shape, int(occ.sum()), "->", p)
    return occ, p


def stage_stamp(occ, n, parts):
    """Stamp only the blueprint parts as structure (strict)."""
    bp_path = f"art/final/meta/{n}_blueprint.json"
    if not os.path.exists(bp_path):
        if n != "cathedral":
            raise SystemExit(f"stamp: no blueprint at {bp_path} (only cathedral is wired today)")
        bp = BP.parse_notes(); json.dump(bp, open(bp_path, "w"), indent=1)
    else:
        bp = json.load(open(bp_path))
    print("stamp: parts", "all" if parts is None else sorted(parts))
    occ2, S = SP.stamp(occ, parts=parts)
    rows = SP.check(S, bp)
    return occ2, S, rows, bp


def stage_resize(occ, size):
    """Optional nearest-neighbour resize to exact W×H×D (e.g. 45,80,84)."""
    if not size: return occ
    xs, ys, zs = np.nonzero(occ)
    occ = occ[xs.min():xs.max() + 1, ys.min():ys.max() + 1, zs.min():zs.max() + 1]
    zoom = (size[0] / occ.shape[0], size[1] / occ.shape[1], size[2] / occ.shape[2])
    occ = ndimage.zoom(occ.astype(float), zoom, order=0) >= 0.5
    out = np.zeros(size, bool)
    sl = tuple(slice(0, min(size[i], occ.shape[i])) for i in range(3))
    out[sl] = occ[sl]
    print("resize:", size, int(out.sum()))
    return out


def label_materials(occ, S, n):
    """Geometry materials for mc_map: roof from the heightfield, openings from stamp masks (or front recesses)."""
    W, H, D = occ.shape
    bases = BASES.get(n, BASES["cathedral"])
    hf = np.where(occ.any(1), H - 1 - np.argmax(occ[:, ::-1, :], 1), -1)
    mid = hf[:, D // 4:D // 2]; ridge = int(np.median(mid[mid >= 0])) if (mid >= 0).any() else H // 2
    xs, ys, zs = np.nonzero(occ)
    top = ys == hf[xs, zs]
    roof = np.zeros_like(occ); roof[xs, ys, zs] = top & (ys >= int(0.55 * ridge))
    surf = occ & ~ndimage.binary_erosion(np.pad(occ, 1), iterations=1)[1:-1, 1:-1, 1:-1]
    win = np.zeros_like(occ, bool)
    if S is not None and getattr(S, "mask", None):
        for part, m in S.mask.items():
            if part in WINDOW_PARTS or part.replace("_left", "") in WINDOW_PARTS:
                win |= m.astype(bool)
        win &= surf & occ & ~roof
        pad = np.pad(occ, 1); air = False
        for ax in range(3):
            for sgn in (1, -1):
                air = air | ~np.roll(pad, -sgn, ax)[1:-1, 1:-1, 1:-1]
        win &= air
    else:
        # after resize: openings = surface cells set back from the local front plane
        z_out = np.where(occ.any(2), D - 1 - np.argmax(occ[:, :, ::-1], 2), -1)
        sx, sy, sz = np.nonzero(surf)
        for x, y, z in zip(sx, sy, sz):
            if z_out[x, y] >= 0 and 1 <= (z_out[x, y] - z) <= 4: win[x, y, z] = True
        win &= ~roof
    g = ndimage.gaussian_filter(occ.astype(float), 1.0)
    ao = np.clip(1.0 - g / (g[occ].mean() + 1e-6), 0, 1)
    mat = np.full(occ.shape, "limestone", object); mat[roof] = "roof_slate"; mat[win] = "window_dark"
    print("materials:", dict(collections.Counter(mat[occ].tolist())))
    return mat, surf, ao, bases


def shade_of(ao, x, y, z):
    a = float(ao[x, y, z])
    if a > 0.55: return -2
    if a > 0.4: return -1
    if a < 0.15: return 1
    return 0


def hex_for(base, sh):
    h = base.lstrip("#"); rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = {-2: 0.72, -1: 0.85, 0: 1.0, 1: 1.12}.get(sh, 1.0)
    rgb = [min(1, max(0, c * f)) for c in rgb]
    return "#%02x%02x%02x" % tuple(int(c * 255) for c in rgb)


def stage_colour_noise(alias, occ, mat, surf, ao, bases):
    """Write the same art/final files palette_generic + noise_measure produce, so mc_map can run unchanged."""
    W, H, D = occ.shape
    vox_tex, vox_lab, vox_nz, pal = [], [], [], {}
    for x, y, z in zip(*np.nonzero(occ)):
        m = mat[x, y, z]; sh = shade_of(ao, x, y, z); hx = hex_for(bases[m], sh)
        if hx not in pal: pal[hx] = f"p{len(pal)}"
        c = pal[hx]
        vox_tex.append({"x": int(x), "y": int(y), "z": int(z), "c": c})
        vox_lab.append({"x": int(x), "y": int(y), "z": int(z), "m": m, "sh": int(sh), "surf": bool(surf[x, y, z])})
        vox_nz.append({"x": int(x), "y": int(y), "z": int(z), "region": f"{m}|{sh}", "noise": float(6 + 8 * ao[x, y, z])})
    tex = {"name": alias, "size": [W, H, D], "camera": {"azim": 35, "elev": 20},
           "palette": {v: k for k, v in pal.items()}, "voxels": vox_tex}
    json.dump(tex, open(f"art/final/{alias}_voxels_textured.json", "w"))
    json.dump({"subject": alias, "size": [W, H, D], "zones": {"y0": 0, "y1": H - 1},
               "crisp": [["limestone", "window_dark"], ["roof_slate", "window_dark"]],
               "bases": bases, "voxels": vox_lab}, open(f"art/final/meta/{alias}_texture_labels.json", "w"))
    json.dump({"subject": alias, "voxels": vox_nz, "material_mean_noise": {}},
              open(f"art/final/meta/{alias}_noise.json", "w"))
    print("colour/noise: art/final/{}_voxels_textured.json ({} voxels)".format(alias, len(vox_tex)))
    return tex


def stage_mc_map(alias, parent):
    """Minecraft blocks. Openings are already carved, so WINDOW_KIT stays off."""
    os.environ["MC_WINDOW_KIT"] = "0"
    import importlib; importlib.reload(mc_map)
    mc_map.STRICT[alias] = set(mc_map.STRICT.get(parent, {"limestone", "roof_slate", "window_dark"}))
    mc_map.ACCENT_ALL = set(mc_map.ACCENT_ALL) | {alias}
    print("mc_map:", alias)
    out = mc_map.run(alias)
    return out


def write_bundle(n, alias, occ, S, rows, mout):
    out_dir = f"out/{alias}"; os.makedirs(out_dir, exist_ok=True)
    np.save(f"{out_dir}/stamped.npy", occ)
    xs, ys, zs = np.nonzero(occ)
    json.dump({"name": alias, "size": list(occ.shape), "camera": {"azim": 35, "elev": 20}, "palette": {"a": "#b9b9b9"},
               "voxels": [{"x": int(x), "y": int(y), "z": int(z), "c": "a"} for x, y, z in zip(xs, ys, zs)]},
              open(f"{out_dir}/{alias}_voxels.json", "w"))
    json.dump(rows, open(f"{out_dir}/part_checks.json", "w"), indent=1)
    shutil.copy(f"art/final/{alias}_mc_blocks.json", f"{out_dir}/{alias}_mc_blocks.json")
    # grey renders
    import vox
    from PIL import Image, ImageDraw
    flat = np.full(occ.shape + (3,), 185, np.uint8)
    for name, (az, el, lit) in {"front": (0, 8, (-0.45, 0.55, 0.7)), "three_quarter": (35, 20, (-0.8, 0.5, 0.5))}.items():
        vox.render(occ, flat, az, el, 700, light=lit, ao=True)[0].save(f"{out_dir}/{name}_grey.png")
    if S is not None:
        pc = SP.parts_colour(S) if hasattr(S, "mask") and S.mask else flat
        # after resize S.mask may not match; skip parts colour if shapes differ
        if pc.shape[:3] == occ.shape:
            im = vox.render(occ, pc, 18, 8, 700, light=(-0.8, 0.5, 0.6), ao=True)[0]
            ImageDraw.Draw(im).text((8, 4), f"{alias} parts", fill="black")
            im.save(f"{out_dir}/front_oblique_parts.png")
    print("bundle:", out_dir)


def run(n, grid=80, size=None, skip_sheet=False, skip_mesh=False, mesh=None, faces=4000, parts=None):
    ensure_dirs()
    alias = f"{n}_stamped"
    print("=== stamped pipeline:", n, "->", alias, "===")

    V = stage_sheet(n, skip_sheet)
    tag = V.get("chosen", "")
    glb = stage_mesh(n, skip_mesh, mesh, faces)
    occ, vp = stage_voxels(glb, grid, n, tag)
    occ, S, rows, bp = stage_stamp(occ, n, parts)
    # geometry check before resize (masks match this grid)
    out_dir = f"out/{alias}"; os.makedirs(out_dir, exist_ok=True)
    json.dump(rows, open(f"{out_dir}/part_checks_fullres.json", "w"), indent=1)
    print(f"{'part':26s} {'count':>5s} {'found':>5s} {'ok':>5s}")
    for k, r in rows.items():
        print(f"{k:26s} {r['count']:5d} {str(r['found']):>5s} {r['geometry_ok']:5d}")

    occ_r = stage_resize(occ, size)
    mat, surf, ao, bases = label_materials(occ_r, None if size else S, n)
    stage_colour_noise(alias, occ_r, mat, surf, ao, bases)
    mout = stage_mc_map(alias, n)
    write_bundle(n, alias, occ_r, S if size is None else None, rows, mout)
    print("=== done:", f"art/final/{alias}_mc_blocks.json", "size", mout["size"], "blocks", len(mout["voxels"]), "===")
    return mout


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Stamped / detailed-parts pipeline (parallel to the original)")
    ap.add_argument("name", help="subject name (cathedral today)")
    ap.add_argument("--grid", type=int, default=80, help="fal voxelize grid (longest side)")
    ap.add_argument("--size", default=None, help="final W,H,D e.g. 45,80,84 (nearest resize after stamp)")
    ap.add_argument("--mesh", default=None, help="reuse this .glb instead of generating")
    ap.add_argument("--faces", type=int, default=4000)
    ap.add_argument("--skip-sheet", action="store_true", help="reuse existing ortho / verify pick")
    ap.add_argument("--skip-mesh", action="store_true", help="reuse existing lowpoly glb or mesh URL")
    ap.add_argument("--parts", default=None, help="comma-separated blueprint ids (default: all)")
    a = ap.parse_args()
    size = None if not a.size else tuple(int(x) for x in a.size.split(","))
    if size and len(size) != 3: raise SystemExit("--size must be W,H,D")
    parts = None if not a.parts else {p.strip() for p in a.parts.split(",") if p.strip()}
    run(a.name, grid=a.grid, size=size, skip_sheet=a.skip_sheet, skip_mesh=a.skip_mesh,
        mesh=a.mesh, faces=a.faces, parts=parts)
