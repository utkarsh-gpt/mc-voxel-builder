"""Shape fidelity vs the ortho drawing sheet: silhouette IoU (bbox-normalised) of front / right / top projections, and
the height:width:depth proportions, for any mix of models.
usage: python shape_compare.py NAME SHEET_TAG label=model.json [label=model.schem ...] [--json out.json]
  model: shape_fit output, subblock *_sub.json / *_sub_fine.json, or a .schem (full blocks)"""
import sys, json
import numpy as np
from PIL import Image
import shape_fit, detail_metrics

def occupancy(path, R=4):
    if path.endswith(".schem"):
        cells = detail_metrics.cells_of(path); ks = np.array(list(cells.keys())); ks -= ks.min(0)
        G = np.zeros(ks.max(0) + 1, bool); G[tuple(ks.T)] = True; return G
    d = json.load(open(path)); W, H, D = d["size"]
    if "_fine" in path:
        G = np.zeros((W, H, D), bool)
        for v in d["voxels"]: G[v["x"], v["y"], v["z"]] = True
        return G
    cells = {(v["x"], v["y"], v["z"]): v.get("s") for v in d["voxels"]}
    for k, s in cells.items():                         # subblock's 'vslab'/'slab' sizes map onto boxes01 directly
        if s and s.get("type") == "stairs": s.setdefault("shape", "straight")
    return shape_fit.raster_model(cells, (W, H, D), R)

def norm_mask(m, S=128):
    ys, xs = np.nonzero(m)
    if len(xs) == 0: return np.zeros((S, S), bool), 1.0
    c = m[ys.min():ys.max()+1, xs.min():xs.max()+1]
    return np.asarray(Image.fromarray(c.astype(np.uint8)*255).resize((S, S), Image.BILINEAR)) > 127, c.shape[1]/c.shape[0]

def sheet_mask(n, tag, view):
    a = np.asarray(Image.open(f"ortho/{n}{tag}_{view}.png").convert("L")).astype(int)
    return a < 235

def projections(G):
    """front: looking +z (image x = +x, up = +y); right: looking -x (image x = +z... mirrored variants are tried); top: looking down"""
    f = G.any(2).T[::-1]; r = G.any(0)[::-1]; t = G.any(1).T
    return {"front": f, "right": r, "top": t}

def best_iou(a, b, dihedral=False):
    A, ra = norm_mask(a); out = (0, None)
    vs = [b, b[:, ::-1]] if not dihedral else [np.rot90(x, k) for x in (b, b[:, ::-1]) for k in range(4)]
    for v in vs:
        B, rb = norm_mask(v); i = (A & B).sum()/max((A | B).sum(), 1)
        if i > out[0]: out = (float(i), rb)
    return out[0], ra, out[1]

def regularity(path):
    """% of shaped blocks whose shape (type+orientation) matches none of their 6 neighbours: speckle, lower = cleaner"""
    if path.endswith(".schem"): return None
    d = json.load(open(path)); C = {(v["x"], v["y"], v["z"]): json.dumps(v.get("s"), sort_keys=True) for v in d["voxels"]}
    shaped = [k for k, s in C.items() if s != "null"]; iso = 0
    for x, y, z in shaped:
        nb = [C.get(p) for p in ((x+1, y, z), (x-1, y, z), (x, y+1, z), (x, y-1, z), (x, y, z+1), (x, y, z-1))]
        iso += C[(x, y, z)] not in nb
    return round(100*iso/max(len(shaped), 1), 1)

def compare(n, tag, models):
    ref = {v: sheet_mask(n, tag, v) for v in ("front", "right", "top")}
    rows = {}
    for lab, path in models:
        P = projections(occupancy(path)); r = {}
        for v in ("front", "right", "top"):
            i, ra, rb = best_iou(ref[v], P[v], dihedral=(v == "top"))
            r[v] = round(i, 3); r[v + "_aspect_err_pct"] = round(100*abs(rb/ra - 1), 1)
        r["mean_iou"] = round(np.mean([r[v] for v in ("front", "right", "top")]), 3); r["speckle_pct"] = regularity(path); rows[lab] = r
        print(f"{lab:32s} " + "  ".join(f"{k}={v}" for k, v in r.items()))
    return rows

if __name__ == "__main__":
    a = sys.argv[1:]; out = None
    if "--json" in a: i = a.index("--json"); out = a[i+1]; del a[i:i+2]
    rows = compare(a[0], a[1], [x.split("=", 1) for x in a[2:]])
    if out: json.dump(rows, open(out, "w"), indent=1)

def elevation_sheet(n, tag, models, out, S=300):
    """drawing views next to orthographic renders of each model (front = azim 0, right = azim 90 mirrored as needed, top)"""
    import shape_view
    from PIL import ImageDraw
    views = [("front", 0, 0), ("right", -90, 0), ("top", 0, 90)]
    cols = [("drawing", None)] + list(models)
    G = Image.new("RGB", (len(cols)*(S+10) + 10, len(views)*(S+10) + 40), "white"); dr = ImageDraw.Draw(G)
    for j, (lab, path) in enumerate(cols):
        dr.text((10 + j*(S+10), 8), lab, fill="black")
        for i, (v, az, el) in enumerate(views):
            if path is None:
                im = Image.open(f"ortho/{n}{tag}_{v}.png").convert("RGB")
                a = np.asarray(im.convert("L")) < 235; ys, xs = np.nonzero(a); im = im.crop((xs.min(), ys.min(), xs.max()+1, ys.max()+1))
            elif path.endswith(".schem"):
                continue
            else:
                im, m = shape_view.render(path, az, el, 2*S, mode="colour" if "colour" in lab else "shape")
                ys, xs = np.nonzero(m); im = im.crop((xs.min(), ys.min(), xs.max()+1, ys.max()+1))
            im.thumbnail((S, S)); G.paste(im, (10 + j*(S+10) + (S - im.width)//2, 26 + i*(S+10) + (S - im.height)//2))
    G.save(out); print(out)
