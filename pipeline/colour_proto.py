#!/usr/bin/env python3
"""PROTOTYPE (not the default pipeline): colour + block selection driven by the ortho drawings. Writes out/proto/ only.
  1. target colour per surface block sampled straight from the aligned ortho views on the FINAL block grid (best-facing view
     where the block is the first hit; top drawing for roofs; unseen blocks copy the nearest seen block) - no transfer from
     the 48-grid paint and no 32-colour k-means in between
  2. material bases locked to the ortho: Lloyd iterations on the sampled colours, seeded with the subject's material hints,
     full-Lab distance (L counts as much as hue: dark trim vs mid-brown roof vs shaded siding are told apart by value)
  3. spatial coherence: surface majority filter (26-neighbours), lone trim/roof specks (<= 2 blocks) -> nearest other material
  4. shade = target L vs the material base in 8-L steps, clamped to -1..+1 (trim: 0), majority-smoothed -> <= 3 slots
  5. mc_map with MC_ACCENTS=0 (no dithered accent blocks), MC_MAX_BLOCKS=3 (<= 3 block types per material) and
     MC_ROLE_POOLS=0 (shadow/trim roles stay inside the material's own ramp: no blackstone hatching, no creaking_heart)
variants: full = 1-5; colours = 1-4 with the default mc_map; mapknobs = today's colours with only step 5 (ablation)
usage: python colour_proto.py house [--variant full|colours|mapknobs]   -> out/proto/NAME_<variant>_mc_blocks.json (+ .schem/.litematic)"""
import argparse, collections, json, os, shutil, subprocess, sys
import numpy as np
from scipy import ndimage
from skimage import color as skc
import feature_detect as fd, palette_texture as PT
K = 8
TOPDIR = (0, 1, 0)
TOP_W = 0.6     # the top drawing is often an oblique roof plan: prefer an elevation whenever one sees the block
def hexlab(h): return skc.rgb2lab(np.array([[[int(h[i:i + 2], 16) for i in (1, 3, 5)]]], float)/255)[0, 0]
def labhex(l): r = (np.clip(skc.lab2rgb(np.asarray(l, float)[None, None])[0, 0], 0, 1)*255).round().astype(int); return "#%02x%02x%02x" % tuple(r)

def top_maps(occ):
    """top view: rows = z ascending (front at the bottom, as ortho_paint), cols = x; first hit from above"""
    W, H, D = occ.shape; A = occ.transpose(2, 0, 1)                    # [z, x, y]
    hit = A.any(2); ytop = H - 1 - np.argmax(A[:, :, ::-1], 2)
    X = np.broadcast_to(np.arange(W)[None], (D, W)); Z = np.broadcast_to(np.arange(D)[:, None], (D, W))
    return hit, np.stack([X, ytop, Z], -1)

def sample_targets(n, tag, occ, surf, nrm):
    best_f = np.full(occ.shape, -1.0); tgt = np.zeros(occ.shape + (3,))
    for view in ("front", "right", "back", "left", "top"):
        if view == "top": hit, xyz = top_maps(occ); dvec = np.array(TOPDIR, float)
        else: hit, xyz, _ = fd.view_maps(occ, view); dvec = np.array(fd.DIR[view], float)
        al = fd.align(n, tag, view, hit, K)
        if al is None: continue
        r0, r1, c0, c1 = al["box"]; lab = skc.rgb2lab(al["rgb"]/255.0)
        for i in range(r1 - r0):
            for j in range(c1 - c0):
                if not hit[r0 + i, c0 + j]: continue
                pm = al["mask"][i*K:(i + 1)*K, j*K:(j + 1)*K]
                if pm.mean() < 0.5: continue
                x, y, z = xyz[r0 + i, c0 + j]; f = float(nrm[x, y, z] @ dvec)*(TOP_W if view == "top" else 1.0)
                if f >= 0.3 and f > best_f[x, y, z]:
                    best_f[x, y, z] = f; tgt[x, y, z] = np.median(lab[i*K:(i + 1)*K, j*K:(j + 1)*K][pm], 0)
    seen = best_f >= 0
    _, ii = ndimage.distance_transform_edt(~seen, return_indices=True)
    tgt = tgt[ii[0], ii[1], ii[2]]
    return tgt, seen

def majority(M, mask, names, keep=(), passes=2, own_max=2, maj_min=4):
    W, H, D = M.shape; idx = {k: i for i, k in enumerate(names)}
    for _ in range(passes):
        cnt = np.zeros(M.shape + (len(names),))
        for i, k in enumerate(names):
            cnt[..., i] = ndimage.convolve(((M == k) & mask).astype(float), np.ones((3, 3, 3)), mode="constant") - ((M == k) & mask)
        own = np.zeros(M.shape); 
        for i, k in enumerate(names): own = np.where(M == k, cnt[..., i], own)
        best = cnt.argmax(-1); bc = cnt.max(-1)
        ch = mask & (own <= own_max) & (bc >= maj_min) & ~np.isin(M, list(keep))
        for i, k in enumerate(names): M[ch & (best == i)] = k
    return M

def build(n, variant):
    tag = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"]
    T = json.load(open(f"art/final/{n}_voxels_textured.json")); Lb = json.load(open(f"art/final/meta/{n}_texture_labels.json"))
    W, H, D = T["size"]; occ = np.zeros((W, H, D), bool)
    for v in T["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    alias = f"{n}proto{variant}"
    shutil.copy(f"art/final/meta/{n}_noise.json", f"art/final/meta/{alias}_noise.json")
    if os.path.exists(f"art/final/meta/{n}_features.json"): shutil.copy(f"art/final/meta/{n}_features.json", f"art/final/meta/{alias}_features.json")
    info = {"variant": variant}
    if variant == "mapknobs":     # isolate the mc_map knobs: same colours/materials as now
        shutil.copy(f"art/final/{n}_voxels_textured.json", f"art/final/{alias}_voxels_textured.json")
        shutil.copy(f"art/final/meta/{n}_texture_labels.json", f"art/final/meta/{alias}_texture_labels.json")
    else:
        surf = PT.surface(occ)
        g = ndimage.gaussian_filter(occ.astype(float), 1.0); nrm = -np.stack(np.gradient(g), -1); nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-9
        tgt, seen = sample_targets(n, tag, occ, surf, nrm)
        names = list(Lb["bases"]); B = np.array([hexlab(Lb["bases"][k]) for k in names])
        dark = [k for k in names if k.startswith("window")]
        ys = np.nonzero(occ.any((0, 2)))[0]; hfrac = (np.indices(occ.shape)[1] - ys.min())/max(ys.max() - ys.min(), 1)
        S = surf & seen; X = tgt[S]
        # two extra free centres for the drawings' greys (dark panes, light foundation/shade): without them the trim and
        # window bases drift to grey and swallow pane cells
        B = np.vstack([B, hexlab("#5a5a5a"), hexlab("#a0a0a0")]); cn = names + ["_grey_dark", "_grey_light"]
        for _ in range(8):                                            # ortho-locked bases (Lloyd, hint-seeded)
            dd = np.linalg.norm(X[:, None] - B[None], axis=-1); a = dd.argmin(1)
            for i in range(len(cn)):
                if cn[i] in dark: continue                            # window base stays (panes come from feature_detect)
                if (a == i).sum() >= 10: B[i] = np.median(X[a == i], 0)
        dist = np.linalg.norm(tgt[..., None, :] - B, axis=-1)
        # no height prior: the ortho colour separates roof (red-brown, a~15) from trim (neutral dark) on its own, and
        # the porch roof / brick piers sit low on the wall
        gi = len(names); wi = names.index(dark[0]) if dark else None; si = names.index("siding") if "siding" in names else 0
        A0 = dist.argmin(-1); dist = dist[..., :gi]; B = B[:gi]
        if wi is not None: dist[..., wi] = np.where(A0 == gi, -1, dist[..., wi])
        dist[..., si] = np.where(A0 == gi + 1, -1, dist[..., si])
        M = np.full(occ.shape, "", object); A = dist.argmin(-1)
        for i, k in enumerate(names): M[occ & (A == i)] = k
        M = majority(M, surf, names, keep=dark)
        # lone specks of trim / roof (<= 2 surface blocks) go to the nearest other material
        for k in names:
            if k in dark: continue
            lab_, kk = ndimage.label((M == k) & surf, np.ones((3, 3, 3)))
            sz = np.bincount(lab_.ravel())
            for j in np.flatnonzero(sz[1:] <= 2) + 1:
                comp = lab_ == j; others = [i for i, q in enumerate(names) if q != k and q not in dark]
                alt = np.array(others)[dist[..., others].argmin(-1)]
                for i in others: M[comp & (alt == i)] = names[i]
        # interior blocks copy the nearest surface block's material
        _, ii = ndimage.distance_transform_edt(~surf, return_indices=True); Mi = M[ii[0], ii[1], ii[2]]; M = np.where(occ & ~surf, Mi, M)
        base = {k: B[i] for i, k in enumerate(names)}
        SH = np.zeros(occ.shape, int)
        for k in names:
            mk = (M == k) & occ
            if k.startswith("trim") or k in dark: continue
            SH[mk] = np.clip(np.round((tgt[mk][:, 0] - base[k][0])/8.0), -1, 1)
        shn = ["-1", "0", "1"]; SHs = np.full(occ.shape, "0", object)
        for s_ in shn: SHs[SH == int(s_)] = s_
        SHs = majority(SHs, surf, shn); SH = SHs.astype(int)
        pal, vox_out, lab_out = {}, [], []
        for v in T["voxels"]:
            x, y, z = v["x"], v["y"], v["z"]; m = M[x, y, z]; sh = int(SH[x, y, z])
            l = base[m].copy(); l[0] = l[0] + 8*sh; h = labhex(l); key = pal.setdefault(h, f"p{len(pal)}")
            vv = dict(v); vv["c"] = key; vox_out.append(vv); lab_out.append({"x": x, "y": y, "z": z, "m": m, "sh": sh, "surf": bool(surf[x, y, z])})
        T2 = dict(T, name=f"{alias}_voxels_textured", palette={k: h for h, k in pal.items()}, voxels=vox_out, colour_source="colour_proto.py: ortho-sampled on the block grid")
        L2 = dict(Lb, subject=alias, voxels=lab_out, bases={k: labhex(base[k]) for k in names})
        open(f"art/final/{alias}_voxels_textured.json", "w").write(json.dumps(T2)); open(f"art/final/meta/{alias}_texture_labels.json", "w").write(json.dumps(L2))
        info.update(bases_ortho={k: labhex(base[k]) for k in names}, bases_before=Lb["bases"], materials=dict(collections.Counter(M[occ].tolist())),
                    materials_before=dict(collections.Counter(v["m"] for v in Lb["voxels"])), seen_share=round(float(seen[surf].mean()), 3))
    env = dict(os.environ) if variant == "colours" else dict(os.environ, MC_ACCENTS="0", MC_MAX_BLOCKS="3", MC_ROLE_POOLS="0")
    code = f"import mc_map; mc_map.STRICT['{alias}'] = mc_map.STRICT.get('{n}', set()); mc_map.ACCENT_ALL.add('{alias}'); mc_map.run('{alias}')"
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    if p.returncode: print(p.stderr[-2000:]); raise SystemExit(1)
    os.makedirs("out/proto", exist_ok=True); dst = f"out/proto/{n}_{variant}_mc_blocks.json"
    shutil.move(f"art/final/{alias}_mc_blocks.json", dst)
    for ext in (".schem", ".litematic"):
        sp = f"art/final/schematics/{alias}_mc_blocks{ext}"
        if os.path.exists(sp): shutil.move(sp, f"out/proto/{n}_{variant}_mc_blocks{ext}")
    for pth in (f"art/final/{alias}_voxels_textured.json", f"art/final/{alias}_voxels_textured_fine.json", f"art/final/meta/{alias}_texture_labels.json",
                f"art/final/meta/{alias}_noise.json", f"art/final/meta/{alias}_features.json"):
        if os.path.exists(pth): os.remove(pth)
    d = json.load(open(dst)); cnt = collections.Counter()
    for v in d["voxels"]: p_ = d["palette"][v["b"]]; cnt[(p_["material"], p_["id"].replace("_slab", "").replace("_stairs", "").replace("_wall", ""))] += 1
    info["blocks_by_material"] = {f"{m}:{b}": c for (m, b), c in sorted(cnt.items())}
    open(f"out/proto/{n}_{variant}_info.json", "w").write(json.dumps(info, indent=1)); print(json.dumps(info, indent=1)[:2500])
    return dst

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--variant", default="full"); a = ap.parse_args(); build(a.name, a.variant)
