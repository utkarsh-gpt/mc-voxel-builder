#!/usr/bin/env python3
"""Geometric-detail metrics for Minecraft builds (DETAIL_DISCOVERY.md P3). The rubric in scorer.py only measures colour
detail; these measure what builders do with shape: partial blocks, overhangs (cornices, eaves, hoods), the detail block
vocabulary, hollowness, and (optionally) agreement with a reference schematic.
Input: art/final/*_mc_blocks.json or any Sponge v2 .schem (read with a small built-in NBT reader).
usage: python detail_metrics.py MODEL [MODEL ...] [--ref REF.schem] [--json out.json]
Target band = the hand-built Little Hagia Sophia benchmark (39x24x34), see TARGET."""
import argparse, collections, gzip, json, struct, sys
import numpy as np

# Little Hagia Sophia (Skyman0), measured with this file. Building subjects should land near these.
TARGET = {"pct_surface_nonfull": 26.6, "pct_upside_down_stairs": 8.5, "pct_overhang": 19.4, "blockstates": 109, "hollowness": 88.0}
PLANTS = {"short_grass", "tall_grass", "fern", "dandelion", "poppy", "azure_bluet", "oxeye_daisy", "cornflower", "rose_bush", "lilac", "peony"}
KW = [("stairs", "stairs"), ("slab", "slab"), ("_wall", "wall"), ("fence_gate", "fence_gate"), ("fence", "fence"), ("trapdoor", "trapdoor"), ("door", "door"),
      ("pane", "pane"), ("iron_bars", "bars"), ("_bars", "bars"), ("button", "button"), ("pressure_plate", "plate"), ("carpet", "carpet"), ("sign", "sign"),
      ("banner", "banner"), ("torch", "torch"), ("lantern", "lantern"), ("chain", "chain"), ("end_rod", "rod"), ("lightning_rod", "rod"), ("ladder", "ladder"),
      ("glass", "glass"), ("leaves", "leaves")]
def shape_of(bid):
    b = bid.replace("minecraft:", "")
    if b in PLANTS: return "plant"
    for k, s in KW:
        if k in b: return s
    return "full"

# ---------- loading ----------
def _nbt(b):
    p = [0]
    def r(n): s = b[p[0]:p[0]+n]; p[0] += n; return s
    def u(f): return struct.unpack(">" + f, r(struct.calcsize(">" + f)))[0]
    def s(): return r(u("H")).decode("utf8", "replace")
    def pl(t):
        if t in (1, 2, 3, 4, 5, 6): return u("bhiqfd"[t-1])
        if t == 7: return r(u("i"))
        if t == 8: return s()
        if t == 9: et = u("b"); return [pl(et) for _ in range(u("i"))]
        if t == 10:
            d = {}
            while (tt := u("b")): k = s(); d[k] = pl(tt)
            return d
        if t == 11: return [u("i") for _ in range(u("i"))]
        if t == 12: return [u("q") for _ in range(u("i"))]
        raise ValueError(t)
    t = u("b"); s(); return pl(t)
def _varints(bs):
    out, v, sh = [], 0, 0
    for c in bs:
        v |= (c & 0x7F) << sh
        if c & 0x80: sh += 7
        else: out.append(v); v, sh = 0, 0
    return out
def _parse_state(st):
    bid, _, pr = st.partition("[")
    return bid.replace("minecraft:", ""), (dict(kv.split("=") for kv in pr.rstrip("]").split(",")) if pr else {})
def cells_of(src):
    """{(x,y,z): (id, props)} from an mc_blocks dict/path or a .schem path; plus 'size' via size_of()."""
    if isinstance(src, str) and src.endswith(".schem"):
        root = _nbt(gzip.open(src).read()); root = root.get("Schematic", root)
        W, L = root["Width"], root["Length"]; pal = {v: k for k, v in root["Palette"].items()}; out = {}
        for i, pid in enumerate(_varints(root["BlockData"])):
            st = pal[pid]
            if st.split("[")[0].endswith(("air", "cave_air", "void_air")): continue
            out[(i % W, i // (W*L), (i // W) % L)] = _parse_state(st)
        return out
    d = json.load(open(src)) if isinstance(src, str) else src
    return {(v["x"], v["y"], v["z"]): (d["palette"][v["b"]]["id"], d["palette"][v["b"]].get("props", {})) for v in d["voxels"]}

# ---------- metrics ----------
N6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
def metrics(cells):
    c = {p: v for p, v in cells.items() if shape_of(v[0]) != "plant"}
    if not c: return {}
    surf = [p for p in c if any((p[0]+a, p[1]+b, p[2]+d) not in c for a, b, d in N6)]
    sh = {p: shape_of(v[0]) for p, v in c.items()}
    fams = collections.Counter(sh.values())
    ups = sum(1 for p, (bid, pr) in c.items() if sh[p] == "stairs" and pr.get("half") == "top")
    y0 = min(p[1] for p in c)
    over = sum(1 for p in surf if p[1] > y0 + 1 and (p[0], p[1]-1, p[2]) not in c)
    states = {(bid, tuple(sorted(pr.items()))) for bid, pr in c.values()}
    xs, ys, zs = zip(*c)
    m = {"size": [max(xs)-min(xs)+1, max(ys)-min(ys)+1, max(zs)-min(zs)+1], "blocks": len(c), "surface": len(surf),
         "hollowness": round(100*len(surf)/len(c), 1),
         "pct_surface_nonfull": round(100*sum(1 for p in surf if sh[p] != "full")/len(surf), 1),
         "pct_upside_down_stairs": round(100*ups/len(surf), 1), "pct_overhang": round(100*over/len(surf), 1),
         "blockstates": len(states), "block_ids": len({bid for bid, _ in c.values()}),
         "shape_families": dict(fams.most_common()), "detail_vocab": sorted(k for k in fams if k not in ("full", "slab", "stairs"))}
    # 0..100 closeness to the benchmark band (geometric mean of per-metric ratios, capped at 1)
    ratios = [min(1.0, m[k]/TARGET[k]) for k in ("pct_surface_nonfull", "pct_upside_down_stairs", "pct_overhang")]
    m["detail_score"] = round(100*float(np.prod([max(r, 0.02) for r in ratios]))**(1/3), 1)
    return m

def _occ(cells):
    c = [p for p, v in cells.items() if shape_of(v[0]) not in ("plant",)]
    a = np.array(c); a -= a.min(0); o = np.zeros(a.max(0) + 1, bool); o[tuple(a.T)] = True; return o
def _resample(o, shape):
    idx = [np.minimum((np.arange(n)*o.shape[i]/n).astype(int), o.shape[i]-1) for i, n in enumerate(shape)]
    return o[np.ix_(*idx)]
def compare(cells, ref_cells):
    """Occupancy agreement after normalising to the reference box. Tries 4 yaw rotations x mirror and keeps the best
    (pipeline fronts are +z, hand builds face anywhere). Returns 3D IoU and silhouette IoUs (front/side/top)."""
    R = _occ(ref_cells); O = _occ(cells); best = None
    for k in range(4):
        for mirror in (False, True):
            o = np.rot90(O, k, axes=(0, 2))
            if mirror: o = o[::-1]
            o = _resample(o, R.shape)
            iou = float((o & R).sum()/(o | R).sum())
            sil = [float((o.any(a) & R.any(a)).sum()/(o.any(a) | R.any(a)).sum()) for a in (2, 0, 1)]
            if best is None or iou + np.mean(sil) > best["iou3d"] + np.mean(best["sil"]): best = {"iou3d": iou, "sil": sil, "rot90": k, "mirror": mirror}
    best["iou3d"] = round(best["iou3d"], 3); best["sil"] = dict(zip(("front", "side", "top"), [round(s, 3) for s in best["sil"]]))
    best["ref_size"] = list(R.shape); best["model_size_before_resample"] = list(O.shape)
    return best

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("models", nargs="+"); ap.add_argument("--ref"); ap.add_argument("--json"); a = ap.parse_args()
    ref = cells_of(a.ref) if a.ref else None; res = {}
    if ref: res["REF " + a.ref] = metrics(ref)
    for path in a.models:
        cl = cells_of(path); r = metrics(cl)
        if ref: r["vs_ref"] = compare(cl, ref)
        res[path] = r
    keys = ["size", "blocks", "hollowness", "pct_surface_nonfull", "pct_upside_down_stairs", "pct_overhang", "blockstates", "block_ids", "detail_vocab", "detail_score"]
    for p, r in res.items():
        print(p); print("   " + "  ".join(f"{k}={r.get(k)}" for k in keys))
        if "vs_ref" in r: print("   vs ref:", r["vs_ref"])
    print("target band (Little Hagia Sophia):", TARGET)
    if a.json: json.dump(res, open(a.json, "w"), indent=1)
