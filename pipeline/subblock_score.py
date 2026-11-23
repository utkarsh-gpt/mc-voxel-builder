import json
from concurrent.futures import ThreadPoolExecutor
import scorer
cams = json.load(open("out/ortho_rendered_scores.json"))
jobs = [(n, v) for n in ("windmill", "cottage", "bonsai") for v in ("half_full", "half_sub_fine")]
def run(j):
    n, v = j; az, el = cams[n]["camera"]
    r = scorer.score(f"refs/{n}.jpg", f"art/{n}_{v}.json", f"out/{n}_{v}", az, el, fit=False, use_judge=True)
    jj = r.get("judge", {}); return f"{n}/{v}", {"auto": float(r["auto_total"]), "judge": jj.get("overall"), "judge_scores": jj.get("scores"), "fixes": jj.get("fixes")}
with ThreadPoolExecutor(6) as ex: S = dict(ex.map(run, jobs))
for n in ("windmill", "cottage", "bonsai"): S[f"{n}/full_size_toned"] = {"auto": cams[n]["auto"], "judge": cams[n]["judge"]}
json.dump(S, open("out/subblock_scores.json", "w"), indent=1)
for k, v in S.items(): print(k, v["auto"], v["judge"], v.get("judge_scores"))
