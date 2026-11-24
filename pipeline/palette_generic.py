#!/usr/bin/env python3
"""Colour stage for new subjects (same TEXTURE_RULES as palette_texture.py, but data-driven instead of hand-written zoning):
1. material bases MEASURED FROM THE REFERENCE PHOTO: every masked photo pixel goes to its nearest material hint (Lab), the base is the
   median a*/b* and the 60th-percentile L* of those pixels (lit tone, keeps chroma: warm stone stays warm, greens stay saturated);
2. zoning = nearest material base to each voxel's smoothed painted colour, limited by simple geometric priors (e.g. roof only high up,
   water only low, grass only on up-facing top surfaces), then a majority filter that keeps thin/detail parts;
3. ramps, placement score (openness, up, height, sun, cluster noise, overhang shadow), cleanup, gradient blends: as palette_texture.py.
Organic materials get 5-step chromatic ramps with hue shift so greens/browns are not flattened.
usage: python palette_generic.py SUBJECT  -> art/final/SUBJECT_voxels_textured.json (+ _fine), art/final/meta/SUBJECT_texture_labels.json"""
import json, sys, numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color as skc
import palette_texture as PT, scorer, subblock
DEF = PT.DEF
ORG = dict(DEF, w_open=1.1, w_up=0.6, w_dir=0.4, w_n=1.0, scale=3, q=(0.05, 0.12, 0.10, 0.03))
# name: (hint hex, ramp (lo, hi, dL_dn, dL_up, mode), ramp kw, placement params or None, prior)
CFG = {
 "cathedral": {"src": "art/cathedral_lowpoly_half_sub.json", "mats": {
    "limestone":   ("#b8925a", (-2, 2, 6, 5, "chromatic"), dict(dh=4, cd=0.05, cu=0.05), DEF, None),
    "roof_slate":  ("#4a4f57", (-2, 1, 5, 6, "neutral"), dict(db_up=-1.0, db_dn=0.5), dict(DEF, w_h=0.2), "high"),
    "window_dark": ("#2e2a2a", (-1, 0, 5, 0, "neutral"), dict(db_dn=0.5), None, "dark")},
   "blend": [("limestone", "roof_slate", -1)], "crisp": [("limestone", "window_dark"), ("roof_slate", "window_dark")]},
 "hagia": {"src": "art/hagia_shapefit.json", "mats": {   # shape_fit.py voxels (was art/hagia_lowpoly_half_sub.json, saved as hagia_p0_*)
    "masonry":     ("#8c6a5e", (-2, 2, 6, 5, "chromatic"), dict(dh=4, cd=0.05, cu=0.04), DEF, None),
    "drum_render": ("#b07a6e", (-1, 1, 6, 5, "chromatic"), dict(dh=4, cd=0.05, cu=0.04), DEF, "high"),
    "lead_roof":   ("#8e9497", (-2, 1, 5, 6, "neutral"), dict(db_up=-1.0, db_dn=0.5), dict(DEF, w_h=0.2), "high"),
    "window_dark": ("#2e2a2a", (-1, 0, 5, 0, "neutral"), dict(db_dn=0.5), None, "dark")},
   "blend": [("masonry", "lead_roof", -1)], "crisp": [("masonry", "window_dark"), ("drum_render", "window_dark"), ("drum_render", "lead_roof")]},
 "house": {"src": "art/house_shapefit.json", "mats": {   # two-storey Foursquare-style house (refs/house_SOURCE.txt)
    "siding":       ("#ede3a6", (-2, 2, 6, 5, "chromatic"), dict(dh=4, cd=0.05, cu=0.04), DEF, None),
    "trim_brown":   ("#4a2c22", (-1, 1, 5, 4, "chromatic"), dict(dh=3, cd=0.04, cu=0.03), DEF, None),
    "roof_shingle": ("#7c5040", (-2, 1, 5, 6, "chromatic"), dict(dh=3, cd=0.04, cu=0.04), dict(DEF, w_h=0.2), "high"),
    "window_dark":  ("#2e2a2a", (-1, 0, 5, 0, "neutral"), dict(db_dn=0.5), None, "dark")},
   "hint_only": ("roof_shingle", "trim_brown"),
   "max_share": {"trim_brown": 0.15},   # dark-painted wall voxels (shadow, glass, porch) otherwise zone as trim and turn the walls brown   # photo roof is sun-faded (measures #a78271 vs the painted #7c5040) and trim pixels mix with shadow
   "blend": [], "crisp": [("siding", "trim_brown"), ("siding", "window_dark"), ("siding", "roof_shingle"), ("trim_brown", "roof_shingle")]},
 "landscape": {"src": "art/landscape_lowpoly_half_sub.json", "mats": {
    "grass":       ("#7da343", (-2, 2, 7, 6, "chromatic"), dict(dh=7, cd=0.06, cu=0.06), ORG, "top"),
    "rock_grey":   ("#7d7a72", (-2, 2, 6, 5, "neutral"), dict(db_up=1.2, db_dn=0.8), DEF, None),
    "rock_ochre":  ("#b89a5e", (-2, 2, 6, 5, "chromatic"), dict(dh=4, cd=0.05, cu=0.05), DEF, None),
    "rock_dark":   ("#4d4a45", (-1, 1, 5, 5, "neutral"), dict(db_dn=0.5), DEF, None),
    "sand":        ("#d8c39a", (-1, 1, 5, 4, "chromatic"), dict(dh=3, cd=0.04, cu=0.04), DEF, "near_water"),
    "water":       ("#3fb3b0", (-2, 1, 6, 5, "chromatic"), dict(dh=3, cd=0.04, cu=0.04), dict(DEF, w_h=0.1, w_n=0.5), "water"),
    "foam":        ("#eef2f2", (-1, 0, 4, 0, "neutral"), dict(db_dn=1.5), None, "foam")},
   "blend": [("rock_ochre", "rock_grey", 0), ("grass", "rock_ochre", -1)], "crisp": [("water", "foam"), ("grass", "water")]},
 "turtle": {"src": "art/turtle_half_sub.json", "mats": {
    "shell":       ("#7a6a45", (-2, 2, 7, 6, "chromatic"), dict(dh=5, cd=0.06, cu=0.05), ORG, None),
    "skin":        ("#8a8c78", (-2, 2, 7, 5, "chromatic"), dict(dh=4, cd=0.05, cu=0.04), ORG, None),
    "coral":       ("#e0784a", (-1, 1, 6, 5, "chromatic"), dict(dh=5, cd=0.04, cu=0.03), None, "detail_top"),
    "coral_pink":  ("#d7708a", (-1, 1, 6, 5, "chromatic"), dict(dh=5, cd=0.04, cu=0.03), None, "detail_top"),
    "algae":       ("#6f9a3a", (-1, 1, 6, 6, "chromatic"), dict(dh=7, cd=0.05, cu=0.05), None, "detail_top"),
    "fan":         ("#9a6aa8", (-1, 1, 6, 5, "chromatic"), dict(dh=4, cd=0.04, cu=0.03), None, "detail_top")},
   "blend": [("shell", "algae", 0)], "crisp": [("shell", "coral"), ("shell", "coral_pink"), ("shell", "fan")]}}
DETAIL_MAX = 0.12   # detail materials may cover at most 12% of the surface (keeps accents accents)

def photo_bases(n, mats, hint_only=()):
    im = Image.open(f"refs/{n}.jpg"); m = scorer.ref_mask(im)
    lab = skc.rgb2lab(np.asarray(im.convert("RGB"))[m].astype(float)[None]/255)[0]
    names = list(mats); H = np.array([PT.hex2lab(mats[k][0]) for k in names])
    d = ((lab[:, None, :] - H[None])**2 * np.array([1.0, 1.2, 1.2])).sum(-1); idx = d.argmin(1)   # photo pixels vs photo-like hints: full L weight
    out, info = {}, {}
    for i, k in enumerate(names):
        px = lab[idx == i]
        if k in hint_only:   # photo colour unreliable for this material (e.g. sun-faded roof): use the hint as the base
            out[k] = mats[k][0]; info[k] = {"hint": mats[k][0], "base": mats[k][0], "hint_only": True, "photo_share": round(len(px)/len(lab), 3)}; continue
        if len(px) < 0.003*len(lab): out[k] = mats[k][0]; info[k] = {"hint": mats[k][0], "base": mats[k][0], "photo_share": round(len(px)/len(lab), 3)}; continue
        base = np.array([np.percentile(px[:, 0], 62), np.median(px[:, 1]), np.median(px[:, 2])])
        _, Ch, hh = PT.lch(H[i]); _, Cm, hm = PT.lch(base)
        guard = (Ch < 10 and Cm > max(Ch + 4, 8)) or (Ch >= 10 and abs((hm - hh + 180) % 360 - 180) > 40)   # photo cluster polluted by another material
        desat = (not guard) and Ch >= 10 and Cm < 0.6*Ch      # flat/overcast light greys a coloured material (Hagia brick read as C 6 vs hint 14)
        if desat: base = np.array([base[0], Ch*np.cos(np.radians(hm)), Ch*np.sin(np.radians(hm))])   # keep measured L and hue, restore the hint's chroma
        out[k] = mats[k][0] if guard else PT.lab2hex(base)
        info[k] = {"hint": mats[k][0], "base": out[k], "measured": PT.lab2hex(base), "guard_used_hint": bool(guard), "chroma_restored": bool(desat), "photo_share": round(len(px)/len(lab), 3)}
    return out, info

def run(n):
    C = CFG[n]; mats = C["mats"]; bases, binfo = photo_bases(n, mats, C.get("hint_only", ()))
    d, occ, occw, lab0 = PT.load(C["src"]); W, H, D = occ.shape; X, Y, Z = np.indices(occ.shape)
    lab_s = PT.smooth_lab(lab0, occ, passes=1); surf = PT.surface(occ)
    g = ndimage.gaussian_filter(occ.astype(float), 1.0); Nrm = -np.stack(np.gradient(g), -1); Nrm /= np.linalg.norm(Nrm, axis=-1, keepdims=True) + 1e-9
    up = np.clip(Nrm[..., 1], 0, 1); dirl = Nrm @ PT.SUN
    openness = np.clip((0.50 - ndimage.gaussian_filter(occw, 1.2))/0.15, -1, 1)
    ys = np.nonzero(occ.any((0, 2)))[0]; y0, y1 = ys.min(), ys.max(); hfrac = (Y - y0)/max(y1 - y0, 1)
    top_open = occ & ~np.concatenate([occ[:, 1:, :], np.zeros((W, 1, D), bool)], 1)
    names = list(mats); B = np.array([PT.hex2lab(bases[k]) for k in names])
    WT = np.array([0.3, 1.2, 1.2])
    dist = ((lab_s[..., None, :] - B)**2 * WT).sum(-1)        # (W,H,D,K) hue/chroma-weighted (value comes from the ramps)
    draw = ((lab0[..., None, :] - B)**2 * WT).sum(-1)         # unsmoothed: small accents (coral, windows) survive
    for i, k in enumerate(names):   # geometric priors
        pr = mats[k][4]; bad = np.zeros(occ.shape, bool)
        if pr == "high": bad = hfrac < 0.35
        if pr == "top": bad = ~(top_open | (up > 0.55)) | (hfrac < 0.5)
        if pr == "water": bad = (hfrac > 0.7) & ~(up < 0.3)
        if pr in ("foam", "near_water", "dark", "detail", "detail_top"): bad = np.ones(occ.shape, bool)   # assigned in the second pass
        dist[..., i] = np.where(bad, 1e9, dist[..., i])
    M = np.full(occ.shape, "", object); A = dist.argmin(-1)
    for i, k in enumerate(names): M[occ & (A == i)] = k
    # second pass: context materials
    L0 = lab0[..., 0]; C0 = np.hypot(lab0[..., 1], lab0[..., 2])
    for i, k in enumerate(names):
        pr = mats[k][4]
        if pr == "dark": M[surf & (L0 < 24) & (up < 0.3) & (hfrac > 0.04)] = k   # windows: dark, on vertical faces
        if pr in ("foam", "near_water") and (M == "water").any():
            dw = ndimage.distance_transform_edt(~(M == "water"))
            near = occ & surf & (dw <= (4 if pr == "foam" else 6))
            if pr == "foam": M[near & (L0 > 72) & (C0 < 12)] = k
            else: M[near & (draw[..., i] < draw[..., [names.index(m) for m in M[near] if False] or [i]].min(-1) + 1) & (draw[..., i] <= dist.min(-1)) & (hfrac < 0.5)] = k
        if pr == "detail_top":
            # accents from the RAW painted colour by hue: within 25 deg of the accent's photo hue, saturated, and at least
            # 20 deg away from the hue of the material the voxel was zoned as (the shell stays shell)
            _, Cb, hb = PT.lch(PT.hex2lab(bases[k])); _, C0_, h0 = PT.lch(lab0); hd = lambda a_, b_: np.abs((a_ - b_ + 180) % 360 - 180)
            zh = np.zeros(occ.shape)
            for m2 in names:
                if mats[m2][4] != "detail_top": zh = np.where(M == m2, PT.lch(PT.hex2lab(bases[m2]))[2], zh)
            M[surf & (hfrac >= 0.3) & (hd(h0, hb) < 25) & (C0_ >= max(12, 0.45*Cb)) & (hd(h0, zh) > 20)] = k
    # detail materials: keep only small clusters / limited share (rest -> next best non-detail material)
    det = [k for k in names if mats[k][4] in ("detail", "detail_top", "dark", "foam")]
    nondet = [i for i, k in enumerate(names) if k not in det]
    alt = np.array(nondet)[dist[..., nondet].argmin(-1)]
    for k in det:
        mk = M == k; lim = DETAIL_MAX*surf.sum()
        if mk.sum() > lim:   # keep the voxels closest to the detail colour
            thr = np.quantile(dist[..., names.index(k)][mk], lim/mk.sum()); drop = mk & (dist[..., names.index(k)] > thr)
            for i in nondet: M[drop & (alt == i)] = names[i]
        lab_, kk = ndimage.label(M == k, np.ones((3, 3, 3)))
        for j in range(1, kk+1):
            comp = lab_ == j
            if comp.sum() < 2 or (mats[k][4] == "dark" and comp.sum() > 12):   # windows are small openings, not dark walls
                for i in nondet: M[comp & (alt == i)] = names[i]
    # per-subject share caps (e.g. trim): keep the voxels closest to the material's colour, the rest -> next best other material
    for k, cap in C.get("max_share", {}).items():
        mk = M == k; lim = cap*surf.sum()
        if mk.sum() > lim:
            others = [i for i, kk in enumerate(names) if kk != k and mats[kk][4] not in ("dark", "detail", "detail_top", "foam")]
            alt_k = np.array(others)[dist[..., others].argmin(-1)]
            thr = np.quantile(dist[..., names.index(k)][mk & surf], min(1.0, lim/max((mk & surf).sum(), 1)))
            drop = mk & (dist[..., names.index(k)] > thr)
            for i in others: M[drop & (alt_k == i)] = names[i]
    M2 = PT.mode_filter_labels(M, occ, names, {})
    for k in det: M2[M == k] = k
    M = PT.mode_filter_labels(M2, occ, names, {k: 2 for k in det}, majority=False)
    # ramps + placement
    ramps = {}
    for k in names:
        lo, hi, dn, upL, mode = mats[k][1]; ramps[k] = PT.ramp(bases[k], lo, hi, dn, upL, mode, **mats[k][2])
    yj = Y + 1.2*PT.noise(occ.shape, 2, n + "yj", False)
    empty_below = occ & ~np.concatenate([np.ones((W, 1, D), bool), occ[:, :-1, :]], 1)
    cause = np.zeros(occ.shape); cause[empty_below & (hfrac > 0.05)] -= 0.8; cause[(yj - y0) <= 1] -= 0.5   # overhang shadow, damp/contact foot
    IDX = np.zeros(occ.shape, int); FORCED = np.zeros(occ.shape, bool)
    for k in names:
        mm = (M == k) & surf
        if not mm.any(): continue
        lo, hi = mats[k][1][0], mats[k][1][1]; p = mats[k][3]
        if p is None:
            S = 1.0*openness + 0.5*up + 0.3*dirl; IDX[mm & (S < -0.6)] = max(lo, -1)
            if hi >= 1: IDX[mm & (S > 0.7)] = 1
            continue
        yy = np.argwhere(M == k)[:, 1]; hgt = 2*(yj - yy.min())/max(yy.max() - yy.min(), 1) - 1
        S = p["w_open"]*openness + p["w_up"]*up + p["w_h"]*hgt + p["w_dir"]*dirl + p["w_n"]*PT.noise(occ.shape, p["scale"], n + k) + cause
        v = S[mm]; q2, q1, p1, p2 = [1.35*q for q in p["q"]]; idx = np.zeros(len(v), int)
        if lo <= -2 and q2 > 0: idx[v <= np.quantile(v, q2)] = -2
        if lo <= -1 and q1 > 0: idx[(v > (np.quantile(v, q2) if q2 > 0 and lo <= -2 else -1e9)) & (v <= np.quantile(v, q2 + q1))] = -1
        if hi >= 1 and p1 > 0: idx[v >= np.quantile(v, 1 - p2 - p1)] = 1
        if hi >= 2 and p2 > 0: idx[v >= np.quantile(v, 1 - p2)] = 2
        IDX[mm] = idx
    IDX = PT.cleanup(IDX, M, surf, FORCED, ramps)
    LAB = np.zeros(occ.shape + (3,))
    for k in ramps:
        for s, c in ramps[k].items(): LAB[(M == k) & (IDX == s)] = c
        LAB[(M == k) & ~surf] = ramps[k][0]
    # gradient blends (same rule as palette_texture: chain length from the colour gap, ragged edge, no skipped step)
    blend_info, BLm = [], {}
    for A_, B_, shB in C["blend"]:
        mA, mB = (M == A_), (M == B_)
        if not mA.any() or not mB.any(): continue
        dist_b = ndimage.distance_transform_edt(~mB); dj = dist_b + 0.9*PT.noise(occ.shape, 2, f"blend{A_}{B_}", False)
        sel = mA & surf & (dist_b <= 4.5)
        if not sel.any(): continue
        cA, cB = ramps[A_][0], ramps[B_].get(shB, ramps[B_][0]); nn = int(np.clip(round(PT.dE(cA, cB)/11) - 1, 0, 3))
        if nn == 0: continue
        chain = [cA + (cB - cA)*kk/(nn+1) for kk in range(1, nn+1)]
        k_v = np.where(sel, np.clip(nn + 1 - np.ceil(dj), 0, nn).astype(int), 0)
        apply = sel & (k_v > 0)
        for kk in range(1, nn+1): LAB[apply & (k_v == kk)] = chain[kk-1]
        for x, y, z in np.argwhere(apply): BLm[(x, y, z)] = [B_, int(k_v[x, y, z]), nn]
        blend_info.append({"pair": f"{A_}<-{B_}", "n_intermediates": nn, "voxels_blended": int(apply.sum())})
    # palette
    flat = LAB[occ]; keys_hex = [PT.lab2hex(c) for c in flat]; uniq = {}
    for hx in keys_hex: uniq[hx] = uniq.get(hx, 0) + 1
    labs = {hx: PT.hex2lab(hx) for hx in uniq}; kept, rep = [], {}
    for hx in sorted(uniq, key=lambda k: -uniq[k]):
        t = next((k for k in kept if float(skc.deltaE_ciede2000(labs[k], labs[hx])) < 2.0), None); rep[hx] = t or hx
        if not t: kept.append(hx)
    pal = {f"p{i}": hx for i, hx in enumerate(kept)}; inv = {hx: k for k, hx in pal.items()}
    col_of = {tuple(c): inv[rep[h]] for c, h in zip(np.argwhere(occ), keys_hex)}
    vs = [dict(v, c=col_of[(v["x"], v["y"], v["z"])]) for v in d["voxels"]]
    dst = f"art/final/{n}_voxels_textured.json"; Z_ = {"y0": int(y0), "y1": int(y1)}
    out = dict(d, palette=pal, voxels=vs, name=f"{n}_voxels_textured")
    out["texture"] = {"rules": "TEXTURE_RULES.md + palette_generic.py", "photo_bases": binfo, "materials": {k: int((M == k).sum()) for k in names}, "blends": blend_info}
    json.dump(out, open(dst, "w"))
    json.dump({"subject": n, "size": d["size"], "zones": Z_, "crisp": C["crisp"], "bases": bases, "voxels": [
        {"x": int(x), "y": int(y), "z": int(z), "m": M[x, y, z], "sh": int(IDX[x, y, z]) if surf[x, y, z] else 0, "surf": bool(surf[x, y, z]),
         **({"blend": BLm[(x, y, z)]} if (x, y, z) in BLm else {})} for x, y, z in np.argwhere(occ)]}, open(f"art/final/meta/{n}_texture_labels.json", "w"))
    subblock.expand(dst, dst.replace(".json", "_fine.json"))
    print(n, json.dumps({"palette": len(pal), "materials": out["texture"]["materials"], "bases": {k: v["base"] for k, v in binfo.items()}, "blends": blend_info}))
if __name__ == "__main__":
    for n in sys.argv[1:]: run(n)
