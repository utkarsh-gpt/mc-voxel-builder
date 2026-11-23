"""Tuned pass: score (auto + Sonnet judge) the half-size sub-block models and build out/tuned_pass_gallery.png
rows: reference | tuned ortho sheet | half-size sub-block front | side | back | 3/4"""
import json, numpy as np
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw
import vox, scorer, run_fal, run_subject
LIGHT = (-0.25, 0.8, 0.55)
SUBJ = [("windmill", "windmill_t2"), ("cottage", "cottage_t"), ("bonsai", "bonsai_t")]
def R(o, c, a, e, s=512): return vox.render(o, c, a, e, s, light=LIGHT)[0]
def run(sk):
    n, k = sk; fine = f"art/{k}_half_sub_fine.json"; ref = f"refs/{n}.jpg"
    _, o, c, _ = vox.load(fine, seed=0); az, el = run_fal.fit_cardinal(Image.open(ref), o, c)
    r = scorer.score(ref, fine, f"out/{k}_half_sub", az, el, fit=False, use_judge=True)
    _, oc, cc, _ = vox.load(f"art/{k}_half_sub.json", seed=0); cm = scorer.craft_metrics(oc, cc); craft = dict(r["craft"])
    for key in ("surface_colour_variation", "unique_surface_colours"): craft[key] = cm[key]     # colour detail from the block grid, not the 4x expansion
    tot, parts = scorer.total_score(r["view"], craft, r["multiview_min_area_ratio"])
    j = r.get("judge", {}); rep = json.load(open(f"out/{k}_subblock_report.json"))
    return n, {"model": f"art/{k}_half_sub.json", "camera": [az, el], "auto": float(tot), "judge": j.get("overall"), "judge_scores": j.get("scores"),
               "judge_fixes": j.get("fixes"), "pct_sub": rep["pct_sub_of_all_cells"], "by_type": rep["by_type"], "grid": rep["block_grid"]}
with ThreadPoolExecutor(3) as ex: S = dict(ex.map(run, SUBJ))
json.dump(S, open("out/tuned_pass_scores.json", "w"), indent=1)
for n, s in S.items(): print(n, s["auto"], s["judge"], s["judge_scores"], s["pct_sub"], s["grid"])
Sz = 230; Wd = 6*Sz + 5*10 + 20; Hr = Sz + 50; G = Image.new("RGB", (Wd, Hr*len(SUBJ) + 10), "white"); dr = ImageDraw.Draw(G)
for i, (n, k) in enumerate(SUBJ):
    _, o, c, _ = vox.load(f"art/{k}_half_sub_fine.json", seed=0); s = S[n]
    items = [("reference photo", run_subject.masked_ref(f"refs/{n}.jpg")), ("tuned ortho sheet", Image.open(f"ortho/{k}_sheet.png")),
             ("front", R(o, c, 0, 10)), ("side", R(o, c, 90, 10)), ("back", R(o, c, 180, 10)), ("3/4", R(o, c, 35, 25))]
    y = i*Hr + 5
    dr.text((10, y), f"{n} - tuned sheet -> Hunyuan3D-MV -> ortho colour -> half size {s['grid'][0]}x{s['grid'][1]}x{s['grid'][2]} with slabs/vslabs/stairs "
            f"({s['pct_sub']}% sub-blocks)   auto {s['auto']:.1f} / judge {s['judge']}/10", fill="black")
    for j, (lab, im) in enumerate(items):
        im = im.convert("RGB"); im.thumbnail((Sz, Sz)); x = 10 + j*(Sz+10)
        G.paste(im, (x + (Sz-im.width)//2, y + 18 + (Sz-im.height)//2)); dr.text((x, y + Sz + 22), lab, fill="gray")
G.save("out/tuned_pass_gallery.png"); print("ok")
