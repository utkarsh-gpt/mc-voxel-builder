#!/usr/bin/env python3
"""SME-15 combined flow: generic geometry stamping (stamp_generic.py, after William Lam's stamp_parts.py) + our colour mapping
(mc_map, window-only glass) + shadow sampling (shade_gradient: shaded ortho sheets + 3D AO/sun/eave, no photo projection).

    python run_combined.py gate house turtle [--organic] [--orient-apply] [--detect]

per subject N (writes the variant N_combined; N's own files are never touched):
  1. load art/final/N_voxels_textured.json + meta/N_texture_labels.json + meta/N_noise.json
  2. orient (William's orient.facade_flip): verdict logged; applied only with --orient-apply (a raw blueprint/hyper3d mesh;
     models built by shape_fit from the sheets are already facade-on-+z and their cached features are in that frame)
  3. features: cached meta/N_features.json, else feature_detect.detect(N, llm=False) (image-only, $0); parts: meta/N_parts.json (legacy list or parts_list.py dict schema; organic / built_as / open read through parts_list.iter_parts)
  4. organic? (--organic, parts "organic", or auto: no wall openings + non-planar sides) -> no stamping
  5. stamp_generic.stamp -> new occupancy + per-feature recess masks (rect.plane moved to the recess back)
  6. alias files art/final/N_combined_voxels_textured.json, meta/N_combined_{texture_labels,noise,features}.json
     (cells exposed / added by a cut copy colour + label from the nearest original cell)
  7. mc_map N_combined with MC_GLASS=windows -> out/combined/N_combined_mapped.json (glass only in feature-pass openings)
  8. shade_gradient on that model, sampling N's own ortho sheets (sheet_subject=N), auto zones for uncurated materials
     -> art/final/N_combined_mc_blocks.json (+ schematics)
  9. audit: glass outside stamped openings, creaking_heart, through-openings still open
Spend: $0 (no fal, no LLM: feature_detect runs with llm=False and only when no cached features exist).
"""
import argparse, collections, json, os, subprocess, sys
import numpy as np
from scipy.spatial import cKDTree
import orient, stamp_generic as SG

def load(n):
    T = json.load(open(f"art/final/{n}_voxels_textured.json")); L = json.load(open(f"art/final/meta/{n}_texture_labels.json"))
    N = json.load(open(f"art/final/meta/{n}_noise.json")); return T, L, N

def occ_of(T):
    W, H, D = T["size"]; o = np.zeros((W, H, D), bool)
    for v in T["voxels"]: o[v["x"], v["y"], v["z"]] = True
    return o

def pick_tag(n, occ):
    vp = f"art/final/meta/{n}_views.json"
    if os.path.exists(vp): return json.load(open(vp))["chosen"]
    import feature_detect as fd, glob
    tags = sorted({os.path.basename(p)[len(n):-len("_front.png")] for p in glob.glob(f"ortho/{n}_*_front.png")})
    best = None
    for t in tags:
        s = []
        for view in ("front", "right", "back"):
            al = fd.align(n, t, view, fd.view_maps(occ, view)[0], 2)
            if al: s.append(al["iou"])
        if s and (best is None or np.mean(s) > best[0]): best = (float(np.mean(s)), t)
    print(f"  sheet tag by IoU: {best}"); return best[1] if best else "_v1"

def peak_material(L, T, hexc):
    """the subject material whose base colour is nearest the peak's drawn colour (slate cap -> roof slate, stone pinnacle -> stone)"""
    import mc_map as MM
    bases = L.get("bases") or {}
    cand = {m: h for m, h in bases.items() if m not in ("window_dark", "window_lit", "glass", "door", "frame")}
    if not cand or not hexc: return None
    t = MM.hex2lab(hexc); return min(cand, key=lambda m: MM.dE(t, MM.hex2lab(cand[m])))

def write_alias(n, a, T, L, N, occ2, feats2, fj, rep, organic, override=None, shapes=None):
    o_xyz = np.array([[v["x"], v["y"], v["z"]] for v in T["voxels"]]); tree = cKDTree(o_xyz)
    idx = {(v["x"], v["y"], v["z"]): i for i, v in enumerate(T["voxels"])}
    W, H, D = occ2.shape; cells = list(zip(*np.nonzero(occ2)))
    pad = np.pad(occ2, 1); surf = lambda x, y, z: not all(pad[x + 1 + dx, y + 1 + dy, z + 1 + dz] for dx, dy, dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)))
    tv, lv, nv = [], [], []; Lidx = {(v["x"], v["y"], v["z"]): v for v in L["voxels"]}; Nidx = {(v["x"], v["y"], v["z"]): v for v in N["voxels"]}
    new = 0; override = override or {}
    tmpl = {}   # material -> its most common (colour key) surface voxel, the template for re-materialised peak cells
    for m in set(override.values()):
        vs = [v for v in L["voxels"] if v["m"] == m and v.get("surf")]
        if vs:
            cc = collections.Counter(T["voxels"][idx[(v["x"], v["y"], v["z"])]]["c"] for v in vs).most_common(1)[0][0]
            tmpl[m] = next((v["x"], v["y"], v["z"]) for v in vs if T["voxels"][idx[(v["x"], v["y"], v["z"])]]["c"] == cc)
    for (x, y, z) in cells:
        k = (int(x), int(y), int(z))
        if k in override and override[k] in tmpl: src = tmpl[override[k]]; new += k not in idx
        elif k in idx: src = k
        else:
            _, j = tree.query(k); src = tuple(int(c) for c in o_xyz[j]); new += 1
        t = dict(T["voxels"][idx[src]], x=k[0], y=k[1], z=k[2])
        if src != k: t.pop("s", None)                          # a new (backing) cell is a full block
        if shapes and k in shapes: t["s"] = shapes[k]         # peak slope (stairs)
        elif k in override: t.pop("s", None)
        l = dict(Lidx[src], x=k[0], y=k[1], z=k[2]); l["surf"] = bool(surf(*k))
        nz = dict(Nidx[src], x=k[0], y=k[1], z=k[2])
        tv.append(t); lv.append(l); nv.append(nz)
    T2 = dict(T, name=a, voxels=tv, size=list(occ2.shape)); T2["stamp"] = {"source": n, "organic": organic, "counts": rep.get("counts", {}), "new_cells": new}
    json.dump(T2, open(f"art/final/{a}_voxels_textured.json", "w"))
    json.dump(dict(L, subject=a, voxels=lv, size=list(occ2.shape)), open(f"art/final/meta/{a}_texture_labels.json", "w"))
    json.dump(dict(N, subject=a, voxels=nv), open(f"art/final/meta/{a}_noise.json", "w"))
    if fj is not None:
        json.dump(dict(fj, subject=a, features=feats2, stamp={k: v for k, v in rep.items() if k != "parts"}), open(f"art/final/meta/{a}_features.json", "w"))
    elif os.path.exists(f"art/final/meta/{a}_features.json"): os.remove(f"art/final/meta/{a}_features.json")
    return new

def drop_lone_posts(p):
    d = json.load(open(p)); occ = {(v["x"], v["y"], v["z"]) for v in d["voxels"]}; gone = set()
    for v in d["voxels"]:
        q = d["palette"][v["b"]]
        if (q["id"].endswith("_wall") or q["id"].endswith("_fence")) and q.get("material") != "spire":
            x, y, z = v["x"], v["y"], v["z"]
            if sum((x + a, y, z + b) in occ for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))) <= 1: gone.add((x, y, z))
    if gone:
        d["voxels"] = [v for v in d["voxels"] if (v["x"], v["y"], v["z"]) not in gone]
        for q in d["palette"].values(): q["count"] = 0
        for v in d["voxels"]: d["palette"][v["b"]]["count"] += 1
        json.dump(d, open(p, "w"))
    return len(gone)

def audit(a, feats2):
    d = json.load(open(f"art/final/{a}_mc_blocks.json")); pal = d["palette"]
    ids = collections.Counter(pal[v["b"]]["id"] for v in d["voxels"])
    glass = [(v["x"], v["y"], v["z"]) for v in d["voxels"] if "pane" in pal[v["b"]]["id"] or "glass" in pal[v["b"]]["id"]]
    # allowed: inside a window / door opening's (u, y) footprint, within 3 of its (recessed) plane
    ok = set()
    for f in feats2 or []:
        r = f.get("rect")
        if not r or f["kind"] not in ("window", "door"): continue
        for u in range(r["u"][0], r["u"][1] + 1):
            for y in range(r["y"][0], r["y"][1] + 1):
                for k in range(-3, 4):
                    pl = r["plane"] + k; ok.add((u, y, pl) if r["axis"] == "z" else (pl, y, u))
    stray = [g for g in glass if g not in ok]
    return {"blocks": len(d["voxels"]), "glass": len(glass), "glass_ids": {k: c for k, c in ids.items() if "pane" in k or "glass" in k},
            "stray_glass": len(stray), "creaking_heart": ids.get("creaking_heart", 0), "shroomlight": ids.get("shroomlight", 0)}

def run(n, organic_flag=False, orient_apply=False, detect=False, no_peaks=False):
    a = f"{n}_combined"; print(f"== {n} -> {a}")
    T, L, N = load(n); occ = occ_of(T)
    fp = f"art/final/meta/{n}_features.json"; pp = f"art/final/meta/{n}_parts.json"
    P = json.load(open(pp)) if os.path.exists(pp) else {}
    tag = pick_tag(n, occ)
    flip = orient.facade_flip(occ, f"ortho/{n}{tag}_right.png")
    if flip and orient_apply:
        occ = orient.flip_occ(occ).copy()
        for d in (T, L, N): orient.flip_voxel_dict(d)
        detect = True                                  # cached features are in the old frame
    fj = json.load(open(fp)) if os.path.exists(fp) and not detect else None
    organic, why = (True, {"reason": "--organic"}) if organic_flag else SG.is_organic(occ, (fj or {}).get("features", []), P)
    if fj is None and not organic:
        import feature_detect as fd
        had = os.path.exists(fp)
        try:
            fd.detect(n, tag, llm=False); fj = json.load(open(fp)) if os.path.exists(fp) else None   # image-only, $0
        except Exception as e: print("  feature_detect (llm=False) failed:", e)
        if not had and os.path.exists(fp): os.remove(fp)        # the detection belongs to the variant, not to N
        organic, why = SG.is_organic(occ, (fj or {}).get("features", []), P)
    if organic: fj = None                                         # no openings / chimneys / spires on a creature or a tree
    feats = (fj or {}).get("features", [])
    print(f"  organic={organic} {why}")
    if organic:
        occ2, rep, feats2 = occ, {"counts": {"organic_bypass": 1}}, feats
    else:
        occ2, rep, feats2 = SG.stamp(occ, feats, P)
    override = {}
    if not organic and not no_peaks:   # tower caps / turrets / spires / chimneys the mesh clipped (drawn above the mesh top)
        import feature_detect as fd
        peaks = fd.above_mesh_peaks(n, tag, occ)
        occ2, prep, owner, pshapes = SG.stamp_peaks(occ2, peaks)
        mats = [peak_material(L, T, p.get("colour")) for p in peaks]
        rowm = [{int(y): peak_material(L, T, h) for y, h in (p.get("row_colours") or {}).items()} for p in peaks]
        override = {c: (rowm[k].get(c[1]) or mats[k]) for c, k in owner.items() if (rowm[k].get(c[1]) or mats[k])}
        for pr, m, rm in zip(prep, mats, rowm): pr["material"] = m; pr["row_materials"] = {str(y): v for y, v in sorted(rm.items())}
        rep["peaks"] = prep; rep["counts"]["peaks"] = len(prep)
        rep["peaks_cells"] = {f"{c[0]},{c[1]},{c[2]}": k for c, k in owner.items()}
    new = write_alias(n, a, T, L, N, occ2, feats2, fj, rep, organic, override, pshapes if not organic and not no_peaks else None)
    print(f"  occupancy {int(occ.sum())} -> {int(occ2.sum())} (new cells {new})")
    os.makedirs("out/combined", exist_ok=True); mapped = f"out/combined/{a}_mapped.json"
    e = dict(os.environ, MC_GLASS="windows", MC_MAP_OUT=mapped)
    r = subprocess.run([sys.executable, "mc_map.py", a], capture_output=True, text=True, env=e)
    print(r.stdout[-800:], r.stderr[-1500:])
    if r.returncode: raise SystemExit("mc_map failed")
    if P.get("drop_lone_posts"): print("  lone posts dropped", drop_lone_posts(mapped))
    import shade_gradient
    w = {"cottage_v2": (0.25, 0.75)}.get(n, (0.5, 0.5))
    shade_gradient.run(a, a, w[0], w[1], model=mapped, sheet_subject=n, sheet_tag=tag, auto=True)
    au = audit(a, feats2 if not organic else None)
    info = {"subject": n, "alias": a, "sheet_tag": tag, "orient_flip_verdict": bool(flip), "orient_applied": bool(flip and orient_apply),
            "organic": organic, "organic_why": why, "stamp": rep.get("counts"), "peaks": rep.get("peaks", []), "occupancy": [int(occ.sum()), int(occ2.sum())], "audit": au}
    json.dump(info, open(f"out/combined/{a}_report.json", "w"), indent=1); print("  audit", au)
    return info

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("names", nargs="+"); ap.add_argument("--organic", action="store_true")
    ap.add_argument("--orient-apply", action="store_true"); ap.add_argument("--no-peaks", action="store_true", help="skip the above-mesh peak rebuild"); ap.add_argument("--detect", action="store_true", help="re-detect features (image-only, llm=False)")
    x = ap.parse_args()
    for n in x.names: run(n, x.organic, x.orient_apply, x.detect, x.no_peaks)
