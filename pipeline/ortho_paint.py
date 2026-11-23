#!/usr/bin/env python3
"""Colour a Hunyuan voxel shape from the 4 ortho drawings, then palette-snap + crevice ramp.
usage: python ortho_paint.py NAME [TAG]   (reads art/NAME_hymv.json, ortho/NAME{TAG}_{front,right,back,top}.png)
writes art/NAME_rendered.json + out/NAME_paint_report.json
Per surface voxel: candidate views = those where the voxel is the first hit along the view ray; pick the one whose
direction best matches the smoothed normal (facing >= MINF), else fall back to Hunyuan's own texture colour."""
import sys, json, numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color as skc
import vox, ortho_carve, scorer
MINF, KBASE = 0.35, 12
import os
n, tag = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "")
SKIP = next((x.split("=", 1)[1].split(",") for x in sys.argv if x.startswith("--skip=")), [])
key = n + tag if os.path.exists(f"art/{n}{tag}_hymv.json") else n
MODEL = next((x.split("=", 1)[1] for x in sys.argv if x.startswith("--model=")), None)   # e.g. windmill_lowpoly -> art/windmill_lowpoly.json
if MODEL: key = MODEL
d0, occ0, hcol, _ = vox.load(f"art/{key}.json" if MODEL else f"art/{key}_hymv.json", seed=0)
# Hunyuan voxelisation is a (leaky) shell -> make solid: fill holes of a 1-dilated copy, erode back
occ = occ0 | ndimage.binary_erosion(ndimage.binary_fill_holes(ndimage.binary_dilation(occ0)))
for y in range(occ.shape[1]):   # open-ended shells (towers): fill each horizontal ring
    sl = occ[:, y, :]; occ[:, y, :] = sl | ndimage.binary_erosion(ndimage.binary_fill_holes(ndimage.binary_dilation(sl)))
lab, k = ndimage.label(occ); sz = np.bincount(lab.ravel()); sz[0] = 0; occ &= sz[lab] >= 0.01*sz.max()  # drop floaters
W, H, D = occ.shape
# Hunyuan colour for filled interior: nearest shell voxel
_, idx = ndimage.distance_transform_edt(~occ0, return_indices=True); hcol = hcol[idx[0], idx[1], idx[2]]
pad = np.pad(occ, 1); surf = occ & ~ndimage.binary_erosion(pad, iterations=1, border_value=0)[1:-1, 1:-1, 1:-1]
g = ndimage.gaussian_filter(occ.astype(float), 1.6)
N = -np.stack(np.gradient(g), -1); N /= np.linalg.norm(N, axis=-1, keepdims=True) + 1e-9

# view definitions: dir (unit vector toward camera), projection axis, image (u,v)->grid mapping
# P is a 2D array [rows(top->bottom), cols(left->right)] as the drawing should look
def proj(view, A):
    if view == "front": return A.any(2).T[::-1, :]              # rows=y desc, cols=x
    if view == "back":  return A.any(2).T[::-1, ::-1]           # cols=x reversed
    if view == "right": return A.any(0)[::-1, ::-1]              # (H,D): rows=y desc, cols=z reversed (front on left)
    if view == "top":   return A.any(1).T                        # rows=z asc (front at bottom), cols=x
DIRS = {"front": (0, 0, 1), "back": (0, 0, -1), "right": (1, 0, 0), "left": (-1, 0, 0), "top": (0, 1, 0)}
def first_hit(view):
    """bool grid: voxel is the first occupied voxel seen from that view"""
    if view == "front": c = np.cumsum(occ[:, :, ::-1], 2)[:, :, ::-1]
    if view == "back":  c = np.cumsum(occ, 2)
    if view == "right": c = np.cumsum(occ[::-1], 0)[::-1]
    if view == "left":  c = np.cumsum(occ, 0)
    if view == "top":   c = np.cumsum(occ[:, ::-1], 1)[:, ::-1]
    return occ & (c == 1)
def pix_index(view, xs, ys, zs):
    """(row, col) of each voxel in the proj() image"""
    if view == "front": return H-1-ys, xs
    if view == "back":  return H-1-ys, W-1-xs
    if view == "right": return H-1-ys, D-1-zs
    if view == "top":   return zs, xs

xs, ys, zs = np.nonzero(surf); nrm = N[xs, ys, zs]
best_f = np.full(len(xs), -1.0); best_c = np.zeros((len(xs), 3)); rep = {"views": {}}
for view in ("front", "right", "back", "top", "left"):
    src = "right" if view == "left" else view   # no left drawing: mirrored right view (same pixel mapping)
    if src in SKIP: continue
    m, rgb = ortho_carve.mask_of(f"ortho/{n}{tag}_{src}.png")
    P = proj(src, occ); rr, cc = np.nonzero(P); r0, r1, c0, c1 = rr.min(), rr.max()+1, cc.min(), cc.max()+1
    h, w = r1-r0, c1-c0
    # fill background pixels with nearest in-mask colour (eroded mask avoids outline/edge pixels), then box-resize
    me = ndimage.binary_erosion(m, iterations=2) if ndimage.binary_erosion(m, iterations=2).sum() > 0.5*m.sum() else m
    _, ii = ndimage.distance_transform_edt(~me, return_indices=True); filled = rgb[ii[0], ii[1]]
    best = None
    for flip in (False, True):
        mm = np.asarray(Image.fromarray(m.astype(np.uint8)*255).resize((w, h), Image.BILINEAR)) > 127
        if flip: mm = mm[:, ::-1]
        iou = (mm & P[r0:r1, c0:c1]).sum() / (mm | P[r0:r1, c0:c1]).sum()
        if best is None or iou > best[0]: best = (iou, flip)
    iou, flip = best
    im = np.asarray(Image.fromarray(filled).resize((w*4, h*4), Image.BOX).resize((w, h), Image.BOX)).astype(float)
    if flip: im = im[:, ::-1]
    rep["views"][view] = {"iou": round(float(iou), 3), "mirrored": flip}
    vis = first_hit(view)[xs, ys, zs]; f = nrm @ np.array(DIRS[view], float)
    pr, pc = pix_index(src, xs, ys, zs); pr = np.clip(pr - r0, 0, h-1); pc = np.clip(pc - c0, 0, w-1)
    take = vis & (f > best_f) & (f >= MINF) & (iou > 0.6)
    best_f[take] = f[take]; best_c[take] = im[pr[take], pc[take]]
fb = best_f < 0; best_c[fb] = hcol[xs[fb], ys[fb], zs[fb]]
# background bleed: near-white samples (wispy edges on the white page) -> Hunyuan colour, unless Hunyuan also says white (white walls)
def _nw(c): l = skc.rgb2lab(np.asarray(c, float)[None]/255)[0]; return (l[:, 0] > 85) & (np.hypot(l[:, 1], l[:, 2]) < 12)
hc = hcol[xs, ys, zs].astype(float); bleed = ~fb & _nw(best_c) & ~_nw(hc); best_c[bleed] = hc[bleed]
rep_bleed = int(bleed.sum())
rep["white_bleed_fixed"] = rep_bleed; rep["from_drawings"] = round(float((~fb).mean()), 3); rep["hunyuan_fallback"] = round(float(fb.mean()), 3)
# smooth isolated speckles: median-ish -> each voxel takes palette later; light 3D Lab smoothing on surface only
L = skc.rgb2lab(best_c[None]/255)[0]
# palette: KBASE base colours (k-means in Lab) + a darker ramp step for crevices
from scipy.cluster.vq import kmeans2
cent, lbl = kmeans2(L, KBASE, minit="++", seed=0, iter=30)
used = np.unique(lbl); remap = -np.ones(KBASE, int); remap[used] = np.arange(len(used)); lbl = remap[lbl]; cent = cent[used]; KB = len(used)
# crevice: openness of 5^3 neighbourhood
open_ = ndimage.uniform_filter((~occ).astype(float), 5, mode="constant", cval=1.0)[xs, ys, zs]
crev = open_ < np.percentile(open_, 12)
dark = cent.copy(); dark[:, 0] *= 0.78; dark[:, 1:] *= 0.95
pal, vox_out = {}, []
keys = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
def hexc(l): r = (np.clip(skc.lab2rgb(l[None, None])[0, 0], 0, 1)*255).round().astype(int); return "#%02x%02x%02x" % tuple(r)
for i in range(KB): pal[keys[i]] = hexc(cent[i]); pal[keys[KB+i]] = hexc(dark[i])
for j in range(len(xs)):
    vox_out.append({"x": int(xs[j]), "y": int(ys[j]), "z": int(zs[j]), "c": keys[lbl[j] + (KB if crev[j] else 0)]})
# interior voxels (not visible) keep nearest-surface colour so the model stays solid for scoring
ix, iy, iz = np.nonzero(occ & ~surf)
lookup = -np.ones(occ.shape, int); lookup[xs, ys, zs] = lbl
_, si = ndimage.distance_transform_edt(~surf, return_indices=True)
for a, b, c in zip(ix, iy, iz): vox_out.append({"x": int(a), "y": int(b), "z": int(c), "c": keys[lookup[si[0][a, b, c], si[1][a, b, c], si[2][a, b, c]]]})
out = {"name": f"{key}_rendered", "size": [W, H, D], "camera": {"azim": 35, "elev": 20}, "palette": pal, "voxels": vox_out}
json.dump(out, open(f"art/{key}_rendered.json", "w"))
rep.update({"surface_voxels": int(len(xs)), "total_voxels": len(vox_out), "palette_size": len(set(v["c"] for v in vox_out))})
json.dump(rep, open(f"out/{key}_paint_report.json", "w"), indent=1); print(key, json.dumps(rep))
