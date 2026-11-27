#!/usr/bin/env python3
"""Generic geometry stamping (SME-15): William Lam's stamp_parts.py primitives (f5a1ee7), with every cathedral-specific
landmark / drawing-pixel coordinate removed. Positions come from the generic feature detector (feature_detect.py boxes,
already aligned to the block grid) and the subject's parts list; the wall plane is always measured locally in the voxels.

Face   a = to the viewer's right, b = up, n = outward, for front / back / right / left (a view of the occupancy array, so
       edits write through). Masks: rect, disc, pointed, tri. Ops relative to a wall plane: carve (set_back), proud, shave,
       flat, plus open (all the way through).
built_as by feature kind (a parts-list entry may override it for the kinds it names):
       window / arched_window / round_window / rose_window / door  -> set_back   (recess 1-2 into the local wall plane,
                                                                      solid backing kept; rect / pointed / disc mask)
       arch / open_arch / arcade                                    -> open       (through the wall / pier) - only when the
                                                                      parts list names an open part or the opposite face
                                                                      shows the same opening; otherwise left as built
       buttress / pilaster / trim / hood                            -> proud      (1-2 out of the wall plane; parts boxes)
       gable / spire / battlement / chimney                         -> outline    (parts boxes: silhouette flattened to the
                                                                      wall plane; detected spires / chimneys are left to
                                                                      mc_map's protrusion builder, which already makes them)
Parts-list boxes: {"id": ..., "built_as": "proud", "boxes": {"front": [[x0, y0, x1, y1], ...]}} normalised to the drawing's
building outline (0,0 = top-left of the silhouette bbox of that view), mapped onto the face's (a, b) via the same bbox of the
voxel projection - no subject coordinates in code.

stamp(occ, features, parts) -> occ2, report, features2 (each stamped opening's rect.plane moved to the recess back, plus
"stamp": {"op", "plane_cells", "removed", "added"}) so mc_map builds frame / door / window-only glass inside the recess.

ORGANIC subjects (trees, creatures, statues: bonsai, turtle): is_organic() -> no stamping at all (no flat facade planes to
cut into, no openings); the combined runner goes straight to materials -> mc_map -> shade_gradient.
"""
import collections, json, math
import numpy as np
from scipy import ndimage

FILL = 1           # backing kept directly behind a recess (one block), never the whole interior

# ------------------------------------------------------------------ faces (William's Face, plus coordinate conversion)
class Face:
    def __init__(s, occ, name):
        s.name = name; s.W, s.H, s.D = occ.shape
        if name == "front": V = occ                                  # a = x,        n = z
        elif name == "back": V = occ[::-1, :, ::-1]                  # a = W-1-x,    n = D-1-z
        elif name == "right": V = occ.transpose(2, 1, 0)[::-1]       # a = D-1-z,    n = x
        elif name == "left": V = occ.transpose(2, 1, 0)[:, :, ::-1]  # a = z,        n = W-1-x
        s.V = V; s.A, s.B, s.N = V.shape
        s.a, s.b = np.meshgrid(np.arange(s.A) + 0.5, np.arange(s.B) + 0.5, indexing="ij")

    def xyz(s, a, b, n):
        W, D = s.W, s.D
        return {"front": (a, b, n), "back": (W - 1 - a, b, D - 1 - n), "right": (n, b, D - 1 - a), "left": (W - 1 - n, b, a)}[s.name]

    def surf(s):
        """outermost occupied n per (a, b), -1 where empty"""
        has = s.V.any(2); last = s.N - 1 - np.argmax(s.V[:, :, ::-1], 2)
        return np.where(has, last, -1)

    def ref_band(s, b0, b1, smooth=3):
        """wall plane per a: median surface over the band b0..b1 (ignores empty cells)"""
        S = s.surf()[:, int(b0):int(b1) + 1].astype(float); S[S < 0] = np.nan
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore"); r = np.nanmedian(S, 1)
        r = np.where(np.isnan(r), np.nanmedian(r), r)
        return ndimage.median_filter(r, size=smooth, mode="nearest").round().astype(int)

    def ref_local(s, m, ring=2):
        """wall plane around a mask: median surface of the ring of cells just outside it (the opening itself may already be
        dented / bumpy in the mesh), falling back to the mask's own median"""
        S = s.surf(); grown = ndimage.binary_dilation(m, iterations=ring) & ~m
        v = S[grown & (S >= 0)]
        if not len(v): v = S[m & (S >= 0)]
        return int(np.median(v)) if len(v) else None

    # --- masks (cells whose centre is inside the shape)
    def rect(s, a0, a1, b0, b1): return (s.a >= a0) & (s.a < a1) & (s.b >= b0) & (s.b < b1)
    def disc(s, ac, bc, r): return (s.a - ac) ** 2 + (s.b - bc) ** 2 <= r * r
    def pointed(s, ac, w, b0, b1, head=None):
        head = min(0.8 * w, 0.6 * (b1 - b0)) if head is None else head; spring = b1 - head
        t = np.clip((s.b - spring) / max(head, 1e-6), 0, 1)
        hw = np.where(s.b <= spring, w / 2, (w / 2) * (1 - t ** 1.6))
        return (s.b >= b0) & (s.b < b1) & (np.abs(s.a - ac) < hw)
    def tri(s, ac, b_base, b_apex, half):
        t = np.clip((s.b - b_base) / max(b_apex - b_base, 1e-6), 0, 1)
        return (s.b >= b_base) & (s.b < b_apex) & (np.abs(s.a - ac) <= half * (1 - t))

    # --- operations relative to a wall plane (ref: int or array over a); each returns (removed, added) (a, b, n) lists
    def _ref(s, ref, a): return int(ref if np.isscalar(ref) else ref[a])
    def _apply(s, a, b, keep_to, fill_from=None):
        col = s.V[a, b]; rem = [(a, b, n) for n in range(max(0, keep_to), s.N) if col[n]]
        col[max(0, keep_to):] = False; add = []
        if fill_from is not None:
            for n in range(max(0, fill_from), max(0, keep_to)):
                if not col[n]: col[n] = True; add.append((a, b, n))
        return rem, add
    def carve(s, m, ref, depth, fill=FILL):
        """set_back: remove everything outside plane-depth, keep `fill` solid blocks directly behind it"""
        R, A = [], []
        for a, b in zip(*np.nonzero(m)):
            cut = max(0, s._ref(ref, a) - depth + 1)
            if not s.V[a, b, cut:].any(): continue          # already open here (a through arch): nothing to cut, no backing
            r, ad = s._apply(a, b, cut, cut - fill); R += r; A += ad
        return R, A
    def open(s, m):
        """open: carve all the way through the model along n"""
        R = []
        for a, b in zip(*np.nonzero(m)):
            R += [(a, b, n) for n in np.nonzero(s.V[a, b])[0]]; s.V[a, b, :] = False
        return R, []
    def proud(s, m, ref, k, fill=FILL):
        A = []
        for a, b in zip(*np.nonzero(m)):
            r = s._ref(ref, a)
            for n in range(max(0, r - fill), min(s.N, r + k + 1)):
                if not s.V[a, b, n]: s.V[a, b, n] = True; A.append((a, b, n))
        return [], A
    def shave(s, m, plane):
        R = []
        for a, b in zip(*np.nonzero(m)):
            p = s._ref(plane, a); R += [(a, b, n) for n in range(p + 1, s.N) if s.V[a, b, n]]; s.V[a, b, p + 1:] = False
        return R, []
    def flat(s, m, plane, fill=FILL):
        R, A = s.shave(m, plane)
        for a, b in zip(*np.nonzero(m)):
            p = s._ref(plane, a)
            for n in range(max(0, p - fill), p + 1):
                if not s.V[a, b, n]: s.V[a, b, n] = True; A.append((a, b, n))
        return R, A

FACE_OF_OUT = {(0, 0, 1): "front", (0, 0, -1): "back", (1, 0, 0): "right", (-1, 0, 0): "left"}
OPP = {"front": "back", "back": "front", "right": "left", "left": "right"}
BUILT_AS = {"window": "set_back", "arched_window": "set_back", "round_window": "set_back", "rose_window": "set_back", "door": "set_back",
            "arch": "open", "open_arch": "open", "arcade": "open",
            "buttress": "proud", "pilaster": "proud", "trim": "proud", "hood": "proud",
            "gable": "outline", "spire": "outline", "battlement": "outline", "chimney": "outline"}
DEPTH = {"window": 1, "arched_window": 1, "round_window": 1, "rose_window": 2, "door": 1, "arcade": 2}
KEYWORDS = [("rose", "rose_window"), ("round", "round_window"), ("window", "window"), ("door", "door"), ("portal", "door"),
            ("arcade", "arcade"), ("arch", "arch"), ("buttress", "buttress"), ("pilaster", "pilaster"), ("hood", "hood"),
            ("trim", "trim"), ("gable", "gable"), ("spire", "spire"), ("battlement", "battlement"), ("chimney", "chimney"),
            ("cap", "outline")]

def part_kind(p):
    """the feature kind a parts-list entry is about: explicit stamp kind, else a keyword in its id.
    Blueprint kind 'mass' / 'feature' (specs/detailed-parts.md) is not a stamp kind, so it falls through."""
    k = p.get("kind")
    if k and k not in ("mass", "feature"): return k
    pid = (p.get("id") or "").lower()
    for kw, k in KEYWORDS:
        if kw in pid: return k
    return None

def ab_range(F, rect):
    """feature_detect rect (axis/plane/u/y in block units) -> face a-range, b-range, n of the plane"""
    u0, u1 = rect["u"]; y0, y1 = rect["y"]; W, D = F.W, F.D
    if F.name == "front": a0, a1, n = u0, u1, rect["plane"]
    elif F.name == "back": a0, a1, n = W - 1 - u1, W - 1 - u0, D - 1 - rect["plane"]
    elif F.name == "right": a0, a1, n = D - 1 - u1, D - 1 - u0, rect["plane"]
    else: a0, a1, n = u0, u1, W - 1 - rect["plane"]
    return a0, a1 + 1, y0, y1 + 1, n

def norm_box(F, box):
    """normalised drawing box [x0, y0, x1, y1] (0..1 of the drawing's building outline, y down) -> (a0, a1, b0, b1) on the face,
    using the bbox of the face's own silhouette (the same bbox feature_detect aligns the drawing to)"""
    S = F.surf(); aa, bb = np.nonzero(S >= 0)
    A0, A1, B0, B1 = aa.min(), aa.max() + 1, bb.min(), bb.max() + 1
    x0, y0, x1, y1 = box
    return A0 + x0*(A1 - A0), A0 + x1*(A1 - A0), B1 - y1*(B1 - B0), B1 - y0*(B1 - B0)

def mask_for(F, kind, a0, a1, b0, b1, arch=False):
    w, h = a1 - a0, b1 - b0
    if kind in ("rose_window", "round_window"): return F.disc((a0 + a1)/2, (b0 + b1)/2, max(w, h)/2)
    if (arch or kind in ("arched_window", "arch", "open_arch")) and w >= 2 and h >= 3:
        return F.pointed((a0 + a1)/2, w, b0, b1, head=min(w/2 + 0.5, 0.5*h))
    return F.rect(a0, a1, b0, b1)

def flat_wall_share(occ):
    """share of the four side views' silhouette pixels whose first-hit depth is constant over their 3x3 neighbourhood, i.e.
    that sit on a flat vertical wall patch. Measured (Nov 26): turtle 0.000, bonsai 0.011, windmill 0.047 (round tower),
    windmill_v2 0.121, gate 0.179, cathedral 0.190, cottage_v2 0.215, house 0.325, hagia 0.42"""
    import feature_detect as fd
    sc = []
    for v in ("front", "right", "back", "left"):
        hit, _, depth = fd.view_maps(occ, v); eq = hit.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sh = np.roll(np.roll(depth, dy, 0), dx, 1); hs = np.roll(np.roll(hit, dy, 0), dx, 1); eq &= hs & (sh == depth)
        sc.append(float(eq.sum()/max(hit.sum(), 1)))
    return float(np.mean(sc))

ORGANIC_SHARE, ORGANIC_SHARE_NO_OPENINGS = 0.03, 0.08

def is_organic(occ, features=None, parts=None):
    """organic = no flat facade to stamp. parts.json "organic": true/false wins; otherwise the flat-wall share decides:
    < 0.03 -> organic even if the detector reported 'windows' (it does on a turtle shell's plates), < 0.08 with no
    detected wall openings -> organic. Everything else is a building and gets stamped."""
    if parts and "organic" in parts: return bool(parts["organic"]), {"reason": "parts.json organic flag"}
    share = flat_wall_share(occ)
    openings = sum(1 for f in (features or []) if f.get("rect") and f["kind"] in ("window", "door", "arcade"))
    organic = share < ORGANIC_SHARE or (share < ORGANIC_SHARE_NO_OPENINGS and openings == 0)
    return organic, {"flat_wall_share": round(share, 3), "openings": openings, "reason": "auto"}

def stamp(occ, features, parts=None, log=print):
    occ = occ.copy(); W, H, D = occ.shape
    faces = {nm: Face(occ, nm) for nm in ("front", "back", "right", "left")}
    import parts_list as PL
    P = parts or {}; plist = list(PL.iter_parts(P))
    over = {}                       # feature kind -> built_as from the parts list
    listed_open = set()
    for p in plist:
        k = part_kind(p); op = PL.stamp_op(p)
        if k and op: over.setdefault(k, op)
        if k and PL.has_built(p, "open"): listed_open.add(k)
    if "arch" in over and "arcade" not in over: over["arcade"] = over["arch"]
    if "arch" in listed_open: listed_open.add("arcade")
    rep = collections.Counter(); feats2 = []
    # opposite-face confirmation for open arches: a box on the opposite face covering the same (u, y)
    def seen_opposite(f):
        r = f["rect"]
        for g in features:
            if g is f or not g.get("rect") or g["kind"] not in ("arcade", "arch", "open_arch"): continue
            if tuple(g["out"]) != tuple(-c for c in f["out"]) or g["rect"]["axis"] != r["axis"]: continue
            if min(r["u"][1], g["rect"]["u"][1]) >= max(r["u"][0], g["rect"]["u"][0]) and min(r["y"][1], g["rect"]["y"][1]) >= max(r["y"][0], g["rect"]["y"][0]): return g
        return None
    for f in features:
        f2 = json.loads(json.dumps(f))
        r = f.get("rect"); kind = f["kind"]
        if not r or tuple(f.get("out", (0, 0, 0))) not in FACE_OF_OUT: feats2.append(f2); continue
        op = over.get(kind, BUILT_AS.get(kind))
        F = faces[FACE_OF_OUT[tuple(f["out"])]]
        a0, a1, b0, b1, n0 = ab_range(F, r)
        m = mask_for(F, kind, a0, a1, b0, b1, f.get("arch"))
        if not m.any(): feats2.append(f2); continue
        ref = F.ref_local(m)
        if ref is None: feats2.append(f2); continue
        if op == "open" and not (kind in listed_open or seen_opposite(f) is not None):   # an unconfirmed arcade (one face only, no open part
            feats2.append(f2); rep[f"open_unconfirmed_left:{kind}"] += 1; continue   # listed) is left as built - never cut through
        if op in ("set_back", "set_back_deep"):
            depth = DEPTH.get(kind, 1) if op == "set_back" else 2
            R, A = F.carve(m, ref, depth)
            back = ref - depth                                       # recess back plane (n)
            plane_cells = [F.xyz(int(a), int(b), int(back)) for a, b in zip(*np.nonzero(m)) if 0 <= back < F.N and F.V[a, b, back]]
            newplane = back if F.name in ("front", "right") else ((D - 1 - back) if F.name == "back" else (W - 1 - back))
            f2["rect"] = dict(r, plane=int(newplane), plane_before=int(r["plane"]))
            f2["stamp"] = {"op": "set_back", "depth": depth, "face": F.name, "wall_plane_n": int(ref), "plane_cells": [list(map(int, c)) for c in plane_cells],
                           "removed": len(R), "added": len(A)}
            rep[f"set_back:{kind}"] += 1
        elif op == "open":
            g = seen_opposite(f)
            if g:   # a through opening is only what both faces show: cut the overlap of the two boxes, never widen one side
                gr = g["rect"]; ri = dict(r, u=[max(r["u"][0], gr["u"][0]), min(r["u"][1], gr["u"][1])], y=[max(r["y"][0], gr["y"][0]), min(r["y"][1], gr["y"][1])])
                a0, a1, b0, b1, _ = ab_range(F, ri); m = mask_for(F, kind, a0, a1, b0, b1, f.get("arch") or g.get("arch"))
            R, A = F.open(m)
            f2["stamp"] = {"op": "open", "face": F.name, "removed": len(R), "added": 0}; rep[f"open:{kind}"] += 1
        else:
            feats2.append(f2); rep[f"skipped:{kind}:{op}"] += 1; continue
        f2["stamp"]["removed_cells"] = [list(map(int, F.xyz(*c))) for c in R]; f2["stamp"]["added_cells"] = [list(map(int, F.xyz(*c))) for c in A]
        feats2.append(f2)
    # parts-list boxes (proud / outline / set_back / open from normalised drawing boxes)
    extra = []
    for p in plist:
        for view, boxes in (p.get("boxes") or {}).items():
            if view not in faces: continue
            F = faces[view]; k = part_kind(p); op = PL.stamp_op(p) or BUILT_AS.get(k)
            for box in boxes:
                a0, a1, b0, b1 = norm_box(F, box); m = mask_for(F, k, a0, a1, b0, b1)
                ref = F.ref_local(m)
                if ref is None or not m.any(): continue
                k_out = int(p.get("depth", 1))
                if op == "proud": R, A = F.proud(m, ref, k_out)
                elif op == "outline": R, A = F.flat(m, ref)
                elif op == "open": R, A = F.open(m)
                else: R, A = F.carve(m, ref, k_out)
                extra.append({"part": p["id"], "view": view, "op": op, "removed": len(R), "added": len(A),
                              "removed_cells": [list(map(int, F.xyz(*c))) for c in R], "added_cells": [list(map(int, F.xyz(*c))) for c in A]})
                rep[f"part:{p['id']}:{op}"] += 1
        if not p.get("boxes") and PL.has_built(p, "proud", "outline") and part_kind(p) not in ("spire", "chimney"):
            rep[f"part:{p['id']}:{PL.stamp_op(p)}:no_boxes"] += 1
    log("stamp", dict(rep))
    return occ, {"counts": dict(rep), "parts": extra}, feats2


def stamp_peaks(occ, peaks, log=print):
    """above-mesh peaks (feature_detect.above_mesh_peaks): rebuild each tower cap / turret / spire / chimney from its drawn
    profile. Inside the peak's box (its x range, the supporting z run, rows above its base) every voxel outside the profile is
    removed (the clipped, ragged mesh stub) and every profile cell is filled. Returns occ2, report, {cell: peak index}."""
    occ = occ.copy(); W, H, D = occ.shape; owner = {}; rep = []; shapes = {}
    for k, p in enumerate(peaks):
        prof = {tuple(c) for c in p["cells"] if 0 <= c[0] < W and 0 <= c[2] < D}
        if not prof: continue
        top = max(c[1] for c in prof)
        if top >= H:   # grow the grid upward for a peak taller than the mesh
            occ = np.concatenate([occ, np.zeros((W, top - H + 1, D), bool)], 1); H = occ.shape[1]
        x0, x1 = p["x"]; z0, z1 = p["z"]; removed = added = 0
        for x in range(x0, x1 + 1):
            for y in range(p["base_y"] + 1, H):
                for z in range(z0, z1 + 1):
                    if occ[x, y, z] and (x, y, z) not in prof: occ[x, y, z] = False; removed += 1
        for c in prof:
            if not occ[c]: occ[c] = True; added += 1
            owner[c] = k
        # slope shapes: a cell with nothing of the peak above it steps down outward (stairs facing inward = the tall back
        # toward the peak's axis), like a builder's slate cap; the 1x1 apex column stays full blocks (the finial)
        if p["built_as"] == "outline":
            xc, zc = (x0 + x1)/2, (min(c[2] for c in prof) + max(c[2] for c in prof))/2
            for (x, y, z) in prof:
                if (x, y + 1, z) in prof: continue
                if sum((x + a, y, z + b) in prof for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))) == 0: continue   # apex
                dx, dz = x - xc, z - zc
                if abs(dx) >= abs(dz) and dx != 0: f = "east" if dx < 0 else "west"
                elif dz != 0: f = "south" if dz < 0 else "north"
                else: continue
                shapes[(x, y, z)] = {"type": "stairs", "facing": f, "half": "bottom", "shape": "straight"}
        rep.append({"kind": p["kind"], "built_as": p["built_as"], "x": p["x"], "z": p["z"], "base_y": p["base_y"], "top_y": top,
                    "widths": [r[2] - r[1] + 1 for r in p["rows"]], "colour": p.get("colour"), "removed": removed, "added": added,
                    "cells": len(prof)})
        log(f"  peak {k}: {p['kind']} x {x0}..{x1} y {p['base_y'] + 1}..{top} z {z0}..{z1}: -{removed} stub +{added} -> {len(prof)} cells")
    return occ, rep, owner, shapes
