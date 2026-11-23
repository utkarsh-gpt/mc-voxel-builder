"""Turntables + reprojection IoU vs ortho views + out/ortho_gallery.png"""
import json, numpy as np
from PIL import Image, ImageDraw
from skimage.transform import resize
import vox, run_subject, ortho_carve
ROWS = [("windmill", "", "windmill_hymv", "Hunyuan3D-MV"), ("windmill", "", "windmill_ortho", "carve"),
        ("cottage", "", "cottage_ortho", "carve"),
        ("bonsai", "_v2", "bonsai_hymv", "Hunyuan3D-MV"), ("bonsai", "_v2", "bonsai_v2_ortho", "carve")]
def sil(occ, col, az, el=0):
    ids = np.zeros((1,), int); im, idb = vox.render(occ, col, az, el, 400, ids=True)[:2] if False else (None, None)
    a = np.asarray(vox.render(occ, col, az, el, 400)[0].convert("L")) < 250
    ys, xs = np.nonzero(a); return a[ys.min():ys.max()+1, xs.min():xs.max()+1]
def iou(a, b):
    b = resize(b.astype(float), a.shape, order=1) > .5; return (a & b).sum() / (a | b).sum()
rep, S = {}, 230
rows = []
for n, tag, model, how in ROWS:
    d, occ, col, _ = vox.load(f"art/{model}.json")
    views = [(f"azim {a}", vox.render(occ, col, a, 15, 512)[0]) for a in (0, 60, 120, 180, 240, 300)] + \
            [("top el 75", vox.render(occ, col, 30, 75, 512)[0]), ("low el -20", vox.render(occ, col, 30, -20, 512)[0])]
    run_subject.label_strip(views, f"out/{model}_turntable.png", 260)
    m = {k: ortho_carve.mask_of(f"ortho/{n}{tag}_{k}.png")[0] for k in ("front", "right", "back")}
    r = {"front": iou(m["front"], sil(occ, col, 0)), "back": iou(m["back"], sil(occ, col, 180)),
         "side": max(iou(m["right"], sil(occ, col, a)) for a in (90, 270))}
    r["mean"] = float(np.mean(list(r.values()))); rep[model] = {k: round(float(v), 3) for k, v in r.items()}
    print(model, rep[model], "voxels", int(occ.sum()))
    side = max((90, 270), key=lambda a: iou(m["right"], sil(occ, col, a)))
    rows.append((f"{n} - {how}", [("reference", run_subject.masked_ref(f"refs/{n}.jpg")),
        ("ortho sheet (nano-banana)", Image.open(f"ortho/{n}{tag}_sheet.png")),
        ("voxel front", vox.render(occ, col, 0, 8, 512)[0]), ("voxel side", vox.render(occ, col, side, 8, 512)[0]),
        ("voxel back", vox.render(occ, col, 180, 8, 512)[0]), ("voxel 3/4", vox.render(occ, col, 35, 25, 512)[0])]))
json.dump(rep, open("out/ortho_reproj_iou.json", "w"), indent=1)
W = 6*S + 5*10 + 20; Hrow = S + 50
G = Image.new("RGB", (W, Hrow*len(rows) + 10), "white"); dr = ImageDraw.Draw(G)
for i, (title, items) in enumerate(rows):
    y = i*Hrow + 5; dr.text((10, y), title + f"   (reprojection IoU vs ortho views: {rep[ROWS[i][2]]['mean']:.2f})", fill="black")
    for j, (t, im) in enumerate(items):
        im = im.convert("RGB"); im.thumbnail((S, S)); x = 10 + j*(S+10)
        G.paste(im, (x + (S-im.width)//2, y + 18 + (S-im.height)//2)); dr.text((x, y + S + 22), t, fill="gray")
G.save("out/ortho_gallery.png"); print("ok")
