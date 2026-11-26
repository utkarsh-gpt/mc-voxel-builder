#!/usr/bin/env python3
"""Colour fidelity of a Minecraft-block build vs the verified ortho drawings (and the reference photo). Free: no fal, no LLM.

Per elevation view (front / right / back; 'left' = mirrored right drawing, reported but not in the mean):
  1. project the block grid from that side (first visible block per cell, feature_detect.view_maps) and align the drawing to
     the projection's bounding box at K px per block (feature_detect.align: same bbox + mirror-by-IoU as ortho_paint)
  2. ortho colour per block cell = median Lab of the drawing pixels in that cell; build colour = the block's side-face mean
     colour from the dataset (what a player sees from a distance)
  3. metrics over cells where both the drawing and the build have something:
     - de_mean / de_median / de_p90: CIEDE2000 per cell
     - outlier_pct: % of visible blocks whose colour is > OUTLIER_DE (CIEDE2000) from EVERY ortho cell in its 3x3 block
       neighbourhood (so a 1-block misalignment at an edge does not count; a brown block in yellow siding does)
     - palette_emd: earth-mover distance (CIEDE76 in Lab units) between the ortho's and the build's k=6 colour clusters
       (weights = pixel shares): 'are the right colours used in the right amounts', independent of position
     headline numbers use the build AS SEEN: a real-texture render (mc_render, lit head-on) resampled onto the drawing and
     reduced to a per-block median (partial blocks such as trapdoor trim or panes show what is behind them); *_block
     numbers use one dataset colour per block instead
  4. blame: outlier blocks counted by block id and by material; heatmaps out/colour/NAME_VIEW.png
Photo: scorer.view_metrics on the reference photo vs the baked 4x render at the fitted camera (pixel dE, hist intersection).
usage: python colour_score.py NAME [--model art/final/NAME_mc_blocks.json] [--label run] [--no-photo]
  -> out/colour/NAME_<label>.json + out/colour/NAME_<label>_VIEW.png + out/colour/NAME_<label>_sheet.png"""
import argparse, collections, json, os
import numpy as np
from PIL import Image, ImageDraw
from skimage import color as skc
from scipy import ndimage
from scipy.optimize import linprog
import feature_detect as fd, mc_render

OUTLIER_DE = 20.0
VIEWS = ("front", "right", "back", "left")
def de2000(a, b): return skc.deltaE_ciede2000(a, b)

def load_build(path):
    d = json.load(open(path)); W, H, D = d["size"]; B = mc_render.blocks()
    occ = np.zeros((W, H, D), bool); bid = np.full((W, H, D), "", object); mat = np.full((W, H, D), "", object)
    for v in d["voxels"]:
        p = d["palette"][v["b"]]; occ[v["x"], v["y"], v["z"]] = True; bid[v["x"], v["y"], v["z"]] = p["id"]; mat[v["x"], v["y"], v["z"]] = p.get("material", "")
    lab = {i: np.array(B[i]["faces"].get("side", B[i]["overall"])["lab"], float) for i in set(bid[occ].tolist())}
    return d, occ, bid, mat, lab

def kclusters(X, k=6, seed=0):
    from scipy.cluster.vq import kmeans2
    X = X[np.random.default_rng(seed).choice(len(X), min(len(X), 4000), replace=False)]
    C, l = kmeans2(X, min(k, len(X)), minit="++", seed=seed); w = np.bincount(l, minlength=len(C)).astype(float)
    keep = w > 0; return C[keep], w[keep]/w[keep].sum()

def emd(Ca, wa, Cb, wb):
    """earth mover's distance between two weighted Lab point sets (transport LP)"""
    M = np.linalg.norm(Ca[:, None] - Cb[None], axis=-1); n, m = M.shape
    A = []; b = []
    for i in range(n): r = np.zeros((n, m)); r[i] = 1; A.append(r.ravel()); b.append(wa[i])
    for j in range(m): r = np.zeros((n, m)); r[:, j] = 1; A.append(r.ravel()); b.append(wb[j])
    res = linprog(M.ravel(), A_eq=np.array(A), b_eq=np.array(b), bounds=(0, None), method="highs")
    return float(res.fun)

def textured_view(d, view, al, P, box, K):
    """real-texture render lit head-on, cropped to its silhouette bbox, resampled onto the aligned drawing grid"""
    az = {"front": 0, "right": 90, "back": 180, "left": 270}[view]
    best = None
    for a in (az, (az + 180) % 360) if view in ("right", "left") else (az,):
        light = tuple(mc_render.vox.cam_R(a, 0)[2])                  # light from this camera: faces seen head-on are unshaded
        img, m = mc_render.render(d, a, 0, 4*max(al["rgb"].shape), light=light)
        ys, xs = np.nonzero(m)
        if len(xs) == 0: continue
        im = np.asarray(img)[ys.min():ys.max() + 1, xs.min():xs.max() + 1]; mm = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        h, w = al["rgb"].shape[:2]
        im = np.asarray(Image.fromarray(im).resize((w, h), Image.LANCZOS)).astype(float); mm = np.asarray(Image.fromarray(mm.astype(np.uint8)*255).resize((w, h))) > 127
        for flip in (False, True):
            a2, m2 = (im[:, ::-1], mm[:, ::-1]) if flip else (im, mm)
            pm = np.kron(P, np.ones((K, K), bool))[:h, :w]
            iou = (m2 & pm).sum()/max((m2 | pm).sum(), 1)
            if best is None or iou > best[0]: best = (iou, a2, m2)
    return best

def score(n, model=None, label="run", photo=True, K=8, log=print):
    model = model or f"art/final/{n}_mc_blocks.json"
    d, occ, bid, mat, blab = load_build(model); W, H, D = occ.shape
    tag = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"] if os.path.exists(f"art/final/meta/{n}_views.json") else "_v1"
    os.makedirs("out/colour", exist_ok=True)
    res = {"subject": n, "model": model, "sheet": tag, "outlier_de": OUTLIER_DE, "views": {}}
    blame_b, blame_m, vis_b = collections.Counter(), collections.Counter(), collections.Counter()
    sheet_tiles = []
    for view in VIEWS:
        hit, xyz, depth = fd.view_maps(occ, view); al = fd.align(n, tag, view, hit, K)
        if al is None: continue
        r0, r1, c0, c1 = al["box"]; h, w = r1 - r0, c1 - c0; P = hit[r0:r1, c0:c1]; X = xyz[r0:r1, c0:c1]
        lab_img = skc.rgb2lab(al["rgb"]/255.0); msk = al["mask"]
        O = np.full((h, w, 3), np.nan); Bc = np.full((h, w, 3), np.nan); ids = np.full((h, w), "", object); mats = np.full((h, w), "", object)
        for i in range(h):
            for j in range(w):
                pm = msk[i*K:(i + 1)*K, j*K:(j + 1)*K]
                if pm.mean() >= 0.5: O[i, j] = np.median(lab_img[i*K:(i + 1)*K, j*K:(j + 1)*K][pm], 0)
                if P[i, j]:
                    x, y, z = X[i, j]; ids[i, j] = bid[x, y, z]; mats[i, j] = mat[x, y, z]; Bc[i, j] = blab[ids[i, j]]
        # what the eye sees per block cell: median of a real-texture render (partial blocks show what is behind them)
        Tc = np.full((h, w, 3), np.nan); tv = textured_view(d, view, al, P, al["box"], K)
        if tv:
            _, timg, tm = tv; tlab = skc.rgb2lab(timg/255.0)
            for i in range(h):
                for j in range(w):
                    pm = tm[i*K:(i + 1)*K, j*K:(j + 1)*K]
                    if pm.mean() >= 0.5 and P[i, j]: Tc[i, j] = np.median(tlab[i*K:(i + 1)*K, j*K:(j + 1)*K][pm], 0)
        def metrics(Bx, tag):
            both = ~np.isnan(O[..., 0]) & ~np.isnan(Bx[..., 0]); dE = np.full((h, w), np.nan); dE[both] = de2000(O[both], Bx[both])
            mind = np.full((h, w), np.inf)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    Os = np.full_like(O, np.nan)
                    Os[max(0, di):h + min(0, di), max(0, dj):w + min(0, dj)] = O[max(0, -di):h - max(0, di), max(0, -dj):w - max(0, dj)]
                    ok = ~np.isnan(Os[..., 0]) & ~np.isnan(Bx[..., 0]); t = np.full((h, w), np.inf); t[ok] = de2000(Os[ok], Bx[ok]); mind = np.minimum(mind, t)
            vis = ~np.isnan(Bx[..., 0]); out = vis & (mind > OUTLIER_DE) & np.isfinite(mind)
            Ca, wa = kclusters(O[~np.isnan(O[..., 0])]); Cb, wb = kclusters(Bx[vis])
            r = {f"de_mean{tag}": round(float(np.nanmean(dE)), 2), f"de_median{tag}": round(float(np.nanmedian(dE)), 2), f"de_p90{tag}": round(float(np.nanpercentile(dE, 90)), 2),
                 f"outlier_pct{tag}": round(100*out.sum()/max(1, vis.sum()), 2), f"palette_emd{tag}": round(emd(Ca, wa, Cb, wb), 2)}
            return r, dE, out, vis, both
        rec = {"drawing": f"ortho/{n}{tag}_{al['src']}.png", "mirrored": al["mirrored"], "iou": al["iou"]}
        rb, dEb, outb, visb, bothb = metrics(Bc, "_block"); rec.update(rb)
        if not np.isnan(Tc[..., 0]).all():
            rt, dE, out, vis, both = metrics(Tc, ""); rec.update(rt)
        else: dE, out, vis, both = dEb, outb, visb, bothb
        rec["cells_compared"] = int(both.sum()); rec["outliers"] = int(out.sum())
        res["views"][view] = rec
        if view != "left":
            for i, j in zip(*np.nonzero(out)): blame_b[ids[i, j]] += 1; blame_m[mats[i, j]] += 1
            for i, j in zip(*np.nonzero(vis)): vis_b[ids[i, j]] += 1
        # heatmap tile: drawing | build colours | dE map (outliers boxed)
        S = 12; to_rgb = lambda A: (np.clip(skc.lab2rgb(np.nan_to_num(A, nan=100.0)), 0, 1)*255).astype(np.uint8)
        Bs = Tc if not np.isnan(Tc[..., 0]).all() else Bc
        A = to_rgb(O); Bi = to_rgb(Bs); Bi[~vis] = 255; A[np.isnan(O[..., 0])] = 255
        hm = np.full((h, w, 3), 255, np.uint8); t = np.clip(np.nan_to_num(dE, nan=0)/40, 0, 1)
        hm[both] = (np.stack([255*t, 255*(1 - t), 60*(1 - t)], -1)[both]).astype(np.uint8)
        tiles = []
        for arr in (A, Bi, hm):
            im = Image.fromarray(arr).resize((w*S, h*S), Image.NEAREST); tiles.append(im)
        dr = ImageDraw.Draw(tiles[2]); dr1 = ImageDraw.Draw(tiles[1])
        for i, j in zip(*np.nonzero(out)):
            for dd in (dr, dr1): dd.rectangle([j*S, i*S, (j + 1)*S - 1, (i + 1)*S - 1], outline=(255, 0, 255), width=2)
        T = Image.new("RGB", (3*w*S + 20, h*S + 34), "white"); dt = ImageDraw.Draw(T)
        for k, im in enumerate(tiles): T.paste(im, (k*(w*S + 10), 30))
        dt.text((4, 2), f"{n} [{label}] {view}: drawing (per-block median) | build as seen (textured render, per-block median; magenta = outlier) | dE2000 (green 0 .. red 40)", fill="black")
        dt.text((4, 15), f"dE mean {rec.get('de_mean')}  p90 {rec.get('de_p90')}  outliers {rec.get('outlier_pct')}%  palette EMD {rec.get('palette_emd')}   | block-colour: dE {rec['de_mean_block']}  outliers {rec['outlier_pct_block']}%", fill="black")
        T.save(f"out/colour/{n}_{label}_{view}.png"); sheet_tiles.append(T)
    main = [v for v in ("front", "right", "back") if v in res["views"]]
    agg = lambda k: round(float(np.mean([res["views"][v][k] for v in main if k in res["views"][v]])), 2)
    res["summary"] = {k: agg(k) for k in ("de_mean", "de_median", "de_p90", "outlier_pct", "palette_emd", "de_mean_block", "de_p90_block", "outlier_pct_block", "palette_emd_block")}
    res["outliers_by_block"] = [(b, c, round(100*c/max(1, vis_b[b]), 1)) for b, c in blame_b.most_common(12)]
    res["outliers_by_material"] = blame_m.most_common()
    if photo:
        try:
            import vox, scorer, run_fal
            fine = f"out/colour/{n}_{label}_fine.json"; mc_render.bake_fine(model, fine)
            _, o, c, _ = vox.load(fine, seed=0); ref = Image.open(f"refs/{n}.jpg"); az, el = run_fal.fit_cardinal(ref, o, c)
            vm = scorer.view_metrics(ref, o, c, az, el)
            vm = vm[0] if isinstance(vm, tuple) else vm
            res["photo"] = {"camera": [az, el], **{k: vm[k] for k in ("pixel_deltaE", "palette_deltaE", "lab_hist_intersection", "luminance_corr", "silhouette_iou") if k in vm}}
        except Exception as e: res["photo"] = {"error": str(e)[:200]}
    if sheet_tiles:
        Wd = max(t.width for t in sheet_tiles); G = Image.new("RGB", (Wd, sum(t.height + 6 for t in sheet_tiles)), "white"); y = 0
        for t in sheet_tiles: G.paste(t, (0, y)); y += t.height + 6
        G.save(f"out/colour/{n}_{label}_sheet.png")
    open(f"out/colour/{n}_{label}.json", "w").write(json.dumps(res, indent=1))
    log(f"{n} [{label}] summary {res['summary']} photo {res.get('photo')}")
    log(f"  outliers by block {res['outliers_by_block'][:8]}")
    log(f"  outliers by material {res['outliers_by_material']}")
    return res

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--model"); ap.add_argument("--label", default="run"); ap.add_argument("--no-photo", action="store_true")
    a = ap.parse_args(); score(a.name, a.model, a.label, not a.no_photo)
