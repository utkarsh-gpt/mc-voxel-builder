#!/usr/bin/env python3
"""Cheap, image-only check that an ortho sheet is flat albedo (no cast shadows, ambient occlusion, gradients or
directional light). No API calls. Used by ortho_verify.geo_checks; also: python shading_check.py NAME TAG [TAG ...]
Per material (k-means colour clusters of the elevations, matched across panels by hue/chroma):
  top_vs_front_dL   lightness of the same material in the TOP plan minus the FRONT elevation (directional light from the
                    front/side makes the top darker or lighter; flat albedo -> ~0)
  shadow_share      share of a material's pixels that keep its hue but are >= 8 L darker than its median (cast shadows,
                    eave/AO bands, shaded faces)
  gradient_std      std of the large-scale (blurred) lightness residual inside each material (smooth gradients)
flags: |top_vs_front_dL| > 8, shadow_share > 0.10, gradient_std > 3.0"""
import json, sys
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color as skc
from scipy.cluster.vq import kmeans2
SHADOW_DL = 8.0
TH = {"top_vs_front_dL": 8.0, "shadow_share": 0.10, "gradient_std": 3.0}   # flat _a1 sheet: 2.3 / 0.03 / 1.5; shaded _v1: 0.9 / 0.18 / 4.6
VIEWS = ("front", "right", "back", "top")

def panel(n, tag, v, S=256):
    im = Image.open(f"ortho/{n}{tag}_{v}.png").convert("RGB"); im.thumbnail((S, S)); a = np.asarray(im).astype(float)/255
    lab = skc.rgb2lab(a); m = (a.min(-1) < 0.92) | (np.hypot(lab[..., 1], lab[..., 2]) > 8)
    m = ndimage.binary_opening(m, np.ones((3, 3)))
    return lab, m

def clusters(X, k=5, seed=0):
    rng = np.random.default_rng(seed); Xs = X[rng.choice(len(X), min(len(X), 6000), replace=False)]
    C, a = kmeans2(Xs, k, minit="++", seed=seed); w = np.bincount(a, minlength=k)/len(a)
    return C, w

def check(n, tag):
    P = {v: panel(n, tag, v) for v in VIEWS}
    el = np.vstack([P[v][0][P[v][1]] for v in ("front", "right", "back")])
    # materials = chroma-carrying clusters; neutral darks/whites (lines, panes) are not materials for this test
    C, w = clusters(el[:, 1:], k=5)   # cluster on a*b* only so shading (an L change) stays inside one material
    res = {"materials": []}; sh_all, gr_all = [], []
    for i in np.argsort(-w):
        if w[i] < 0.08 or np.hypot(*C[i]) < 6: continue
        rec = {"ab": [round(float(c), 1) for c in C[i]], "share": round(float(w[i]), 3)}
        Ls = {}
        for v in VIEWS:
            lab, m = P[v]; d = np.hypot(lab[..., 1] - C[i][0], lab[..., 2] - C[i][1]); mm = m & (d < 7)
            if mm.sum() < 150: continue
            L = lab[..., 0]; med = np.median(L[mm]); Ls[v] = float(np.percentile(L[mm], 60))
            if v != "top":
                if w[i] >= 0.15: sh_all.append((float((L[mm] < med - SHADOW_DL).mean()), mm.sum()))
                res_ = np.where(mm, L - med, 0.0); wgt = ndimage.gaussian_filter(mm.astype(float), 6) + 1e-6
                sm = ndimage.gaussian_filter(res_, 6)/wgt; gr_all.append((float(np.std(sm[mm])), mm.sum()))
        if "top" in Ls and "front" in Ls and w[i] >= 0.15: rec["top_vs_front_dL"] = round(Ls["top"] - Ls["front"], 1)
        rec["L60"] = {k: round(v, 1) for k, v in Ls.items()}; res["materials"].append(rec)
    wavg = lambda xs: round(float(sum(a*b for a, b in xs)/max(sum(b for _, b in xs), 1)), 3)
    dls = [m["top_vs_front_dL"] for m in res["materials"] if "top_vs_front_dL" in m]
    res.update(top_vs_front_dL=max(dls, key=abs) if dls else None, shadow_share=wavg(sh_all), gradient_std=wavg(gr_all))
    issues = []
    if res["top_vs_front_dL"] is not None and abs(res["top_vs_front_dL"]) > TH["top_vs_front_dL"]:
        issues.append(f"lighting is not flat: the same material is {abs(res['top_vs_front_dL']):.0f} L {'darker' if res['top_vs_front_dL'] < 0 else 'lighter'} in the TOP plan than in the FRONT view; draw every view with the same flat, evenly lit colour and no directional light")
    if res["shadow_share"] > TH["shadow_share"]:
        issues.append(f"cast shadows / shading: {100*res['shadow_share']:.0f}% of wall and roof pixels are shaded copies of their material; remove all shadows (eaves, overhangs, porch, ambient occlusion)")
    if res["gradient_std"] > TH["gradient_std"]:
        issues.append(f"lighting gradients inside flat materials (std {res['gradient_std']:.1f} L); use uniform flat colour per material")
    res["issues"] = issues; res["shaded"] = bool(issues)
    return res

if __name__ == "__main__":
    n = sys.argv[1]
    for t in sys.argv[2:]:
        r = check(n, t); print(n, t, {k: r[k] for k in ("top_vs_front_dL", "shadow_share", "gradient_std", "shaded")}, [(m["ab"], m["share"], m.get("L60")) for m in r["materials"]])
