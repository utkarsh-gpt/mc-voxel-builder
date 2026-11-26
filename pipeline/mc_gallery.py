"""out/mc_blocks_gallery.png: reference | previous textured pass colours (3/4) | NEW Minecraft-block pass with real block textures (front, side, back, 3/4)."""
import json, numpy as np
from PIL import Image, ImageDraw
import vox, mc_render
def _fine(n):
    """4x render grid, built on demand (palette_generic only writes it with --fine)"""
    import os, subblock; p = f"art/final/{n}_voxels_textured_fine.json"
    if not os.path.exists(p): subblock.expand(f"art/final/{n}_voxels_textured.json", p)
    return p
LIGHT = (-0.25, 0.8, 0.55); VIEWS = [("front", 0, 10), ("side", 90, 10), ("back", 180, 10), ("3/4", 35, 25)]
S = 300; SUBJ = ["windmill", "cottage", "bonsai"]
G = Image.new("RGB", (10 + 6*(S+10), 30 + len(SUBJ)*(S+40)), "white"); dr = ImageDraw.Draw(G)
dr.text((10, 8), "Minecraft block pass (mc_map.py, real 26.3 block textures). Left: reference photo, then the previous textured pass's colours (3/4).", fill="black")
for i, n in enumerate(SUBJ):
    y = 30 + i*(S+40); d = json.load(open(f"art/final/{n}_mc_blocks.json"))
    ref = Image.open(f"refs/{n}.jpg").convert("RGB"); ref.thumbnail((S, S)); G.paste(ref, (10 + (S-ref.width)//2, y + (S-ref.height)//2)); dr.text((10, y+S+4), f"{n} reference", fill="gray")
    _, o, c, _ = vox.load(_fine(n), seed=0); im, _ = vox.render(o, c, 35, 25, 2*S, light=LIGHT); im.thumbnail((S, S))
    x = 10 + (S+10); G.paste(im, (x + (S-im.width)//2, y + (S-im.height)//2)); dr.text((x, y+S+4), "previous: textured colours (3/4)", fill="gray")
    nids = len({p["id"] for p in d["palette"].values()})
    for j, (vn, a, e) in enumerate(VIEWS):
        im, _ = mc_render.render(d, a, e, 2*S, light=LIGHT); im.thumbnail((S, S)); x = 10 + (j+2)*(S+10)
        G.paste(im, (x + (S-im.width)//2, y + (S-im.height)//2)); dr.text((x, y+S+4), f"MC blocks {vn} ({nids} block types)", fill="gray")
G.save("out/mc_blocks_gallery.png"); print("ok")
