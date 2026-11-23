"""Second opinion (sonnet) on views dropped ONLY by the haiku check (geometric checks did not flag them). Updates out/NAME_verify.json views_used."""
import json, sys
from concurrent.futures import ThreadPoolExecutor
import ortho_verify as ov
def run(n):
    V = json.load(open(f"out/{n}_verify.json")); att = next(a for a in V["attempts"] if a["tag"] == V["chosen"])
    geo = att.get("geo_recheck_after_frame_fix", att["geo"]); geo_bad = set(geo["bad_views"])
    llm_only = [v for v in att["llm"].get("bad_views", []) if v in ov.VIEWS and v not in geo_bad and v != "front"]
    why = " ".join(att["llm"].get("issues", []))
    conf = {v: ov.confirm_view(n, n + V["chosen"], v, why) for v in llm_only}
    drop = sorted((geo_bad - {"front"}) | {v for v, c in conf.items() if c.get("unusable")})
    V.update({"views_used_haiku_only": V["views_used"], "sonnet_confirm": conf, "geo_bad_after_fix": sorted(geo_bad),
              "views_used": [v for v in ov.VIEWS if v not in drop], "views_dropped": drop})
    json.dump(V, open(f"out/{n}_verify.json", "w"), indent=1); return n, V["views_used"], {v: (c.get("unusable"), c.get("reason", "")[:200]) for v, c in conf.items()}
with ThreadPoolExecutor(3) as ex:
    for r in ex.map(run, sys.argv[1:] or ["windmill", "cottage", "bonsai"]): print(r)
