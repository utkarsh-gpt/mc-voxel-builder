#!/usr/bin/env python3
"""Albedo colour stage (replaces palette_generic's colours for subjects run through it; COLOUR.md). Geometry is kept.
  1. sample: every surface block that is the first hit in a view (facing >= 0.3) gets that drawing cell's median colour
     (aligned with feature_detect); top drawing weighted x0.6
  2. de-shade (deshade.py): visibility V / sky visibility Vsky per sampled face from the block geometry, fit how shaded THIS
     sheet is (per view gain + AO + overhang terms, luminance and chroma), divide it out. The photo-toned 48-grid colours
     (unseen blocks) get the same treatment on the voxelised mesh (+ a down-facing term)
  3. material bases = robust median of WELL-LIT samples only (V > 0.8, Vsky > 0.85), Lloyd on the de-shaded colours,
     seeded with the subject's material hints, full-Lab distance; two free grey centres (panes -> window material,
     light grey foundation -> siding)
  4. cleanup: surface majority filter, lone trim/roof specks (<= 2) reassigned; shade slot only where the neighbourhood-
     smoothed albedo L is >= 12 from the base (real weathering), clamped to -1..+1 (trim 0), majority-smoothed
  5. labels colour_mode = albedo -> mc_map: no accent dither, <= 3 blocks per material, roles stay in the ramp,
     role-suited families preferred within 4 dE (PREFER), creaking_heart banned
usage: python colour_albedo.py NAME [--sheet _a3] [--no-deshade] [--toned PATH] [--variant V]
  no --variant: writes art/final/NAME_voxels_textured.json + meta/NAME_texture_labels.json (then run mc_map NAME)
  --variant V : writes out/albedo/NAME_V_mc_blocks.json (+ info) via a temporary alias, art/final untouched"""
import argparse, collections, json, os, shutil, subprocess, sys
import numpy as np
from scipy import ndimage
from skimage import color as skc
import feature_detect as fd, palette_texture as PT, deshade as DS, shape_fit, vox
from colour_proto import top_maps, majority, hexlab, labhex, TOP_W

def majority_guarded(M, mask, names, dist, keep=(), passes=2, own_max=2, maj_min=4, slack=6.0):
    """colour_proto.majority, but a block only flips to the neighbourhood majority if its own albedo is within `slack` dE
    of that material's base as well (a one-block porch roof row keeps its roof colour next to a dark fascia)"""
    for _ in range(passes):
        cnt = np.stack([ndimage.convolve(((M == k) & mask).astype(float), np.ones((3, 3, 3)), mode="constant") - ((M == k) & mask) for k in names], -1)
        own = np.zeros(M.shape); od = np.zeros(M.shape)
        for i, k in enumerate(names): own = np.where(M == k, cnt[..., i], own); od = np.where(M == k, dist[..., i], od)
        best = cnt.argmax(-1); bc = cnt.max(-1); bd = np.take_along_axis(dist, best[..., None], -1)[..., 0]
        ch = mask & (own <= own_max) & (bc >= maj_min) & ~np.isin(M, list(keep)) & (bd <= od + slack)
        for i, k in enumerate(names): M[ch & (best == i)] = k
    return M
K = 8
LIT = (0.8, 0.85)
SH_STEP = 12.0

def samples(n, tag, occ, nrm):
    rec = []   # (x, y, z, view, facing, L, a, b)
    for view in ("front", "right", "back", "left", "top"):
        if view == "top": hit, xyz = top_maps(occ); dvec = np.array([0, 1.0, 0])
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
                if f >= 0.3: rec.append((x, y, z, view, f, *np.median(lab[i*K:(i + 1)*K, j*K:(j + 1)*K][pm], 0)))
    return rec

def fit_groups(lab, bases):
    """grouping for the shading fit only: nearest of the hints + 2 greys, lightness half-weighted (shade-tolerant)"""
    B = np.vstack([bases, hexlab("#5a5a5a"), hexlab("#a0a0a0")]); w = np.array([0.5, 1, 1])
    return np.linalg.norm((lab[:, None] - B[None])*w, axis=-1).argmin(1)

def toned_blocks(T, occ, toned, deshade, bases, info):
    """photo-toned 48-grid colours (ortho_paint + tone_to_ref on the voxelised mesh) for every block; de-shaded on the mesh"""
    d48, occ48, col48, _ = vox.load(toned, seed=0)
    surf48 = occ48 & ~ndimage.binary_erosion(np.pad(occ48, 1))[1:-1, 1:-1, 1:-1] & (col48.sum(-1) > 0)
    src = toned
    if deshade:
        g = ndimage.gaussian_filter(occ48.astype(float), 1.5); nr = -np.stack(np.gradient(g), -1); nr /= np.linalg.norm(nr, axis=-1, keepdims=True) + 1e-9
        idx = np.argwhere(surf48); lab = skc.rgb2lab(col48[surf48][None]/255.0)[0]; nv = nr[surf48]
        V, Vs = DS.visibility(occ48, idx + 0.5, nv, R=14.0, step=0.7)
        grp = fit_groups(lab, bases); view = ["front"]*len(lab); down = np.maximum(0, -nv[:, 1])
        fit = DS.fit_shading(lab, V, Vs, view, grp, down, views=("front",)); S, Sc = DS.factors(fit, V, Vs, view, down)
        lab2 = DS.apply(lab, S, Sc); rgb = (np.clip(skc.lab2rgb(lab2[None])[0], 0, 1)*255).round().astype(int)
        pal, vox_ = {}, []
        for (x, y, z), c in zip(idx, rgb): vox_.append({"x": int(x), "y": int(y), "z": int(z), "c": pal.setdefault("#%02x%02x%02x" % tuple(c), f"q{len(pal)}")})
        inner = occ48 & ~surf48
        for x, y, z in np.argwhere(inner): vox_.append({"x": int(x), "y": int(y), "z": int(z), "c": pal.setdefault("#000000", f"q{len(pal)}")})
        src = toned.replace(".json", "_albedo.json"); src = os.path.join("out/albedo", os.path.basename(src))
        json.dump({"name": "toned_albedo", "size": d48["size"], "palette": {k: h for h, k in pal.items()}, "voxels": vox_}, open(src, "w"))
        info["mesh_shading_fit"] = fit; info["mesh_V_mean"] = round(float(V.mean()), 3)
    tr = T["transform"]; keys = np.argwhere(occ); ctr = keys + 0.5
    col = shape_fit.painted_colours(None, info["mesh"], ctr, tr["rotate_y_rad"], tr["drawing_stretch_xz"], tr["scale"], np.array(tr["translate_after_scale"]), path=src)
    out = np.full(occ.shape + (3,), np.nan); out[tuple(keys.T)] = skc.rgb2lab(col[None]/255.0)[0]
    return out

def build(n, sheet=None, deshade=True, toned=None, variant=None, mesh=None, dark_rules=False):
    sheet = sheet or json.load(open(f"art/final/meta/{n}_views.json"))["chosen"]
    T = json.load(open(f"art/final/{n}_voxels_textured.json")); Lb = json.load(open(f"art/final/meta/{n}_texture_labels.json"))
    W, H, D = T["size"]; occ = np.zeros((W, H, D), bool)
    for v in T["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    surf = PT.surface(occ)
    g = ndimage.gaussian_filter(occ.astype(float), 1.0); nrm = -np.stack(np.gradient(g), -1); nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-9
    names = list(Lb.get("hints") or Lb["bases"]); hint = Lb.get("hints") or Lb["bases"]
    B0 = np.array([hexlab(hint[k]) for k in names]); dark = [k for k in names if k.startswith("window")]
    info = {"sheet": sheet, "deshade": deshade, "mesh": mesh or f"out/proxy/{n}_lowpoly.glb", "toned": toned or f"art/{n}_lowpoly_rendered_toned.json"}
    # 1 samples + 2 de-shade (fit on all samples, one colour per block = best-facing de-shaded sample)
    R = samples(n, sheet, occ, nrm); P = np.array([r[:3] for r in R], int); view = [r[3] for r in R]; F = np.array([r[4] for r in R]); lab = np.array([r[5:] for r in R])
    nv = np.array([[0, 1.0, 0] if v == "top" else fd.DIR[v] for v in view], float)
    V, Vs = DS.visibility(occ, P + 0.5, nv)
    if deshade:
        fit = DS.fit_shading(lab, V, Vs, view, fit_groups(lab, B0)); S, Sc = DS.factors(fit, V, Vs, view); lab_a = DS.apply(lab, S, Sc)
        info["sheet_shading_fit"] = fit; info["mean_lum_gain_removed"] = round(float(np.mean(1/S)), 3)
    else: lab_a = lab
    tgt = np.full(occ.shape + (3,), np.nan); best = np.full(occ.shape, -1.0); litb = np.zeros(occ.shape, bool); bview = np.full(occ.shape, "", object)
    for i, (x, y, z) in enumerate(P):
        if F[i] > best[x, y, z]: best[x, y, z] = F[i]; tgt[x, y, z] = lab_a[i]; litb[x, y, z] = V[i] > LIT[0] and Vs[i] > LIT[1]; bview[x, y, z] = view[i]
    seen = best >= 0
    # unseen blocks: photo-toned mesh colours (de-shaded), else nearest seen block
    tb = toned_blocks(T, occ, info["toned"], deshade, B0, info) if os.path.exists(info["mesh"]) else None
    _, ii = ndimage.distance_transform_edt(~seen, return_indices=True); near = tgt[ii[0], ii[1], ii[2]]
    fill = near if tb is None else np.where(np.isnan(tb), near, tb)
    if tb is not None:   # bias-correct the mesh colours to the drawings on blocks both see
        both = seen & surf & ~np.isnan(tb[..., 0]); info["toned_vs_drawing_dE_median"] = round(float(np.median(np.linalg.norm(tb[both] - tgt[both], axis=-1))), 2)
        fill = fill + np.median(tgt[both] - tb[both], 0)
    tgt = np.where(seen[..., None], tgt, fill)
    # 3 bases from well-lit samples (Lloyd, hint-seeded, two free greys)
    X = tgt[surf & seen]; Xl = litb[surf & seen]
    B = np.vstack([B0, hexlab("#5a5a5a"), hexlab("#a0a0a0")]); cn = names + ["_grey_dark", "_grey_light"]
    for _ in range(8):
        a = np.linalg.norm(X[:, None] - B[None], axis=-1).argmin(1)
        for i in range(len(cn)):
            if cn[i] in dark: continue
            k = a == i; kl = k & Xl
            if kl.sum() >= 10: B[i] = np.median(X[kl], 0)
            elif k.sum() >= 10: B[i] = np.median(X[k], 0)
    dist = np.linalg.norm(tgt[..., None, :] - B, axis=-1)
    gi = len(names); si = names.index("siding") if "siding" in names else 0
    if dark_rules:   # v2 runs (--dark-rules): panes go to window_dark only, and only where the albedo really is dark
        wi = names.index("window_dark") if "window_dark" in names else None   # a lit-window hint never takes the panes
    else: wi = names.index(dark[0]) if dark else None
    A0 = dist.argmin(-1); dist = dist[..., :gi]; B = B[:gi]
    # (dark rules) the free dark grey only means "pane" when the albedo is dark (L < 40): a shaded mid-grey thatch/stone stays its material
    if wi is not None: dist[..., wi] = np.where((A0 == gi) & ((tgt[..., 0] < 40) if dark_rules else True), -1, dist[..., wi])
    dist[..., si] = np.where(A0 == gi + 1, -1, dist[..., si])
    M = np.full(occ.shape, "", object); A = dist.argmin(-1)
    for i, k in enumerate(names): M[occ & (A == i)] = k
    # 4 cleanup
    M = majority_guarded(M, surf, names, np.maximum(dist, 0), keep=dark)
    for k in names:
        if k in dark: continue
        lab_, _ = ndimage.label((M == k) & surf, np.ones((3, 3, 3))); sz = np.bincount(lab_.ravel())
        for j in np.flatnonzero(sz[1:] <= 2) + 1:
            comp = lab_ == j; others = [i for i, q in enumerate(names) if q != k and q not in dark]
            alt = np.array(others)[dist[..., others].argmin(-1)]
            for i in others: M[comp & (alt == i)] = names[i]
    # dark panes are small: a big connected dark patch is a drawn shadow (eave underside, roof in shade), not a window
    if dark_rules and wi is not None:
        others = [i for i, q in enumerate(names) if q not in dark]
        lab_, _ = ndimage.label((M == "window_dark") & surf, np.ones((3, 3, 3))); sz = np.bincount(lab_.ravel()); big = np.flatnonzero(sz[1:] > 12) + 1
        comp = np.isin(lab_, big); alt = np.array(others)[np.maximum(dist[..., others], 0).argmin(-1)]
        for i in others: M[comp & (alt == i)] = names[i]
        info["dark_patches_reassigned"] = int(comp.sum())
    _, ii = ndimage.distance_transform_edt(~surf, return_indices=True); M = np.where(occ & ~surf, M[ii[0], ii[1], ii[2]], M)
    # shade slots only for real albedo variation (weathering, a darker base course): target L smoothed over the surface
    # neighbourhood, >= SH_STEP away from the base. Lighting is Minecraft's job, so most blocks stay on the base shade.
    base = {k: B[i] for i, k in enumerate(names)}; SH = np.zeros(occ.shape, int)
    for k in names:
        mk = (M == k) & occ
        if k.startswith("trim") or k in dark: continue
        mk &= surf; Lt = np.where(mk, tgt[..., 0], 0.0); Ls = ndimage.uniform_filter(Lt, 3)/np.maximum(ndimage.uniform_filter(mk.astype(float), 3), 1e-6)   # within the material SH[mk] = np.clip(np.trunc((Ls[mk] - base[k][0])/SH_STEP), -1, 1)
    SHs = np.full(occ.shape, "0", object)
    for s_ in ("-1", "0", "1"): SHs[SH == int(s_)] = s_
    SH = majority(SHs, surf, ["-1", "0", "1"]).astype(int); SH = np.where(occ & ~surf, SH[ii[0], ii[1], ii[2]], SH)
    os.makedirs("out/albedo", exist_ok=True)
    np.savez_compressed(f"out/albedo/{n}_{variant or 'final'}_debug.npz", tgt=tgt, M=M.astype(str), seen=seen, view=bview.astype(str))
    pal, vox_out, lab_out = {}, [], []
    for v in T["voxels"]:
        x, y, z = v["x"], v["y"], v["z"]; m = M[x, y, z]; sh = int(SH[x, y, z])
        l = base[m].copy(); l[0] += 8*sh; key = pal.setdefault(labhex(l), f"p{len(pal)}")
        vv = dict(v); vv["c"] = key; vox_out.append(vv); lab_out.append({"x": x, "y": y, "z": z, "m": m, "sh": sh, "surf": bool(surf[x, y, z])})
    info.update(bases={k: labhex(base[k]) for k in names}, hints=hint, materials=dict(collections.Counter(M[occ].tolist())),
                seen_share=round(float(seen[surf].mean()), 3), shades_surface=dict(collections.Counter(SH[surf].tolist())))
    info = json.loads(json.dumps(info, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    alias = n if variant is None else f"{n}alb{variant}"
    T2 = dict(T, name=f"{alias}_voxels_textured", palette={k: h for h, k in pal.items()}, voxels=vox_out, colour_source=f"colour_albedo.py (sheet {sheet}, deshade {deshade})")
    T2["texture"] = dict(T.get("texture", {}), rules="COLOUR.md (albedo)", photo_bases=None)
    L2 = dict(Lb, subject=alias, voxels=lab_out, bases={k: labhex(base[k]) for k in names}, hints=hint, colour_mode="albedo", albedo=info)
    open(f"art/final/{alias}_voxels_textured.json", "w").write(json.dumps(T2)); open(f"art/final/meta/{alias}_texture_labels.json", "w").write(json.dumps(L2))
    if variant is None:   # note: art/final/NAME_voxels_textured_fine.json (galleries only) still holds palette_generic's colours
        print(json.dumps({k: info[k] for k in ("bases", "materials", "shades_surface", "seen_share")}), json.dumps(info.get("sheet_shading_fit")))
        return info
    for ext in ("noise", "features"):
        if os.path.exists(f"art/final/meta/{n}_{ext}.json"): shutil.copy(f"art/final/meta/{n}_{ext}.json", f"art/final/meta/{alias}_{ext}.json")
    code = f"import mc_map; mc_map.STRICT['{alias}'] = mc_map.STRICT.get('{n}', set()); mc_map.ACCENT_ALL.add('{alias}'); mc_map.run('{alias}')"
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if p.returncode: print(p.stderr[-2000:]); raise SystemExit(1)
    os.makedirs("out/albedo", exist_ok=True); dst = f"out/albedo/{n}_{variant}_mc_blocks.json"; shutil.move(f"art/final/{alias}_mc_blocks.json", dst)
    for ext in (".schem", ".litematic"):
        sp = f"art/final/schematics/{alias}_mc_blocks{ext}"
        if os.path.exists(sp): shutil.move(sp, f"out/albedo/{n}_{variant}_mc_blocks{ext}")
    for pth in (f"art/final/{alias}_voxels_textured.json", f"art/final/meta/{alias}_texture_labels.json", f"art/final/meta/{alias}_noise.json", f"art/final/meta/{alias}_features.json"):
        if os.path.exists(pth): os.remove(pth)
    d = json.load(open(dst)); cnt = collections.Counter()
    for v in d["voxels"]: q = d["palette"][v["b"]]; cnt[(q["material"], q["id"].replace("_slab", "").replace("_stairs", "").replace("_wall", ""))] += 1
    info["blocks_by_material"] = {f"{m}:{b}": c for (m, b), c in sorted(cnt.items())}
    json.dump(info, open(f"out/albedo/{n}_{variant}_info.json", "w"), indent=1)
    print(variant, json.dumps({k: info[k] for k in ("bases", "materials", "shades_surface")}), "\n ", info["blocks_by_material"], "\n  fit", json.dumps(info.get("sheet_shading_fit")))
    return info

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--sheet"); ap.add_argument("--no-deshade", action="store_true")
    ap.add_argument("--toned"); ap.add_argument("--variant"); ap.add_argument("--mesh")
    ap.add_argument("--dark-rules", action="store_true", help="window_dark takes panes only where L < 40, big dark patches go back to their material (v2 runs; off keeps the house as deployed)")
    a = ap.parse_args(); build(a.name, a.sheet, not a.no_deshade, a.toned, a.variant, a.mesh, a.dark_rules)
