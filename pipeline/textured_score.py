"""Score the textured pass (auto + Sonnet judge) and compare with the current finals -> out/textured_pass_scores.json"""
import json, numpy as np
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import vox, scorer, run_fal
def run(n):
    fine = f"art/final/{n}_voxels_textured_fine.json"; ref = f"refs/{n}.jpg"
    _, o, c, _ = vox.load(fine, seed=0); az, el = run_fal.fit_cardinal(Image.open(ref), o, c)
    r = scorer.score(ref, fine, f"out/{n}_textured", az, el, fit=False, use_judge=True)
    _, oc, cc, _ = vox.load(f"art/final/{n}_voxels_textured.json", seed=0); cm = scorer.craft_metrics(oc, cc); craft = dict(r["craft"])
    for key in ("surface_colour_variation", "unique_surface_colours"): craft[key] = cm[key]
    tot, _ = scorer.total_score(r["view"], craft, r["multiview_min_area_ratio"]); j = r.get("judge", {})
    return n, {"auto": round(float(tot), 1), "judge": j.get("overall"), "judge_scores": j.get("scores"), "judge_fixes": j.get("fixes"), "camera": [az, el]}
with ThreadPoolExecutor(3) as ex: S = dict(ex.map(run, ["windmill", "cottage", "bonsai"]))
lp = json.load(open("out/verified_lowpoly_scores.json")); tp = json.load(open("out/tuned_pass_scores.json"))
for n in S: S[n]["before_final_lowpoly"] = {"auto": lp[n]["auto"], "judge": lp[n]["judge"]}
S["bonsai"]["before_same_shape_hunyuan_t"] = {k: tp["bonsai"].get(k) for k in ("auto", "judge")}
json.dump(S, open("out/textured_pass_scores.json", "w"), indent=1)
for n, s in S.items(): print(n, s["auto"], s["judge"], s["judge_scores"], "| before", s["before_final_lowpoly"], s.get("before_same_shape_hunyuan_t", ""))
