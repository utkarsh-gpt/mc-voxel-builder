"""Stamp only the blueprint parts into the voxel model as geometry - strict, no judge, no colour.

The Hyper3D mesh gives the masses (nave, towers, roof, apse) but loses the openings and fine parts. This script takes the
oriented voxels (orient.py: facade on +z) and, for each part listed in the blueprint, cuts or builds only that part's own
shape, at its count, with the geometry its `built_as` names:

    set_back  carved into the wall (relative to a wall plane, so a rough mesh wall still gets a clean recess)
    open      carved all the way through, or a gap between solid bars
    proud     solid added outside the wall plane
    outline   changes the silhouette (gable, spike, battlement teeth)

Positions come from the drawings (ortho/cathedral_v3_*.png) mapped onto landmarks measured in the voxels (tower columns,
roof ridge, wall planes), so the same code fits any mesh of this building.

    python stamp_parts.py [--glb /tmp/exp/bpA3.glb --grid 120 --out out/cathedral_stamped]
"""
import argparse, json, os, sys
import numpy as np
from scipy import ndimage

PAD = 5
FILL = 7      # how far behind a wall plane a stamp fills solid (the wall thickness), so nothing fills the whole interior


# ------------------------------------------------------------------ faces: a = to the viewer's right, b = up, n = outward
class Face:
    def __init__(s, occ, name):
        s.name = name
        if name == "front": V = occ                               # a = x,        n = z
        elif name == "back": V = occ[::-1, :, ::-1]               # a = W-1-x,    n = D-1-z
        elif name == "right": V = occ.transpose(2, 1, 0)[::-1]    # a = D-1-z,    n = x
        elif name == "left": V = occ.transpose(2, 1, 0)[:, :, ::-1]  # a = z,     n = W-1-x
        s.V = V; s.A, s.B, s.N = V.shape
        s.a, s.b = np.meshgrid(np.arange(s.A) + 0.5, np.arange(s.B) + 0.5, indexing="ij")

    def surf(s):
        """outermost occupied n per (a, b), -1 where empty"""
        has = s.V.any(2); last = s.N - 1 - np.argmax(s.V[:, :, ::-1], 2)
        return np.where(has, last, -1)

    def ref_band(s, b0, b1, smooth=3):
        """wall plane per a: median surface over the band b0..b1 (ignores empty cells)"""
        S = s.surf()[:, int(b0):int(b1) + 1].astype(float); S[S < 0] = np.nan
        with np.errstate(all="ignore"): r = np.nanmedian(S, 1)
        r = np.where(np.isnan(r), np.nanmedian(r), r)
        return ndimage.median_filter(r, size=smooth, mode="nearest").round().astype(int)

    # --- masks (cells whose centre is inside the shape)
    def rect(s, a0, a1, b0, b1): return (s.a >= a0) & (s.a < a1) & (s.b >= b0) & (s.b < b1)

    def disc(s, ac, bc, r): return (s.a - ac) ** 2 + (s.b - bc) ** 2 <= r * r

    def pointed(s, ac, w, b0, b1, head=None):
        """window / arch: straight sides up to the spring, then a pointed head; b0..b1 full height, w wide"""
        head = min(0.8 * w, 0.6 * (b1 - b0)) if head is None else head; spring = b1 - head
        t = np.clip((s.b - spring) / max(head, 1e-6), 0, 1)
        hw = np.where(s.b <= spring, w / 2, (w / 2) * (1 - t ** 1.6))
        return (s.b >= b0) & (s.b < b1) & (np.abs(s.a - ac) < hw)

    def tri(s, ac, b_base, b_apex, half):
        t = np.clip((s.b - b_base) / max(b_apex - b_base, 1e-6), 0, 1)
        return (s.b >= b_base) & (s.b < b_apex) & (np.abs(s.a - ac) <= half * (1 - t))

    # --- operations relative to a wall plane (ref: int or array over a)
    def _ref(s, ref, a): return int(ref if np.isscalar(ref) else ref[a])

    def carve(s, m, ref, depth):
        """set_back: remove everything outside plane-depth, keep solid behind it"""
        for a, b in zip(*np.nonzero(m)):
            cut = max(0, s._ref(ref, a) - depth + 1); s.V[a, b, cut:] = False; s.V[a, b, max(0, cut - FILL):cut] = True

    def proud(s, m, ref, k):
        """proud: solid out to plane+k (and solid behind it)"""
        for a, b in zip(*np.nonzero(m)):
            r = s._ref(ref, a); top = min(s.N, r + k + 1); s.V[a, b, max(0, r - FILL):top] = True

    def shave(s, m, plane):
        """remove everything outside the plane (no filling)"""
        for a, b in zip(*np.nonzero(m)): s.V[a, b, s._ref(plane, a) + 1:] = False

    def flat(s, m, plane):
        """flatten a region to exactly the plane: solid up to it, nothing beyond"""
        for a, b in zip(*np.nonzero(m)): p = s._ref(plane, a); s.V[a, b, max(0, p - FILL):p + 1] = True; s.V[a, b, p + 1:] = False


# ------------------------------------------------------------------ landmarks measured from the voxels
def runs(v):
    x = np.nonzero(v)[0]
    if not len(x): return []
    out, st, p = [], x[0], x[0]
    for q in x[1:]:
        if q != p + 1: out.append((int(st), int(p))); st = q
        p = q
    out.append((int(st), int(p))); return out


def landmarks(occ):
    W, H, D = occ.shape; L = {"W": W, "H": H, "D": D}
    ys = np.nonzero(occ.any((0, 2)))[0]; L["tip"] = int(ys.max())
    pz = np.array([np.nonzero(occ[:, :, z].any(0))[0].max() if occ[:, :, z].any() else -1 for z in range(D)])
    mid = pz[D // 4: D // 2]; L["ridge"] = int(np.median(mid))                      # nave roof ridge: flat part of the profile
    zs = np.nonzero(occ.any((0, 1)))[0]; L["z_min"], L["z_max"] = int(zs.min()), int(zs.max())
    hi = np.nonzero(pz >= L["ridge"] + 8)[0]; hi = hi[hi > D // 2]
    L["z_tr"], L["z_tf"] = int(hi.min()), int(hi.max())                             # towers: rear and front z (at the tip side)
    yq = L["ridge"] + 10; r = [q for q in runs(occ[:, yq, :].any(1)) if q[1] - q[0] >= 3]
    L["ta"], L["tb"] = r[0], r[-1]                                                  # tower x ranges
    wt = np.array([sum(q[1] - q[0] + 1 for q in runs(occ[:, y, :].any(1))) for y in range(H)])
    tw = np.array([max([q[1] - q[0] + 1 for q in runs(occ[:, y, :].any(1))] or [0]) for y in range(H)])
    ymax_tw = int(tw[L["ridge"] + 2: L["ridge"] + 25].max())
    L["b_para"] = int(max(y for y in range(L["ridge"], L["tip"]) if tw[y] >= 0.85 * ymax_tw))   # tower top before the spire
    Fr = Face(occ, "front"); S = Fr.surf()
    reg = S[L["ta"][0]: L["tb"][1] + 1, int(0.3 * L["ridge"]): int(0.85 * L["ridge"])]
    L["zf"] = int(np.median(reg[reg >= 0]))                                          # facade plane
    # side walls at mid nave: aisle wall (outer) and clerestory wall (inner)
    zm = int(0.5 * (L["z_min"] + L["z_tr"]))
    xmax = np.array([np.nonzero(occ[:, y, zm])[0].max() if occ[:, y, zm].any() else -1 for y in range(H)])
    aisle = np.nonzero(xmax >= xmax[2] - 4)[0]; L["b_aisle"] = int(aisle[aisle < L["ridge"]].max())
    return L


# ------------------------------------------------------------------ the parts
class Stamper:
    def __init__(s, occ, L):
        s.occ, s.L = occ, L; s.log = {}; s.mask = {}; s.before = occ.copy(); s.inst = {}
        s.fr, s.bk, s.rt, s.lf = (Face(occ, n) for n in ("front", "back", "right", "left"))
        ta, tb = L["ta"], L["tb"]
        s.xk = ([160, 215, 275, 330], [ta[0], ta[1] + 1, tb[0], tb[1] + 1])           # drawing px -> a on the front
        s.yk = ([418, 200, 62], [1, L["ridge"], L["tip"]])
        # wall planes on the long sides (a is per face), measured on the unmodified model
        bl = L["b_aisle"]
        s.ref_a = {f: F.ref_band(max(3, int(0.2 * bl)), int(0.8 * bl)) for f, F in (("right", s.rt), ("left", s.lf), ("back", s.bk))}
        s.ref_c = {f: F.ref_band(bl + 8, bl + 24) for f, F in (("right", s.rt), ("left", s.lf), ("back", s.bk))}

    def fx(s, px):
        kp, ka = s.xk
        if px < kp[0]: return ka[0] + (px - kp[0]) * (ka[1] - ka[0]) / (kp[1] - kp[0])
        if px > kp[-1]: return ka[-1] + (px - kp[-1]) * (ka[-1] - ka[-2]) / (kp[-1] - kp[-2])
        return float(np.interp(px, kp, ka))

    def fy(s, py): return float(np.interp(-py, [-v for v in s.yk[0]], s.yk[1]))
    def fw(s, pw): return pw * (s.L["tb"][1] - s.L["ta"][0]) / 170.0                                  # px width -> voxels (towers + centre = 170 px)
    def note(s, part, **kw): s.log.setdefault(part, []).append(kw)

    def reg(s, part, F, mask, ref, kind, key, **kw):
        """remember one instance of a part (its defining cells, the wall plane it was cut against, and the geometry it must have)"""
        s.inst.setdefault(part, []).append({"face": F, "mask": mask.copy(), "ref": ref if np.isscalar(ref) else np.array(ref), "kind": kind, "key": key, **kw})

    def track(s, part, fn):
        """run fn and remember which cells it removed (set_back / open) and added (proud / outline) for the parts map"""
        a = s.occ.copy(); fn(); s.mask.setdefault(part, np.zeros_like(a, np.uint8))
        s.mask[part] |= ((a & ~s.occ) | (~a & s.occ)).astype(np.uint8)

    # ---------------- masses
    def plinth(s):
        o = s.occ; base = o[:, :2, :].any(1)
        grown = ndimage.binary_dilation(base, structure=np.ones((5, 3), bool))          # a little wider on every side, more along the long sides
        o[:, :2, :] |= grown[:, None, :]
        s.note("plinth", count=1)

    def west_front(s):
        """strict: only flatten the facade to one plane so openings can be cut into it. No invented piers, string courses or teeth."""
        L, F = s.L, s.fr; zf = L["zf"]; ta, tb = L["ta"], L["tb"]
        top = np.where((F.a >= ta[0]) & (F.a < ta[1] + 1) | (F.a >= tb[0]) & (F.a < tb[1] + 1), L["b_para"], 0).astype(float)
        gap = (F.a >= ta[1] + 1) & (F.a < tb[0])
        gab = F.tri((ta[1] + 1 + tb[0]) / 2, s.fy(240), L["ridge"] + 1, (tb[0] - ta[1] - 1) / 2)
        mask = ((top > 0) & (F.b < top) & (F.b >= 1)) | (gap & (F.b >= 1) & (F.b < s.fy(240))) | gab
        F.flat(mask, zf); s.fr_mask = mask
        s.note("west_front", count=1, plane=zf)

    # ---------------- west front features
    def portal(s, ac, w, b_arch, b_gable, kind, depth):
        """strict: one recessed pointed opening and its triangular gable. No medallion, no tip spike, no extra rings."""
        F, zf = s.fr, s.L["zf"]
        s.track(kind, lambda: (
            F.carve(F.pointed(ac, w, 1, b_arch), zf, depth),
            F.proud(F.tri(ac, b_arch - 1, b_gable, w * 0.55) & ~F.rect(ac - 1, ac + 1, b_arch - 1, b_arch + 2), zf, 1)))
        if kind == "portal_main":
            F.proud(F.rect(ac - 0.5, ac + 0.5, 1, b_arch - 4), zf, -depth + 2)   # centre post (notes: two doors)
        s.reg(kind, F, F.pointed(ac, w * 0.7, 1, b_arch - 2), zf, "set_back", round(ac, 1))
        s.reg(kind, F, F.tri(ac, b_arch + 1, b_gable - 2, w * 0.2), zf, "proud", round(ac, 1))
        s.note(kind, ac=round(ac, 1), w=round(w, 1), arch=round(b_arch, 1), gable=round(b_gable, 1))

    def portals(s):
        b = s.fy
        if "portal_main" in s.want: s.portal(s.fx(245), s.fw(54), b(355), b(322), "portal_main", 4)
        if "portal_side" in s.want:
            s.portal(s.fx(188), s.fw(32), b(372), b(344), "portal_side", 3)
            s.portal(s.fx(302), s.fw(32), b(372), b(344), "portal_side", 3)

    def gallery_arcade(s):
        """strict: the five pointed lights only. No ledge, no moulded band."""
        F, zf = s.fr, s.L["zf"]; ac = s.fx(245); w = 2; gap = 1; n = 5; tot = n * w + (n - 1) * gap; b0, b1 = s.fy(340), s.fy(318)
        def run():
            for k in range(n):
                c = ac - tot / 2 + w / 2 + k * (w + gap); F.carve(F.pointed(c, w, b0, b1, head=2.5), zf, 2)
        s.track("gallery_arcade", run); s.note("gallery_arcade", lights=n, width=w, column=gap)
        for k in range(n):
            c = ac - tot / 2 + w / 2 + k * (w + gap); s.reg("gallery_arcade", F, F.pointed(c, w, b0, b1, head=2.5), zf, "set_back", 0)

    def rose(s):
        """strict: circular recess, raised ring, hub and twelve spokes. No corner medallions, no string course."""
        F, zf = s.fr, s.L["zf"]; ac, bc = s.fx(245), s.fy(285); r = min(s.fw(27) * 1.0, (s.L["tb"][0] - s.L["ta"][1] - 1) / 2 - 1.5)
        def run():
            F.proud(F.disc(ac, bc, r + 1.6) & ~F.disc(ac, bc, r + 0.2), zf, 1)
            F.carve(F.disc(ac, bc, r), zf, 5)
            rim = F.disc(ac, bc, r) & ~F.disc(ac, bc, r - 1.0)
            hub = F.disc(ac, bc, 1.6)
            sp = np.zeros_like(rim)
            ang = np.arctan2(F.b - bc, F.a - ac); rr = np.hypot(F.a - ac, F.b - bc)
            for k in range(12):
                th = k * np.pi / 6 + np.pi / 12
                d = np.abs(np.sin(ang - th)) * rr; sp |= (d <= 0.55) & (np.cos(ang - th) > 0) & (rr <= r)
            bars = rim | hub | sp
            for a, b in zip(*np.nonzero(bars)): F.V[a, b, zf - 2 - FILL + 1:zf - 2 + 1] = True; F.V[a, b, zf - 2 + 1:] = False
        s.track("rose", run); s.note("rose", centre=(round(ac, 1), round(bc, 1)), radius=round(r, 1), spokes=12)
        s.rose_geo = (ac, bc, r)
        s.reg("rose", F, F.disc(ac, bc, r), zf, "set_back", 0); s.reg("rose", F, F.disc(ac, bc, r + 1.6) & ~F.disc(ac, bc, r + 0.2), zf, "proud", 0)

    def front_windows(s):
        """strict: pointed recess, centre mullion, sill. No outer moulding ring."""
        F, zf = s.fr, s.L["zf"]; w = 5
        def one(ac, b0, b1):
            F.carve(F.pointed(ac, w, b0, b1, head=3), zf, 2)
            F.proud(F.rect(ac - 0.5, ac + 0.5, b0, b1 - 3.5), zf - 1, 0)
            F.proud(F.rect(ac - w / 2 - 1, ac + w / 2 + 1, b0 - 1.5, b0 - 0.5), zf, 1)
        def run():
            for ac in (s.fx(188), s.fx(302)):
                one(ac, s.fy(300), s.fy(258)); one(ac, s.fy(340), s.fy(312))
        s.track("front_window", run); s.note("front_window", count=4)
        for ac in (s.fx(188), s.fx(302)):
            for (b0, b1) in ((s.fy(300), s.fy(258)), (s.fy(340), s.fy(312))):
                s.reg("front_window", F, F.pointed(ac - 1.2, 2, b0, b1 - 3, head=1), zf, "set_back", (round(ac), round(b0)))
                s.reg("front_window", F, F.rect(ac - w / 2 - 1, ac + w / 2 + 1, b0 - 1.5, b0 - 0.5), zf, "proud", (round(ac), round(b0)))

    def front_gable(s):
        """strict: three vertical slits in the gable. No tip cross."""
        F, zf = s.fr, s.L["zf"]; ac = (s.L["ta"][1] + 1 + s.L["tb"][0]) / 2; apex = s.L["ridge"]
        def run():
            F.carve(F.rect(ac - 0.5, ac + 0.5, s.fy(236), apex - 4), zf, 2)
            for d in (-3, 3): F.carve(F.rect(ac + d - 0.5, ac + d + 0.5, s.fy(236), apex - 8), zf, 2)
        s.track("front_gable", run); s.note("front_gable", slits=3)
        s.reg("front_gable", F, F.rect(ac - 0.5, ac + 0.5, s.fy(236), apex - 4), zf, "set_back", 0)
        for d in (-3, 3): s.reg("front_gable", F, F.rect(ac + d - 0.5, ac + d + 0.5, s.fy(236), apex - 8), zf, "set_back", 0)

    def balustrade(s):
        F, zf = s.fr, s.L["zf"]; ta, tb = s.L["ta"], s.L["tb"]; a0, a1 = ta[1] + 2, tb[0] - 1; b0 = s.fy(246)
        def run():
            F.proud(F.rect(a0, a1, b0, b0 + 1), zf, 1)                                        # base
            F.proud(F.rect(a0, a1, b0 + 3, b0 + 4), zf, 1)                                    # top rail
            for a in range(int(a0), int(a1), 2): F.proud(F.rect(a, a + 1, b0 + 1, b0 + 3), zf, 1)   # posts, a gap between each
            F.carve(F.rect(a0, a1, b0 + 1, b0 + 3) & ((np.floor(F.a).astype(int) - int(a0)) % 2 == 1), zf, 3)   # the gaps go deep
        s.track("gallery_balustrade", run); s.note("gallery_balustrade", posts=int((a1 - a0) // 2))
        s.reg("gallery_balustrade", F, F.rect(a0, a1, b0, b0 + 1), zf, "proud", 0)
        for a in range(int(a0), int(a1), 2):
            s.reg("gallery_balustrade", F, F.rect(a, a + 1, b0 + 1, b0 + 3), zf, "proud", 0)

    # ---------------- towers: belfry, openings, parapet
    def tower_box(s, tx):
        L, o = s.L, s.occ; b = L["b_para"] - 6
        z = np.nonzero(o[tx[0]:tx[1] + 1, b, :].any(0))[0]
        return tx[0], tx[1], int(z.min()), int(z.max())

    def belfries(s):
        """each tower's top stage: a clean square box, hollow inside with 2-thick walls; on each of the four faces two tall pointed
        openings cut through the wall (a ladder of slots: every other row of the opening stays as a slat), in a shared shallow panel"""
        L, o = s.L, s.occ; b1 = L["b_para"]; b0 = b1 - 18; cnt = [0]
        s.boxes = []
        def run():
            zr = None
            for tx in (L["ta"], L["tb"]):
                x0, x1, z0, z1 = s.tower_box(tx)
                if zr is None: zr = (z0, z1)
                z0, z1 = zr; s.boxes.append((x0, x1, z0, z1))                       # the towers are identical copies: same depth, so their openings line up
                o[x0:x1 + 1, b0:b1 + 1, z0:z1 + 1] = True
                o[x0 + 2:x1 - 1, b0 + 1:b1, z0 + 2:z1 - 1] = False
                sides = {"front": (s.fr, (x0 + x1 + 1) / 2, z1), "back": (s.bk, s.L["W"] - (x0 + x1 + 1) / 2, s.L["D"] - 1 - z0),
                         "right": (s.rt, s.L["D"] - (z0 + z1 + 1) / 2, x1), "left": (s.lf, (z0 + z1 + 1) / 2, s.L["W"] - 1 - x0)}
                for name, (F, ac, pl) in sides.items():
                    for dc in (-2.5, 2.5):
                        m = F.pointed(ac + dc, 3, b0 + 3, b1 - 1, head=2.5); slats = (np.floor(F.b).astype(int) - (b0 + 3)) % 2 == 1
                        for a_, b_ in zip(*np.nonzero(m & ~slats)): F.V[a_, b_, pl - 1:pl + 1] = False
                        s.reg("belfry_opening", F, m & ~slats, pl, "open", (tx[0], name, dc)); cnt[0] += 1
        s.track("belfry_opening", run); s.note("belfry_opening", count=cnt[0]); s.note("belfry", count=2, b0=b0, b1=b1)

    def parapets(s):
        """battlement: a corbel course one voxel proud, then a wall of square teeth with a gap between each pair round the whole top"""
        L, o = s.L, s.occ; b1 = L["b_para"]; n = [0]
        if not getattr(s, "boxes", None):
            s.boxes = [s.tower_box(tx) for tx in (L["ta"], L["tb"])]
        def run():
            for x0, x1, z0, z1 in s.boxes:
                o[x0 - 1:x1 + 2, b1 + 1, z0 - 1:z1 + 2] = True
                cells = [(x, z0) for x in range(x0, x1 + 1)] + [(x1, z) for z in range(z0 + 1, z1 + 1)] + \
                        [(x, z1) for x in range(x1 - 1, x0 - 1, -1)] + [(x0, z) for z in range(z1 - 1, z0, -1)]
                for k, (x, z) in enumerate(cells): o[x, b1 + 2:b1 + 4, z] = (k % 2 == 0)                 # tooth, gap, tooth, gap ...
                s.inst.setdefault("parapet", []).append({"kind": "ring", "cells": cells, "b": b1 + 2, "key": (x0, z0)}); n[0] += 1
        s.track("parapet", run); s.note("parapet", count=n[0])

    # ---------------- sides: nave bays
    def bay_centres(s, name, n=11):
        L = s.L; D = L["D"]; zr = L["z_tr"] - 1; ze = L["z_min"] + s.apse_len
        zc = [zr - (k + 0.5) * (zr - ze) / n for k in range(n)]
        return [(D - 1 - z) if name == "right" else z for z in zc], (zr - ze) / n

    def side(s, name):
        L = s.L; F = {"right": s.rt, "left": s.lf}[name]; suf = "" if name == "right" else "_left"
        ref_a, ref_c = s.ref_a[name], s.ref_c[name]; bl = L["b_aisle"]; ac_list, pitch = s.bay_centres(name)
        wa, wc = 5, 5; ab0, ab1 = max(4, int(0.2 * bl)), int(0.8 * bl); cb0, cb1 = bl + 9, bl + 23
        # aisle windows: pointed recess, two lights split by a mullion; a shallow outer recess around each
        def aisle():
            for ac in ac_list:
                F.carve(F.pointed(ac, wa, ab0, ab1, head=3), ref_a, 2)
                F.proud(F.rect(ac - 0.5, ac + 0.5, ab0, ab1 - 3), ref_a - 1, 0)
        def clere():
            for ac in ac_list[:-1]:
                F.carve(F.pointed(ac, wc, cb0, cb1, head=3), ref_c, 2)
                F.proud(F.rect(ac - 0.5, ac + 0.5, cb0, cb1 - 3), ref_c - 1, 0)
                F.proud(F.rect(ac - wc / 2 - 1, ac + wc / 2 + 1, cb0 - 1.5, cb0 - 0.5), ref_c, 1)
        piers = [(ac_list[k] + ac_list[k + 1]) / 2 for k in range(len(ac_list) - 1)]
        top = bl + 2; pw = 3
        def pier():
            for pc in piers:
                F.proud(F.rect(pc - pw / 2, pc + pw / 2, 1, top * 0.55), ref_a, 2); F.proud(F.rect(pc - pw / 2, pc + pw / 2, top * 0.55, top), ref_a, 1)
                F.proud(F.rect(pc - pw / 2 - 0.5, pc + pw / 2 + 0.5, top * 0.55, top * 0.55 + 1), ref_a, 2)
        def pinn():
            for pc in piers:
                for t in range(12):
                    w = 3 if t < 3 else (2 if t < 7 else 1)
                    F.proud(F.rect(pc - w / 2, pc + w / 2, top + t, top + t + 1), ref_a, 2 if t < 3 else 1)
        def fly():
            for pc in piers:
                a = int(round(pc)); n0 = int(ref_a[a]) + 1; n1 = int(ref_c[a]); b0 = top + 2; rise = 13; L_ = max(n0 - n1, 1)
                for k in range(L_ + 1):
                    n = n0 - k; b = b0 + int(round(rise * (k / L_) ** 1.0))
                    for da in (-0, 1):
                        for db in (0, 1): F.V[a + da - 0, b + db, n] = True
        if "aisle_window" + suf in s.want:
            for k, ac in enumerate(ac_list):
                s.reg("aisle_window" + suf, F, F.pointed(ac, wa, ab0, ab1, head=3), ref_a, "set_back", k)
            s.track("aisle_window" + suf, aisle); s.note("aisle_window" + suf, count=len(ac_list))
        if "clerestory_window" + suf in s.want:
            for k, ac in enumerate(ac_list[:-1]):
                s.reg("clerestory_window" + suf, F, F.pointed(ac, wc, cb0, cb1, head=3), ref_c, "set_back", k)
            s.track("clerestory_window" + suf, clere); s.note("clerestory_window" + suf, count=len(ac_list) - 1)
        if "side_buttress" + suf in s.want:
            for k, pc in enumerate(piers):
                s.reg("side_buttress" + suf, F, F.rect(pc - pw / 2, pc + pw / 2, 4, top * 0.55 - 1), ref_a, "proud", k)
            s.track("side_buttress" + suf, pier); s.note("side_buttress" + suf, count=len(piers))
        if "pinnacle" + suf in s.want:
            for k, pc in enumerate(piers):
                s.reg("pinnacle" + suf, F, F.rect(pc - 0.5, pc + 0.5, top + 7, top + 12), ref_a, "proud", k)
            s.track("pinnacle" + suf, pinn); s.note("pinnacle" + suf, count=len(piers))
        if "flying_buttress" + suf in s.want:
            for k, pc in enumerate(piers):
                a = int(round(pc)); n_mid = int(ref_c[a]) + 3
                L_ = max(int(ref_a[a]) + 1 - int(ref_c[a]), 1); k_mid = int(ref_a[a]) + 1 - n_mid
                s.inst.setdefault("flying_buttress" + suf, []).append({"kind": "arm", "face": F, "a": a, "n": n_mid, "b": top + 2 + int(round(13 * k_mid / L_)), "key": k})
            s.track("flying_buttress" + suf, fly); s.note("flying_buttress" + suf, count=len(piers))


    # ---------------- east end
    def apse(s):
        L = s.L; F = s.bk; ref_a, ref_c = s.ref_a["back"], s.ref_c["back"]; bl = L["b_aisle"]; ab0, ab1 = max(4, int(0.2 * bl)), int(0.8 * bl)
        ac = F.A / 2; xs = np.nonzero(F.V.any((1, 2)))[0]; half = (xs.max() - xs.min()) / 2
        def win():
            for d in (-0.32, 0, 0.32):
                c = ac + d * half * 2 * 0.9
                F.carve(F.pointed(c, 5, ab0, ab1, head=3), ref_a, 2)
                F.proud(F.rect(c - 0.5, c + 0.5, ab0, ab1 - 3), ref_a - 1, 0)
        top = bl + 2; zc = L["z_min"] + s.apse_len + 2
        xc_ = np.nonzero(s.occ[:, bl + 15, zc])[0]; hw = (xc_.max() - xc_.min() + 1) / 2; s.arm_len = s.xa - s.xc
        s.arm_a = [int(round(ac + (k - 3) * hw * 0.62 / 3 * 3 / 3.0)) for k in range(7)]
        def fly():
            for a in s.arm_a:
                n0 = int(ref_a[a]) + 1; L_ = s.arm_len
                for kk in range(L_ + 1):
                    n = n0 - kk; b = top + 2 + int(round(9 * kk / L_))
                    for da in (0, 1):
                        for db in (0, 1): F.V[a + da, b + db, n] = True
        if "apse_window" in s.want:
            for k, d in enumerate((-0.32, 0, 0.32)): s.reg("apse_window", F, F.pointed(ac + d * half * 2 * 0.9, 5, ab0, ab1, head=3), ref_a, "set_back", k)
            s.track("apse_window", win); s.note("apse_window", count=3)
        if "apse_flying_buttress" in s.want:
            for k, a in enumerate(s.arm_a):
                n_mid = int(ref_a[a]) + 1 - s.arm_len + 3; L_ = s.arm_len
                s.inst.setdefault("apse_flying_buttress", []).append({"kind": "arm", "face": F, "a": a, "n": n_mid, "b": top + 2 + int(round(9 * (int(ref_a[a]) + 1 - n_mid) / L_)), "key": k})
            s.track("apse_flying_buttress", fly); s.note("apse_flying_buttress", count=7)

    def prep(s):
        """strict: measure wall planes and apse length only. Do not rebuild the nave walls or invent a cornice."""
        L = s.L; s.apse_len = max(10, int(0.14 * (L["z_tr"] - L["z_min"])))
        bl = L["b_aisle"]; s.eave = bl + 25
        for name, F in (("right", s.rt), ("left", s.lf)):
            a_lo = int(F.A - L["z_tr"] if name == "right" else L["z_min"] + s.apse_len); a_hi = int(F.A - L["z_min"] - s.apse_len if name == "right" else L["z_tr"] - 1)
            Xa = int(np.median(s.ref_a[name][a_lo:a_hi])); Xc = int(np.median(s.ref_c[name][a_lo:a_hi]))
            s.xa, s.xc = Xa, Xc; s.lean = max(1, (Xa - Xc) // 2)

    def run(s, parts=None):
        """parts = set of blueprint ids to stamp. None = every id in the blueprint file. Masses that only exist as mesh
        (tower, spire, nave, roof) are never rewritten here; only listed feature/mass stamps below run."""
        want = set(parts) if parts is not None else set(json.load(open("art/final/meta/cathedral_blueprint.json"))["parts"])
        s.want = want; s.prep()
        # west_front flatten is required so openings cut into a plane; always run when any front feature is wanted
        front_feats = {"portal_main", "portal_side", "gallery_arcade", "rose", "front_window", "front_gable", "gallery_balustrade"}
        if "west_front" in want or want & front_feats: s.west_front()
        if "plinth" in want: s.plinth()
        if "portal_main" in want or "portal_side" in want: s.portals()
        if "gallery_arcade" in want: s.gallery_arcade()
        if "rose" in want: s.rose()
        if "front_window" in want: s.front_windows()
        if "front_gable" in want: s.front_gable()
        if "gallery_balustrade" in want: s.balustrade()
        if "belfry" in want or "belfry_opening" in want: s.belfries()
        if "parapet" in want: s.parapets()
        side_ids = {"aisle_window", "clerestory_window", "side_buttress", "flying_buttress", "pinnacle"}
        if want & side_ids: s.side("right")
        if want & {k + "_left" for k in side_ids}: s.side("left")
        if want & {"apse", "apse_window", "apse_flying_buttress"}: s.apse()
        return s


def pad(occ, p=PAD):
    return np.pad(occ, ((p, p), (0, p), (p, p)))


def load_voxels(path):
    d = json.load(open(path)); W, H, D = d["size"]; occ = np.zeros((W, H, D), bool)
    for v in d["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    return occ


def stamp(occ, parts=None):
    occ = pad(occ).copy(); L = landmarks(occ); S = Stamper(occ, L).run(parts=parts)
    return S.occ, S


# ------------------------------------------------------------------ checks: geometry only, read from the final voxels (no judge)
def _frac(ok): return float(np.mean(ok)) if len(ok) else 0.0


def check(S, bp):
    """per part: instances found vs the blueprint count, and how many of them really have their geometry in the final voxels"""
    o, L = S.occ, S.L; rows = {}
    for part, p in bp["parts"].items():
        want = p["count"]; ins = S.inst.get(part, []); found = ok = 0; note = ""
        if ins and ins[0].get("kind") == "arm":
            found = len(ins)
            for i in ins:
                V = i["face"].V; a, b, n = i["a"], i["b"], i["n"]
                good = V[a:a + 2, b:b + 2, n].any() and not V[a, max(0, b - 3), n]       # a solid arm, with air under it
                ok += bool(good)
        elif ins and ins[0].get("kind") == "ring":
            found = len(ins)
            for i in ins:
                occ_ring = np.array([o[x, i["b"], z] for x, z in i["cells"]]); exp = np.arange(len(occ_ring)) % 2 == 0
                good = _frac(occ_ring == exp) >= 0.9; ok += bool(good); note = f"{int(exp.sum())} teeth, {int((~exp).sum())} gaps round each top"
        elif ins:
            groups = {}
            for i in ins: groups.setdefault(i["key"], []).append(i)
            found = len(groups)
            for key, items in groups.items():
                good = True
                for i in items:
                    S_ = i["face"].surf(); m = i["mask"]
                    if not m.any(): good = False; continue
                    r = i["ref"]; refv = np.broadcast_to(np.asarray(r)[:, None] if np.ndim(r) else r, m.shape)
                    v = S_[m]; rr = refv[m]
                    if i["kind"] == "set_back": good &= _frac(v <= rr - 1) >= 0.85
                    elif i["kind"] == "proud": good &= _frac(v >= rr + 1) >= 0.85
                    elif i["kind"] == "open": good &= _frac(v == -1) >= 0.8
                ok += bool(good)
        else:
            found = None
        rows[part] = {"count": want, "found": found, "geometry_ok": ok, "built_as": p["built_as"], "note": note}
    # masses and the rose's own gaps
    if hasattr(S, "rose_geo") and "rose" in rows:
        ac, bc, r = S.rose_geo; F = S.fr; Sf = F.surf(); deep = F.disc(ac, bc, r - 1.2) & ~F.disc(ac, bc, 1.8) & (Sf <= L["zf"] - 4)
        lab, n = ndimage.label(deep); sizes = ndimage.sum(deep, lab, range(1, n + 1)); rows["rose"]["note"] = f"{int((sizes >= 2).sum())} open gaps between spokes (12 wanted), hub + rim + spokes stand at depth 2"
    yq = L["b_para"]; tw = [q for q in runs(o[:, yq, :].any(1)) if q[1] - q[0] >= 3]
    def mass(part, found, ok, note=""): rows[part].update(found=found, geometry_ok=ok, note=note)
    base = S.before[:, 0:2, :].any(1); now = o[:, 0:2, :].any(1)
    mass("plinth", 1, int(now.sum() > base.sum()), f"base footprint {int(base.sum())} -> {int(now.sum())} cells")
    if hasattr(S, "fr_mask"):
        Sv = S.fr.surf()[S.fr_mask]; mass("west_front", 1, int(_frac(Sv == L["zf"]) >= 0.5 and _frac(Sv <= L["zf"] + 1) >= 0.97), f"{int(100 * _frac(Sv == L['zf']))}% of the front on the facade plane, nothing beyond +1")
    else:
        mass("west_front", 0, 0, "not stamped")
    mass("tower", len(tw), int(len(tw) == 2), "two shafts clear of the roof")
    sp = [q for q in runs(o[:, L["tip"] - 6, :].any(1))]; mass("spire", len(sp), int(len(sp) == 2), "two pointed tips")
    boxes = getattr(S, "boxes", [])
    hol = sum(bool((~o[x0 + 3:x1 - 2, L["b_para"] - 9, z0 + 3:z1 - 2]).all()) for x0, x1, z0, z1 in boxes); mass("belfry", hol, int(hol == 2), "hollow stage with 2-thick walls" if boxes else "not stamped")
    zm = (L["z_min"] + L["z_tr"]) // 2; prof = [int(np.nonzero(o[:, :, z].any(0))[0].max()) for z in (zm - 10, zm, zm + 10)]
    mass("roof", 1, int(max(prof) - min(prof) <= 1 and prof[1] >= L["ridge"] - 1), f"straight ridge at height {prof[1]}")
    eave = getattr(S, "eave", L["b_aisle"] + 25)
    xs = np.nonzero(o[:, eave - 6, zm])[0]; xs2 = np.nonzero(o[:, 5, zm])[0]
    if len(xs) and len(xs2):
        mass("nave", 1, int((xs2.max() - xs2.min()) > (xs.max() - xs.min()) + 12), f"aisle level {xs2.max() - xs2.min() + 1} wide, clerestory {xs.max() - xs.min() + 1} wide")
    else:
        mass("nave", 1, 0, "profile empty")
    w0 = np.nonzero(o[:, 10, L["z_min"] + 3])[0]; w1 = np.nonzero(o[:, 10, min(L["z_min"] + 40, L["D"] - 1)])[0]
    if len(w0) and len(w1):
        mass("apse", 1, int((w0.max() - w0.min()) < (w1.max() - w1.min()) - 6), f"rounded end: {w0.max() - w0.min() + 1} wide at the tip, {w1.max() - w1.min() + 1} at the nave")
    else:
        mass("apse", 1, 0, "could not measure tip / nave width")
    return rows


PART_RGB = {"plinth": (150, 150, 150), "west_front": (170, 170, 170), "portal_main": (230, 90, 60), "portal_side": (240, 150, 40), "gallery_arcade": (60, 170, 230),
            "rose": (220, 40, 160), "front_window": (60, 90, 230), "front_gable": (120, 220, 80), "gallery_balustrade": (150, 90, 40), "belfry_opening": (40, 190, 150),
            "parapet": (250, 220, 40), "aisle_window": (60, 90, 230), "clerestory_window": (130, 60, 220), "side_buttress": (230, 130, 130),
            "pinnacle": (250, 250, 100), "flying_buttress": (240, 60, 60), "apse_window": (60, 90, 230), "apse_flying_buttress": (240, 60, 60)}


def parts_colour(S):
    col = np.full(S.occ.shape + (3,), 170, np.uint8)
    for part, m in S.mask.items():
        base = part.replace("_left", "")
        if base not in PART_RGB or base in ("plinth", "west_front"): continue
        mm = ndimage.binary_dilation(m.astype(bool), iterations=1) & S.occ
        col[mm] = PART_RGB[base]
    return col


def main():
    import vox
    from PIL import Image, ImageDraw
    ap = argparse.ArgumentParser(); ap.add_argument("--vox", default="/tmp/exp/A3_g120.json"); ap.add_argument("--out", default="out/cathedral_stamped")
    ap.add_argument("--parts", default=None, help="comma-separated blueprint ids to stamp (default: every id in the blueprint)")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    bp = json.load(open("art/final/meta/cathedral_blueprint.json"))
    parts = None if a.parts is None else {p.strip() for p in a.parts.split(",") if p.strip()}
    occ0 = load_voxels(a.vox); occ, S = stamp(occ0, parts=parts)
    np.save(f"{a.out}/stamped.npy", occ)
    rows = check(S, bp); json.dump(rows, open(f"{a.out}/part_checks.json", "w"), indent=1)
    flat = np.full(occ.shape + (3,), 185, np.uint8); size = 1100
    views = {"front": (0, 0, (-0.45, 0.55, 0.7)), "front_oblique": (18, 8, (-0.8, 0.5, 0.6)), "three_quarter_right": (35, 20, (-0.8, 0.5, 0.5)),
             "side_right": (300, 10, (0.2, 0.6, 0.9)), "three_quarter_left": (325, 20, (0.8, 0.5, 0.5)), "back": (180, 8, (-0.5, 0.55, -0.7))}
    for k, (az, el, l) in views.items():
        vox.render(occ, flat, az, el, size, light=l, ao=True)[0].save(f"{a.out}/{k}_grey.png")
    pc = parts_colour(S)
    for k in ("front_oblique", "three_quarter_right", "three_quarter_left", "back"):
        az, el, l = views[k]; im = vox.render(occ, pc, az, el, size, light=l, ao=True)[0]
        d = ImageDraw.Draw(im); y = 8
        for part, rgb in PART_RGB.items():
            if part in ("plinth", "west_front"): continue
            d.rectangle([8, y, 22, y + 12], fill=rgb); d.text((28, y), part, fill="black"); y += 16
        im.save(f"{a.out}/{k}_parts.png")
    # voxel json (one stone colour) for the viewer's flat format
    xs, ys, zs = np.nonzero(occ)
    json.dump({"name": "cathedral_stamped", "size": list(occ.shape), "camera": {"azim": 35, "elev": 20}, "palette": {"a": "#b9b9b9"},
               "voxels": [{"x": int(x), "y": int(y), "z": int(z), "c": "a"} for x, y, z in zip(xs, ys, zs)]}, open(f"{a.out}/cathedral_stamped_voxels.json", "w"))
    print(f"{'part':26s} {'count':>5s} {'found':>5s} {'geometry ok':>11s}  built_as")
    for k, r in rows.items(): print(f"{k:26s} {r['count']:5d} {str(r['found']):>5s} {r['geometry_ok']:11d}  {','.join(r['built_as'])}  {r['note']}")


if __name__ == "__main__":
    main()
