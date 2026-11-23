"""out/subblock_gallery.png: per subject rows [full-size full blocks | half-size full blocks | half-size + sub-blocks] x (front, side, 3/4)
plus silhouette IoU of each half-size version vs the full-size render (same views)."""
import json, sys, numpy as np
from PIL import Image, ImageDraw
import vox
LIGHT = (-0.25, 0.8, 0.55); VIEWS = [("front", 0, 10), ("side", 90, 10), ("3/4", 35, 25)]
SUBJ = sys.argv[1:] or ["windmill", "cottage", "bonsai"]
def R(path, a, e, s=480):
    d, o, c, _ = vox.load(path, seed=0); return vox.render(o, c, a, e, s, light=LIGHT)
def crop_mask(m):
    ys, xs = np.nonzero(m); return m[ys.min():ys.max()+1, xs.min():xs.max()+1]
def iou(a, b):
    from skimage.transform import resize
    a, b = crop_mask(a), crop_mask(b); b = resize(b.astype(float), a.shape, order=1) > .5; return float((a & b).sum()/(a | b).sum())
S = 200; rows = []; M = {}
for n in SUBJ:
    variants = [("full size, full blocks", f"art/{n}_rendered_toned.json"), ("half size, full blocks", f"art/{n}_half_full.json"),
                ("half size + sub-blocks", f"art/{n}_half_sub_fine.json")]
    rep = json.load(open(f"out/{n}_subblock_report.json")); M[n] = {}
    for label, path in variants:
        ims = []; ious = []
        for vn, a, e in VIEWS:
            im, m = R(path, a, e); ims.append((f"{vn}", im))
            if label.startswith("full"): M[n].setdefault("ref_masks", {})[vn] = m
            else: ious.append(iou(M[n]["ref_masks"][vn], m))
        t = f"{n} - {label}"
        if ious: t += f"   silhouette IoU vs full-size: {np.mean(ious):.3f}"; M[n][label] = round(float(np.mean(ious)), 3)
        if "sub" in label: t += f"   ({rep['pct_sub_of_all_cells']}% of blocks are sub-blocks)"
        rows.append((t, ims))
    del M[n]["ref_masks"]
json.dump(M, open("out/subblock_silhouette_iou.json", "w"), indent=1); print(M)
S = 170; per = 3; rowsN = len(SUBJ); Wd = 9*S + 8*6 + 3*14 + 20; Hr = S + 58
G = Image.new("RGB", (Wd, Hr*rowsN + 30), "white"); dr = ImageDraw.Draw(G)
heads = ["FULL SIZE, full blocks", "HALF SIZE, full blocks only", "HALF SIZE + sub-blocks (slab/vslab/stairs)"]
for k, h in enumerate(heads): dr.text((10 + k*(3*S+2*6+14), 6), h, fill="black")
for si_, n in enumerate(SUBJ):
    y = 24 + si_*Hr; rep = json.load(open(f"out/{n}_subblock_report.json"))
    dr.text((10, y), f"{n}:  half-size silhouette IoU vs full size - full blocks {M[n]['half size, full blocks']:.3f}, sub-blocks {M[n]['half size + sub-blocks']:.3f};  "
            f"grid {rep['full_size_grid']} -> {rep['block_grid']};  sub-blocks {rep['pct_sub_of_all_cells']}% of blocks", fill="black")
    for k in range(3):
        for j, (lab, im) in enumerate(rows[si_*3 + k][1]):
            im = im.convert("RGB"); im.thumbnail((S, S)); x = 10 + k*(3*S+2*6+14) + j*(S+6)
            G.paste(im, (x + (S-im.width)//2, y + 16 + (S-im.height)//2)); dr.text((x, y + S + 20), lab, fill="gray")
G.save("out/subblock_gallery.png"); print("ok")
