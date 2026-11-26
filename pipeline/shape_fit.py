#!/usr/bin/env python3
"""Shape-fitting voxelizer (DETAIL_DISCOVERY.md §9). Replaces subblock.py's "voxelize, then guess shapes per block" with:

  1. real-world scale: 1 block = 1 m by default (a player is 1.8 blocks tall), from meta/NAME_scale.json
  2. fit primitives to the mesh surface: planes, vertical cylinders, spheres (RANSAC on points + normals)
  3. snap them like a builder would: walls on block boundaries, heights on half blocks, roof slopes to
     1:4 ... 4:1 ratios, sphere/cylinder centres and radii on half blocks; one global grid offset puts the walls on block edges
  4. rebuild a 1/R-block occupancy field: inside each primitive's band the analytic surface replaces the
     (soft, low-poly) mesh; where two primitives meet, the corner is resolved as their CSG intersection or union,
     whichever agrees with the mesh
  5. pick each block's shape against that field from measured vanilla geometry (assets/.../models/block):
     full, slab (8/16) and quarter slab (3/16 = trapdoor), the same two thicknesses vertical, stairs (straight + inner/outer
     corners, bottom/top), walls (post 8/16, arms 6/16 x 14/16) and fences (post 4/16, two 2/16 bars), with Minecraft's
     auto-connection rules applied afterwards (walls<->walls, fences<->fences, both -> full faces; wall post drops on straight runs)

usage: python shape_fit.py NAME [--mesh out/NAME_lowpoly.glb] [--bpm 1.0] [--R 8] [--no-fit] [--tag shapefit]
writes art/NAME_<tag>.json (voxel JSON; 's' = shape, absent = full block) and out/NAME_<tag>_report.json"""
import argparse, json, math, os, time
import numpy as np, trimesh
from scipy import ndimage
from scipy.spatial import cKDTree
import mc_render, scorer, fal_shape

SIDES = ("north", "east", "south", "west")
DIRV = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
OPP = {"north": "south", "south": "north", "east": "west", "west": "east"}
QUARTER = 3/16     # trapdoor thickness (template_trapdoor_bottom: 0..3)

# ---------------------------------------------------------------- shapes (measured vanilla geometry)
def boxes01(s):
    """block-space boxes (x0,y0,z0,x1,y1,z1) in 0..1 for a shape dict (None/full = whole block)"""
    t = (s or {"type": "full"})["type"]
    if t == "full": return [(0, 0, 0, 1, 1, 1)]
    if t == "slab":
        k = s["size"]; return [(0, 0, 0, 1, k, 1)] if s["align"] == "bottom" else [(0, 1-k, 0, 1, 1, 1)]
    if t == "vslab":
        k = s["size"]
        return [{"west": (0, 0, 0, k, 1, 1), "east": (1-k, 0, 0, 1, 1, 1), "north": (0, 0, 0, 1, 1, k), "south": (0, 0, 1-k, 1, 1, 1)}[s["align"]]]
    if t == "stairs": return mc_render.stair_boxes(s)
    if t == "wall": return mc_render.connect_boxes("wall", {**{d: s[d] for d in SIDES}, "up": "true" if s["up"] else "false"})
    if t == "fence": return mc_render.connect_boxes("fence", {d: "true" if s[d] else "false" for d in SIDES})
    raise ValueError(t)

def raster(bxs, R):
    """coverage of an R^3 block grid by boxes (exact, via a 16^3 sub-raster)"""
    S = 16; g = np.zeros((S, S, S), bool)
    for x0, y0, z0, x1, y1, z1 in bxs:
        g[round(x0*S):round(x1*S), round(y0*S):round(y1*S), round(z0*S):round(z1*S)] = True
    f = S // R
    return g.reshape(R, f, R, f, R, f).mean((1, 3, 5)).astype(np.float32)

def template_shapes():
    S = [{"type": "full"}]
    for size in (0.5, QUARTER):
        for al in ("bottom", "top"): S.append({"type": "slab", "size": size, "align": al})
        for al, ax in (("west", "x"), ("east", "x"), ("north", "z"), ("south", "z")): S.append({"type": "vslab", "size": size, "axis": ax, "align": al})
    for half in ("bottom", "top"):
        for f in SIDES:
            for sh in ("straight", "inner_left", "inner_right", "outer_left", "outer_right"):
                S.append({"type": "stairs", "facing": f, "half": half, "shape": sh})
    for mask in range(16):
        arms = {d: bool(mask >> i & 1) for i, d in enumerate(SIDES)}
        S.append({"type": "wall", **{d: ("low" if v else "none") for d, v in arms.items()}, "up": True})
        S.append({"type": "fence", **arms})
    S.append({"type": "wall", "north": "low", "south": "low", "east": "none", "west": "none", "up": False})
    S.append({"type": "wall", "east": "low", "west": "low", "north": "none", "south": "none", "up": False})
    return S

def penalty(s):
    """complexity cost in 1/512-block cells: a shape must beat the plain block/air by this much"""
    t = s["type"]
    if t == "full": return 0
    if t == "slab": return 3 if s["size"] == 0.5 else 6
    if t == "vslab": return 4 if s["size"] == 0.5 else 8
    if t == "stairs": return 4 if s["shape"] == "straight" else 6
    return 10 if t == "wall" else 12

# ---------------------------------------------------------------- primitives
class Prim:
    """kind: plane (n, d: n.p = d) | sphere (c, r) | vcyl (c=(cx, cz), r). sign=+1: phi<0 is inside."""
    def __init__(self, kind, **k): self.kind = kind; self.__dict__.update(k); self.sign = 1.0
    def phi(self, P):
        if self.kind == "plane": v = P @ self.n - self.d
        elif self.kind == "sphere": v = np.linalg.norm(P - self.c, axis=1) - self.r
        else: v = np.hypot(P[:, 0] - self.c[0], P[:, 2] - self.c[1]) - self.r
        return self.sign * v
    def normal(self, P):
        if self.kind == "plane": return np.broadcast_to(self.n, P.shape)
        if self.kind == "sphere": v = P - self.c
        else: v = np.stack([P[:, 0] - self.c[0], np.zeros(len(P)), P[:, 2] - self.c[1]], 1)
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    def desc(self):
        f = lambda a: [round(float(x), 3) for x in np.atleast_1d(a)]
        if self.kind == "plane": return {"kind": "plane", "n": f(self.n), "d": round(float(self.d), 3), "snap": self.snap}
        return {"kind": self.kind, "c": f(self.c), "r": round(float(self.r), 3), "snap": self.snap}

def inliers(p, P, N, eps, cosang):
    return (np.abs(p.phi(P)) < eps) & (np.abs((N * p.normal(P)).sum(1)) > cosang)

def largest_component(P, mask):
    """largest 26-connected patch (1-block cells) of the masked points"""
    idx = np.flatnonzero(mask)
    if len(idx) == 0: return mask
    c = np.floor(P[idx]).astype(int); c -= c.min(0); g = np.zeros(c.max(0) + 1, bool); g[tuple(c.T)] = True
    lab, k = ndimage.label(g, np.ones((3, 3, 3)))
    pl = lab[tuple(c.T)]; best = np.bincount(pl).argmax() if k > 1 else 1
    out = np.zeros_like(mask); out[idx[pl == best]] = True; return out

def refine(p, P):
    if p.kind == "plane":
        ctr = P.mean(0); n = np.linalg.svd(P - ctr, full_matrices=False)[2][-1]
        if n @ p.n < 0: n = -n
        return Prim("plane", n=n, d=float(n @ ctr))
    if p.kind == "sphere":
        A = np.c_[2*P, np.ones(len(P))]; b = (P**2).sum(1); x = np.linalg.lstsq(A, b, rcond=None)[0]
        c = x[:3]; return Prim("sphere", c=c, r=float(math.sqrt(max(x[3] + c @ c, 1e-6))))
    Q = P[:, [0, 2]]; A = np.c_[2*Q, np.ones(len(Q))]; b = (Q**2).sum(1); x = np.linalg.lstsq(A, b, rcond=None)[0]
    c = x[:2]; return Prim("vcyl", c=c, r=float(math.sqrt(max(x[2] + c @ c, 1e-6))))

def candidates(P, N, tree, rng, k=250):
    """minimal-sample candidates using normals: plane = 1 point, sphere / vertical cylinder = 2 nearby points"""
    m = len(P); out = []
    for i in rng.integers(0, m, k): out.append(Prim("plane", n=N[i], d=float(N[i] @ P[i])))
    I = rng.integers(0, m, 2*k)
    nb = tree.query(P[I], k=min(48, m))[1]; J = nb[np.arange(len(I)), rng.integers(1, nb.shape[1], len(I))] if m > 1 else I
    for i, j in zip(I[:k], J[:k]):            # sphere: closest point of the two normal lines
        a, b, n1, n2 = P[i], P[j], N[i], N[j]; w = a - b; B = n1 @ n2; den = 1 - B*B
        if den < 1e-3: continue
        t = (B*(n2 @ w) - (n1 @ w))/den; s = ((n2 @ w) - B*(n1 @ w))/den
        c1, c2 = a + t*n1, b + s*n2
        if np.linalg.norm(c1 - c2) > 0.5: continue
        c = (c1 + c2)/2; r = (np.linalg.norm(a - c) + np.linalg.norm(b - c))/2
        if 1.5 < r < 40: out.append(Prim("sphere", c=c, r=float(r)))
    for i, j in zip(I[k:], J[k:]):            # vertical cylinder: 2D normal-line intersection in xz
        if abs(N[i, 1]) > 0.3 or abs(N[j, 1]) > 0.3: continue
        a, b = P[i, [0, 2]], P[j, [0, 2]]; n1, n2 = N[i, [0, 2]], N[j, [0, 2]]
        n1 = n1/np.linalg.norm(n1); n2 = n2/np.linalg.norm(n2); M = np.c_[n1, -n2]
        if abs(np.linalg.det(M)) < 0.05: continue
        t, s = np.linalg.solve(M, b - a); c = a + t*n1; r = (np.linalg.norm(a - c) + np.linalg.norm(b - c))/2
        if 0.75 < r < 30: out.append(Prim("vcyl", c=c, r=float(r)))
    return out

def score_candidates(cands, P, N, eps, cosang, chunk=64):
    """inlier counts of many candidates at once (same test as inliers(), vectorised over candidates)"""
    out = np.zeros(len(cands), int)
    for kind in ("plane", "sphere", "vcyl"):
        ix = [i for i, c in enumerate(cands) if c.kind == kind]
        for j in range(0, len(ix), chunk):
            cs = [cands[i] for i in ix[j:j+chunk]]
            if kind == "plane":
                Nc = np.stack([c.n for c in cs]); d = np.array([c.d for c in cs])
                ok = (np.abs(P @ Nc.T - d) < eps) & (np.abs(N @ Nc.T) > cosang)
            elif kind == "sphere":
                C = np.stack([c.c for c in cs]); r = np.array([c.r for c in cs])
                V = P[:, None, :] - C[None]; L = np.linalg.norm(V, axis=2)
                ok = (np.abs(L - r) < eps) & (np.abs((N[:, None, :]*V).sum(2))/(L + 1e-9) > cosang)
            else:
                C = np.stack([c.c for c in cs]); r = np.array([c.r for c in cs])
                vx = P[:, None, 0] - C[None, :, 0]; vz = P[:, None, 2] - C[None, :, 1]; L = np.hypot(vx, vz)
                ok = (np.abs(L - r) < eps) & (np.abs(N[:, None, 0]*vx + N[:, None, 2]*vz)/(L + 1e-9) > cosang)
            out[ix[j:j+chunk]] = ok.sum(0)
    return out

def fit_primitives(P, N, eps=0.22, ang=22, min_pts=40, max_prims=150, seed=0, log=print):
    rng = np.random.default_rng(seed); cosang = math.cos(math.radians(ang))
    remaining = np.ones(len(P), bool); prims, fails = [], 0
    while len(prims) < max_prims and remaining.sum() > max(200, 0.03*len(P)) and fails < 4:
        ridx = np.flatnonzero(remaining); Pr, Nr = P[ridx], N[ridx]
        sub = rng.choice(len(Pr), min(12000, len(Pr)), replace=False)
        cands = candidates(Pr, Nr, cKDTree(Pr), rng)
        best = {}
        for c, sc in zip(cands, score_candidates(cands, Pr[sub], Nr[sub], eps, cosang)):   # batched (was one inliers() call per candidate)
            if sc > best.get(c.kind, (0, None))[0]: best[c.kind] = (sc, c)
        if not best: fails += 1; continue
        top = max(v[0] for v in best.values())
        kind = "plane" if "plane" in best and best["plane"][0] >= 0.6*top else max(best, key=lambda k: best[k][0])
        p = best[kind][1]
        for _ in range(2):                    # inliers -> connected patch -> least-squares refit
            m = largest_component(Pr, inliers(p, Pr, Nr, eps, cosang))
            if m.sum() < min_pts: break
            q = refine(p, Pr[m])
            if q.kind != "plane" and (q.r > 45 or q.r < 0.75): break
            p = q
        m = largest_component(Pr, inliers(p, Pr, Nr, eps, cosang))
        if m.sum() < min_pts: fails += 1; continue
        fails = 0; p.idx = ridx[m]; prims.append(p); remaining[p.idx] = False
    log(f"  {len(prims)} primitives, {100*(1-remaining.mean()):.1f}% of surface explained "
        f"({', '.join(f'{k}:{sum(q.kind == k for q in prims)}' for k in ('plane', 'vcyl', 'sphere'))})")
    return prims

# ---------------------------------------------------------------- snapping (builder-friendly values)
SLOPES = [1/8, 1/6, 1/5, 1/4, 1/3, 1/2, 2/3, 1, 3/2, 2, 3, 4]
# plan directions a builder can draw cleanly: axis, 45 deg, and the 1:2, 1:3, 2:3 step lines (integer a:b)
PLAN_DIRS = sorted({(sa*a, sb*b) for a, b in ((1, 0), (0, 1), (1, 1), (1, 2), (2, 1), (1, 3), (3, 1), (2, 3), (3, 2))
                    for sa in (1, -1) for sb in (1, -1)})
def snap_half_pref_int(v):
    return float(round(v)) if abs(v - round(v)) < 0.3 else round(v*2)/2
def snap_azimuth(h):
    """nearest drawable plan direction (a, b) for unit horizontal vector h=(x, z), or None"""
    a = math.atan2(h[1], h[0]); best = None
    for d in PLAN_DIRS:
        e = abs((math.atan2(d[1], d[0]) - a + math.pi) % (2*math.pi) - math.pi)
        tol = math.radians(10 if 0 in d or abs(d[0]) == abs(d[1]) else 6)
        if e < tol and (best is None or e < best[0]): best = (e, d)
    return best and best[1]

def snap(p, P, N):
    """snapped copy of p if it still fits its own inliers (mean |phi| < 0.45 block, normals within 15 deg)"""
    q = None
    if p.kind == "plane":
        n = p.n
        if abs(n[1]) > 0.95:                                      # floor / ledge / flat roof: half-block heights
            sy = math.copysign(1, n[1]); y0 = round(2*float(P[:, 1].mean()))/2; q = Prim("plane", n=np.array([0, sy, 0.]), d=y0*sy, snap="horizontal")
        else:
            h = np.array([n[0], n[2]]); hn = np.linalg.norm(h); ab = snap_azimuth(h/hn)
            if ab is not None:
                L = math.hypot(*ab); hx, hz = ab[0]/L, ab[1]/L; axis = 0 in ab
                if abs(n[1]) < 0.2:                               # wall: on a block-corner lattice line a*x + b*z = k
                    nn = np.array([hx, 0, hz]); u = float(nn @ P.mean(0))*L
                    u = (snap_half_pref_int(u) if len(P) < 300 else float(round(u))) if axis else round(u)   # big walls: whole blocks
                    q = Prim("plane", n=nn, d=u/L, snap="wall" if axis else f"wall {abs(ab[0])}:{abs(ab[1])}")
                else:                                             # roof slope: rise/run from the stair/slab ratios
                    tan = hn/abs(n[1]); s = min(SLOPES, key=lambda v: abs(math.log(v/tan)))
                    if abs(math.log(s/tan)) < 0.3:
                        sy = math.copysign(1, n[1]); a = math.atan(s)
                        nn = np.array([hx*math.sin(a), sy*math.cos(a), hz*math.sin(a)])
                        c0 = float(nn @ P.mean(0))/nn[1]; dd = (round(2*c0)/2)*nn[1]   # plane height at x=z=0 on a half block
                        q = Prim("plane", n=nn, d=dd, snap=f"slope {s:.3g}" + ("" if axis else f" plan {abs(ab[0])}:{abs(ab[1])}"))
    elif p.kind == "sphere":
        q = Prim("sphere", c=np.round(p.c*2)/2, r=round(p.r*2)/2, snap="half-block centre/radius")
    else:
        q = Prim("vcyl", c=np.round(p.c*2)/2, r=round(p.r*2)/2, snap="half-block centre/radius")
    if q is None: p.snap = None; return p
    ok = np.abs(q.phi(P)).mean() < 0.45 and np.median(np.abs((N*q.normal(P)).sum(1))) > math.cos(math.radians(15))
    if not ok: p.snap = None; return p
    q.idx = p.idx; return q

def orient(p, P, N):
    """sign so that phi<0 is inside (mesh normals point out)"""
    p.sign = 1.0
    if np.mean((N*p.normal(P)).sum(1)) < 0: p.sign = -1.0

def grid_offset(prims, P):
    """translation (x, z) putting the axis-aligned walls (weighted by support) on block boundaries"""
    t = np.zeros(3)
    for ax in (0, 2):
        vals, w = [], []
        for p in prims:
            if p.kind == "plane" and abs(p.n[ax]) > 0.97: vals.append(p.d*np.sign(p.n[ax])); w.append(len(p.idx))
        if vals:
            ang = 2*math.pi*np.array(vals); z = (np.array(w)*np.exp(1j*ang)).sum(); t[ax] = -(np.angle(z)/(2*math.pi))
    return t

# ---------------------------------------------------------------- occupancy
def mesh_occupancy(mesh, shape, R, close=2):
    """1/R-block solid occupancy of a (leaky) mesh already in block coordinates (cell i covers [i/R, (i+1)/R))"""
    # surface cells: barycentric samples spaced <= 1 cell on every face (same criterion as trimesh's subdivide-based
    # voxelized(), whose vertices are rounded to the grid), without the slow repeated edge subdivision
    V = (mesh.vertices - 0.5/R)*R; T = V[mesh.faces]                 # in cell units, shifted like the old code
    L = np.linalg.norm(T - np.roll(T, 1, axis=1), axis=2).max(1); K = np.maximum(1, np.ceil(2*L)).astype(int)
    o = np.zeros(shape, bool); hi = np.array(shape) - 1
    for k in np.unique(K):
        tri = T[K == k]; i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij"); keep = i + j <= k
        B = np.stack([i[keep], j[keep], k - i[keep] - j[keep]], 1)/k        # (m, 3) barycentric
        step = max(1, 2_000_000//len(B))
        for c in range(0, len(tri), step):
            idx = np.round(np.einsum("mb,fbd->fmd", B, tri[c:c + step]).reshape(-1, 3)).astype(np.int64)   # = floor(cell + 0.5)
            idx = idx[np.all((idx >= 0) & (idx <= hi), 1)]; o[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    o = o | ndimage.binary_erosion(ndimage.binary_fill_holes(ndimage.binary_dilation(o, iterations=close)), iterations=close)
    for y in range(o.shape[1]):                 # open-bottom shells: per-slice ring fill
        sl = o[:, y, :]; o[:, y, :] = sl | ndimage.binary_erosion(ndimage.binary_fill_holes(ndimage.binary_dilation(sl, iterations=close)), iterations=close)
    return o

def regularise(O, prims, P, R, band=0.6, log=print):
    """replace the mesh occupancy by the snapped primitives inside their support bands; corners -> CSG op chosen by the mesh"""
    shape = np.array(O.shape); bc = int(math.ceil(band*R)); all_i, all_phi, all_p = [], [], []
    for k, p in enumerate(prims):
        c = np.floor(P[p.idx]*R).astype(int); lo = np.maximum(c.min(0) - bc - 1, 0); hi = np.minimum(c.max(0) + bc + 2, shape)
        if np.any(hi <= lo): continue
        g = np.zeros(hi - lo, bool); cc = c - lo; ok = np.all((cc >= 0) & (cc < hi - lo), 1); g[tuple(cc[ok].T)] = True
        sup = ndimage.distance_transform_edt(~g) <= bc
        ii = np.argwhere(sup) + lo; ph = p.phi((ii + 0.5)/R); keep = np.abs(ph) < band
        ii, ph = ii[keep], ph[keep]
        all_i.append(np.ravel_multi_index(ii.T, O.shape)); all_phi.append(ph.astype(np.float32)); all_p.append(np.full(len(ii), k, np.int32))
    if not all_i: return O.copy(), {}
    I = np.concatenate(all_i); PH = np.concatenate(all_phi); PI = np.concatenate(all_p)
    o = np.lexsort((np.abs(PH), I)); I, PH, PI = I[o], PH[o], PI[o]
    first = np.r_[True, I[1:] != I[:-1]]; f_idx = np.flatnonzero(first)
    has2 = np.zeros(len(f_idx), bool); has2[:-1] = (f_idx[1:] - f_idx[:-1]) > 1
    if len(f_idx): has2[-1] = (len(I) - f_idx[-1]) > 1
    cell = I[f_idx]; ph1, p1 = PH[f_idx], PI[f_idx]
    ph2 = np.where(has2, PH[np.minimum(f_idx + 1, len(I) - 1)], np.nan); p2 = np.where(has2, PI[np.minimum(f_idx + 1, len(I) - 1)], -1)
    F = O.copy().ravel(); Of = O.ravel(); near = ndimage.binary_dilation(O, iterations=3).ravel()
    single = ~has2
    F[cell[single & (ph1 >= 0)]] = False                                   # carve mesh bulges
    s_in = single & (ph1 < 0); F[cell[s_in & near[cell]]] = True           # fill dents, but never grow far past the mesh
    agree = has2 & ((ph1 < 0) == (ph2 < 0)); F[cell[agree]] = ph1[agree] < 0
    conf = has2 & ~agree; stats = {"cells_single": int(single.sum()), "cells_agree": int(agree.sum()), "cells_corner": int(conf.sum())}
    if conf.any():
        a, b = np.minimum(p1[conf], p2[conf]), np.maximum(p1[conf], p2[conf]); key = a.astype(np.int64)*100000 + b
        inter = np.maximum(ph1[conf], ph2[conf]) < 0; uni = np.minimum(ph1[conf], ph2[conf]) < 0; truth = Of[cell[conf]]
        uk, inv = np.unique(key, return_inverse=True)
        ag_i = np.bincount(inv, inter == truth, len(uk)); ag_u = np.bincount(inv, uni == truth, len(uk))
        use_inter = (ag_i >= ag_u)[inv]; F[cell[conf]] = np.where(use_inter, inter, uni)
        stats["corner_pairs"] = int(len(uk)); stats["corner_pairs_intersection"] = int((ag_i >= ag_u).sum())
    F = F.reshape(O.shape)
    lab, k = ndimage.label(F); sz = np.bincount(lab.ravel()); sz[0] = 0
    F = F & (sz >= R**3)[lab]                                              # drop floaters smaller than one block
    log(f"  regularised: {stats}")
    return F, stats

# ---------------------------------------------------------------- per-block shapes
def match_blocks(F, R, pen_scale=1.0):
    W, H, D = (np.array(F.shape)//R)
    B = F[:W*R, :H*R, :D*R].reshape(W, R, H, R, D, R).transpose(0, 2, 4, 1, 3, 5).reshape(W, H, D, R**3)
    frac = B.mean(-1); cells = {}
    full = frac >= 0.985
    for p in np.argwhere(full): cells[tuple(p)] = None
    mixed = np.argwhere((frac > 0.02) & ~full)
    S = template_shapes(); T = np.stack([raster(boxes01(s), R).ravel() for s in S])
    pen = np.array([penalty(s) for s in S], np.float32)*pen_scale*(R/8)**3
    Tn = T.sum(1)
    # stairs only where the height changes AND the plan changes; slabs only where height changes; vertical slabs only where plan changes
    ty = [s["type"] for s in S]
    need_v = np.array([t in ("stairs", "slab") for t in ty]); need_h = np.array([t in ("stairs", "vslab") for t in ty])
    for i in range(0, len(mixed), 4096):
        ch = mixed[i:i+4096]; O = B[tuple(ch.T)].astype(np.float32); On = O.sum(1)
        E = On[:, None] + Tn[None] - 2*O @ T.T + pen[None]
        Ob = O.reshape(-1, R, R, R) > 0.5                                   # [x, y, z]
        vvar = (Ob.any(2) & ~Ob.all(2)).mean((1, 2))                         # (x,z) columns mixed along y
        hvar = (Ob.any((1, 3)) & ~Ob.all((1, 3))).mean(1)                    # y layers mixed in plan
        E[np.ix_(vvar < 0.15, need_v)] = np.inf; E[np.ix_(hvar < 0.15, need_h)] = np.inf
        best = E.argmin(1); bE = E[np.arange(len(ch)), best]
        for p, b, e, on in zip(ch, best, bE, On):
            if on <= e: continue                                         # air is cheaper
            cells[tuple(p)] = None if S[b]["type"] == "full" else dict(S[b])
    return cells, (W, H, D), frac

def heightfield_pass(cells, frac, prims, P, N, log=print):
    """Upward-facing slopes and curves (roof planes, domes) the way builders lay them: one top per block column at the
    snapped primitive's height, rounded to half a block (x.5 -> bottom slab), and a stair (facing uphill) where the column
    drops a full block downhill; Minecraft's neighbour rule gives the inner/outer corners. Flat roofs and walls are already exact."""
    from subblock import stair_shape
    W, H, D = frac.shape; claims = {}
    for k, p in enumerate(prims):
        if p.kind == "vcyl" or (p.kind == "plane" and (abs(p.n[1]) > 0.95 or abs(p.n[1]) < 0.2)): continue
        up = N[p.idx, 1] > 0.35
        if up.sum() < 20: continue
        Pi = P[p.idx][up]; col = np.floor(Pi[:, [0, 2]]).astype(int)
        uc, inv = np.unique(col, axis=0, return_inverse=True); inv = inv.ravel()
        ymean = np.bincount(inv, Pi[:, 1]) / np.bincount(inv)
        for (X, Z), ym in zip(uc, ymean):
            x, z = X + 0.5, Z + 0.5
            if p.kind == "plane":
                h = (p.d - p.n[0]*x - p.n[2]*z) / p.n[1]
            else:
                dd = (x - p.c[0])**2 + (z - p.c[2])**2
                if dd > p.r**2: continue
                h = p.c[1] + math.sqrt(p.r**2 - dd)
            if abs(h - ym) > 1.5: continue
            c = claims.get((X, Z))
            if c is None or abs(h - ym) < c[1]: claims[(X, Z)] = (h, abs(h - ym), k)
    tops, skipped = {}, 0
    for (X, Z), (h, _, _) in claims.items():                          # only where the field's own surface agrees
        col = frac[X, :, Z]; occ = np.flatnonzero(col > 0.02)
        near = occ[np.abs(occ + 0.5 - h) < 2.5] if len(occ) else occ
        if len(near) == 0: skipped += 1; continue
        ft = near.max() + col[near.max()]
        if abs(ft - h) > 0.75: skipped += 1; continue
        tops[(X, Z)] = round(2*h)/2
    for (X, Z), t in tops.items():
        yt = int(math.ceil(t)) - 1
        c = (X, yt + 1, Z)
        if c in cells and cells[c] is not None and cells[c]["type"] not in ("wall", "fence") and frac[c] < 0.5: del cells[c]   # shaped clutter above
        if 0 <= yt < H: cells[(X, yt, Z)] = {"type": "slab", "size": 0.5, "align": "bottom"} if t != int(t) else None
    stairs = {}
    for (X, Z), t in tops.items():
        if t != int(t): continue
        drop = {d: t - tops[(X+dx, Z+dz)] for d, (dx, dz) in DIRV.items() if (X+dx, Z+dz) in tops}
        down = [d for d, v in drop.items() if v >= 1]
        if not down: continue
        ups = [OPP[d] for d in down if drop.get(OPP[d], 0) <= 0]       # uphill side: opposite neighbour not lower (or absent)
        if not ups: continue
        f = max(ups, key=lambda u: drop.get(OPP[u], 0) - drop.get(u, 0)); stairs[(X, int(t) - 1, Z)] = (f, "bottom")
    for pos, st in stairs.items():
        cells[pos] = {"type": "stairs", "facing": st[0], "half": "bottom", "shape": stair_shape(pos, st, stairs)}
    log(f"  heightfield: {len(tops)} columns ({skipped} skipped: field disagrees) from {len({k for _, _, k in claims.values()})} sloped/curved primitives, {len(stairs)} stairs")
    return cells, {"columns": len(tops), "skipped": skipped, "stairs": len(stairs)}

MIRROR = {"east": "west", "west": "east"}
def mirror_shape(s, axis):
    """shape dict mirrored across an x (axis 0) or z (axis 2) plane"""
    if not s: return s
    sw = MIRROR if axis == 0 else {"north": "south", "south": "north"}; s = dict(s); t = s["type"]
    if t == "stairs":
        s["facing"] = sw.get(s["facing"], s["facing"])
        if s["shape"] != "straight": s["shape"] = s["shape"].replace("left", "R").replace("right", "left").replace("R", "right")
    elif t == "vslab": s["align"] = sw.get(s["align"], s["align"])
    elif t in ("wall", "fence"):
        a, b = list(sw); s[a], s[b] = s[b], s[a]
    return s

def symmetrise(cells, frac, log=print):
    """detect mirror planes (x and z) on the block occupancy; if the model is mirror-symmetric (IoU > 0.9), copy the half
    that agrees better with the regularised field onto the other half (shapes mirrored)"""
    occ = frac > 0.5; info = {}
    for axis in (0, 2):
        n = occ.shape[axis]; best = (0, None)
        for c2 in range(n - 6, n + 7):                                 # mirror plane at c2/2 (block units)
            idx = c2 - 1 - np.arange(n); ok = (idx >= 0) & (idx < n)
            a = np.take(occ, np.flatnonzero(ok), axis); b = np.take(occ, idx[ok], axis)
            v = (a & b).sum() / max((a | b).sum(), 1)
            if v > best[0]: best = (v, c2)
        info["xz"[axis // 2]] = {"iou": round(float(best[0]), 3), "plane": best[1] / 2}
        if best[0] < 0.9: continue
        c2 = best[1]
        have = np.zeros(occ.shape, bool)
        for k in cells: have[k] = True
        v = np.arange(n); low = 2*v + 1 < c2; high = 2*v + 1 > c2
        bad = np.moveaxis(have != occ, axis, 0).reshape(n, -1).sum(1)
        keep_low = bad[low].sum() <= bad[high].sum(); new = {}
        for k, sh in cells.items():
            w = k[axis]
            if 2*w + 1 == c2: new[k] = sh; continue
            if (2*w + 1 < c2) != keep_low: continue
            new[k] = sh; m = list(k); m[axis] = c2 - 1 - w; new[tuple(m)] = mirror_shape(sh, axis)
        cells = {k: x for k, x in new.items() if all(0 <= k[i] < occ.shape[i] for i in range(3))}
        info["xz"[axis // 2]]["applied"] = "low half" if keep_low else "high half"
    log(f"  symmetry: {info}")
    return cells, info

def sturdy_face(s, toward):
    """does a neighbour with shape s present a full face toward direction `toward` (from the neighbour's point of view)?"""
    if s is None: return True
    t = s["type"]
    if t == "stairs": return s["facing"] == toward and s["shape"] in ("straight", "inner_left", "inner_right")
    if t == "vslab": return s["align"] == toward
    return False

def prune_slivers(cells):
    """walls/fences glued to a solid neighbour (full block, slab, stair) are mesh slivers (a bulge left outside the snapped wall), not posts:
    drop them unless they belong to a horizontal run of walls/fences (a vertical stack glued to a wall is a pilaster sliver)"""
    drop = []
    for (x, y, z), s in cells.items():
        if not s or s["type"] not in ("wall", "fence"): continue
        nbs = [(x+dx, y, z+dz) for dx, dz in DIRV.values()]
        glued = any(nb in cells and (cells[nb] is None or cells[nb]["type"] not in ("wall", "fence")) for nb in nbs)
        run = any(isinstance(cells.get(nb), dict) and cells[nb]["type"] == s["type"] for nb in nbs)
        if glued and not run: drop.append((x, y, z))
    for k in drop: del cells[k]
    return cells

def connect(cells):
    """Minecraft auto-connection for walls and fences (and the wall post / tall-arm rules)"""
    for (x, y, z), s in cells.items():
        if not s or s["type"] not in ("wall", "fence"): continue
        for d in SIDES:
            dx, dz = DIRV[d]; nb = (x+dx, y, z+dz); c = False
            if nb in cells:
                n = cells[nb]
                c = (n is not None and n["type"] == s["type"]) or sturdy_face(n, OPP[d])
            if s["type"] == "fence": s[d] = c
            else: s[d] = "low" if c else "none"
    for (x, y, z), s in cells.items():
        if not s or s["type"] != "wall": continue
        above = cells.get((x, y+1, z), "air"); conn = [d for d in SIDES if s[d] != "none"]
        straight = len(conn) == 2 and OPP[conn[0]] == conn[1]
        post_above = isinstance(above, dict) and above["type"] == "wall" and above.get("up")
        s["up"] = bool(not straight or post_above or (above is None))
        for d in conn:
            if above is None or (isinstance(above, dict) and above["type"] == "wall" and above.get(d, "none") != "none"): s[d] = "tall"
    return cells

# ---------------------------------------------------------------- metrics
def raster_model(cells, size, R):
    W, H, D = size; G = np.zeros((W*R, H*R, D*R), bool); cache = {}
    for (x, y, z), s in cells.items():
        k = json.dumps(s, sort_keys=True)
        if k not in cache: cache[k] = raster(boxes01(s), R) >= 0.5
        G[x*R:(x+1)*R, y*R:(y+1)*R, z*R:(z+1)*R] |= cache[k]
    return G

def surface_cells(G):
    return G & ~ndimage.binary_erosion(np.pad(G, 1))[1:-1, 1:-1, 1:-1]

def chamfer(A_pts, B_pts):
    """mean / p90 symmetric surface distance between two point sets (same units)"""
    da = cKDTree(B_pts).query(A_pts)[0]; db = cKDTree(A_pts).query(B_pts)[0]
    return {"mesh_to_model_mean": round(float(da.mean()), 3), "mesh_to_model_p90": round(float(np.percentile(da, 90)), 3),
            "model_to_mesh_mean": round(float(db.mean()), 3), "model_to_mesh_p90": round(float(np.percentile(db, 90)), 3)}

def iou(a, b): return float((a & b).sum() / max((a | b).sum(), 1))

# ---------------------------------------------------------------- main
def sheet_aspect_fix(mesh, n, tag, log=print):
    """per-axis stretch so the mesh's front (x:y) and top (x:z) proportions match the ortho drawing (thin spikes such as
    finials/minarets removed by a morphological opening before taking bounding boxes). Returns (kx, kz) applied to x, z."""
    from PIL import Image
    def bbox_aspect(m):
        r = max(2, int(0.03*max(m.shape))); m = ndimage.binary_opening(m, iterations=r)
        ys, xs = np.nonzero(m); return (xs.max() - xs.min() + 1)/(ys.max() - ys.min() + 1)
    sheet = {v: np.asarray(Image.open(f"ortho/{n}{tag}_{v}.png").convert("L")) < 235 for v in ("front", "top")}
    p = mesh.extents.max()/95; G = mesh.voxelized(p).fill().matrix
    front = G.any(2).T[::-1]; top = G.any(1).T                       # [y, x] and [z, x]
    kx = bbox_aspect(sheet["front"])/bbox_aspect(front)              # x relative to y
    kz = kx*bbox_aspect(top)/bbox_aspect(sheet["top"])                # z from the plan's x:z
    kx, kz = float(np.clip(kx, 0.6, 1.6)), float(np.clip(kz, 0.6, 1.6))
    log(f"  drawing proportions: stretch x*{kx:.3f}, z*{kz:.3f} (y fixed)")
    mesh.apply_scale([kx, 1.0, kz]); return kx, kz

def painted_colours(n_stem, mesh_path, ctr, rot, stretch, s, translate, path=None):
    """colour block centres from the painted model (art/<stem>_rendered_toned.json: ortho-painted + toned to the photo, the
    48-grid voxelisation of the same mesh) instead of the raw mesh texture; None if that model does not exist"""
    import vox
    path = path or f"art/{n_stem}_rendered_toned.json"
    if not os.path.exists(path): return None
    sc = trimesh.load(mesh_path); m0 = sc.to_geometry() if isinstance(sc, trimesh.Scene) else sc
    d48, occ48, col48, _ = vox.load(path, seed=0)
    p48 = m0.extents.max()/(max(d48["size"]) - 1); o48 = m0.voxelized(p48).transform[:3, 3]
    surf48 = occ48 & ~ndimage.binary_erosion(np.pad(occ48, 1))[1:-1, 1:-1, 1:-1]
    surf48 &= col48.sum(-1) > 0                      # pure black = never painted (unseen in every view): take the nearest painted voxel
    _, si = ndimage.distance_transform_edt(~surf48, return_indices=True)
    w = (ctr - translate)/s; w[:, 0] /= stretch[0]; w[:, 2] /= stretch[1]                     # undo scale, offsets and stretch
    Rm = trimesh.transformations.rotation_matrix(-rot, [0, 1, 0])[:3, :3]; w = w @ Rm.T         # undo the y rotation
    j = np.clip(np.round((w - o48)/p48).astype(int), 0, np.array(occ48.shape) - 1)
    k = si[:, j[:, 0], j[:, 1], j[:, 2]]
    return col48[k[0], k[1], k[2]].astype(float)

def load_scale(n, mesh_ext):
    """meta/NAME_scale.json: {"length_m": longest horizontal side, ...}; falls back to 40 m"""
    p = f"art/final/meta/{n}_scale.json"
    sc = json.load(open(p)) if os.path.exists(p) else {"length_m": 40.0, "source": "default (no meta/NAME_scale.json)"}
    return sc, sc["length_m"] / max(mesh_ext[0], mesh_ext[2])

def run(n, mesh_path=None, bpm=1.0, R=8, fit=True, tag="shapefit", log=print, height=True, sym=True, sheet=None):
    t0 = time.time(); mesh_path = mesh_path or f"out/{n}_lowpoly.glb"
    if not os.path.exists(mesh_path) and os.path.exists(f"art/final/meta/{n}_mesh.json"):   # re-download the recorded mesh (no new generation)
        import urllib.request; os.makedirs(os.path.dirname(mesh_path) or ".", exist_ok=True)
        urllib.request.urlretrieve(json.load(open(f"art/final/meta/{n}_mesh.json"))["url"], mesh_path)
    sc = trimesh.load(mesh_path); mesh = sc.to_geometry() if isinstance(sc, trimesh.Scene) else sc
    # 1. orientation: rotate about y so the dominant wall directions are the x/z axes
    fn, fa = mesh.face_normals, mesh.area_faces; vert = np.abs(fn[:, 1]) < 0.3
    th = np.arctan2(fn[vert, 2], fn[vert, 0]); rot = float(np.angle((fa[vert]*np.exp(4j*th)).sum())/4)
    if abs(rot) < math.radians(1): rot = 0.0
    Rm = trimesh.transformations.rotation_matrix(rot, [0, 1, 0]); mesh.apply_transform(Rm)
    stretch = sheet_aspect_fix(mesh, n, sheet, log) if sheet else (1.0, 1.0)
    # 2. scale: metres -> blocks
    scale_info, m_per_unit = load_scale(n, mesh.extents); s = m_per_unit*bpm
    mesh.apply_scale(s); t1 = -mesh.bounds[0] + [1, 0, 1]; mesh.apply_translation(t1)
    log(f"{n}: rotate {math.degrees(rot):.1f} deg, {scale_info['length_m']} m -> {s:.2f} blocks per mesh unit, extents {np.round(mesh.extents, 1)} blocks")
    sp, scol, fi = fal_shape.surface_colours(mesh, int(min(400000, 16*mesh.area)), seed=0)
    N = mesh.face_normals[fi]
    prims, rstats, shift = [], {}, np.zeros(3)
    if fit:
        prims = fit_primitives(sp, N, log=log)
        shift = grid_offset(prims, sp); mesh.apply_translation(shift); sp = sp + shift
        for p in prims:
            if p.kind == "plane": p.d = float(p.d + p.n @ shift)
            elif p.kind == "sphere": p.c = p.c + shift
            else: p.c = p.c + shift[[0, 2]]
        prims = [snap(p, sp[p.idx], N[p.idx]) for p in prims]
        for p in prims: orient(p, sp[p.idx], N[p.idx])
        log(f"  grid offset {np.round(shift, 2)}; snapped {sum(p.snap is not None for p in prims)}/{len(prims)}")
    size = tuple(int(math.ceil(v)) + 1 for v in mesh.bounds[1])
    O = mesh_occupancy(mesh, tuple(v*R for v in size), R)
    F, rstats = regularise(O, prims, sp, R, log=log) if fit else (O, {})
    cells, size, frac = match_blocks(F, R)
    hstats = {}
    if fit:
        if height: cells, hstats = heightfield_pass(cells, frac, prims, sp, N, log=log)
        if sym: cells, sym = symmetrise(cells, frac, log=log)
        else: sym = {}
    cells = connect(prune_slivers(cells))
    # colour: nearest coloured surface sample to the block centre
    keys = np.array(list(cells.keys())); ctr = keys + 0.5
    stem = os.path.basename(mesh_path)[:-4]
    col = painted_colours(stem, mesh_path, ctr, rot, stretch, s, t1 + shift)
    colour_src = f"art/{stem}_rendered_toned.json" if col is not None else "mesh texture"
    if col is None: col = scol[cKDTree(sp).query(ctr)[1]]
    pal, _ = scorer.kmeans_palette(col, k=32); lab = ((col[:, None]-pal[None])**2).sum(-1).argmin(1)
    pk = [f"c{i}" for i in range(len(pal))]
    vox = []
    for (x, y, z), l in zip(map(tuple, keys), lab):
        v = {"x": int(x), "y": int(y), "z": int(z), "c": pk[l]}; sh = cells[(x, y, z)]
        if sh: v["s"] = sh
        vox.append(v)
    d = {"name": f"{n}_{tag}", "size": list(map(int, size)), "camera": {"azim": 35, "elev": 20},
         "palette": {k: "#%02x%02x%02x" % tuple(np.clip(c, 0, 255).astype(int)) for k, c in zip(pk, pal)}, "voxels": vox,
         "scale": {"blocks_per_metre": bpm, **scale_info}, "colour_source": colour_src, "transform": {"rotate_y_rad": rot, "drawing_stretch_xz": stretch, "scale": s, "translate_after_scale": list(map(float, t1 + shift)), "note": "block = (Ry(rot) @ mesh_point)*scale + translate"},
         "format_note": "voxel 's' = shape (absent = full block): slab{size 0.5|0.1875,align} vslab{size,axis,align} stairs{facing,half,shape} "
                        "wall{north..west: none|low|tall, up} fence{north..west: bool}; geometry = vanilla models (shape_fit.boxes01)"}
    open(f"art/{n}_{tag}.json", "w").write(json.dumps(d))
    # metrics: everything in metres (blocks / bpm)
    G = raster_model(cells, size, R); Gs = np.argwhere(surface_cells(G))/R
    cnt = {}
    for sh in cells.values():
        k = "full" if sh is None else sh["type"] + ("" if sh["type"] not in ("slab", "vslab") else ("_half" if sh["size"] == 0.5 else "_quarter")) \
            + ("" if sh["type"] != "stairs" else ("" if sh["shape"] == "straight" else "_corner"))
        cnt[k] = cnt.get(k, 0) + 1
    rep = {"name": n, "tag": tag, "fit": fit, "size_blocks": list(map(int, size)), "blocks": len(cells), "by_shape": cnt,
           "pct_shaped": round(100*sum(v for k, v in cnt.items() if k != "full")/len(cells), 1),
           "occupancy_iou_vs_mesh": round(iou(G, O[:G.shape[0], :G.shape[1], :G.shape[2]]), 3),
           "occupancy_iou_vs_regularised": round(iou(G, F[:G.shape[0], :G.shape[1], :G.shape[2]]), 3),
           "surface_distance_m_vs_mesh": {k: round(v/bpm, 3) for k, v in chamfer(sp[np.random.default_rng(0).choice(len(sp), min(60000, len(sp)), replace=False)], Gs).items()},
           "regularise": rstats, "heightfield": hstats, "symmetry": sym, "primitives": [p.desc() | {"support_pts": int(len(p.idx))} for p in prims], "seconds": round(time.time() - t0, 1)}
    json.dump(rep, open(f"out/{n}_{tag}_report.json", "w"), indent=1)
    log(f"  {len(cells)} blocks, size {size}, shaped {rep['pct_shaped']}%: {cnt}")
    log(f"  IoU vs mesh {rep['occupancy_iou_vs_mesh']}, surface distance (m) {rep['surface_distance_m_vs_mesh']}  [{rep['seconds']}s]")
    return d, rep

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--mesh"); ap.add_argument("--bpm", type=float, default=1.0)
    ap.add_argument("--R", type=int, default=8); ap.add_argument("--no-fit", action="store_true"); ap.add_argument("--tag")
    ap.add_argument("--no-height", action="store_true"); ap.add_argument("--no-sym", action="store_true")
    ap.add_argument("--sheet", help="ortho sheet tag (e.g. _v2): stretch the mesh to the drawing's proportions")
    a = ap.parse_args(); run(a.name, a.mesh, a.bpm, a.R, not a.no_fit, a.tag or ("shapefit_nofit" if a.no_fit else "shapefit"),
                             height=not a.no_height, sym=not a.no_sym, sheet=a.sheet)
