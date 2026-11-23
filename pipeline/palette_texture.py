#!/usr/bin/env python3
"""Colour stage: base materials -> brightness ramps -> cause/cluster placement -> cleanup -> gradient blends -> palette.
Implements TEXTURE_RULES.md (designed by Opus) on the half-size sub-block models; geometry and sub-block shapes are kept, only colours change.
usage: python palette_texture.py SUBJECT [--in path.json] [--out path.json]"""
import argparse, json, hashlib, numpy as np
from scipy import ndimage
from skimage import color as skc
import vox

# ---------------- colour helpers ----------------
def hex2lab(h): return skc.rgb2lab(np.array(vox.hex2rgb(h), float)[None, None]/255)[0, 0]
def lab2hex(l):
    L, a, b = l; C = np.hypot(a, b); H = np.arctan2(b, a)
    for _ in range(50):
        rgb = skc.lab2rgb(np.array([[[L, C*np.cos(H), C*np.sin(H)]]]))[0, 0]
        raw = skc.lab2rgb(np.array([[[L, C*np.cos(H), C*np.sin(H)]]]))  # skimage clips; check via roundtrip
        back = skc.rgb2lab(rgb[None, None])[0, 0]
        if np.linalg.norm(back - [L, C*np.cos(H), C*np.sin(H)]) < 1.5 or C < 1: break
        C *= 0.98
    return "#%02x%02x%02x" % tuple((np.clip(rgb, 0, 1)*255).round().astype(int))
def dE(a, b): return float(np.linalg.norm(np.asarray(a) - np.asarray(b)))
def rot_toward(h, target, deg):
    d = (target - h + 180) % 360 - 180
    return h + np.sign(d)*min(abs(d), deg)

def ramp(base_hex, lo, hi, dL_dn, dL_up, mode, dh=0, db_up=0, db_dn=0, cd=0, cu=0):
    """returns {shade: lab}"""
    L0, a0, b0 = hex2lab(base_hex); C0 = np.hypot(a0, b0); h0 = np.degrees(np.arctan2(b0, a0)) % 360
    out = {}
    for s in range(lo, hi+1):
        L = L0 + (s*dL_up if s > 0 else s*dL_dn)
        if mode == "chromatic":
            h = rot_toward(h0, 85 if s > 0 else 250, abs(s)*dh) if s else h0
            C = min(C0*(1 + cu*s) if s > 0 else C0*(1 - cd*abs(s)), C0 + 10)
            a, b = C*np.cos(np.radians(h)), C*np.sin(np.radians(h))
        else:
            a, b = a0, b0
            if s > 0: b += s*db_up
            elif s < 0: b -= abs(s)*db_dn; a -= 0.3*abs(s)
        out[s] = np.array([L, a, b])
    return out

# ---------------- per-subject material + ramp specs (TEXTURE_RULES.md §1-§3) ----------------
DEF = dict(w_open=0.9, w_up=0.6, w_h=0.5, w_dir=0.35, w_n=0.8, scale=4, q=(0.03, 0.10, 0.07, 0.02))
MAT = {
 "windmill": {
  "stone":       dict(base="#958f81", r=(-2, 2, 6, 5, "neutral"), kw=dict(db_up=1.5, db_dn=1.0), p=DEF),
  "cap_slate":   dict(base="#4f555c", r=(-2, 1, 5, 6, "neutral"), kw=dict(db_up=-1.5, db_dn=0.5), p=dict(DEF, w_open=0.6, w_up=0.8, w_h=0.3, w_dir=0.3, w_n=0.4, q=(0.04, 0.10, 0.08, 0))),
  "sail_white":  dict(base="#e2dfd4", r=(-2, 1, 5, 3, "neutral"), kw=dict(db_up=1.0, db_dn=1.5), p=dict(DEF, w_open=0.5, w_up=0.5, w_h=0, w_dir=0.3, w_n=0.3, scale=5, q=(0.02, 0.08, 0.06, 0))),
  "dark_detail": dict(base="#34312d", r=(-1, 0, 5, 0, "neutral"), kw=dict(db_dn=0.5), p=None)},
 "cottage": {
  "wall_white":  dict(base="#e6e3dc", r=(-2, 1, 6, 3, "neutral"), kw=dict(db_up=1.5, db_dn=2.0), p=dict(DEF, w_open=0.7, w_up=0, w_h=0.4, w_n=0.5, q=(0.03, 0.12, 0.06, 0))),
  "thatch":      dict(base="#8d8c74", r=(-2, 2, 6, 6, "chromatic"), kw=dict(dh=6, cd=0.05, cu=0.08), p=DEF),
  "moss":        dict(base="#6f7a4a", r=(-1, 1, 6, 6, "chromatic"), kw=dict(dh=8, cd=0.05, cu=0.06), p=None),
  "door_red":    dict(base="#a1392d", r=(-1, 1, 6, 5, "chromatic"), kw=dict(dh=4, cd=0.06, cu=0.03), p=None),
  "glass_dark":  dict(base="#3a3e44", r=(-1, 0, 5, 0, "neutral"), kw=dict(db_dn=1.0), p=None),
  "chimney_brick": dict(base="#8a4e3e", r=(-2, 1, 6, 5, "chromatic"), kw=dict(dh=5, cd=0.08, cu=0.03), p=dict(DEF, w_open=0.8, w_up=0.4, w_h=0, w_dir=0.2, w_n=0.6, scale=2, q=(0.04, 0.10, 0.08, 0)))},
 "bonsai": {
  "foliage":     dict(base="#6a9030", r=(-2, 2, 8, 7, "chromatic"), kw=dict(dh=7, cd=0.08, cu=0.06), p=dict(DEF, w_open=1.3, w_up=0.7, w_dir=0.4, w_n=0.9, scale=3, q=(0.05, 0.12, 0.10, 0.03))),
  "trunk":       dict(base="#9a6234", r=(-2, 2, 7, 6, "chromatic"), kw=dict(dh=5, cd=0.06, cu=0.04), p=dict(DEF, scale=2)),
  "pot":         dict(base="#7a2a20", r=(-2, 1, 5, 5, "chromatic"), kw=dict(dh=4, cd=0.04, cu=0.03), p=dict(DEF, w_open=0.8, w_up=0.9, w_dir=0.3, w_n=0.25, scale=5, q=(0.06, 0.12, 0.08, 0))),
  "soil":        dict(base="#3d2d1f", r=(-1, 1, 4, 4, "chromatic"), kw=dict(dh=3, cd=0.05, cu=0.03), p=dict(DEF, w_open=0.8, w_up=0.4, w_h=0, w_dir=0.2, w_n=0.6, scale=3, q=(0, 0.12, 0.10, 0))),
  "moss":        dict(base="#55692a", r=(-1, 1, 6, 6, "chromatic"), kw=dict(dh=8, cd=0.05, cu=0.06), p=None)}}
BLEND = {"windmill": [("stone", "cap_slate", -1)],
         "cottage": [("wall_white", "thatch", -2), ("thatch", "chimney_brick", -2), ("thatch", "moss", 0)],
         "bonsai": [("trunk", "soil", 0), ("trunk", "foliage", -2), ("soil", "moss", -1)]}
SUN = np.array([-0.5, 1.0, 0.6]); SUN /= np.linalg.norm(SUN)

def noise(shape, scale, key, octaves=True):
    rng = np.random.default_rng(int(hashlib.md5(key.encode()).hexdigest()[:8], 16))
    def one(s):
        g = [int(np.ceil(n/s)) + 2 for n in shape]; lat = rng.uniform(-1, 1, g)
        z = ndimage.zoom(lat, [ (n+2*s)/gg for n, gg in zip(shape, g)], order=1)
        return z[:shape[0], :shape[1], :shape[2]]
    n = one(scale)
    if octaves and scale >= 2: n = n + 0.4*one(max(scale/2, 1))
    return n

# ---------------- geometry ----------------
def load(path):
    d = json.load(open(path)); W, H, D = d["size"]
    occ = np.zeros((W, H, D), bool); occw = np.zeros((W, H, D)); lab0 = np.zeros((W, H, D, 3))
    pal = {k: hex2lab(v) for k, v in d["palette"].items()}
    for v in d["voxels"]:
        x, y, z = v["x"], v["y"], v["z"]; occ[x, y, z] = True; s = v.get("s"); occw[x, y, z] = s.get("size", 1.0) if s else 1.0
        lab0[x, y, z] = pal[v["c"]]
    return d, occ, occw, lab0
def smooth_lab(lab0, occ, zone=None, passes=2):
    out = lab0.copy(); W, H, D = occ.shape
    for _ in range(passes):
        new = out.copy()
        for x, y, z in np.argwhere(occ):
            sl = (slice(max(x-1, 0), x+2), slice(max(y-1, 0), y+2), slice(max(z-1, 0), z+2))
            m = occ[sl] if zone is None else occ[sl] & (zone[sl] == zone[x, y, z])
            new[x, y, z] = np.median(out[sl][m], axis=0)
        out = new
    return out
def lch(lab): return lab[..., 0], np.hypot(lab[..., 1], lab[..., 2]), np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360

# ---------------- zoning per subject ----------------
def zones_windmill(occ, lab_s, lab0=None):
    W, H, D = occ.shape; L, C, h = lch(lab_s); M = np.full(occ.shape, "", object)
    ys = range(1, max(2, int(0.45*H)) + 1)
    foot = np.mean([occ[:, y, :] for y in ys], axis=0) >= 0.6
    xs_, zs_ = np.nonzero(foot); zf = zs_.max(); core_top = max(y for y in range(H) if (occ[:, y, :] & foot).any())
    footd = ndimage.binary_dilation(foot)
    X, Y, Z = np.indices(occ.shape)
    sail = occ & ((Z > zf) | (Y > core_top) | ((~footd[X, Z]) & (Y >= 2)))
    core = occ & ~sail
    # cap: lowest y >= 0.4H where >= 50% of core surface in layer is bluish or dark
    surf = surface(occ); ycap = None
    for y in range(int(0.4*H), core_top+1):
        m = core[:, y, :] & surf[:, y, :]
        if m.sum() >= 4 and (lab0[:, y, :, 2][m] < -2).mean() >= 0.5: ycap = y; break
    if ycap is None: ycap = core_top - 3
    M[core] = "stone"; M[core & (Y >= ycap)] = "cap_slate"; M[sail] = "sail_white"
    cx = xs_.mean()
    hub = sail & (np.abs(X - cx) <= 1) & (np.abs(Y - ycap) <= 1) & (L < 45); M[hub] = "dark_detail"
    win = core & surf & (M == "stone") & (L < 32) & (Y >= 0.55*ycap) & (Y <= ycap - 1)
    lab_, k = ndimage.label(win, np.ones((3, 3, 3)))
    for i in range(1, k+1):
        comp = lab_ == i
        arch = (ndimage.binary_dilation(comp) & ~occ & footd[X, Z]).any()
        if 2 <= comp.sum() <= 6 and not arch: M[comp] = "dark_detail"
    return M, dict(zf=int(zf), ycap=int(ycap), core_top=int(core_top), cx=float(cx))

def zones_cottage(occ, lab_s, lab0=None):
    W, H, D = occ.shape; L, C, h = lch(lab_s); M = np.full(occ.shape, "", object); X, Y, Z = np.indices(occ.shape)
    area = occ.sum((0, 2)); ye = next((y for y in range(1, H) if area[y] >= 1.15*max(area[y-1], 1)), 3)
    yr = max(y for y in range(H) if area[y] >= 6)
    M[occ & (Y < ye)] = "wall_white"; M[occ & (Y >= ye)] = "thatch"
    chim = occ & (Y > yr)
    # extend chimney downward: connected warm-ish voxels
    warm = occ & (h >= 15) & (h <= 55) & (C > 8)
    lab_, _ = ndimage.label(chim | warm, np.ones((3, 3, 3)))
    ids = set(np.unique(lab_[chim])) - {0}
    chim = np.isin(lab_, list(ids)) & (chim | (warm & (Y >= ye)))
    M[chim] = "chimney_brick"
    surf = surface(occ)
    nearwall = surf
    region = nearwall | ((np.abs(Y - ye) <= 2) & occ)
    L0, C0, h0 = lch(lab0)
    red = region & surf & (lab0[..., 1] > 10) & ((h0 <= 45) | (h0 >= 350)) & ~chim & (Y <= ye)
    lab_, k = ndimage.label(red, np.ones((3, 3, 3)))
    for i in range(1, k+1):
        if (lab_ == i).sum() >= 2: M[lab_ == i] = "door_red"
    # glass: dark wall-face clusters (2-8) below the eave, or dark voxels hugging the red frames
    rn = ndimage.convolve((M == "door_red").astype(int), np.ones((3, 3, 3)), mode="constant")
    dark = occ & surf & (L0 < 30) & (Y < ye) & (M == "wall_white")
    lab_, k = ndimage.label(dark, np.ones((3, 3, 3)))
    for i in range(1, k+1):
        comp = lab_ == i
        if 2 <= comp.sum() <= 10 or (rn[comp] >= 2).any(): M[comp] = "glass_dark"
    return M, dict(ye=int(ye), yr=int(yr))

def zones_bonsai(occ, lab_s):
    W, H, D = occ.shape; L, C, h = lch(lab_s); M = np.full(occ.shape, "", object); X, Y, Z = np.indices(occ.shape)
    redl = (lab_s[..., 1] > 12) & (h <= 45)
    area = occ.sum((0, 2)); yp = 0
    for y in range(H//2):
        m = occ[:, y, :]
        if m.sum() and (redl[:, y, :][m]).mean() >= 0.5: yp = y
    # soil band: layers above the glaze that stay wide (>= 50% of the pot top area)
    ys = yp
    while ys + 1 < H and area[ys+1] >= 0.5*area[yp]: ys += 1
    tmin = max(1, min((area[y] for y in range(ys+1, min(H, H//2 + 4)) if area[y] > 0), default=1))
    yc = next((y for y in range(ys+1, H) if area[y] >= 3*tmin and y > np.argmin(np.where(area[ys+1:] > 0, area[ys+1:], 1e9)) + ys + 1), H//2)
    for y in range(0, yp): M[:, y, :][occ[:, y, :]] = "pot"
    for y in range(yp, ys+1):
        m = occ[:, y, :]; inner = ndimage.binary_erosion(m, iterations=1)
        M[:, y, :][m] = "pot"; M[:, y, :][m & inner] = "soil"
    M[occ & (Y > ys) & (Y < yc)] = "trunk"
    up = occ & (Y >= yc); M[up] = "foliage"
    cand = up & (h >= 40) & (h <= 85) & (C > 15) & (L > 28) & (L < 62)
    trunkcol = occ & (M == "trunk")
    lab_, _ = ndimage.label(cand | trunkcol, np.ones((3, 3, 3)))
    ids = set(np.unique(lab_[trunkcol])) - {0}
    M[cand & np.isin(lab_, list(ids))] = "trunk"
    return M, dict(yp=int(yp), ys=int(ys), yc=int(yc))

def surface(occ):
    p = np.pad(occ, 1); n = np.zeros_like(occ)
    for ax in range(3):
        for s in (1, -1): n |= ~np.roll(p, s, ax)[1:-1, 1:-1, 1:-1]
    return occ & n

def mode_filter_labels(M, occ, names, min_size, majority=True):
    """1 pass 3x3x3 mode within occupied, then small components -> most common neighbouring label"""
    idx = {n: i for i, n in enumerate(names)}; A = np.full(occ.shape, -1); 
    for n in names: A[M == n] = idx[n]
    out = A.copy()
    for x, y, z in (np.argwhere(occ) if majority else []):
        sl = (slice(max(x-1, 0), x+2), slice(max(y-1, 0), y+2), slice(max(z-1, 0), z+2)); vals = A[sl][A[sl] >= 0]
        c = np.bincount(vals, minlength=len(names)); 
        if c.max() > c[A[x, y, z]] + 4: out[x, y, z] = c.argmax()       # only flip clear minorities (keeps thin parts)
    for n in names:
        lab_, k = ndimage.label(out == idx[n], np.ones((3, 3, 3)))
        for i in range(1, k+1):
            comp = lab_ == i
            if comp.sum() < min_size.get(n, 1):
                ring = ndimage.binary_dilation(comp, np.ones((3, 3, 3))) & ~comp & (out >= 0)
                if ring.any(): out[comp] = np.bincount(out[ring]).argmax()
    R = np.full(occ.shape, "", object)
    for n in names: R[out == idx[n]] = n
    return R

# ---------------- main ----------------
def run(subject, src, dst):
    d, occ, occw, lab0 = load(src); W, H, D = occ.shape; X, Y, Z = np.indices(occ.shape)
    lab_s = smooth_lab(lab0, occ)
    M, Z_ = (zones_cottage(occ, lab_s, lab0) if subject == "cottage" else zones_windmill(occ, lab_s, lab0) if subject == "windmill" else zones_bonsai(occ, lab_s))
    names = list(MAT[subject].keys())
    keep_thin = {"sail_white", "dark_detail", "door_red", "glass_dark", "chimney_brick", "trunk"}
    M2 = mode_filter_labels(M, occ, names, {})          # majority pass only
    for n in keep_thin: M2[(M == n)] = n                 # thin/detail parts are not eroded by the majority pass
    M = mode_filter_labels(M2, occ, names, {"door_red": 2, "chimney_brick": 3, "dark_detail": 2}, majority=False)
    surf = surface(occ)
    g = ndimage.gaussian_filter(occ.astype(float), 1.0); Nrm = -np.stack(np.gradient(g), -1); Nrm /= np.linalg.norm(Nrm, axis=-1, keepdims=True) + 1e-9
    openness = np.clip((0.50 - ndimage.gaussian_filter(occw, 1.2))/0.15, -1, 1)
    up = np.clip(Nrm[..., 1], 0, 1); dirl = Nrm @ SUN
    yj = Y + 1.2*noise(occ.shape, 2, subject + "yj", False)
    empty_below = occ & ~np.concatenate([np.ones((W, 1, D), bool), occ[:, :-1, :]], 1)
    ramps = {m: ramp(s["base"], *s["r"], **s["kw"]) for m, s in MAT[subject].items()}
    IDX = np.zeros(occ.shape, int); FORCED = np.zeros(occ.shape, bool)
    # material-specific cause terms
    cause = np.zeros(occ.shape)
    if subject == "windmill":
        st = M == "stone"; cause[st & (yj <= 1)] -= 0.8
        cause[st & (Y >= Z_["ycap"]-2) & (Y <= Z_["ycap"]-1)] -= 0.7
        voids_near = ndimage.binary_dilation(~occ & ndimage.binary_dilation(occ, iterations=2), np.ones((3, 3, 3))) # crude arch/window vicinity
        cause[st & (openness < -0.2) & voids_near] -= 0.6
        ledge = st & (up > 0.7) & (Y < Z_["ycap"]-1); cause[ledge] += 0.8
        below = np.zeros_like(ledge); below[:, :-1, :] = ledge[:, 1:, :]; cause[st & below] -= 0.4
        cap = M == "cap_slate"; lip = cap & empty_below & (Y <= Z_["ycap"]+1); cause[cap & (up > 0.5)] += 0.5
        sl = M == "sail_white"; cause[sl & (up > 0.5)] += 0.6; cause[sl & (Z == Z_["zf"]+1)] -= 0.5
    if subject == "cottage":
        wl = M == "wall_white"; cause[wl & (yj < 0.8)] -= 0.9
        th = M == "thatch"
        above = np.zeros_like(th)
        for k in range(1, 2): above[:, :-k, :] |= th[:, k:, :]   # top wall row only: walls are just 3 voxels tall
        cause[wl & above] -= 1.2
        nd = ndimage.binary_dilation((M == "door_red") | (M == "glass_dark")); cause[wl & nd] -= 0.4
        cause[th & (Y == Z_["ye"]) & surf] -= 0.8; cause[th & (Y >= Z_["yr"]-1) & (up > 0.5)] += 1.0
        cause[th & ndimage.binary_dilation(nd, iterations=2)] -= 0.6
        ch = M == "chimney_brick"
        if ch.any():
            cxz = np.argwhere(ch.any(1)); cyb = np.argwhere(ch)[:, 1].min()
            dist = np.min([np.hypot(X - a, Z - b) for a, b in cxz], axis=0); cause[th & (dist <= 2.5) & (Y >= cyb-1)] -= 1.2
            top = ch & (Y == np.argwhere(ch)[:, 1].max())
    if subject == "bonsai":
        fo = M == "foliage"; cause[fo & empty_below & (Y < Z_["yc"] + (H - Z_["yc"])/2)] -= 0.8
        tr = np.argwhere(M == "trunk"); ax = tr[:, [0, 2]].mean(0) if len(tr) else np.array([W/2, D/2])
        cause[fo & (np.hypot(X-ax[0], Z-ax[1]) <= 2) & (openness < 0)] -= 0.5; cause[fo & (up > 0.7)] += 0.6
        cause[(M == "trunk") & (Y >= Z_["yc"]-2) & (Y < Z_["yc"])] -= 0.6
        pt = M == "pot"; cause[pt & (up > 0.7) & (Y >= Z_["yp"])] += 1.0
        so = M == "soil"; cause[so & ndimage.binary_dilation(pt)] -= 0.5
    # score -> ramp index by quantiles
    for m, spec in MAT[subject].items():
        mm = (M == m) & surf
        if not mm.any(): continue
        lo, hi = spec["r"][0], spec["r"][1]
        if spec["p"] is None:   # small details: absolute thresholds
            S = 1.0*openness + 0.5*up + 0.3*dirl
            IDX[mm & (S < -0.6)] = max(lo, -1); 
            if hi >= 1: IDX[mm & (S > 0.7)] = 1
            continue
        p = spec["p"]; y0, y1 = np.argwhere(M == m)[:, 1].min(), np.argwhere(M == m)[:, 1].max()
        hgt = 2*(yj - y0)/max(y1 - y0, 1) - 1
        S = p["w_open"]*openness + p["w_up"]*up + p["w_h"]*hgt + p["w_dir"]*dirl + p["w_n"]*noise(occ.shape, p["scale"], subject+m) + cause
        v = S[mm]; q2, q1, p1, p2 = [1.35*q for q in p["q"]]; idx = np.zeros(len(v), int)
        if lo <= -2 and q2 > 0: idx[v <= np.quantile(v, q2)] = -2
        if lo <= -1 and q1 > 0: idx[(v > (np.quantile(v, q2) if q2 > 0 and lo <= -2 else -1e9)) & (v <= np.quantile(v, q2 + q1))] = -1
        if hi >= 1 and p1 > 0: idx[v >= np.quantile(v, 1 - p2 - p1)] = 1
        if hi >= 2 and p2 > 0: idx[v >= np.quantile(v, 1 - p2)] = 2
        IDX[mm] = idx
    # forced
    if subject == "windmill":
        IDX[lip] = -2; FORCED |= lip
    if subject == "cottage":
        und = (M == "thatch") & empty_below & surf; IDX[und] = -2; FORCED |= und
        if (M == "chimney_brick").any(): IDX[top] = -2; FORCED |= top
        # moss on thatch
        th = (M == "thatch") & surf & ~FORCED
        h01 = (Y - Z_["ye"])/max(Z_["yr"] - Z_["ye"], 1)
        ridge = (Y >= Z_["yr"]-1) & (up > 0.5)
        Ms = 0.6*(-dirl) + 0.4*(-openness) + 0.5*noise(occ.shape, 3, "moss") + 0.3*(1 - h01) - 1.0*ridge - 0.5*(up > 0.7)
        thr = np.quantile(Ms[th], 0.91); moss = th & (Ms >= thr)
        lab_, k = ndimage.label(moss, np.ones((3, 3, 3)))
        for i in range(1, k+1):
            if (lab_ == i).sum() < 3: moss[lab_ == i] = False
        M[moss] = "moss"; IDX[moss] = 0
        mv = np.argwhere(moss)
        if len(mv):
            upm = up[moss]; IDX[moss & (up >= np.quantile(upm, 0.8))] = 1; IDX[moss & (openness < -0.3)] = -1
    if subject == "bonsai":
        feet = (M == "pot") & (Y == 0); IDX[feet] = -2; FORCED |= feet
        so = (M == "soil") & surf
        if so.any():
            tr = np.argwhere(M == "trunk"); ax = tr[:, [0, 2]].mean(0) if len(tr) else np.array([W/2, D/2])
            nm = noise(occ.shape, 3, "soilmoss"); mo = so & ((np.hypot(X-ax[0], Z-ax[1]) <= 2.5) | (nm >= np.quantile(nm[so], 0.9)))
            mo &= (M != "trunk")
            lab_, k = ndimage.label(mo, np.ones((3, 3, 3)))
            for i in range(1, k+1):
                if (lab_ == i).sum() < 2: mo[lab_ == i] = False
            M[mo] = "moss"; IDX[mo] = 0
    # cleanup (surface, same material)
    IDX = cleanup(IDX, M, surf, FORCED, ramps)
    # colours
    LAB = np.zeros(occ.shape + (3,))
    for m in ramps:
        for s, c in ramps[m].items(): LAB[(M == m) & (IDX == s)] = c
    # interior: material base
    for m in ramps: LAB[(M == m) & ~surf] = ramps[m][0]
    # gradient blends
    blend_info = []; BL = {}
    for A, B, shB in BLEND[subject]:
        mA, mB = (M == A), (M == B)
        if not mA.any() or not mB.any(): continue
        dist = ndimage.distance_transform_edt(~mB); dj = dist + 0.9*noise(occ.shape, 2, f"blend{A}{B}", False)
        sel = mA & surf & (dist <= 4.5)
        if not sel.any(): continue
        outside = mA & surf & (dj > 2) & (dj <= 5)
        cA_shade = int(np.bincount(IDX[outside] + 3).argmax() - 3) if outside.any() else 0
        cA = ramps[A].get(cA_shade, ramps[A][0]); cB = ramps[B].get(shB, ramps[B][0])
        n = int(np.clip(round(dE(cA, cB)/11) - 1, 0, 3))
        ya = np.argwhere(mA)[:, 1]; n = min(n, max(1, (ya.max() - ya.min() + 1)//3))   # a blend may not swallow a short part (cottage walls are 3 tall)
        chain = [cA + (cB - cA)*k/(n+1) for k in range(1, n+1)]
        k_v = np.clip(n + 1 - np.ceil(dj), 0, n).astype(int)
        # step check: face neighbours inside the blend may differ by at most one chain position
        k_v = np.where(sel, k_v, 0)
        for _ in range(6):
            ch_ = False
            for ax in range(3):
                for sgn in (1, -1):
                    nb = np.roll(k_v, sgn, ax); ok = np.roll(sel, sgn, ax); sl = [slice(None)]*3; sl[ax] = 0 if sgn == 1 else -1; ok[tuple(sl)] = False
                    bad = sel & ok & (k_v - nb >= 2)
                    if bad.any(): k_v[bad] -= 1; ch_ = True
            if not ch_: break
        apply = sel & (k_v > 0)
        for k in range(1, n+1): LAB[apply & (k_v == k)] = chain[k-1]
        for x, y, z in np.argwhere(apply): BL[(x, y, z)] = [B, int(k_v[x, y, z]), n]
        blend_info.append({"pair": f"{A}<-{B}", "n_intermediates": n, "voxels_blended": int(apply.sum())})
    # palette: unique colours, merge close (dE<2)
    flat = LAB[occ]; keys_hex = [lab2hex(c) for c in flat]
    uniq = {}
    for hx in keys_hex: uniq[hx] = uniq.get(hx, 0) + 1
    labs = {hx: hex2lab(hx) for hx in uniq}; order = sorted(uniq, key=lambda k: -uniq[k]); rep = {}
    kept = []
    for hx in order:
        t = next((k for k in kept if float(skc.deltaE_ciede2000(labs[k], labs[hx])) < 2.0), None)
        rep[hx] = t if t else hx
        if not t: kept.append(hx)
    pal = {f"p{i}": hx for i, hx in enumerate(kept)}; inv = {hx: k for k, hx in pal.items()}
    coords = np.argwhere(occ); col_of = {tuple(c): inv[rep[h]] for c, h in zip(coords, keys_hex)}
    vs = []
    for v in d["voxels"]:
        v2 = dict(v); v2["c"] = col_of[(v["x"], v["y"], v["z"])]; vs.append(v2)
    out = dict(d); out["palette"] = pal; out["voxels"] = vs; out["name"] = f"{subject}_voxels_textured"
    out["texture"] = {"rules": "TEXTURE_RULES.md", "zones": Z_, "materials": {m: int((M == m).sum()) for m in ramps}, "blends": blend_info}
    json.dump(out, open(dst, "w"))
    lab_out = {"subject": subject, "size": d["size"], "zones": Z_, "voxels": [
        {"x": int(x), "y": int(y), "z": int(z), "m": M[x, y, z], "sh": int(IDX[x, y, z]) if surf[x, y, z] else 0, "surf": bool(surf[x, y, z]),
         **({"blend": BL[(x, y, z)]} if (x, y, z) in BL else {})} for x, y, z in np.argwhere(occ)]}
    json.dump(lab_out, open(f"art/final/meta/{subject}_texture_labels.json", "w"))
    import subblock; subblock.expand(dst, dst.replace(".json", "_fine.json"))
    stats = {"palette": len(pal), "materials": out["texture"]["materials"], "zones": Z_, "blends": blend_info,
             "base_share": {m: round(float((IDX[(M == m) & surf] == 0).mean()), 2) for m in ramps if ((M == m) & surf).any()}}
    print(subject, json.dumps(stats)); return stats

def cleanup(IDX, M, surf, FORCED, ramps):
    K = np.ones((3, 3, 3), int)
    for m in ramps:
        mm = (M == m) & surf
        if not mm.any(): continue
        for _ in range(2):   # anti-speckle
            for k in np.unique(IDX[mm]):
                if k == 0: continue
                same = ndimage.convolve(((IDX == k) & mm).astype(int), K, mode="constant") - 1
                iso = mm & (IDX == k) & (same < 2) & ~FORCED; IDX[iso] = np.sign(k)*(abs(k) - 1)
        # min cluster
        for k in (-1, 1):
            lab_, n = ndimage.label(mm & (np.sign(IDX) == k) & ~FORCED, K)
            for i in range(1, n+1):
                comp = lab_ == i
                if comp.sum() < 3: IDX[comp] = np.sign(IDX[comp])*(np.abs(IDX[comp]) - 1)
        # anti-splatter
        for _ in range(5):
            changed = False
            for ax in range(3):
                for s in (1, -1):
                    nb = np.roll(IDX, s, ax); nbm = np.roll(mm, s, ax); nbf = np.roll(FORCED, s, ax)
                    sl = [slice(None)]*3; sl[ax] = 0 if s == 1 else -1; nbm[tuple(sl)] = False   # no wrap-around
                    far = np.abs(IDX) > np.abs(nb); tie = np.abs(IDX) == np.abs(nb)
                    bad = mm & nbm & (np.abs(IDX - nb) >= 2) & (far | tie | nbf) & ~FORCED
                    if bad.any(): IDX[bad] = np.sign(IDX[bad])*(np.abs(IDX[bad]) - 1); changed = True
            if not changed: break
    return IDX

if __name__ == "__main__":
    SRC = {"windmill": "art/final/windmill_voxels_subblocks.json", "cottage": "art/final/cottage_voxels_subblocks.json", "bonsai": "art/bonsai_t_half_sub.json"}
    ap = argparse.ArgumentParser(); ap.add_argument("subject"); ap.add_argument("--in", dest="src"); ap.add_argument("--out"); a = ap.parse_args()
    run(a.subject, a.src or SRC[a.subject], a.out or f"art/final/{a.subject}_voxels_textured.json")
