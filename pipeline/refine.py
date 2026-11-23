#!/usr/bin/env python3
"""Deterministic fit-to-reference refinement (the 'hybrid' step), run after the LLM has made a plausible 3D model.
 1. Silhouette carve/grow against the reference mask from the matched camera (fixed framing, iterated).
 2. Reference colour projection: voxels visible from the reference camera take the reference colours they cover.
 3. Render-and-compare colour correction: re-render with lighting, nudge each visible voxel's Lab colour by
    (reference - render) so the *lit render* matches the photo (cheap, gradient-free analogue of differentiable
    rendering), a few iterations.
 4. Snap all colours to a k-colour palette from the reference (voxel-art palette discipline); hidden voxels keep the
    LLM's colours, snapped to the same palette.
usage: python refine.py ref.jpg model.json --out art/name_refined.json [--rounds 4] [--k 16] [--color-iters 3]"""
import argparse, json, numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color as skc
import vox, scorer
N, S = scorer.N, 512

def decode(img):
    a = np.asarray(img).astype(np.int64); return ((a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]) - 1

def render_codes(occ, az, el):
    """per-pixel (voxel_id, face_idx); -1 = background"""
    img, _ = vox.render(occ, None, az, el, S, ao=False, ids=np.arange(occ.size).reshape(occ.shape), frame="grid")
    c = decode(img); vid = np.where(c >= 0, c // 6, -1); face = np.where(c >= 0, c % 6, -1); return vid, face

def render_ids(occ, az, el): return render_codes(occ, az, el)[0]

def face_facing(az, el):
    R = vox.cam_R(az, el); return np.array([(R @ np.array(n))[2] for n, _ in vox.FACES])

def make_T(mask):
    """scorer.normalize()'s crop+letterbox transform for this render mask: render px -> N px"""
    ys, xs = np.nonzero(mask); y0, y1, x0, x1 = ys.min(), ys.max()+1, xs.min(), xs.max()+1
    h, w = y1-y0, x1-x0; s = (N-8)/max(h, w); nh, nw = max(1, round(h*s)), max(1, round(w*s))
    return y0, x0, s, (N-nh)//2, (N-nw)//2

def to_N(T):
    y0, x0, s, oy, ox = T; yy, xx = np.mgrid[0:S, 0:S]
    ny = np.floor((yy-y0)*s + oy).astype(int); nx = np.floor((xx-x0)*s + ox).astype(int)
    ok = (ny >= 0) & (ny < N) & (nx >= 0) & (nx < N); return np.clip(ny, 0, N-1), np.clip(nx, 0, N-1), ok

def refine(ref, model, out, rounds=4, k=16, color_iters=3, fit=True, min_facing=0.5):
    d, occ, col, _ = vox.load(model); cam = d.get("camera", {}); az, el = cam.get("azim", 30), cam.get("elev", 20)
    ref_img = Image.open(ref)
    if fit: az, el = scorer.fit_camera(ref_img, occ, col, az, el)
    rr, rm, _ = scorer.normalize(np.asarray(ref_img.convert("RGB")), scorer.ref_mask(ref_img))
    rmd = ndimage.binary_dilation(rm, iterations=1); Lref = skc.rgb2lab(rr)
    buf = render_ids(occ, az, el); T = make_T(buf >= 0); ny, nx, ok = to_N(T)
    tgt = ok & rm[ny, nx]; tgt_d = ok & rmd[ny, nx]
    tgt_e = ok & ndimage.binary_erosion(rm, iterations=3)[ny, nx]   # colour sampling away from edge bleed          # reference silhouette in render space (fixed)
    W, H, D = occ.shape; log = []
    for r in range(rounds):
        shell = ndimage.binary_dilation(occ, structure=ndimage.generate_binary_structure(3, 1)) & ~occ
        b = render_ids(occ | shell, az, el); occ_ids = np.flatnonzero(occ.ravel())
        isocc = np.isin(b, occ_ids); bo = render_ids(occ, az, el)
        grow = np.unique(b[tgt & (bo < 0) & (b >= 0)]); grow = grow[~np.isin(grow, occ_ids)]
        inside = np.unique(b[tgt_d & isocc]); vis = np.unique(b[isocc]); carve = vis[~np.isin(vis, inside)]
        if len(grow) == 0 and len(carve) == 0: break
        for g in grow:
            x, y, z = np.unravel_index(g, occ.shape)
            for dx, dy, dz in ((0,1,0),(0,-1,0),(1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):
                X, Y, Z = x+dx, y+dy, z+dz
                if 0<=X<W and 0<=Y<H and 0<=Z<D and occ[X, Y, Z]: col[x, y, z] = col[X, Y, Z]; break
        fo = occ.ravel().copy(); fo[grow] = True; fo[carve] = False; occ = fo.reshape(occ.shape)
        log.append({"round": r, "grown": int(len(grow)), "carved": int(len(carve))})
    # colour: projection then render-and-compare correction (in Lab)
    lab = skc.rgb2lab(col.reshape(1, -1, 3).astype(float)/255)[0]
    def per_voxel_mean(ids, vals, sel):
        v = ids[sel]; s_ = np.zeros((occ.size, 3)); c_ = np.zeros(occ.size)
        np.add.at(s_, v, vals[sel]); np.add.at(c_, v, 1); return s_, c_
    b, face = render_codes(occ, az, el)
    # Voxel faces are axis-aligned, so use the *smoothed surface normal* (gradient of blurred occupancy):
    # only voxels whose surface faces the camera (cos >= min_facing) receive projected colour -> no grazing leaks
    g = np.stack(np.gradient(ndimage.gaussian_filter(occ.astype(float), 1.5)), -1)
    nrm = -g / (np.linalg.norm(g, axis=-1, keepdims=True) + 1e-9)
    to_cam = vox.cam_R(az, el).T @ np.array([0, 0, 1.0])
    vfacing = (nrm.reshape(-1, 3) @ to_cam)
    sel = (b >= 0) & tgt_e
    sel &= vfacing[np.clip(b, 0, None)] >= min_facing
    Lpix = Lref[ny, nx]
    s_, c_ = per_voxel_mean(b, Lpix, sel); visible = c_ >= 6     # ignore grazing / sliver voxels
    lab[visible] = s_[visible]/c_[visible][:, None]
    def to_rgb(l): return (np.clip(skc.lab2rgb(l[None])[0], 0, 1)*255).round().astype(np.uint8)
    for it in range(color_iters):
        colr = to_rgb(lab).reshape(col.shape)
        img, _ = vox.render(occ, colr, az, el, S, frame="grid")
        Lr = skc.rgb2lab(np.asarray(img).astype(float)/255)
        s2, c2 = per_voxel_mean(b, Lpix - Lr, sel)
        delta = np.zeros_like(lab); delta[visible] = s2[visible]/c2[visible][:, None]
        lab = lab + 0.9*delta; lab[:, 0] = np.clip(lab[:, 0], 0, 100)
        log.append({"colour_iter": it, "mean_abs_dE": round(float(np.linalg.norm(delta[visible], axis=1).mean()), 2)})
    pal, _ = scorer.kmeans_palette(np.concatenate([Lref[rm], lab[occ.ravel()]]), k=k)
    snap = np.linalg.norm(lab[:, None]-pal[None], axis=2).argmin(1)
    keys = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    palette = {keys[i]: "#%02x%02x%02x" % tuple(c) for i, c in enumerate(to_rgb(pal))}
    vl = [{"x": int(x), "y": int(y), "z": int(z), "c": keys[snap[np.ravel_multi_index((x, y, z), occ.shape)]]} for x, y, z in zip(*np.nonzero(occ))]
    json.dump({"name": d.get("name", "model") + "_refined", "size": [W, H, D], "camera": {"azim": az, "elev": el}, "palette": palette, "voxels": vl}, open(out, "w"))
    print(json.dumps(log), "visible:", int(visible.sum()), "->", out); return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("ref"); ap.add_argument("model"); ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, default=4); ap.add_argument("--k", type=int, default=16); ap.add_argument("--color-iters", type=int, default=3)
    a = ap.parse_args(); refine(a.ref, a.model, a.out, a.rounds, a.k, a.color_iters)
