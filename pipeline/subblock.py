#!/usr/bin/env python3
"""Mixed-resolution (Minecraft-style) voxels: build a subject at a smaller block grid, using sub-blocks only on slopes/curves.
usage: python subblock.py NAME [--n 24] [--lam 6]
Fine grid = 4x the target block grid, voxelised from the Hunyuan GLB (out/NAME_hymv.glb); colours from art/NAME_rendered_toned.json.
Allowed shapes (one-axis cuts only, plus stairs):
  full | slab (height 1/2 or 1/4, align bottom/top) | vslab (width 1/2 or 1/4 along x or z, flush to one side) | stairs (facing N/S/E/W, half bottom/top)
Directions (Minecraft): +x = east, -x = west, +z = south (the model front), -z = north. Stairs 'facing' = side of the tall step.
Writes art/NAME_half_full.json (full blocks only), art/NAME_half_sub.json (per-voxel 's' shape), art/NAME_half_sub_fine.json (expanded 4x grid for render/score),
out/NAME_subblock_report.json"""
import argparse, json, numpy as np, trimesh
from scipy import ndimage
import vox
F = 4
def T(): return np.zeros((F, F, F), bool)      # template indexed [x, y, z] in fine units
def shapes():
    S = [({"type": "full"}, np.ones((F, F, F), bool))]
    for size, k in ((0.5, 2), (0.25, 1)):
        t = T(); t[:, :k, :] = 1; S.append(({"type": "slab", "size": size, "align": "bottom"}, t))
        t = T(); t[:, F-k:, :] = 1; S.append(({"type": "slab", "size": size, "align": "top"}, t))
        for axis, ai, lo, hi in (("x", 0, "west", "east"), ("z", 2, "north", "south")):
            for side in (lo, hi):
                t = T(); sl = [slice(None)]*3; sl[ai] = slice(0, k) if side == lo else slice(F-k, F); t[tuple(sl)] = 1
                S.append(({"type": "vslab", "size": size, "axis": axis, "align": side}, t))
    for half in ("bottom", "top"):
        for facing, ai, hi_side in (("east", 0, True), ("west", 0, False), ("south", 2, True), ("north", 2, False)):
            t = T()
            if half == "bottom": t[:, :2, :] = 1; ys = slice(2, 4)
            else: t[:, 2:, :] = 1; ys = slice(0, 2)
            sl = [slice(None)]*3; sl[1] = ys; sl[ai] = slice(2, 4) if hi_side else slice(0, 2); t[tuple(sl)] = 1
            S.append(({"type": "stairs", "facing": facing, "half": half}, t))
    return S
SHAPES = shapes()

def solidify(o, it=2):
    """close gaps of leaky/low-poly shells (it fine voxels), fill enclosed volume, plus per-slice ring fill for open-bottom shells"""
    o = o | ndimage.binary_erosion(ndimage.binary_fill_holes(ndimage.binary_dilation(o, iterations=it)), iterations=it)
    for y in range(o.shape[1]):
        sl = o[:, y, :]; o[:, y, :] = sl | ndimage.binary_erosion(ndimage.binary_fill_holes(ndimage.binary_dilation(sl, iterations=it)), iterations=it)
    return o

def build(n, N=24, lam=6.0, thin_min=0.12, close=2, keep_thin=False):
    """n = model key (e.g. cottage or cottage_t)"""
    import os
    sc = trimesh.load(f"out/{n}.glb" if os.path.exists(f"out/{n}.glb") else f"out/{n}_hymv.glb"); mesh = sc.to_geometry() if isinstance(sc, trimesh.Scene) else sc
    d48, occ48, col48, _ = vox.load(f"art/{n}_rendered_toned.json", seed=0)
    G48 = max(d48["size"]); p48 = mesh.extents.max()/(G48 - 1); o48 = mesh.voxelized(p48).transform[:3, 3]   # colour model grid (48 or larger)
    Nf = N*F; pf = mesh.extents.max()/(Nf-1); vg = mesh.voxelized(pf); of = vg.transform[:3, 3]
    fine = solidify(vg.matrix.copy(), close)
    # keep only fine voxels whose 48-grid cell is in the cleaned full-size model (inherits floater/ring removal)
    idx = np.argwhere(fine); world = of + idx*pf; i48 = np.round((world - o48)/p48).astype(int)
    i48 = np.clip(i48, 0, np.array(occ48.shape)-1)
    keep = ndimage.binary_dilation(occ48)[i48[:, 0], i48[:, 1], i48[:, 2]]
    fine[:] = False; fine[tuple(idx[keep].T)] = True
    # pad fine grid to a multiple of F
    shp = [int(np.ceil(s/F))*F for s in fine.shape]; fp = np.zeros(shp, bool); fp[:fine.shape[0], :fine.shape[1], :fine.shape[2]] = fine; fine = fp
    W, H, D = [s//F for s in shp]
    blocks = fine.reshape(W, F, H, F, D, F).transpose(0, 2, 4, 1, 3, 5)     # [X,Y,Z, fx,fy,fz]
    frac = blocks.mean((3, 4, 5))
    # smoothed surface normal at block centres (from the fine grid)
    g = ndimage.gaussian_filter(fine.astype(float), 2.5); G = -np.stack(np.gradient(g), -1)
    Gc = G[F//2::F, F//2::F, F//2::F][:W, :H, :D]; nn = np.linalg.norm(Gc, axis=-1, keepdims=True) + 1e-9; Nc = Gc/nn
    axis_aligned = np.abs(Nc).max(-1) > 0.92
    # colour: nearest surface voxel of the 48 model to each block centre
    surf48 = occ48 & ~ndimage.binary_erosion(np.pad(occ48, 1))[1:-1, 1:-1, 1:-1]
    _, si = ndimage.distance_transform_edt(~surf48, return_indices=True)
    def colour_at(X, Y, Z):
        w = of + (np.array([X, Y, Z])*F + (F-1)/2)*pf; j = np.clip(np.round((w - o48)/p48).astype(int), 0, np.array(occ48.shape)-1)
        # majority colour of the full-size surface voxels inside this block's footprint (less speckle than a single nearest voxel)
        lo = np.clip(np.floor((of + np.array([X, Y, Z])*F*pf - o48)/p48).astype(int), 0, None); hi = np.ceil((of + (np.array([X, Y, Z])+1)*F*pf - o48)/p48).astype(int)
        reg = surf48[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
        if reg.any():
            cs = col48[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]][reg]; u, cnt = np.unique(cs, axis=0, return_counts=True); return tuple(int(v) for v in u[cnt.argmax()])
        a, b, c = si[0][tuple(j)], si[1][tuple(j)], si[2][tuple(j)]; return tuple(int(v) for v in col48[a, b, c])
    Tm = np.stack([t for _, t in SHAPES]).reshape(len(SHAPES), -1).astype(int)
    full_only, sub = [], []; counts = {}; thin_kept = 0
    for X, Y, Z in np.argwhere(frac > 0):
        b = blocks[X, Y, Z].reshape(-1).astype(int); f = frac[X, Y, Z]
        if f >= 0.5: full_only.append((X, Y, Z))
        err = np.abs(Tm - b).sum(1).astype(float)          # Hamming error per shape (64 = all wrong)
        e_full, e_empty = err[0], b.sum()
        best_fe = (e_full, 0) if e_full <= e_empty else (e_empty, -1)
        choice = best_fe[1]
        partial_ok = (0.1 < f < 0.9) and not axis_aligned[X, Y, Z]
        thin = choice == -1 and f >= thin_min            # thin plates/sails that would vanish: allow a vslab/slab
        if partial_ok or thin:
            k = 1 + int(np.argmin(err[1:])); gain = best_fe[0] - err[k]
            if gain > (0 if thin else lam): choice = k
        if choice == -1 and keep_thin and f >= 0.04:
            # thin-feature preservation (spires, arch ribs, branches, flippers): material that runs THROUGH the cell (touches two
            # opposite faces) would vanish at block size and cut the feature; keep it as its best partial shape or a full block
            bb = blocks[X, Y, Z]
            through = (bb[:, 0, :].any() and bb[:, F-1, :].any()) or (bb[0].any() and bb[F-1].any()) or (bb[:, :, 0].any() and bb[:, :, F-1].any())
            if through:
                k = 1 + int(np.argmin(err[1:])); choice = k if err[k] < err[0] else 0; thin = True; thin_kept += 1
        if choice == -1: continue
        sub.append((X, Y, Z, choice, bool(thin and choice > 0)))
    # cleanup: (1) drop dangling sub-blocks (<= 1 occupied face neighbour) unless they are thin-plate cells (sails);
    # (2) drop connected pieces smaller than 1% of the model (stray rails/planks from the mesh)
    occc = np.zeros((W, H, D), bool)
    for c in sub: occc[c[:3]] = True
    nb = sum(np.roll(occc, s_, a_) for a_ in range(3) for s_ in (1, -1))
    removed = 0; keep_ = []
    for c in sub:
        if c[3] > 0 and not c[4] and nb[c[:3]] <= 1: removed += 1; continue
        keep_.append(c)
    occc[:] = False
    for c in keep_: occc[c[:3]] = True
    lab_, k_ = ndimage.label(occc); szs = np.bincount(lab_.ravel()); szs[0] = 0
    small = szs < 0.01*szs.sum()
    sub = []
    for c in keep_:
        if small[lab_[c[:3]]]: removed += 1; continue
        sub.append(c[:4]); nm = SHAPES[c[3]][0]["type"]; counts[nm] = counts.get(nm, 0) + 1
    # palette
    def write(cells, path, with_shape):
        pal, vs = {}, []
        for c in cells:
            X, Y, Z = c[:3]; h = "#%02x%02x%02x" % colour_at(X, Y, Z)
            key = pal.setdefault(h, f"c{len(pal)}")
            v = {"x": int(X), "y": int(Y), "z": int(Z), "c": key}
            if with_shape and c[3] != 0: v["s"] = SHAPES[c[3]][0]
            vs.append(v)
        json.dump({"name": path.split("/")[-1][:-5], "size": [W, H, D], "camera": {"azim": 35, "elev": 20},
                   "palette": {v: k for k, v in pal.items()}, "voxels": vs, "format_note": "voxel 's' = sub-block shape (absent = full block); see subblock.py"},
                  open(path, "w"))
        return pal
    write([c + (0,) for c in full_only], f"art/{n}_half_full.json", False)
    pal = write(sub, f"art/{n}_half_sub.json", True)
    expand(f"art/{n}_half_sub.json", f"art/{n}_half_sub_fine.json")
    nsub = sum(1 for c in sub if c[3] != 0)
    exposed = sum(1 for (X, Y, Z, _) in sub if any(not (0 <= X+dx < W and 0 <= Y+dy < H and 0 <= Z+dz < D) or frac[X+dx, Y+dy, Z+dz] < 0.5
                                                   for dx, dy, dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))))
    rep = {"block_grid": [W, H, D], "fine_grid": shp, "full_size_grid": list(occ48.shape), "cells_full_only": len(full_only), "cells_sub_model": len(sub),
           "sub_blocks": nsub, "pct_sub_of_all_cells": round(100*nsub/len(sub), 1), "pct_sub_of_surface_cells": round(100*nsub/max(exposed, 1), 1),
           "by_type": counts, "thin_kept": thin_kept, "lambda": lam, "close_fine_voxels": close, "cleanup_removed": removed}
    json.dump(rep, open(f"out/{n}_subblock_report.json", "w"), indent=1); print(n, rep); return rep

def expand(src, dst):
    """Sub-block JSON -> 4x fine voxel JSON (exact box geometry) for the standard renderer/scorer."""
    d = json.load(open(src)); W, H, D = d["size"]; lut = {json.dumps(s, sort_keys=True): t for s, t in SHAPES}
    vs = []
    for v in d["voxels"]:
        k = json.dumps(v.get("s", {"type": "full"}), sort_keys=True)
        if k not in lut:   # shape_fit.py shapes (stair corners, 3/16 quarters, walls, fences): rasterise the real geometry
            import shape_fit; lut[k] = shape_fit.raster(shape_fit.boxes01(v["s"]), F) >= 0.5
        t = lut[k]
        for a, b, c in np.argwhere(t): vs.append({"x": v["x"]*F+int(a), "y": v["y"]*F+int(b), "z": v["z"]*F+int(c), "c": v["c"]})
    json.dump({"name": d["name"] + "_fine", "size": [W*F, H*F, D*F], "camera": d["camera"], "palette": d["palette"], "voxels": vs}, open(dst, "w"))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--n", type=int, default=24); ap.add_argument("--lam", type=float, default=6); ap.add_argument("--close", type=int, default=2)
    ap.add_argument("--keep-thin", action="store_true"); a = ap.parse_args(); build(a.name, a.n, a.lam, close=a.close, keep_thin=a.keep_thin)

# ---------- block-grid stair pass (used by mc_features before block mapping) ----------
DIRS = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}
CW = {"north": "east", "east": "south", "south": "west", "west": "north"}; CCW = {v: k for k, v in CW.items()}
def _solid(s): return s is None or s.get("type") in ("full", "slab", "stairs") or s.get("size", 1) >= 0.5
def stair_shape(pos, st, stairs):
    """Minecraft's StairBlock.getStairsShape on our stair map {pos: (facing, half)}."""
    f, h = st; x, y, z = pos
    def at(d, p=pos): dx, dz = DIRS[d]; return stairs.get((p[0]+dx, p[1], p[2]+dz))
    def can_take(d):
        n = at(d); return n is None or n[0] != f or n[1] != h
    a = at(f)                                   # block on the tall side
    if a and a[1] == h and (a[0] in ("east", "west")) != (f in ("east", "west")) and can_take({"north": "south", "south": "north", "east": "west", "west": "east"}[a[0]]):
        return "outer_left" if a[0] == CCW[f] else "outer_right"
    opp = {"north": "south", "south": "north", "east": "west", "west": "east"}[f]; b = at(opp)
    if b and b[1] == h and (b[0] in ("east", "west")) != (f in ("east", "west")) and can_take(b[0]):
        return "inner_left" if b[0] == CCW[f] else "inner_right"
    return "straight"
def stairify(voxels, mats=None, skip=()):
    """Turn stepped/sloped block-grid voxels into stairs. A voxel whose top is open becomes a bottom stair facing d when the
    neighbour toward d and the cell above that neighbour are solid (the slope rises toward d) and the cell toward -d (and above it)
    is open. Mirrored (top-open -> bottom-open) for upside-down stairs under overhangs/eaves. Shape (straight/inner/outer) uses
    Minecraft's own neighbour rule. Only full blocks, 1/2 bottom/top slabs and existing stairs are eligible.
    voxels: list of dicts with x,y,z,s (modified in place); mats: {pos: material}; returns count of stairs."""
    S = {(v["x"], v["y"], v["z"]): v.get("s") for v in voxels}
    solid = {p for p, s in S.items() if _solid(s)}
    def sol(x, y, z): return (x, y, z) in solid
    stairs = {}
    for v in voxels:
        p = (v["x"], v["y"], v["z"]); s = v.get("s"); x, y, z = p
        if mats and mats.get(p) in skip: continue
        if s and s.get("type") == "stairs": stairs[p] = (s["facing"], s.get("half", "bottom")); continue
        if s and not (s.get("type") == "slab" and s.get("size") == 0.5): continue
        for half, dy in (("bottom", 1), ("top", -1)):
            if sol(x, y+dy, z): continue
            if s and s.get("type") == "slab" and (s["align"] == "top") != (half == "top"): continue
            hits = []
            for d, (dx, dz) in DIRS.items():
                if sol(x+dx, y, z+dz) and sol(x+dx, y+dy, z+dz) and not sol(x-dx, y, z-dz) and not sol(x-dx, y+dy, z-dz):
                    hits.append(d)
            if len(hits) == 1 or (len(hits) == 2 and DIRS[hits[0]][0] != -DIRS[hits[1]][0] and DIRS[hits[0]][1] != -DIRS[hits[1]][1]):
                stairs[p] = (hits[0], half); break
    for v in voxels:
        p = (v["x"], v["y"], v["z"])
        if p in stairs: v["s"] = {"type": "stairs", "facing": stairs[p][0], "half": stairs[p][1], "shape": stair_shape(p, stairs[p], stairs)}
    return len(stairs)
