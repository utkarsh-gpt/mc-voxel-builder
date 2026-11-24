#!/usr/bin/env python3
"""Score a colour voxel model against a reference image.
usage: python scorer.py ref.jpg model.json [--azim A --elev E | --fit] [--out out/prefix] [--judge]
Outputs JSON scores + <out>_compare.png (ref | render | silhouette overlay) + <out>_sheet.png (6 views)."""
import argparse, json, subprocess, os, numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color as skc
from skimage.metrics import structural_similarity as ssim
from skimage.transform import resize
import vox

N = 256
def ref_mask(img, thr=28):
    fn = getattr(img, "filename", "") or ""
    side = os.path.splitext(fn)[0] + "_mask.png"
    if fn and os.path.exists(side):   # precomputed subject mask (rembg isnet) wins
        return np.asarray(Image.open(side).convert("L").resize(img.size)) > 127
    a = np.asarray(img.convert("RGB")).astype(float)
    # background colour = median of border pixels
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]); bg = np.median(border, 0)
    m = np.linalg.norm(a - bg, axis=2) > thr
    m = ndimage.binary_opening(m, iterations=2); m = ndimage.binary_fill_holes(m)
    lab, n = ndimage.label(m)
    if n: m = lab == (np.bincount(lab.ravel())[1:].argmax() + 1)
    return m

def normalize(rgb, mask):
    """crop to mask bbox, letterbox into NxN (keeps aspect). returns rgb (N,N,3) float [0,1], mask, aspect"""
    ys, xs = np.nonzero(mask); y0, y1, x0, x1 = ys.min(), ys.max()+1, xs.min(), xs.max()+1
    r = rgb[y0:y1, x0:x1].astype(float)/255; m = mask[y0:y1, x0:x1]
    h, w = m.shape; s = (N-8)/max(h, w); nh, nw = max(1, round(h*s)), max(1, round(w*s))
    r = resize(r, (nh, nw, 3), anti_aliasing=True); m = resize(m.astype(float), (nh, nw)) > .5
    R = np.ones((N, N, 3)); M = np.zeros((N, N), bool); oy, ox = (N-nh)//2, (N-nw)//2
    R[oy:oy+nh, ox:ox+nw] = r; M[oy:oy+nh, ox:ox+nw] = m
    R[~M] = 1.0
    return R, M, w/h

def kmeans_palette(px, k=6, it=15, seed=0):
    rng = np.random.default_rng(seed); c = px[rng.choice(len(px), min(k, len(px)), replace=False)]
    for _ in range(it):
        lab = ((px[:, None]-c[None])**2).sum(-1).argmin(1)
        c = np.array([px[lab==i].mean(0) if (lab==i).any() else c[i] for i in range(len(c))])
    w = np.bincount(lab, minlength=len(c))/len(px); return c, w

def craft_metrics(occ, col):
    W, H, D = occ.shape; n = int(occ.sum())
    lab, ncomp = ndimage.label(occ, structure=np.ones((3, 3, 3)))
    sizes = np.bincount(lab.ravel())[1:] if ncomp else np.array([0])
    floating = int(n - sizes.max()) if ncomp else 0
    # surface voxels
    pad = np.pad(occ, 1); inner = np.ones_like(occ)
    for ax in range(3):
        for s in (-1, 1): inner &= np.roll(pad, s, ax)[1:-1, 1:-1, 1:-1]
    surf = occ & ~inner; ns = int(surf.sum())
    cols = col[surf].reshape(-1, 3)
    uniq = len({tuple(c) for c in cols}) if ns else 0
    # local colour variation on the surface: fraction of surface neighbour pairs with different colour
    diffs = tot = 0
    for ax in range(3):
        a = surf & np.roll(surf, 1, ax); 
        if a.any():
            c1 = col[a]; c2 = np.roll(col, 1, ax)[a]; tot += len(c1); diffs += int((np.abs(c1.astype(int)-c2).sum(1) > 6).sum())
    var = diffs/tot if tot else 0
    # value range of surface colours (L*)
    L = skc.rgb2lab(cols[None].astype(float)/255)[0, :, 0] if ns else np.array([0])
    bbox_fill = n / max(1, np.prod([np.ptp(i)+1 for i in np.nonzero(occ)])) if n else 0
    return {"voxels": n, "surface_voxels": ns, "components": int(ncomp), "floating_voxels": floating,
            "unique_surface_colours": uniq, "surface_colour_variation": round(var, 3),
            "value_range_L": round(float(np.percentile(L, 95)-np.percentile(L, 5)), 1), "bbox_fill": round(float(bbox_fill), 3)}

def view_metrics(ref_img, occ, col, azim, elev):
    img, m = vox.render(occ, col, azim, elev, 512)
    rr, rm, ra = normalize(np.asarray(ref_img.convert("RGB")), ref_mask(ref_img))
    vr, vm, va = normalize(np.asarray(img), m)
    inter, union = (rm & vm).sum(), (rm | vm).sum(); iou = inter/union
    g1, g2 = skc.rgb2gray(rr), skc.rgb2gray(vr)
    ss = ssim(g1, g2, data_range=1.0)
    # low-frequency structure (blurred) SSIM: is the light/dark layout right?
    ss_lo = ssim(ndimage.gaussian_filter(g1, 4), ndimage.gaussian_filter(g2, 4), data_range=1.0)
    L1, L2 = skc.rgb2lab(rr), skc.rgb2lab(vr); both = rm & vm
    dE_pix = float(np.linalg.norm(L1[both]-L2[both], axis=1).mean()) if both.any() else 100
    # palette distance: k-means palettes (Lab), weighted symmetric nearest dE
    p1, w1 = kmeans_palette(L1[rm]); p2, w2 = kmeans_palette(L2[vm])
    dmat = np.linalg.norm(p1[:, None]-p2[None], axis=2)
    pal_d = float((dmat.min(1)*w1).sum()/2 + (dmat.min(0)*w2).sum()/2)
    # Lab histogram intersection (a*,b* chroma + L)
    def hist(L, m):
        h, _ = np.histogramdd(L[m], bins=(8, 8, 8), range=((0, 100), (-60, 60), (-60, 60))); return h/h.sum()
    hi = float(np.minimum(hist(L1, rm), hist(L2, vm)).sum())
    # luminance correlation in overlap (shading layout)
    lc = float(np.corrcoef(L1[both][:, 0], L2[both][:, 0])[0, 1]) if both.sum() > 10 else 0
    return {"silhouette_iou": round(float(iou), 3), "aspect_ratio_ref": round(ra, 3), "aspect_ratio_render": round(va, 3),
            "ssim": round(float(ss), 3), "ssim_lowfreq": round(float(ss_lo), 3), "pixel_deltaE": round(dE_pix, 1),
            "palette_deltaE": round(pal_d, 1), "lab_hist_intersection": round(hi, 3), "luminance_corr": round(lc, 3)}, img, (rr, rm, vr, vm)

def fit_camera(ref_img, occ, col, azim0=30, elev0=20, span_a=60, span_e=35):
    """Search camera near the declared prior. Objective = silhouette IoU + colour agreement (silhouette alone
    cannot tell 'from above' and 'from below' apart for roughly symmetric objects)."""
    rr, rm, _ = normalize(np.asarray(ref_img.convert("RGB")), ref_mask(ref_img)); L1 = skc.rgb2lab(rr)
    def obj(a, e):
        img, m = vox.render(occ, col, a, e, 160)
        vr, vm, _ = normalize(np.asarray(img), m); both = rm & vm
        iou = both.sum()/(rm | vm).sum()
        dE = np.linalg.norm(L1[both]-skc.rgb2lab(vr)[both], axis=1).mean() if both.any() else 100
        return iou + 0.5*max(0, 1-dE/50)
    best = max(((obj(a, e), a, e) for a in range(int(azim0-span_a), int(azim0+span_a)+1, 20)
                for e in range(int(max(-85, elev0-span_e)), int(min(85, elev0+span_e))+1, 10)))
    _, a0, e0 = best
    best = max([best]+[(obj(a, e), a, e) for a in range(a0-10, a0+11, 5) for e in range(e0-6, e0+7, 3)])
    return best[1] % 360, best[2]

def multiview_ok(occ, col):
    """readability from all angles: silhouette area of 6 views, relative to the max. Flags views that collapse."""
    areas = []
    for a, e in ((0, 15), (90, 15), (180, 15), (270, 15), (0, 80), (45, 30)):
        _, m = vox.render(occ, col, a, e, 128, ao=False); areas.append(m.sum())
    areas = np.array(areas, float); return round(float(areas.min()/areas.max()), 3)

def composite(ref_img, render_img, rr, rm, vr, vm, path, title=""):
    ov = np.ones((N, N, 3)); ov[rm & ~vm] = (1, .3, .3); ov[vm & ~rm] = (.3, .4, 1); ov[rm & vm] = (.75, .75, .75)
    tiles = [(rr*255).astype(np.uint8), (vr*255).astype(np.uint8), (ov*255).astype(np.uint8)]
    S = Image.new("RGB", (N*3+20, N+24), (255, 255, 255))
    for i, t in enumerate(tiles): S.paste(Image.fromarray(t), (i*(N+10), 24))
    from PIL import ImageDraw; ImageDraw.Draw(S).text((4, 4), title + "   [reference | voxel render | overlap: red=missing, blue=extra]", fill=(0, 0, 0))
    S.save(path); return path

def total_score(v, c, mv):
    """0-100 weighted composite of the automatic criteria (judge scores reported separately)."""
    s = {
      "silhouette": 100*v["silhouette_iou"],
      "proportion": 100*max(0, 1-abs(np.log(v["aspect_ratio_render"]/v["aspect_ratio_ref"]))/0.5),
      "structure": 100*max(0, v["ssim_lowfreq"]),
      "colour_palette": 100*max(0, 1-v["palette_deltaE"]/40),
      "colour_pixel": 100*max(0, 1-v["pixel_deltaE"]/50),
      "shading_layout": 100*max(0, v["luminance_corr"]),
      "integrity": 100*max(0, 1 - c["floating_voxels"]/max(1, c["voxels"])*20),
      "detail": 100*min(1, c["surface_colour_variation"]/0.35) * min(1, c["unique_surface_colours"]/12),
      "all_angles": 100*min(1, mv/0.35),
    }
    w = {"silhouette": .22, "proportion": .08, "structure": .12, "colour_palette": .14, "colour_pixel": .1,
         "shading_layout": .1, "integrity": .08, "detail": .08, "all_angles": .08}
    return round(sum(s[k]*w[k] for k in w), 1), {k: round(x, 1) for k, x in s.items()}

JUDGE_PROMPT = """You are a strict voxel-art critic. Read these images with the Read tool:
1. REFERENCE (inspiration): {ref}
2. COMPARE strip (reference | voxel render from the matching camera | silhouette overlap): {cmp}
3. SHEET (the voxel model from 6 angles incl. top and below): {sheet}
Score each 1-10 (10 = indistinguishable intent / expert quality) and be harsh:
- likeness: would a viewer instantly match the voxel render to the reference?
- silhouette_proportion: outline, key proportions, gesture
- colour_fidelity: hues and palette match the reference materials
- shading_value: value ramps, light direction, AO / contact shadows read like the reference
- surface_detail: texture noise, pattern, edge detailing at an appropriate density (not noisy, not flat)
- all_angles: looks finished and believable from every view in the sheet
- craft: clean voxel-art craftsmanship (stepped curves, no stray voxels, intentional palette)
Then list the 5 most impactful concrete fixes, each naming the part, the change, and voxel coordinates/sizes when possible.
Output ONLY JSON: {{"scores": {{...}}, "overall": <1-10>, "fixes": ["..."]}}"""

def judge(ref, cmp, sheet, model="sonnet"):
    out = subprocess.run(["claude", "-p", "--model", model, JUDGE_PROMPT.format(ref=os.path.abspath(ref), cmp=os.path.abspath(cmp), sheet=os.path.abspath(sheet)),
                          "--allowedTools", "Read", "--output-format", "json"], capture_output=True, text=True, timeout=600).stdout
    cost, used = None, None
    try: env = json.loads(out); out = env.get("result", ""); cost = env.get("total_cost_usd"); used = list(env.get("modelUsage", {}).keys())
    except Exception: pass
    s = out[out.find("{"): out.rfind("}")+1]
    try: r = json.loads(s)
    except Exception: r = {"raw": out}
    r["_cost_usd"] = cost; r["_models"] = used; return r

def score(ref, model, out, azim=None, elev=None, fit=False, use_judge=False):
    ref_img = Image.open(ref); d, occ, col, warn = vox.load(model)
    cam = d.get("camera", {})
    if azim is None: azim = cam.get("azim", 30)
    if elev is None: elev = cam.get("elev", 20)
    if fit: azim, elev = fit_camera(ref_img, occ, col, azim, elev)
    v, img, (rr, rm, vr, vm) = view_metrics(ref_img, occ, col, azim, elev)
    c = craft_metrics(occ, col); mv = multiview_ok(occ, col)
    tot, parts = total_score(v, c, mv)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cmp = composite(ref_img, img, rr, rm, vr, vm, out + "_compare.png", f"{d.get('name','')} auto={tot} cam=({azim},{elev})")
    sh = vox.sheet(occ, col, out + "_sheet.png")
    img.save(out + "_render.png")
    res = {"model": model, "reference": ref, "camera": {"azim": azim, "elev": elev}, "auto_total": tot, "auto_parts": parts,
           "view": v, "craft": c, "multiview_min_area_ratio": mv, "warnings": warn[:10],
           "files": {"compare": cmp, "sheet": sh, "render": out + "_render.png"}}
    if use_judge: res["judge"] = judge(ref, cmp, sh)
    res.update(geometric_detail(model))
    json.dump(res, open(out + "_score.json", "w"), indent=2); return res

def geometric_detail(model):
    """Shape-detail metrics (detail_metrics.py) for Minecraft-block models, reported next to the colour rubric. The rubric's
    'detail density' is colour-only; this is what tells a flat build from one with cornices, hoods, panes and walls.
    Works on an mc_blocks JSON or on the *_mc_blocks.json that sits next to a baked/fine model."""
    import detail_metrics
    path = model if isinstance(model, str) else None
    if path and not path.endswith("_mc_blocks.json"):
        path = path.replace("_mc_baked_fine.json", "_mc_blocks.json")
    if not path or not path.endswith("_mc_blocks.json") or not os.path.exists(path): return {}
    m = detail_metrics.metrics(detail_metrics.cells_of(path))
    return {"geometric_detail": m, "geometric_detail_target": detail_metrics.TARGET}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("ref"); ap.add_argument("model"); ap.add_argument("--out", default="out/score")
    ap.add_argument("--azim", type=float); ap.add_argument("--elev", type=float); ap.add_argument("--fit", action="store_true"); ap.add_argument("--judge", action="store_true")
    a = ap.parse_args(); print(json.dumps(score(a.ref, a.model, a.out, a.azim, a.elev, a.fit, a.judge), indent=2))
