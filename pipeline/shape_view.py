"""Render shape-voxel JSON (shape_fit.py output, or subblock.py *_sub.json) with mc_render's painter, flat-shaded.
mode "shape": colour by shape type (legend below); mode "colour": the voxel's own colour.
usage: python shape_view.py OUT.png "label" model.json [...]   (one row of 4 views per model)"""
import sys, json, contextlib
import numpy as np
from PIL import Image, ImageDraw
import mc_render, shape_fit

SHAPE_COL = {"full": (205, 205, 205), "slab_half": (120, 170, 235), "slab_quarter": (50, 95, 200), "vslab_half": (150, 215, 150),
             "vslab_quarter": (60, 150, 70), "stairs": (245, 175, 90), "stairs_corner": (225, 105, 55), "wall": (200, 90, 205), "fence": (125, 80, 40)}

def shape_key(s):
    if not s: return "full"
    t = s["type"]
    if t in ("slab", "vslab"): return t + ("_half" if s.get("size", 0.5) >= 0.5 else "_quarter")
    if t == "stairs": return "stairs" if s.get("shape", "straight") == "straight" else "stairs_corner"
    return t

def _tex(rgb):
    a = np.zeros((16, 16, 4), np.uint8); a[..., :3] = rgb; a[..., 3] = 255
    d = (np.array(rgb)*0.8).astype(np.uint8); a[0, :, :3] = d; a[-1, :, :3] = d; a[:, 0, :3] = d; a[:, -1, :3] = d
    return Image.fromarray(a, "RGBA")

def to_mc(d, mode="shape"):
    """fake mc_blocks dict: palette id = shape json, props carry the colour"""
    pal, idx, vox = {}, {}, []
    for v in d["voxels"]:
        s = v.get("s"); rgb = SHAPE_COL[shape_key(s)] if mode == "shape" else tuple(int(d["palette"][v["c"]][i:i+2], 16) for i in (1, 3, 5))
        k = json.dumps([s, rgb]); b = idx.setdefault(k, f"b{len(idx)}"); pal[b] = {"id": k, "props": {}}
        vox.append({"x": v["x"], "y": v["y"], "z": v["z"], "b": b})
    return {"size": d["size"], "palette": pal, "voxels": vox}

@contextlib.contextmanager
def patched():
    o = (mc_render.boxes, mc_render.blocks, mc_render.face_tex); cache = {}
    class Fake(dict):
        def __missing__(self, k): return {"shape": "x", "has_cutout": False}
    def boxes(bid, props): return shape_fit.boxes01(json.loads(bid)[0])
    def face_tex(bid, face):
        if bid not in cache: cache[bid] = _tex(tuple(json.loads(bid)[1]))
        return cache[bid]
    mc_render.boxes, mc_render.blocks, mc_render.face_tex = boxes, (lambda: Fake()), face_tex
    try: yield
    finally: mc_render.boxes, mc_render.blocks, mc_render.face_tex = o

def render(d, azim=35, elev=25, size=512, mode="shape", light=(-0.25, 0.8, 0.55)):
    d = json.load(open(d)) if isinstance(d, str) else d
    with patched(): return mc_render.render(to_mc(d, mode), azim, elev, size, light=light)

VIEWS = [("3/4", 35, 25), ("front", 0, 5), ("side", 90, 5), ("back 3/4", 215, 30)]
def strip(out, pairs, S=330, mode="shape", views=VIEWS):
    G = Image.new("RGB", (10 + len(views)*(S+10), len(pairs)*(S+40) + 40), "white"); dr = ImageDraw.Draw(G)
    for i, (lab, path) in enumerate(pairs):
        d = json.load(open(path)); y = 10 + i*(S+40)
        dr.text((10, y), f"{lab}  |  {d['size'][0]}x{d['size'][1]}x{d['size'][2]}, {len(d['voxels'])} blocks", fill="black")
        for j, (vn, a, e) in enumerate(views):
            im, _ = render(d, a, e, 2*S, mode); im.thumbnail((S, S)); x = 10 + j*(S+10)
            G.paste(im, (x + (S-im.width)//2, y + 16 + (S-im.height)//2)); dr.text((x, y + S + 20), vn, fill="gray")
    x = 10; y = G.height - 22
    if mode == "shape":
        for k, c in SHAPE_COL.items(): dr.rectangle((x, y, x+12, y+12), fill=c, outline="black"); dr.text((x+16, y), k, fill="black"); x += 22 + 7*len(k)
    G.save(out); print(out)

if __name__ == "__main__":
    a = sys.argv[1:]; mode = "shape"
    if "--colour" in a: a.remove("--colour"); mode = "colour"
    strip(a[0], list(zip(a[1::2], a[2::2])), mode=mode)
