"""out/new_set_mc_blocks_gallery.png: ONLY the new-set Minecraft block pass: reference | MC blocks front, side, back, 3/4 (real 26.3 textures)."""
import json
from PIL import Image, ImageDraw
import mc_render
LIGHT = (-0.25, 0.8, 0.55); VIEWS = [("front", 0, 10), ("side", 90, 10), ("back", 180, 10), ("3/4", 35, 25)]
S = 340; SUBJ = ["cathedral", "landscape", "turtle"]
G = Image.new("RGB", (10 + 5*(S+10), 30 + len(SUBJ)*(S+40)), "white"); dr = ImageDraw.Draw(G)
dr.text((10, 8), "New set - Minecraft block pass (generated reference | MC blocks with real 26.3 textures). Sizes in blocks W x H x D.", fill="black")
for i, n in enumerate(SUBJ):
    y = 30 + i*(S+40); d = json.load(open(f"art/final/{n}_mc_blocks.json"))
    ref = Image.open(f"refs/{n}.jpg").convert("RGB"); ref.thumbnail((S, S)); G.paste(ref, (10 + (S-ref.width)//2, y + (S-ref.height)//2))
    W, H, D = d["size"]; nids = len({p["id"] for p in d["palette"].values()})
    dr.text((10, y+S+4), f"{n} reference (nano-banana)  |  {W}x{H}x{D}, {len(d['voxels'])} blocks, {nids} block types, {d['summary']['stairs']['placed']} stairs", fill="gray")
    for j, (vn, a, e) in enumerate(VIEWS):
        im, _ = mc_render.render(d, a, e, 2*S, light=LIGHT); im.thumbnail((S, S)); x = 10 + (j+1)*(S+10)
        G.paste(im, (x + (S-im.width)//2, y + (S-im.height)//2)); dr.text((x + (S//2 if j == 0 else 0), y+S+4) if False else (x, y+S+18), f"MC blocks {vn}", fill="gray")
G.save("out/new_set_mc_blocks_gallery.png"); print("ok")
