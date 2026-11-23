import json, os
from PIL import Image, ImageDraw
import run_subject, vox
names = ["cottage", "lighthouse", "windmill", "teapot", "bonsai", "lantern", "mushroom"]
S = 260; rows = []
for n in names:
    ref = f"refs/{n}.jpg"; model = f"art/{n}_refined.json" if n != "mushroom" else "art/mushroom_v2_refined2.json"
    if not os.path.exists(model): continue
    sc = json.load(open(f"out/{n}_refined_score.json" if n != "mushroom" else "out/mushroom_refined2_score.json"))
    d, occ, col, _ = vox.load(model); az = sc["camera"]["azim"]
    alt = vox.render(occ, col, az + 135, 25, 512)[0]
    j = sc.get("judge", {}).get("overall", "-")
    rows.append((n, sc["auto_total"], j, [run_subject.masked_ref(ref), Image.open(sc["files"]["render"]), alt]))
G = Image.new("RGB", (3*S + 40 + 150, len(rows)*(S+10) + 30), "white"); dr = ImageDraw.Draw(G)
dr.text((160, 8), "reference (masked)", fill="black"); dr.text((160+S+10, 8), "voxel, reference camera", fill="black"); dr.text((160+2*(S+10), 8), "voxel, opposite angle", fill="black")
for r, (n, au, j, ims) in enumerate(rows):
    y = 30 + r*(S+10); dr.text((8, y+S//2-10), f"{n}\nauto {au}\njudge {j}/10", fill="black")
    for i, im in enumerate(ims):
        im = im.convert("RGB"); im.thumbnail((S, S)); G.paste(im, (160+i*(S+10)+(S-im.width)//2, y+(S-im.height)//2))
G.save("out/gallery.png"); print("out/gallery.png", len(rows))
