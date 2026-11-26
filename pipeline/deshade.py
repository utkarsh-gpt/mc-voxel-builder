#!/usr/bin/env python3
"""Remove drawn / baked lighting from sampled colours using the model's own geometry (COLOUR.md, "albedo").
Minecraft lights the build itself (sky light, ambient occlusion, block-face shading), so block colours must be albedo:
a wall under an eave must get the same block as the rest of the wall.

visibility(occ, pts, nrm): per surface point, ray-marched on the occupancy grid (the voxelised mesh or the block grid)
  V     cosine-weighted hemisphere visibility around the normal (ambient occlusion; crevices, inside corners)
  Vsky  visibility of the upper sky (directions with dy > 0.25): overhangs, eaves, porch roofs, sills
fit_shading(lab, V, Vsky, view, mat, down): learns how strongly THIS drawing (or texture) is shaded:
  ln(Y / Y_lit[mat]) = b[view] - kA (1 - V) - kS (1 - Vsky) - kD down      (robust soft-L1 least squares)
  ln(C / C_lit[mat]) = the same form for chroma (drawn shadows also turn colours greyer)
  Y_lit / C_lit = median of the material's well-lit samples (V > 0.8, Vsky > 0.85). b[front] = 0 (b[view] absorbs
  directional light: a top plan drawn darker than the front). Materials are only a grouping for the fit: genuinely dark
  parts (trim, soot, dark wood) are their own material, so they stay dark - only the geometry-predicted part is removed.
apply(lab, ...): Y / S, C / Sc, hue kept; S clamped to [0.45, 1.6] so a mis-fit can never invent colour."""
import numpy as np
from scipy.optimize import least_squares
from skimage import color as skc

def hemi_dirs(n=48):
    """cosine-weighted directions on the +z hemisphere (Fibonacci spiral)"""
    i = np.arange(n) + 0.5; r = np.sqrt(i/n); phi = i*np.pi*(3 - np.sqrt(5))
    return np.stack([r*np.cos(phi), r*np.sin(phi), np.sqrt(1 - r*r)], -1)

def frame(nv):
    ln = np.linalg.norm(nv); nv = nv/ln if ln > 1e-6 else np.array([0, 1.0, 0]); a = np.array([0, 1.0, 0]) if abs(nv[1]) < 0.9 else np.array([1.0, 0, 0])
    t = np.cross(a, nv); t /= np.linalg.norm(t); b = np.cross(nv, t); return np.stack([t, b, nv], 1)   # columns

def visibility(occ, pts, nrm, R=7.0, step=0.35, ndir=48, off=0.55):
    """pts: (N,3) points in voxel units (cell centres = idx + 0.5), nrm: (N,3) unit normals"""
    H = hemi_dirs(ndir); ts = np.arange(0.3, R, step); sh = np.array(occ.shape)
    V = np.zeros(len(pts)); Vs = np.zeros(len(pts))
    for i0 in range(0, len(pts), 256):
        P = pts[i0:i0 + 256]; Nn = nrm[i0:i0 + 256]
        D = np.stack([H @ frame(nv).T for nv in Nn])                        # (B, ndir, 3)
        O = P + off*Nn
        Q = O[:, None, None, :] + D[:, :, None, :]*ts[None, None, :, None]   # (B, ndir, T, 3)
        c = np.floor(Q).astype(int); inb = ((c >= 0) & (c < sh)).all(-1)
        cc = np.clip(c, 0, sh - 1); hit = occ[cc[..., 0], cc[..., 1], cc[..., 2]] & inb
        free = ~hit.any(-1)                                                    # (B, ndir)
        V[i0:i0 + 256] = free.mean(1)
        up = D[..., 1] > 0.25
        Vs[i0:i0 + 256] = np.where(up.any(1), (free & up).sum(1)/np.maximum(up.sum(1), 1), 1.0)
    return V, Vs

def _Y(L): return np.where(L > 8, ((L + 16)/116)**3, L/903.3)
def _L(Y): return np.where(Y > 0.008856, 116*np.cbrt(Y) - 16, 903.3*Y)

def fit_shading(lab, V, Vs, view, mat, down=None, views=("front", "right", "back", "left", "top")):
    down = np.zeros(len(lab)) if down is None else down
    Y = np.maximum(_Y(lab[:, 0]), 1e-3); C = np.hypot(lab[:, 1], lab[:, 2])
    lit = (V > 0.8) & (Vs > 0.85)
    ry, rc, okc = np.full(len(lab), np.nan), np.full(len(lab), np.nan), np.zeros(len(lab), bool)
    for m in np.unique(mat):
        k = mat == m; kl = k & lit
        if kl.sum() < 8: kl = k
        if k.sum() < 8: continue
        ry[k] = np.log(Y[k]/np.median(Y[kl])); cl = np.median(C[kl])
        if cl > 8: rc[k] = np.log(np.maximum(C[k], 1)/cl); okc[k] = True
    vi = np.array([views.index(v) for v in view]); nv = len(views)
    def solve(r, ok):
        ok = ok & np.isfinite(r)
        if ok.sum() < 30: return np.zeros(nv), 0.0, 0.0, 0.0
        def res(p):
            b = np.r_[0.0, p[:nv - 1]]; return (b[vi[ok]] - p[nv - 1]*(1 - V[ok]) - p[nv]*(1 - Vs[ok]) - p[nv + 1]*down[ok]) - r[ok]
        lo = [-1]*(nv - 1) + [0, 0, 0]; hi = [1]*(nv - 1) + [2, 2, 2]
        p = least_squares(res, np.r_[np.zeros(nv - 1), 0.1, 0.1, 0.0], bounds=(lo, hi), loss="soft_l1", f_scale=0.15).x
        return np.r_[0.0, p[:nv - 1]], float(p[nv - 1]), float(p[nv]), float(p[nv + 1])
    by, kA, kS, kD = solve(ry, np.ones(len(lab), bool)); bc, cA, cS, cD = solve(rc, okc)
    used = sorted(set(view))
    return {"lum": {"b": {v: round(float(by[views.index(v)]), 3) for v in used}, "kA": round(kA, 3), "kS": round(kS, 3), "kD": round(kD, 3)},
            "chroma": {"b": {v: round(float(bc[views.index(v)]), 3) for v in used}, "kA": round(cA, 3), "kS": round(cS, 3), "kD": round(cD, 3)}, "views": list(views)}

def factors(fit, V, Vs, view, down=None):
    down = np.zeros(len(V)) if down is None else down; out = []
    for key in ("lum", "chroma"):
        f = fit[key]; b = np.array([f["b"].get(v, 0.0) for v in view])
        out.append(np.clip(np.exp(b - f["kA"]*(1 - V) - f["kS"]*(1 - Vs) - f["kD"]*down), 0.45, 1.6))
    return out

def apply(lab, S, Sc):
    L = _L(np.clip(_Y(lab[:, 0])/S, 0, 1.0)); C = np.hypot(lab[:, 1], lab[:, 2]); h = np.arctan2(lab[:, 2], lab[:, 1])
    C2 = np.minimum(C/Sc, C + 25)
    return np.stack([L, C2*np.cos(h), C2*np.sin(h)], -1)
