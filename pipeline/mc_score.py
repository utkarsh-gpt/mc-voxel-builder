"""Score the Minecraft-block pass (auto + optional Sonnet judge) vs the previous textured pass -> out/mc_blocks_scores.json
The scorer renders the 4x baked colour grid (block textures downsampled to 4x4 per face); craft colour metrics use the block grid
(one colour per block = the block's dataset colour), like the earlier sub-block correction."""
import json, sys, numpy as np
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import vox, scorer, run_fal, mc_render
JUDGE = "--judge" in sys.argv
SUBJ = [a for a in sys.argv[1:] if not a.startswith("--")] or ["windmill", "cottage", "bonsai"]
OUT = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), None)   # e.g. --out=out/new_set_scores.json
def block_grid(n):
    d = json.load(open(f"art/final/{n}_mc_blocks.json")); B = mc_render.blocks(); pal = {}
    vs = []
    for v in d["voxels"]:
        h = B[d["palette"][v["b"]]["id"]]["overall"]["hex"]; vs.append({"x": v["x"], "y": v["y"], "z": v["z"], "c": pal.setdefault(h, f"c{len(pal)}")})
    p = f"/tmp/{n}_mc_blockgrid.json"; json.dump({"size": d["size"], "palette": {k: h for h, k in pal.items()}, "voxels": vs}, open(p, "w")); return p
def run(n):
    fine = f"art/final/meta/{n}_mc_baked_fine.json"; ref = f"refs/{n}.jpg"
    _, o, c, _ = vox.load(fine, seed=0); az, el = run_fal.fit_cardinal(Image.open(ref), o, c)
    r = scorer.score(ref, fine, f"out/{n}_mc_blocks", az, el, fit=False, use_judge=JUDGE)
    _, oc, cc, _ = vox.load(block_grid(n), seed=0); cm = scorer.craft_metrics(oc, cc); craft = dict(r["craft"])
    for key in ("surface_colour_variation", "unique_surface_colours"): craft[key] = cm[key]
    tot, _ = scorer.total_score(r["view"], craft, r["multiview_min_area_ratio"]); j = r.get("judge", {})
    return n, {"auto": round(float(tot), 1), "judge": j.get("overall"), "judge_scores": j.get("scores"), "judge_fixes": j.get("fixes"), "judge_cost_usd": j.get("_cost_usd"), "judge_models": j.get("_models"), "camera": [az, el],
               "view": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r["view"].items() if not isinstance(v, (dict, list))}}
with ThreadPoolExecutor(3) as ex: S = dict(ex.map(run, SUBJ))
prev = json.load(open("out/textured_pass_scores.json"))
for n in S: S[n]["before_textured_pass"] = {"auto": prev[n]["auto"], "judge": prev[n]["judge"]} if n in prev else None
json.dump(S, open(OUT or ("out/mc_blocks_scores.json" if JUDGE else "out/mc_blocks_scores_auto.json"), "w"), indent=1)
for n, s in S.items(): print(n, s["auto"], s["judge"], s["judge_scores"], "| before", s["before_textured_pass"], "| hist", s["view"].get("lab_hist_intersection"), "pixdE", s["view"].get("pixel_deltaE"))
