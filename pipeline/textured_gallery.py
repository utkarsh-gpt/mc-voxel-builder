"""out/textured_pass_gallery.png: reference photo | front | side | back | 3/4 of the NEW textured pass only."""
import json, numpy as np
from PIL import Image, ImageDraw
import vox
def _fine(n):
    """4x render grid, built on demand (palette_generic only writes it with --fine)"""
    import os, subblock; p = f"art/final/{n}_voxels_textured_fine.json"
    if not os.path.exists(p): subblock.expand(f"art/final/{n}_voxels_textured.json", p)
    return p
LIGHT = (-0.25, 0.8, 0.55); VIEWS = [("front", 0, 10), ("side", 90, 10), ("back", 180, 10), ("3/4", 35, 25)]
S = 300; SUBJ = ["windmill", "cottage", "bonsai"]
G = Image.new("RGB", (10 + 5*(S+10), 30 + len(SUBJ)*(S+40)), "white"); dr = ImageDraw.Draw(G)
dr.text((10, 8), "Textured pass (palette_texture.py): base colours + brightness ramps + gradient blends. Left: reference photo.", fill="black")
for i, n in enumerate(SUBJ):
    y = 30 + i*(S+40); d = json.load(open(f"art/final/{n}_voxels_textured.json"))
    ref = Image.open(f"refs/{n}.jpg").convert("RGB"); ref.thumbnail((S, S)); G.paste(ref, (10 + (S-ref.width)//2, y + (S-ref.height)//2))
    dr.text((10, y+S+4), f"{n} reference", fill="gray")
    _, o, c, _ = vox.load(_fine(n), seed=0)
    for j, (vn, a, e) in enumerate(VIEWS):
        im, _ = vox.render(o, c, a, e, 2*S, light=LIGHT); im = im.convert("RGB"); im.thumbnail((S, S)); x = 10 + (j+1)*(S+10)
        G.paste(im, (x + (S-im.width)//2, y + (S-im.height)//2)); dr.text((x, y+S+4), f"{vn}  ({len(d['palette'])} colours)", fill="gray")
G.save("out/textured_pass_gallery.png"); print("ok")
