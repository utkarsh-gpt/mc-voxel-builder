#!/usr/bin/env python3
"""Visual-hull voxel carving from orthographic views (front, right, back, top) + flat colours.
usage: python ortho_carve.py NAME [--n 48] [--tag ""]
Conventions: x = object's right, y = up, z = toward the FRONT (front face = +z, renderer azim 0 looks at it).
 front view: col -> x, row -> y      right view: col -> z reversed (front on the left)
 back view:  col -> x reversed       top view: col -> x, row -> z (front at bottom)
Mirror ambiguities of AI drawings are resolved by trying flips and keeping the most self-consistent hull."""
import argparse, itertools, json, numpy as np
from PIL import Image
from scipy import ndimage
from skimage.transform import resize
from rembg import remove, new_session
import scorer, vox
SESSION = None

def mask_of(path):
    global SESSION
    SESSION = SESSION or new_session("isnet-general-use")
    im = Image.open(path).convert("RGB")
    m = np.asarray(remove(im, session=SESSION, only_mask=True)) > 100
    # union with a non-white threshold mask (rembg drops white walls drawn on a white background)
    nw = (np.asarray(im).min(-1) < 235); nw = ndimage.binary_closing(nw, np.ones((5, 5)), iterations=2)
    nw = ndimage.binary_opening(ndimage.binary_fill_holes(nw), np.ones((9, 9)))   # drops thin ground lines
    m = ndimage.binary_fill_holes(m | nw)
    lab, k = ndimage.label(m)
    if k:
        sz = np.bincount(lab.ravel()); sz[0] = 0; keep = sz >= 0.04*sz.max()
        for i, sl in enumerate(ndimage.find_objects(lab), 1):   # panel-frame / ground lines: long components <= 8 px thick
            if sl and min(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) <= 8 and keep.sum() > 1: keep[i] = False
        m = keep[lab]
    ys, xs = np.nonzero(m)
    box = (ys.min(), ys.max()+1, xs.min(), xs.max()+1)
    rgb = np.asarray(im)[box[0]:box[1], box[2]:box[3]]; return m[box[0]:box[1], box[2]:box[3]], rgb

def fit(m, rgb, shape, thr=0.3):
    f = resize(m.astype(float), shape, anti_aliasing=True, order=1) >= thr
    c = resize(rgb.astype(float)/255, shape + (3,), anti_aliasing=True, order=1); return f, c

def carve(n, N=48, tag="", thr=0.3):
    V = {k: mask_of(f"ortho/{n}{tag}_{k}.png") for k in ("front", "right", "back", "top")}
    hf, wf = V["front"][0].shape; hs, ws = V["right"][0].shape; hb, wb = V["back"][0].shape; ht, wt = V["top"][0].shape
    H = N if hf >= max(wf, ws*hf/hs) else None
    scale = N / max(hf, wf, ws*hf/hs)          # voxels per front-view pixel
    H = max(2, round(hf*scale)); W = max(2, round(wf*scale)); D = max(2, round(ws*hf/hs*scale))
    report = {"grid": [W, H, D], "front_wh": [wf, hf], "right_dh": [ws, hs], "back_wh": [wb, hb], "top_wd": [wt, ht],
              "back_vs_front_aspect": round((wb/hb)/(wf/hf), 3), "top_vs_elev_aspect(W/D)": round((wt/ht)/(W/D), 3)}
    F, Fc = fit(*V["front"], (H, W), thr); S, Sc = fit(*V["right"], (H, D), thr)
    B, Bc = fit(*V["back"], (H, W), thr); T, Tc = fit(*V["top"], (D, W), thr)
    x = np.arange(W)[:, None, None]; y = np.arange(H)[None, :, None]; z = np.arange(D)[None, None, :]
    def hull(fs, fb, ft):
        Sx = S[:, ::-1] if fs else S; Bx = B[:, ::-1] if fb else B; Tx = T[::-1] if ft else T
        r = H-1-y
        occ = F[r, x] & Sx[r, D-1-z] & Bx[r, W-1-x] & Tx[z, x]
        return occ, (Sx, Bx, Tx)
    best = None
    for fs, fb, ft in itertools.product((0, 1), repeat=3):
        occ, (Sx, Bx, Tx) = hull(fs, fb, ft)
        if not occ.any(): continue
        # reprojection IoU: hull projected back into each view vs that view's silhouette
        pf = occ.any(2).T[::-1]; ps = occ.any(0)[::-1, ::-1]; pb = occ.any(2).T[::-1, ::-1]; pt = occ.any(1).T
        ious = [(a & b).sum()/(a | b).sum() for a, b in ((pf, F), (ps, Sx), (pb, Bx), (pt, Tx))]
        sc = float(np.mean(ious))
        if best is None or sc > best[0]: best = (sc, (fs, fb, ft), occ, ious)
    sc, flips, occ, ious = best
    # Silhouette completion: AI top views are the least reliable (e.g. windmill sails drawn as an X instead of an
    # edge-on line). Where an elevation's silhouette is NOT covered by the strict hull, add back voxels from the
    # elevation-only hull (front & side & back) along those pixels' rays. Thin parts survive; the body stays top-carved.
    fs, fb, ft = flips
    Sx = S[:, ::-1] if fs else S; Bx = B[:, ::-1] if fb else B; r = H-1-y
    elev = F[r, x] & Sx[r, D-1-z] & Bx[r, W-1-x]
    pf = occ.any(2).T[::-1]; pb = occ.any(2).T[::-1, ::-1]; ps = occ.any(0)[::-1, ::-1]
    unc_f = F & ~pf; unc_b = Bx & ~pb; unc_s = Sx & ~ps
    # front/back pixels are completed using only that view + the side view (AI back views often re-pose thin parts)
    fside = Sx[r, D-1-z]
    add = ~occ & ((F[r, x] & fside & unc_f[r, x]) | (Bx[r, W-1-x] & fside & unc_b[r, W-1-x]) | (elev & unc_s[r, D-1-z]))
    # keep only the front-most / back-most layer chunk of each completed ray so sails stay thin planes
    if add.any():
        zz = np.where(add, z, -1); front_most = zz.max(2, keepdims=True)
        thick = max(1, round(D*0.08))
        add &= (z >= front_most - thick) | (unc_b[r, W-1-x] & ~unc_f[r, x])
    occ = occ | add
    report["completion_added"] = int(add.sum())
    ious = [(a & b).sum()/(a | b).sum() for a, b in ((occ.any(2).T[::-1], F), (occ.any(0)[::-1, ::-1], Sx), (occ.any(2).T[::-1, ::-1], Bx), (occ.any(1).T, T[::-1] if ft else T))]
    report.update({"flips(side,back,top)": flips, "reprojection_iou": [round(float(i), 3) for i in ious], "voxels": int(occ.sum())})
    # flat colours: each voxel takes the colour of the view its smoothed normal faces most
    Sx = Sc[:, ::-1] if flips[0] else Sc; Bx = Bc[:, ::-1] if flips[1] else Bc; Tx = Tc[::-1] if flips[2] else Tc
    g = np.stack(np.gradient(ndimage.gaussian_filter(occ.astype(float), 1.0)), -1); nrm = -g/(np.linalg.norm(g, axis=-1, keepdims=True)+1e-9)
    X, Y, Z = np.nonzero(occ); r = H-1-Y; nv = nrm[X, Y, Z]
    cand = np.stack([nv[:, 2], np.abs(nv[:, 0]), -nv[:, 2], nv[:, 1]], 1)   # front, side(either), back, top
    pick = cand.argmax(1)
    cols = np.where(pick[:, None] == 0, Fc[r, X], np.where(pick[:, None] == 1, Sx[r, D-1-Z], np.where(pick[:, None] == 2, Bx[r, W-1-X], Tx[Z, X])))
    from skimage import color as skc
    lab = skc.rgb2lab(cols[None])[0]; pal, _ = scorer.kmeans_palette(lab, k=14); snap = np.linalg.norm(lab[:, None]-pal[None], axis=2).argmin(1)
    keys = "abcdefghijklmnop"; prgb = (np.clip(skc.lab2rgb(pal[None])[0], 0, 1)*255).round().astype(int)
    d = {"name": n + "_ortho", "size": [W, H, D], "camera": {"azim": 0, "elev": 10},
         "palette": {keys[i]: "#%02x%02x%02x" % tuple(c) for i, c in enumerate(prgb)},
         "voxels": [{"x": int(a), "y": int(b), "z": int(c), "c": keys[s]} for a, b, c, s in zip(X, Y, Z, snap)]}
    json.dump(d, open(f"art/{n}{tag}_ortho.json", "w")); json.dump(report, open(f"out/{n}{tag}_ortho_report.json", "w"), indent=1)
    print(n, json.dumps(report)); return d

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--n", type=int, default=48); ap.add_argument("--tag", default="")
    ap.add_argument("--thr", type=float, default=0.3); a = ap.parse_args(); carve(a.name, a.n, a.tag, a.thr)
