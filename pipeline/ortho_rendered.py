"""8-angle turntables, scorer (+Sonnet judge) and out/ortho_rendered_gallery.png for art/<n>_rendered.json"""
import json, os, numpy as np
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw
import vox, run_subject, run_fal, scorer
LIGHT = (-0.25, 0.8, 0.55)   # top-front key light
SUBJ = [("windmill", ""), ("cottage", ""), ("bonsai", "_v2")]
def R(occ, col, a, e, s=512): return vox.render(occ, col, a, e, s, light=LIGHT)[0]
def one(n, tag):
    model = f"art/{n}_rendered_toned.json"; ref = f"refs/{n}.jpg"; d, occ, col, _ = vox.load(model)
    run_subject.label_strip([(f"azim {a}", R(occ, col, a, 18)) for a in range(0, 360, 45)], f"out/{n}_rendered_turntable.png", 240)
    az, el = run_fal.fit_cardinal(Image.open(ref), occ, col)
    dd = json.load(open(model)); dd["camera"] = {"azim": az, "elev": el}; json.dump(dd, open(model, "w"))
    r = scorer.score(ref, model, f"out/{n}_rendered_toned", az, el, fit=False, use_judge=True)
    h = scorer.score(ref, f"art/{n}_hymv.json", f"out/{n}_hymv", az, el, fit=False)   # Hunyuan texture only, same camera
    old = json.load(open(f"out/{n}_fal_summary.json")) if os.path.exists(f"out/{n}_fal_summary.json") else {}
    j = r.get("judge", {})
    return n, {"camera": [az, el], "auto": r["auto_total"], "judge": j.get("overall"), "judge_scores": j.get("scores"), "judge_fixes": j.get("fixes"),
               "hymv_texture_auto": h["auto_total"], "old_claude_refined": [old.get("old_auto"), old.get("old_judge")],
               "old_trellis_refined": [old.get("new_auto"), old.get("new_judge")]}
with ThreadPoolExecutor(3) as ex: S = dict(ex.map(lambda a: one(*a), SUBJ))
json.dump(S, open("out/ortho_rendered_scores.json", "w"), indent=1)
for n, s in S.items(): print(n, {k: v for k, v in s.items() if k != "judge_fixes"})
Sz = 230; rows = []
for n, tag in SUBJ:
    d, occ, col, _ = vox.load(f"art/{n}_rendered_toned.json")
    rows.append((f"{n} - Hunyuan3D-MV shape, coloured from ortho drawings + toned to photo   auto {S[n]['auto']} / judge {S[n]['judge']}/10",
        [("reference", run_subject.masked_ref(f"refs/{n}.jpg")), ("ortho sheet (nano-banana)", Image.open(f"ortho/{n}{tag}_sheet.png")),
         ("rendered front", R(occ, col, 0, 10)), ("rendered side", R(occ, col, 90, 10)), ("rendered back", R(occ, col, 180, 10)), ("rendered 3/4", R(occ, col, 35, 25))]))
Wd = 6*Sz + 5*10 + 20; Hr = Sz + 50; G = Image.new("RGB", (Wd, Hr*len(rows) + 10), "white"); dr = ImageDraw.Draw(G)
for i, (t, items) in enumerate(rows):
    y = i*Hr + 5; dr.text((10, y), t, fill="black")
    for j, (lab, im) in enumerate(items):
        im = im.convert("RGB"); im.thumbnail((Sz, Sz)); x = 10 + j*(Sz+10)
        G.paste(im, (x + (Sz-im.width)//2, y + 18 + (Sz-im.height)//2)); dr.text((x, y + Sz + 22), lab, fill="gray")
G.save("out/ortho_rendered_gallery.png"); print("ok")
