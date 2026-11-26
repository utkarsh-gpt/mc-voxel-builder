"""Texture noisiness of each material region, measured on the reference photo and the front ortho view.
Region = (material, vertical band). For every region we project the voxels into the image with the fitted camera (id-buffer
render of the block-grid model), then measure on the image pixels that region covers:
  l_std     local L* std-dev inside a 1-voxel window (same unit as the block dataset's l_stddev: L* spread inside one block)
  hf        high-frequency energy share: var(L - blur(L, sigma = voxel/4)) / var(L - blur(L, sigma = voxel))   (fine grain vs blobs)
  scale_vox power-weighted mean wavelength of L inside the region, in voxels (pattern size; < 1 = grain finer than a block)
Output art/final/meta/{n}_noise.json: per region stats + per-voxel 'noise' (photo 0.7 + ortho 0.3, L* units)."""
import json, sys, numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color as skc
import vox, scorer
ORTHO = {"windmill": "ortho/windmill_v2_front.png", "cottage": "ortho/cottage_v3_front.png", "bonsai": "ortho/bonsai_t_front.png"}
def bbox(m): ys, xs = np.nonzero(m); return ys.min(), ys.max()+1, xs.min(), xs.max()+1
def region_ids(L, H):
    """(material, band) -> int id; bands = 3-layer slices within each material's y-range (>= 2 bands only if tall enough)"""
    keys, vid = {}, {}
    ys = {}
    for v in L["voxels"]: ys.setdefault(v["m"], []).append(v["y"])
    rng = {m: (min(y), max(y)) for m, y in ys.items()}           # once per material (was recomputed for every voxel)
    for v in L["voxels"]:
        y0, y1 = rng[v["m"]]; nb = max(1, min(4, (y1 - y0 + 1)//3)); b = min(nb-1, int((v["y"]-y0)*nb/(y1-y0+1)))
        k = (v["m"], b); keys.setdefault(k, len(keys) + 1); vid[(v["x"], v["y"], v["z"])] = keys[k]
    return keys, vid
def measure(img_path, mask, occ, ids, az, el, nvox_h):
    im = Image.open(img_path).convert("RGB"); rgb = np.asarray(im)
    idimg, idm = vox.render(occ, None, az, el, 512, ids=ids)
    idarr = np.asarray(idimg).astype(int); idv = (idarr[..., 0] << 16 | idarr[..., 1] << 8 | idarr[..., 2]); idv = np.where(idm, (idv - 1)//6, -1)
    y0, y1, x0, x1 = bbox(mask); r0, r1, c0, c1 = bbox(idm)
    crop = Image.fromarray(idv[r0:r1, c0:c1].astype(np.int32)).resize((x1-x0, y1-y0), Image.NEAREST)
    full = np.full(mask.shape, -1); full[y0:y1, x0:x1] = np.asarray(crop); full[~mask] = -1
    L = skc.rgb2lab(rgb/255.0)[..., 0]; vpx = (y1 - y0)/nvox_h                 # pixels per voxel
    w = max(3, int(round(vpx)))
    mu = ndimage.uniform_filter(L, w); var = ndimage.uniform_filter(L*L, w) - mu*mu; lstd = np.sqrt(np.clip(var, 0, None))
    fine = L - ndimage.gaussian_filter(L, max(vpx/4, 0.7)); coarse = L - ndimage.gaussian_filter(L, max(vpx, 1.5))
    er = ndimage.binary_erosion(mask, iterations=max(2, w//2))                    # keep away from the silhouette edge
    return full, lstd, fine, coarse, L, er, vpx
def wavelength(L, m, vpx):
    ys, xs = np.nonzero(m)
    if len(ys) < 64: return None
    y0, y1, x0, x1 = ys.min(), ys.max()+1, xs.min(), xs.max()+1; P = np.where(m[y0:y1, x0:x1], L[y0:y1, x0:x1], L[m].mean()) - L[m].mean()
    F = np.abs(np.fft.fft2(P))**2; fy, fx = np.meshgrid(np.fft.fftfreq(P.shape[0]), np.fft.fftfreq(P.shape[1]), indexing="ij"); r = np.hypot(fx, fy); F[0, 0] = 0
    return float(1/((r*F).sum()/(F.sum() + 1e-9) + 1e-9)/vpx)
def run(n):
    T = f"art/final/{n}_voxels_textured.json"; L = json.load(open(f"art/final/meta/{n}_texture_labels.json"))
    _, occ, col, _ = vox.load(T, seed=0); keys, vid = region_ids(L, occ.shape[1])
    ids = np.zeros(occ.shape, int)
    for (x, y, z), i in vid.items(): ids[x, y, z] = i
    import os
    prev = json.load(open("out/textured_pass_scores.json")) if os.path.exists("out/textured_pass_scores.json") else {}   # out/ is not checked in
    if n in prev: cam = prev[n]["camera"]
    else:   # new subjects: fit the photo camera on the textured fine model
        # camera fit on the block grid: the 4x fine model gives the same azimuth/elevation but took ~30 min to render face by face
        import run_fal; _, o_, c_, _ = vox.load(T, seed=0); cam = list(run_fal.fit_cardinal(Image.open(f"refs/{n}.jpg"), o_, c_))
    if n not in ORTHO:   # chosen sheet: out/NAME_verify.json (local runs) or the checked-in art/final/meta/NAME_views.json
        vp = next(p for p in (f"out/{n}_verify.json", f"art/final/meta/{n}_views.json") if os.path.exists(p))
        ORTHO[n] = f"ortho/{n}{json.load(open(vp))['chosen']}_front.png"
    ref = Image.open(f"refs/{n}.jpg"); rmask = scorer.ref_mask(ref)
    om = Image.open(ORTHO[n]).convert("RGB"); oarr = np.asarray(om).astype(int); omask = ndimage.binary_opening((oarr.min(-1) < 235), np.ones((5, 5)))
    nvh = {}
    res = {}
    for src, path, mask, az, el in [("photo", f"refs/{n}.jpg", rmask, cam[0], cam[1]), ("ortho", ORTHO[n], omask, 0, 0)]:
        # visible model height in voxels for this view = rows covered by the id render / voxel scale; use grid H as approximation
        ys_occ = np.nonzero(occ.any((0, 2)))[0]; full, lstd, fine, coarse, Lm, er, vpx = measure(path, mask, occ, ids, az, el, int(ys_occ.max() - ys_occ.min() + 1))
        for k, i in keys.items():
            m = (full == i) & er
            if m.sum() < 30: continue
            hf = float(fine[m].var()/(coarse[m].var() + 1e-9))
            res.setdefault(f"{k[0]}|{k[1]}", {})[src] = {"px": int(m.sum()), "l_std": round(float(np.median(lstd[m])), 2), "hf": round(hf, 3),
                                                          "scale_vox": (lambda s: round(s, 2) if s else None)(wavelength(Lm, m, vpx)), "vox_px": round(vpx, 1)}
    # combine: photo 0.7 + ortho 0.3 (whichever exists); regions unseen in both inherit the material's mean
    mat_mean = {}
    for kk, r in res.items():
        vals = [(0.7, r["photo"]["l_std"])] if "photo" in r else []
        if "ortho" in r: vals.append((0.3, r["ortho"]["l_std"]))
        r["noise"] = round(sum(w*v for w, v in vals)/sum(w for w, _ in vals), 2); mat_mean.setdefault(kk.split("|")[0], []).append(r["noise"])
    per_vox = []
    for (x, y, z), i in vid.items():
        k = next(kk for kk, ii in keys.items() if ii == i); kk = f"{k[0]}|{k[1]}"
        nz = res[kk]["noise"] if kk in res else (float(np.mean(mat_mean[k[0]])) if k[0] in mat_mean else None)
        per_vox.append({"x": x, "y": y, "z": z, "region": kk, "noise": nz})
    out = {"subject": n, "camera_photo": cam, "regions": res, "material_mean_noise": {m: round(float(np.mean(v)), 2) for m, v in mat_mean.items()}, "voxels": per_vox}
    open(f"art/final/meta/{n}_noise.json", "w").write(json.dumps(out))
    print(n, json.dumps(out["material_mean_noise"])); 
    for kk, r in sorted(res.items()): print("  ", kk, r.get("photo"), "| ortho", r.get("ortho"), "->", r["noise"])
for n in sys.argv[1:] or ["windmill", "cottage", "bonsai"]: run(n)
