#!/usr/bin/env python3
"""Feature identification: windows, doors, arches and small protrusions (chimneys, spires, finials) read off the verified
ortho drawings, regularised into repeating bays and located on the block grid. mc_map.py builds them (feature_pass).

How it works (no fal, no LLM; ~1 s per subject):
  1. align each elevation drawing (front / right / back; left = mirrored right) to the block model's silhouette from that side
     (bounding boxes + mirror test by IoU, same as ortho_paint), resampled to K pixels per block
  2. openings: pixels clearly darker than the surrounding wall (local median), on planar wall faces of the model (not roof),
     grouped into components -> boxes in block units. Door = opening that reaches the floor line and is >= 1.8 m tall.
     Arched = top corners of the box much emptier than its body.
  3. repetition: openings are clustered into rows (same sill/head height); a row gets one common size, and if its spacing is
     regular (>= 3 openings, spacing CV < 0.25) the bays are snapped to that period and a missing bay is filled when the
     wall is there (flagged 'inferred'). The facade's mirror symmetry (if the drawing has it) pairs left/right openings.
  4. protrusions: drawing silhouette above the model's top surface (pixels the mesh lost) -> thin parts; >= 0.75 block wide
     = chimney / turret, thinner = spire / antenna / finial. Their depth comes from the perpendicular view (matched by height),
     else from the model's ridge at that column.
usage: python feature_detect.py NAME [--sheet _v1] [--K 8]  -> art/final/meta/NAME_features.json, out/NAME_features_debug.png"""
import argparse, json, os, math, collections
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import color as skc
import ortho_carve

VIEWS = ("front", "right", "back", "left")
# camera direction (unit vector toward the camera) and the image column axis for each view
DIR = {"front": (0, 0, 1), "back": (0, 0, -1), "right": (1, 0, 0), "left": (-1, 0, 0)}

def load_model(n):
    T = json.load(open(f"art/final/{n}_voxels_textured.json")); L = json.load(open(f"art/final/meta/{n}_texture_labels.json"))
    W, H, D = T["size"]; occ = np.zeros((W, H, D), bool); mat = np.full((W, H, D), "", object)
    for v in L["voxels"]: occ[v["x"], v["y"], v["z"]] = True; mat[v["x"], v["y"], v["z"]] = v["m"]
    bpm = (T.get("scale") or {}).get("blocks_per_metre", 1.0)
    return T, occ, mat, bpm

def view_maps(occ, view):
    """per image pixel (row = top->bottom, col = left->right as drawn): first-hit voxel (x, y, z) or -1, and hit depth along the view"""
    W, H, D = occ.shape
    if view in ("front", "back"):
        A = occ.transpose(1, 0, 2)                                  # [y, x, z]
        idx = (D - 1 - np.argmax(A[:, :, ::-1], 2)) if view == "front" else np.argmax(A, 2)
        hit = A.any(2); cols = np.arange(W) if view == "front" else np.arange(W)[::-1]
        X = np.broadcast_to(cols[None], (H, W)); Z = idx[:, cols]; Y = np.broadcast_to(np.arange(H)[:, None], (H, W)); hitc = hit[:, cols]
        depth = Z if view == "front" else (D - 1 - Z)
    else:
        A = occ.transpose(1, 2, 0)                                  # [y, z, x]
        idx = (W - 1 - np.argmax(A[:, :, ::-1], 2)) if view == "right" else np.argmax(A, 2)
        hit = A.any(2); cols = np.arange(D)[::-1] if view == "right" else np.arange(D)
        Z = np.broadcast_to(cols[None], (H, D)); X = idx[:, cols]; Y = np.broadcast_to(np.arange(H)[:, None], (H, D)); hitc = hit[:, cols]
        depth = X if view == "right" else (W - 1 - X)
    flip = lambda a: a[::-1]                                         # rows: y descending
    return flip(hitc), flip(np.stack([X, Y, Z], -1)), flip(depth)    # depth: larger = closer to the camera

def align(n, tag, view, P, K):
    """drawing for this view resampled onto the projection's bounding box at K px per block; mirror chosen by IoU"""
    src = "right" if view == "left" else view
    path = f"ortho/{n}{tag}_{src}.png"
    if not os.path.exists(path): return None
    m, rgb = ortho_carve.mask_of(path)
    rr, cc = np.nonzero(P); r0, r1, c0, c1 = rr.min(), rr.max() + 1, cc.min(), cc.max() + 1; h, w = r1 - r0, c1 - c0
    mm = np.asarray(Image.fromarray(m.astype(np.uint8)*255).resize((w, h), Image.BILINEAR)) > 127
    ious = [((mm[:, ::-1] if f else mm) & P[r0:r1, c0:c1]).sum()/((mm[:, ::-1] if f else mm) | P[r0:r1, c0:c1]).sum() for f in (False, True)]
    flip = bool(ious[1] > ious[0])
    big = np.asarray(Image.fromarray(rgb).resize((w*K, h*K), Image.LANCZOS)).astype(float)
    bm = np.asarray(Image.fromarray(m.astype(np.uint8)*255).resize((w*K, h*K), Image.BILINEAR)) > 127
    if flip: big, bm = big[:, ::-1], bm[:, ::-1]
    return {"rgb": big, "mask": bm, "box": (int(r0), int(r1), int(c0), int(c1)), "iou": round(float(max(ious)), 3), "mirrored": flip, "src": src}

def planar_faces(depth, hit):
    """block pixels whose first hit is part of a vertical face: the same depth as the block above or below (walls), so roof
    slopes and domes (depth changes every row) are excluded. Uses only the model's geometry, not its colour labels."""
    up = np.roll(depth, 1, 0); dn = np.roll(depth, -1, 0); hu = np.roll(hit, 1, 0); hd = np.roll(hit, -1, 0)
    hu[0] = False; hd[-1] = False
    return hit & ((hu & (up == depth)) | (hd & (dn == depth)))

def wall_mask(rgb, msk, facade, K):
    """wall pixels at the scale of half a block: the patch-mean colour is close to the facade's dominant patch colour.
    Patch means average away siding lines, mortar and brick/stone courses but keep windows (dark panes in frames, or
    light glazing with a dark grille) and doors far from the wall colour."""
    Lab = skc.rgb2lab(rgb/255.0); w = np.array([0.7, 1, 1])
    s = max(3, K//2); m = msk.astype(float)
    P = np.stack([ndimage.uniform_filter(Lab[..., i]*m, s) for i in range(3)], -1)/np.maximum(ndimage.uniform_filter(m, s), 1e-6)[..., None]
    # the wall colour(s): largest patch-colour clusters of the lower 60% of the silhouette (where walls are, roofs are above)
    from scipy.cluster.vq import kmeans2
    rows = np.flatnonzero(msk.any(1)); low = np.zeros_like(msk); low[int(rows.min() + 0.4*(rows.max() - rows.min())):] = True
    F = msk & low & ndimage.binary_erosion(msk, iterations=s)
    if F.sum() < 50: return np.zeros_like(msk), Lab
    X = P[F]*w; rng = np.random.default_rng(0); X = X[rng.choice(len(X), min(6000, len(X)), replace=False)]
    C, lab = kmeans2(X, 5, minit="++", seed=0); share = np.bincount(lab, minlength=5)/len(lab)
    keep = [j for j in np.argsort(-share) if share[j] >= 0.22][:2] or [int(np.argmax(share))]
    wall = np.zeros_like(msk)
    for j in keep:
        dj = np.linalg.norm(X[lab == j] - C[j], axis=1); t = max(8.0, 1.25*float(np.percentile(dj, 90)))
        wall |= msk & (np.linalg.norm(P*w - C[j], axis=-1) <= t)
    return wall, Lab

def openings(al, K, bpm, facade):
    """openings = holes in the wall region of the drawing (windows, doors, arches): whatever the facade colour encloses.
    The silhouette bottom is closed with a strip of wall first so doors (which reach the ground) also become holes."""
    rgb, msk = al["rgb"], al["mask"]; wall, Lab = wall_mask(rgb, msk, facade, K)
    # openings: non-wall blobs at least ~half a block thick (an opening of ~0.45 block removes trim lines, eaves, gutters and
    # frames that would otherwise connect a window to the roof), not touching the silhouette outline except at the ground
    nonwall = msk & ~wall
    kk = max(3, int(round(0.45*K)))
    core = ndimage.binary_opening(nonwall, np.ones((kk, kk)))
    core = ndimage.binary_dilation(core, np.ones((kk//2 + 1, kk//2 + 1))) & nonwall          # grow back to the true edges
    edge = msk & ~ndimage.binary_erosion(msk, iterations=2)
    bottom = np.zeros_like(msk)
    for c in np.flatnonzero(msk.any(0)): bottom[max(0, np.flatnonzero(msk[:, c])[-1] - 2):, c] = True
    grp, k = ndimage.label(core)
    touch = np.zeros(k + 1, bool); touch[np.unique(grp[edge & ~bottom])] = True; touch[0] = True
    lab = np.where(touch[grp], 0, grp); out = []
    sil_bottom = np.array([np.flatnonzero(msk[:, c])[-1] if msk[:, c].any() else -1 for c in range(msk.shape[1])])
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None: continue
        r0, r1, c0, c1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        h, w = (r1 - r0)/K, (c1 - c0)/K; comp = lab[sl] == i; fillr = ndimage.binary_closing(comp, np.ones((3, 3))).mean()
        if w < 0.55 or h < 0.75 or w*h < 0.6 or fillr < 0.5 or w > 0.4*msk.shape[1]/K or h > 0.5*msk.shape[0]/K or h/w > 3.2 or w/h > 4: continue
        q = max(1, comp.shape[0]//5); qc = max(1, comp.shape[1]//4)
        corners = np.r_[comp[:q, :qc].ravel(), comp[:q, -qc:].ravel()].mean(); body = comp[q:].mean() if comp.shape[0] > q else 1
        arch = bool(w >= 0.9 and h >= 1.4 and corners < 0.55*body)
        col = rgb[sl][comp].mean(0)
        gap = (np.median(sil_bottom[c0:c1]) + 1 - r1)/K                    # blocks between the opening's bottom and the ground line
        kind = "door" if (gap <= 0.6 and h/bpm >= 1.7 and w/bpm >= 0.7) else "window"
        out.append({"kind": kind, "r0": r0/K, "r1": r1/K, "c0": c0/K, "c1": c1/K, "arch": arch, "fill": round(float(fillr), 2),
                    "colour": "#%02x%02x%02x" % tuple(int(v) for v in col)})
    return out, wall

HAIKU = "claude-haiku-5-5"
PROMPT = """Read the image {img}. It is an architectural elevation drawing (one side of a building) with a block grid overlaid: column numbers along the top, row numbers down the left side (row 0 = top). Each grid cell is one Minecraft block.

List every OPENING drawn on the walls (windows, doors, arched windows, round windows, porch or arcade openings) and every SMALL PART that sticks out of the main mass (chimney, spire, antenna, finial, cross, turret, dormer, minaret).
For each item give the grid cells it covers, inclusive: col0, col1 (left..right) and row0, row1 (top..bottom). Use the window/door frame's outer edge, read the numbers off the grid carefully, and keep boxes tight (do not include wall around the window).
Count carefully: every window is its own item (two windows side by side with wall or a post between them are two items; a window split into panes by mullions is one item). List repeated windows individually, including small ones high up and in dormers or a drum. Boxes must not overlap.

Reply with ONLY a JSON object:
{{"openings": [{{"kind": "window|door|arched_window|round_window|porch_opening", "col0": 0, "col1": 0, "row0": 0, "row1": 0}}],
 "parts": [{{"kind": "chimney|spire|antenna|finial|cross|turret|dormer|minaret", "col0": 0, "col1": 0, "row0": 0, "row1": 0}}]}}"""

def grid_image(al, K, path):
    """the aligned drawing with a numbered 1-block grid (what Haiku reads); returns px per block"""
    from PIL import ImageFont
    rgb = al["rgb"]; h, w = rgb.shape[0]//K, rgb.shape[1]//K
    px = int(np.clip(900/max(h, w), 14, 40)); m = 22
    im = Image.fromarray(rgb.astype(np.uint8)).resize((w*px, h*px), Image.LANCZOS)
    G = Image.new("RGB", (w*px + m, h*px + m), "white"); G.paste(im, (m, m)); d = ImageDraw.Draw(G)
    try: font = ImageFont.truetype("DejaVuSans.ttf", 10 if px < 20 else 12)
    except OSError: font = ImageFont.load_default()
    step = 1 if px >= 18 else 2
    for i in range(w + 1):
        d.line([(m + i*px, m), (m + i*px, m + h*px)], fill=(255, 0, 255) if i % 5 == 0 else (0, 170, 255), width=1)
        if i < w and i % step == 0: d.text((m + i*px + 2, 4), str(i), fill="black", font=font)
    for j in range(h + 1):
        d.line([(m, m + j*px), (m + w*px, m + j*px)], fill=(255, 0, 255) if j % 5 == 0 else (0, 170, 255), width=1)
        if j < h and j % step == 0: d.text((1, m + j*px + 2), str(j), fill="black", font=font)
    G.save(path); return px

def haiku_parts(img_path, cache_dir="out/cache"):
    """Haiku lists openings/parts with grid boxes; cached by image hash. returns (dict, cost_usd, cached)"""
    import hashlib, subprocess
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha1(open(img_path, "rb").read() + PROMPT.encode() + HAIKU.encode()).hexdigest()[:16]
    cp = f"{cache_dir}/fd_haiku_{key}.json"
    if os.path.exists(cp): return json.load(open(cp)), 0.0, True
    prompt = PROMPT.format(img=os.path.abspath(img_path))
    out = subprocess.run(["claude", "-p", "--model", HAIKU, prompt, "--allowedTools", "Read", "--output-format", "json"],
                         capture_output=True, text=True, timeout=300).stdout
    env = json.loads(out); txt = env.get("result", ""); cost = float(env.get("total_cost_usd") or 0)
    i, j = txt.find("{"), txt.rfind("}")
    try: r = json.loads(txt[i:j + 1])
    except Exception: r = {"openings": [], "parts": [], "error": txt[:300]}
    r["_cost_usd"] = cost; r["_models"] = list(env.get("modelUsage", {}).keys())
    open(cp, "w").write(json.dumps(r)); return r, cost, False

def evidence(rgb, msk, K):
    """local contrast at block scale: how far each half-block patch colour is from its 3-block neighbourhood mean"""
    Lab = skc.rgb2lab(rgb/255.0); s = max(3, K//2); m = msk.astype(float)
    mean = lambda a, k: ndimage.uniform_filter(a*m, k)/np.maximum(ndimage.uniform_filter(m, k), 1e-6)
    P = np.stack([mean(Lab[..., i], s) for i in range(3)], -1); Q = np.stack([mean(Lab[..., i], 3*K) for i in range(3)], -1)
    return np.linalg.norm(P - Q, axis=-1)*msk

def box_score(E, b, K):
    r0, c0, r1, c1 = b["r"]*K, b["c"]*K, (b["r"] + b["h"])*K, (b["c"] + b["w"])*K
    if r0 < 0 or c0 < 0 or r1 > E.shape[0] or c1 > E.shape[1]: return -1e9
    g = K//2; R = E[max(0, r0 - g):r1 + g, max(0, c0 - g):c1 + g]; I = E[r0:r1, c0:c1]
    ring = (R.sum() - I.sum())/max(1, R.size - I.size)
    return float(I.mean() - ring)

def llm_openings(al, K, bpm, view, n, tag, log):
    """Haiku's listed openings -> boxes in block units, each nudged by <= 1 block to where the drawing's local contrast says
    the opening really is (Haiku's grid reading is usually right to +-1 cell). Returns (boxes, parts, cost, cached)."""
    os.makedirs("out/features", exist_ok=True); gp = f"out/features/{n}{tag}_{view}_grid.png"
    grid_image(al, K, gp); r, cost, cached = haiku_parts(gp)
    E = evidence(al["rgb"], al["mask"], K); hb, wb = al["rgb"].shape[0]//K, al["rgb"].shape[1]//K; boxes = []
    for o in r.get("openings", []):
        try: c0, c1, r0, r1 = (int(o[k]) for k in ("col0", "col1", "row0", "row1"))
        except Exception: continue
        c0, c1 = sorted((max(0, c0), min(wb - 1, c1))); r0, r1 = sorted((max(0, r0), min(hb - 1, r1)))
        kind = str(o.get("kind", "window"))
        b = {"r": r0, "c": c0, "h": r1 - r0 + 1, "w": c1 - c0 + 1, "kind": "door" if kind == "door" else ("arcade" if "porch" in kind else "window"),
             "arch": kind == "arched_window", "round": kind == "round_window", "src": "haiku"}
        # (a +-1 block nudge toward the local-contrast peak was tried: it moved good boxes onto siding lines and frames; Haiku's
        # grid reading alone was better, so the evidence score is only recorded)
        b["evidence"] = round(box_score(E, b, K), 2)
        sl = (slice(b["r"]*K, (b["r"] + b["h"])*K), slice(b["c"]*K, (b["c"] + b["w"])*K))
        mk = al["mask"][sl]; b["colour"] = "#%02x%02x%02x" % tuple(int(v) for v in (al["rgb"][sl][mk].mean(0) if mk.any() else (90, 90, 90)))
        boxes.append(b)
    return boxes, r.get("parts", []), cost, cached

def snap_box(o, bpm, kind):
    w = max(1, round(o["c1"] - o["c0"])); h = max(2 if kind == "door" else 1, round(o["r1"] - o["r0"]))
    if kind == "door": h = max(h, round(1.9*bpm))
    cx, cy = (o["c0"] + o["c1"])/2, (o["r0"] + o["r1"])/2
    return {"c": int(round(cx - w/2)), "r": int(round(cy - h/2)), "w": int(w), "h": int(h)}

def regularise(boxes, ncols):
    """rows of openings with one common size, regular spacing snapped to a period, missing bays inferred, mirror pairs"""
    rows = []
    for b in sorted(boxes, key=lambda b: b["r"] + b["h"]/2):
        cy = b["r"] + b["h"]/2
        for row in rows:
            if b["kind"] == row["kind"] and b.get("arch") == row["items"][0].get("arch") and abs(cy - row["cy"]) <= 1.0 and abs(b["h"] - row["h0"]) <= 1: row["items"].append(b); break
        else: rows.append({"kind": b["kind"], "cy": cy, "h0": b["h"], "items": [b]})
    info = []
    for ri, row in enumerate(rows):
        it = row["items"]; h = int(np.median([b["h"] for b in it])); r = int(round(np.median([b["r"] + b["h"] for b in it]))) - h   # common sill line
        wmed = int(np.median([b["w"] for b in it]))
        for b in it:
            b["h"], b["r"] = h, r
            if abs(b["w"] - wmed) <= 1: b["w"] = wmed
        it.sort(key=lambda b: b["c"] + b["w"]/2); ctr = [b["c"] + b["w"]/2 for b in it]
        rec = {"row": ri, "kind": row["kind"], "count": len(it), "h": h, "w": wmed, "regular": False, "period": None, "inferred": 0}
        if len(it) >= 3:
            dif = np.diff(ctr); p = float(np.median(dif))
            if p > 0 and np.std(dif)/p < 0.25 and all(abs(d/p - round(d/p)) < 0.3 for d in dif):
                rec["regular"], rec["period"] = True, round(p, 2)
                c0 = ctr[0]; k = [round((c - c0)/p) for c in ctr]
                for b, kk in zip(it, k): b["c"] = int(round(c0 + kk*p - b["w"]/2)); b["bay"] = int(kk)
                have = set(k)
                for kk in range(min(k), max(k) + 1):                     # missing bays inside the run
                    if kk not in have:
                        nb = dict(it[0]); nb.update({"c": int(round(c0 + kk*p - wmed/2)), "w": wmed, "bay": kk, "inferred": True}); it.append(nb); rec["inferred"] += 1
        else:
            for i, b in enumerate(it): b["bay"] = i
        # mirror pairs about the facade centre (drawings are usually symmetric): average each pair's offset
        mid = (ncols - 1)/2 + 0.5
        for b in it:
            if b.get("paired"): continue
            mc = 2*mid - (b["c"] + b["w"]/2)
            mate = min((o for o in it if o is not b and not o.get("paired")), key=lambda o: abs(o["c"] + o["w"]/2 - mc), default=None)
            if mate is not None and abs(mate["c"] + mate["w"]/2 - mc) <= 0.75 and mate["w"] == b["w"]:
                off = ((mid - (b["c"] + b["w"]/2)) + ((mate["c"] + mate["w"]/2) - mid))/2
                b["c"] = int(round(mid - off - b["w"]/2)); mate["c"] = int(round(mid + off - mate["w"]/2)); b["paired"] = mate["paired"] = True
        row["items"] = it; row["rec"] = rec; info.append(rec)
    return [b for row in rows for b in row["items"]], info

def tidy(boxes, ncols):
    """light regularisation for Haiku's boxes (which are already per-window): drop duplicates, then group openings into
    rows (same kind/arch, sill and height within 1 block); a row gets one common height, sill and (within +-1) width so
    every bay is built from the same kit; >= 3 equal openings with even spacing are tagged as a repeating run (period)
    and a single missing bay inside an otherwise regular run is filled ('inferred')."""
    boxes = sorted(boxes, key=lambda b: -(b.get("evidence") or 0)); keep = []
    for b in boxes:
        dup = False
        for k in keep:
            ov = max(0, min(b["c"] + b["w"], k["c"] + k["w"]) - max(b["c"], k["c"]))*max(0, min(b["r"] + b["h"], k["r"] + k["h"]) - max(b["r"], k["r"]))
            if ov > 0.5*min(b["w"]*b["h"], k["w"]*k["h"]): dup = True; break
        if not dup: keep.append(b)
    rows = []
    for b in sorted(keep, key=lambda b: b["r"] + b["h"]):
        for row in rows:
            f = row["items"][0]
            if b["kind"] == f["kind"] and bool(b.get("arch")) == bool(f.get("arch")) and abs((b["r"] + b["h"]) - (f["r"] + f["h"])) <= 1 and abs(b["h"] - f["h"]) <= 1:
                row["items"].append(b); break
        else: rows.append({"items": [b]})
    info = []
    for ri, row in enumerate(rows):
        it = row["items"]; h = int(round(np.median([b["h"] for b in it]))); sill = int(round(np.median([b["r"] + b["h"] for b in it])))
        wmed = int(round(np.median([b["w"] for b in it])))
        for b in it:
            b["r"], b["h"] = sill - h, h
            if abs(b["w"] - wmed) <= 1: cx = b["c"] + b["w"]/2; b["w"] = wmed; b["c"] = int(round(cx - wmed/2))
            b["row"] = ri
        it.sort(key=lambda b: b["c"]); rec = {"row": ri, "kind": it[0]["kind"], "arch": bool(it[0].get("arch")), "count": len(it), "h": h, "w": wmed, "period": None, "inferred": 0}
        same = [b for b in it if b["w"] == wmed]
        if len(same) >= 3:
            ctr = np.array([b["c"] + b["w"]/2 for b in same]); dif = np.diff(ctr); p = float(np.median(dif))
            if p > 0:
                mult = np.round(dif/p); ok = (mult >= 1) & (np.abs(dif - mult*p) <= 0.75)
                if ok.all() and (mult == 1).sum() >= 2:
                    rec["period"] = round(p, 2)
                    for i, m in enumerate(mult):
                        if m == 2:                                    # one bay missing in the run
                            nb = dict(same[i]); nb.update(c=int(round(ctr[i] + p - wmed/2)), inferred=True, evidence=None); it.append(nb); rec["inferred"] += 1
                    for i, b in enumerate(sorted(it, key=lambda b: b["c"])): b["bay"] = i
        rec["count"] = len(it); info.append(rec)
    return [b for row in rows for b in row["items"]], info


def protrusions(al, P, K, bpm):
    """drawing silhouette above the model's top in that column: parts the mesh lost (chimneys, spires, finials)"""
    msk = al["mask"]; r0, r1, c0, c1 = al["box"]; Pb = P[r0:r1, c0:c1]
    top = np.where(Pb.any(0), Pb.argmax(0), Pb.shape[0])               # first occupied row per column (block units)
    topk = np.repeat(top, K)[:msk.shape[1]]
    rows = np.arange(msk.shape[0])[:, None]
    above = msk & (rows < topk[None]*K - K//4)
    above = ndimage.binary_opening(above, np.ones((2, 2)))
    lab, k = ndimage.label(above); out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None: continue
        comp = lab[sl] == i; h = (sl[0].stop - sl[0].start)/K; widths = comp.sum(1)/K; w = float(np.median(widths[widths > 0]))
        if h < 0.6 or comp.sum()/K**2 < 0.15: continue
        if (sl[1].stop - sl[1].start)/K > 0.35*msk.shape[1]/K: continue        # a whole roof the mesh missed, not a small part
        cols = np.flatnonzero(comp.any(0)) + sl[1].start; cmid = float(np.median(cols))/K
        col = al["rgb"][sl][comp].mean(0)
        kind = "chimney" if w >= 0.75 else "spire"
        base_row = float(topk[int(cmid*K)]) if int(cmid*K) < len(topk) else float(top.max())
        out.append({"kind": kind, "c": round(cmid, 2), "w": round(w, 2), "top_r": round(sl[0].start/K, 2), "base_r": base_row, "h": round(h, 2),
                    "colour": "#%02x%02x%02x" % tuple(int(v) for v in col)})
    return out

def detect(n, tag=None, K=8, log=print, llm=True):
    T, occ, mat, bpm = load_model(n); W, H, D = occ.shape
    if tag is None:
        vp = next((p for p in (f"out/{n}_verify.json", f"art/final/meta/{n}_views.json") if os.path.exists(p)), None)
        tag = json.load(open(vp))["chosen"] if vp else "_v1"
    feats, debug, rows_info, view_info = [], {}, {}, {}
    maps = {v: view_maps(occ, v) for v in VIEWS}
    als = {v: align(n, tag, v, maps[v][0], K) for v in VIEWS}
    llm_res, spend = {}, {"calls": 0, "cached": 0, "cost_usd": 0.0}
    if llm:
        from concurrent.futures import ThreadPoolExecutor
        todo = [v for v in VIEWS if als[v] is not None]
        with ThreadPoolExecutor(4) as ex:
            for v, r in zip(todo, ex.map(lambda v: llm_openings(als[v], K, bpm, v, n, tag, log), todo)): llm_res[v] = r
        for v, (_, _, cost, cached) in llm_res.items(): spend["calls"] += 1; spend["cached"] += int(cached); spend["cost_usd"] += cost
    for view in VIEWS:
        hit, xyz, depth = maps[view]; al = als[view]
        if al is None: continue
        r0, r1, c0, c1 = al["box"]
        sub = lambda a: a[r0:r1, c0:c1]
        Vb = planar_faces(sub(depth), sub(hit)); facade = np.kron(Vb, np.ones((K, K), bool))[:al["mask"].shape[0], :al["mask"].shape[1]]
        facade = ndimage.binary_dilation(facade, np.ones((K//2, K//2)))
        hparts = []
        if llm:
            boxes, hparts, _, _ = llm_res[view]; wallb = np.ones_like(al["mask"])
        else:
            ops, wallb = openings(al, K, bpm, facade)
            boxes = []
            for o in ops: b = snap_box(o, bpm, o["kind"]); b.update(kind=o["kind"], arch=o["arch"], colour=o["colour"]); boxes.append(b)
        boxes, rinfo = (tidy if llm else regularise)(boxes, c1 - c0); rows_info[view] = rinfo
        # 3D: cells in the facade plane (modal depth of the opening's hit voxels)
        sd, sx = sub(depth), sub(xyz); dvec = np.array(DIR[view])
        for b in boxes:
            rr = slice(max(0, b["r"]), min(r1 - r0, b["r"] + b["h"])); cc = slice(max(0, b["c"]), min(c1 - c0, b["c"] + b["w"]))
            hv = sub(hit)[rr, cc]
            if hv.sum() == 0: continue
            dmode = collections.Counter(sd[rr, cc][hv].tolist()).most_common(1)[0][0]
            cells = []
            for i in range(rr.start, rr.stop):
                for j in range(cc.start, cc.stop):
                    if not sub(hit)[i, j]: continue
                    x, y, z = sx[i, j]
                    # move the cell onto the facade plane (depth dmode) along the view axis
                    if view in ("front", "back"): z = dmode if view == "front" else D - 1 - dmode
                    else: x = dmode if view == "right" else W - 1 - dmode
                    if 0 <= x < W and 0 <= z < D and occ[x, y, z]: cells.append([int(x), int(y), int(z)])
            if not cells: continue
            jj = [c0 + b["c"], c0 + b["c"] + b["w"] - 1]; ys = [H - 1 - (r0 + b["r"] + b["h"] - 1), H - 1 - (r0 + b["r"])]
            if view == "front": rect = {"axis": "z", "plane": int(dmode), "u": jj}
            elif view == "back": rect = {"axis": "z", "plane": int(D - 1 - dmode), "u": sorted(W - 1 - j for j in jj)}
            elif view == "right": rect = {"axis": "x", "plane": int(dmode), "u": sorted(D - 1 - j for j in jj)}
            else: rect = {"axis": "x", "plane": int(W - 1 - dmode), "u": jj}
            rect["u"] = [int(v) for v in rect["u"]]; rect["y"] = [int(v) for v in ys]
            feats.append({"rect": rect, "kind": b["kind"], "view": view, "out": list(map(int, dvec)), "w": b["w"], "h": b["h"], "arch": b["arch"], "round": bool(b.get("round")),
                          "src": b.get("src", "image"), "evidence": b.get("evidence"),
                          "row": f"{view}:{b.get('row', 0)}", "period": (rinfo[b["row"]]["period"] if "row" in b and b["row"] < len(rinfo) else None), "bay": b.get("bay"), "inferred": bool(b.get("inferred")),
                          "colour": b["colour"], "cells": cells, "img_box": [b["r"], b["c"], b["h"], b["w"]]})
        pr = protrusions(al, hit, K, bpm) if al["src"] == view else []     # a mirrored stand-in drawing adds no new parts
        for p in pr:
            p["view"] = view
            # name it from Haiku's part list when one of its parts overlaps (chimney / spire / finial / cross / minaret ...)
            for q in hparts:
                try:
                    if q["col0"] - 1 <= p["c"] <= q["col1"] + 2 and q["row0"] - 1 <= p["top_r"] <= q["row1"] + 1 and q["kind"] != "dormer":
                        p["kind"] = {"minaret": "spire", "turret": "chimney"}.get(q["kind"], q["kind"]); p["named_by"] = "haiku"; break
                except Exception: pass
        debug[view] = {"al": al, "boxes": boxes, "prot": pr, "wall": wallb, "hparts": hparts}
        view_info[view] = {"drawing": f"ortho/{n}{tag}_{al['src']}.png", "iou": al["iou"], "mirrored": al["mirrored"], "openings": len(boxes), "protrusions": len(pr)}
    # protrusions -> 3D (pair front/back with right/left by height; else depth = ridge of the model at that column)
    prot3, used = [], set()
    tops = np.where(occ.any(1), H - 1 - np.argmax(occ[:, ::-1, :], 1), -1)       # [x, z] top surface height
    for va, vb in (("front", "right"), ("back", "right"), ("front", "left"), ("back", "left")):
        for i, a in enumerate(debug.get(va, {}).get("prot", [])):
            if (va, i) in used: continue
            ra0, rc0 = debug[va]["al"]["box"][0], debug[va]["al"]["box"][2]
            xa = (W - 1 - (rc0 + a["c"])) if va == "back" else (rc0 + a["c"])
            ytop = H - (ra0 + a["top_r"])
            best = None
            for j, b in enumerate(debug.get(vb, {}).get("prot", [])):
                rb0, cb0 = debug[vb]["al"]["box"][0], debug[vb]["al"]["box"][2]
                yb = H - (rb0 + b["top_r"])
                if a["kind"] == b["kind"] and abs(yb - ytop) <= 1.5 and (best is None or abs(yb - ytop) < best[0]): best = (abs(yb - ytop), j, b, cb0)
            if best:
                _, j, b, cb0 = best; zb = (D - 1 - (cb0 + b["c"])) if vb == "right" else (cb0 + b["c"]); used.add((vb, j)); dz = b["w"]
            else:
                xi = int(np.clip(round(xa), 0, W - 1)); col = tops[xi]; zb = float(np.argmax(col)) if (col >= 0).any() else D/2; dz = a["w"]
            used.add((va, i))
            prot3.append({"kind": a["kind"], "x": round(float(xa), 2), "z": round(float(zb), 2), "w": a["w"], "d": round(float(dz), 2),
                          "y_top": round(float(ytop), 2), "colour": a["colour"], "views": [va] + ([vb] if best else [])})
    for vb in ("right", "left"):                                     # seen only from a side: x from the model's ridge there
        for j, b in enumerate(debug.get(vb, {}).get("prot", [])):
            if (vb, j) in used: continue
            rb0, cb0 = debug[vb]["al"]["box"][0], debug[vb]["al"]["box"][2]
            zb = (D - 1 - (cb0 + b["c"])) if vb == "right" else (cb0 + b["c"]); zi = int(np.clip(round(zb), 0, D - 1))
            ytop = H - (rb0 + b["top_r"]); xa = None
            # x from Haiku's part list on the front/back drawing (same kind of part at about the same height)
            for va in ("front", "back"):
                if va not in debug: continue
                ra0, ca0 = debug[va]["al"]["box"][0], debug[va]["al"]["box"][2]
                for q in debug[va]["hparts"]:
                    try:
                        qk = {"minaret": "spire", "turret": "chimney", "antenna": "spire", "finial": "spire", "cross": "spire"}.get(q["kind"], q["kind"])
                        if qk == b["kind"] and abs((H - (ra0 + q["row0"])) - ytop) <= 2.5:
                            cm = ca0 + (q["col0"] + q["col1"] + 1)/2; xa = (W - cm) if va == "back" else cm; break
                    except Exception: pass
                if xa is not None: break
            if xa is None:
                col = tops[:, zi]; m = col.max(); xa = float(np.median(np.flatnonzero(col == m))) if m >= 0 else W/2
            prot3.append({"kind": b["kind"], "x": round(float(xa), 2), "z": round(float(zb), 2), "w": b["w"], "d": b["w"], "y_top": round(float(ytop), 2),
                          "colour": b["colour"], "views": [vb]})
    # dedupe (front and back can both see the same chimney)
    keep = []
    for p in sorted(prot3, key=lambda p: -len(p["views"])):
        if any(q["kind"] == p["kind"] and abs(q["x"] - p["x"]) <= 1.5 and abs(q["z"] - p["z"]) <= 1.5 for q in keep): continue
        keep.append(p)
    for p in keep:
        X, Z = int(np.clip(round(p["x"] - 0.5), 0, W - 1)), int(np.clip(round(p["z"] - 0.5), 0, D - 1))
        p["base_y"] = int(tops[X, Z]) if tops[X, Z] >= 0 else 0
        feats.append(dict(p, kind=p["kind"], cells=None))
    spend["cost_usd"] = round(spend["cost_usd"], 5)
    res = {"subject": n, "sheet": tag, "blocks_per_metre": bpm, "K": K, "method": "haiku+image" if llm else "image", "llm": spend if llm else None,
           "views": view_info, "rows": rows_info,
           "counts": dict(collections.Counter(f["kind"] for f in feats)), "inferred": sum(1 for f in feats if f.get("inferred")), "features": feats}
    os.makedirs("art/final/meta", exist_ok=True)
    open(f"art/final/meta/{n}_features.json", "w").write(json.dumps(res, indent=1))
    debug_png(n, debug)
    log(f"{n}: {res['counts']} ({res['inferred']} inferred bays) llm {spend} views {[(v, i['openings'], i['iou']) for v, i in view_info.items()]}")
    return res

def debug_png(n, debug, S=520):
    """drawings with the detected openings (red = window, blue = door, orange = inferred bay) and protrusions (green)"""
    tiles = []
    for view, d in debug.items():
        al = d["al"]; K = al["rgb"].shape[0]/(al["box"][1] - al["box"][0])
        base = al["rgb"].copy(); wl = d["wall"]; base[~wl & al["mask"]] = base[~wl & al["mask"]]*0.35 + np.array([0, 160, 255])*0.65
        im = Image.fromarray(base.astype(np.uint8)); dr = ImageDraw.Draw(im)
        for b in d["boxes"]:
            c = (255, 140, 0) if b.get("inferred") else ((40, 90, 255) if b["kind"] == "door" else (230, 30, 30))
            dr.rectangle([b["c"]*K, b["r"]*K, (b["c"] + b["w"])*K - 1, (b["r"] + b["h"])*K - 1], outline=c, width=2)
        for p in d["prot"]:
            dr.rectangle([(p["c"] - p["w"]/2)*K, p["top_r"]*K, (p["c"] + p["w"]/2)*K, (p["top_r"] + p["h"])*K], outline=(0, 170, 0), width=2)
        f = S/max(im.size); im = im.resize((int(im.width*f), int(im.height*f)), Image.NEAREST); t = Image.new("RGB", (S, S + 16), "white"); t.paste(im, ((S - im.width)//2, 16)); ImageDraw.Draw(t).text((4, 2), view, fill="black"); tiles.append(t)
    if not tiles: return
    G = Image.new("RGB", (len(tiles)*(S + 6), S + 16), "white")
    for i, t in enumerate(tiles): G.paste(t, (i*(S + 6), 0))
    os.makedirs("out", exist_ok=True); G.save(f"out/{n}_features_debug.png")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name", nargs="+"); ap.add_argument("--sheet"); ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--no-llm", action="store_true", help="image-only detector (no Haiku; weaker)")
    a = ap.parse_args()
    for n in a.name: detect(n, a.sheet, a.K, llm=not a.no_llm)
