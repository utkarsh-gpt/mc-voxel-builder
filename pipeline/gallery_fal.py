import json
from PIL import Image, ImageDraw
import run_subject, run_fal, vox
names = ["mushroom", "cottage", "lighthouse", "windmill", "teapot", "bonsai", "lantern"]
S = 260; rows = []
for n in names:
    s = json.load(open(f"out/{n}_fal_summary.json")); om, osc = run_fal.old_paths(n); o = json.load(open(osc))
    _, oo, oc, _ = vox.load(om); _, no, nc, _ = vox.load(f"art/{n}_fal_refined.json"); cam = s["camera"]
    rows.append((n, s, [run_subject.masked_ref(f"refs/{n}.jpg"), vox.render(oo, oc, o["camera"]["azim"], o["camera"]["elev"], 512)[0],
                        vox.render(no, nc, cam["azim"], cam["elev"], 512)[0], vox.render(no, nc, cam["azim"]+180, 20, 512)[0]]))
G = Image.new("RGB", (4*(S+10)+170, len(rows)*(S+10)+30), "white"); dr = ImageDraw.Draw(G)
for i, t in enumerate(["reference", "OLD (Claude shape + texture)", "NEW fal Trellis, ref camera", "NEW fal Trellis, back"]):
    dr.text((170+i*(S+10), 8), t, fill="black")
for r, (n, s, ims) in enumerate(rows):
    y = 30+r*(S+10); dr.text((8, y+S//2-24), f"{n}\nold auto {s['old_auto']} / judge {s['old_judge']}\nnew auto {s['new_auto']} / judge {s['new_judge']}", fill="black")
    for i, im in enumerate(ims):
        im = im.convert("RGB"); im.thumbnail((S, S)); G.paste(im, (170+i*(S+10)+(S-im.width)//2, y+(S-im.height)//2))
G.save("out/gallery_fal.png"); print("ok")
