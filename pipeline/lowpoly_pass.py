"""Verified-sheet + Hyper3D low-poly pass: scores, out/verified_lowpoly_gallery.png, final viewer JSONs in art/final/."""
import json, os, shutil, numpy as np
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw
import vox, scorer, run_fal, run_subject
LIGHT = (-0.25, 0.8, 0.55)
FINAL = {"windmill": "windmill_lowpoly", "cottage": "cottage_lowpoly_fbt", "bonsai": "bonsai_lowpoly"}
LP_RUNS = {"windmill": 1, "cottage": 3, "bonsai": 1}     # cottage: front+back (policy v1), all-4 (A/B), front+back+top (final policy)
def R(o, c, a, e, s=512): return vox.render(o, c, a, e, s, light=LIGHT)[0]
def run(n):
    k = FINAL[n]; fine = f"art/{k}_half_sub_fine.json"; ref = f"refs/{n}.jpg"
    _, o, c, _ = vox.load(fine, seed=0); az, el = run_fal.fit_cardinal(Image.open(ref), o, c)
    r = scorer.score(ref, fine, f"out/{k}_half_sub", az, el, fit=False, use_judge=True)
    _, oc, cc, _ = vox.load(f"art/{k}_half_sub.json", seed=0); cm = scorer.craft_metrics(oc, cc); craft = dict(r["craft"])
    for key in ("surface_colour_variation", "unique_surface_colours"): craft[key] = cm[key]
    tot, _ = scorer.total_score(r["view"], craft, r["multiview_min_area_ratio"]); j = r.get("judge", {})
    V = json.load(open(f"out/{n}_verify.json")); rep = json.load(open(f"out/{k}_subblock_report.json"))
    cost = {"sheets": V["sheets_generated"], "sheet_usd": round(0.039*V["sheets_generated"], 3), "lowpoly_runs": LP_RUNS[n], "lowpoly_usd": 0.20*LP_RUNS[n]}
    cost["total_usd"] = round(cost["sheet_usd"] + cost["lowpoly_usd"], 3); cost["pipeline_usd_per_subject"] = round(cost["sheet_usd"] + 0.20, 3)
    return n, {"model": k, "auto": float(tot), "judge": j.get("overall"), "judge_scores": j.get("scores"), "judge_fixes": j.get("fixes"), "camera": [az, el],
               "verify": {"chosen": V["chosen"], "views_used": V["views_used"], "views_dropped": V["views_dropped"]}, "pct_sub": rep["pct_sub_of_all_cells"],
               "by_type": rep["by_type"], "grid": rep["block_grid"], "cost": cost}
with ThreadPoolExecutor(3) as ex: S = dict(ex.map(run, FINAL))
old = json.load(open("out/tuned_pass_scores.json"))
for n in S: S[n]["hunyuan_pro_tuned_pass"] = {"auto": old[n]["auto"], "judge": old[n]["judge"], "cost_usd": round(0.525 + 0.039*(2 if n == "windmill" else 1), 3)}
json.dump(S, open("out/verified_lowpoly_scores.json", "w"), indent=1)
for n, s in S.items(): print(n, s["auto"], s["judge"], s["judge_scores"], s["pct_sub"], s["verify"], s["cost"], s["hunyuan_pro_tuned_pass"])
# gallery
Sz = 230; Wd = 6*Sz + 5*10 + 20; Hr = Sz + 50; G = Image.new("RGB", (Wd, Hr*3 + 10), "white"); dr = ImageDraw.Draw(G)
for i, n in enumerate(FINAL):
    k = FINAL[n]; s = S[n]; _, o, c, _ = vox.load(f"art/{k}_half_sub_fine.json", seed=0)
    items = [("reference photo", run_subject.masked_ref(f"refs/{n}.jpg")), (f"verified sheet {s['verify']['chosen']} (used: {'/'.join(s['verify']['views_used'])})", Image.open(f"ortho/{n}{s['verify']['chosen']}_sheet.png")),
             ("front", R(o, c, 0, 10)), ("side", R(o, c, 90, 10)), ("back", R(o, c, 180, 10)), ("3/4", R(o, c, 35, 25))]
    y = i*Hr + 5
    dr.text((10, y), f"{n} - 3D: Hyper3D low-poly (hyper3d/lowpoly/image-to-3d, $0.20) -> ortho colour -> half size {s['grid'][0]}x{s['grid'][1]}x{s['grid'][2]} "
            f"with slabs/vslabs/stairs ({s['pct_sub']}%)   auto {s['auto']:.1f} / judge {s['judge']}/10", fill="black")
    for j, (lab, im) in enumerate(items):
        im = im.convert("RGB"); im.thumbnail((Sz, Sz)); x = 10 + j*(Sz+10)
        G.paste(im, (x + (Sz-im.width)//2, y + 18 + (Sz-im.height)//2)); dr.text((x, y + Sz + 22), lab, fill="gray")
G.save("out/verified_lowpoly_gallery.png")
# final viewer files
os.makedirs("art/final", exist_ok=True)
for n, k in FINAL.items():
    d = json.load(open(f"art/{k}_half_sub.json")); s = S[n]
    d.update({"name": f"{n}_voxels_subblocks", "source": {"pipeline": "verified nano-banana ortho sheet -> Hyper3D low-poly -> ortho colour + tone -> half-size sub-blocks",
              "sheet": f"ortho/{n}{s['verify']['chosen']}_sheet.png", "views_used": s["verify"]["views_used"], "model_key": k}})
    json.dump(d, open(f"art/final/{n}_voxels_subblocks.json", "w"))
    shutil.copy(f"art/{k}_half_sub_fine.json", f"art/final/{n}_voxels_subblocks_fine.json")
print("ok")
