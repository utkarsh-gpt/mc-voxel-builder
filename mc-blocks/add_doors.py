"""Re-admit doors (feature pass: real 2-tall doors in detected door openings). Each door copies the metadata of its
trapdoor of the same wood/metal and gets colour stats from its lower-half texture composited over a dark interior.
textures: side = lower half (door_bottom), side_upper = upper half (door_top); top/bottom = the leaf edge.
Never base-block candidates (mc_map.allowed() requires full blocks). Re-runnable (idempotent). Needs assets/assets/minecraft."""
import json, copy
import numpy as np
from PIL import Image
from skimage import color as skc
A = "assets/assets/minecraft"
B = json.load(open("blocks.json")); E = json.load(open("excluded.json"))
BL = {b["id"]: b for b in B["blocks"]}
def stats(tex, backdrop=(40, 32, 24)):
    im = np.asarray(Image.open(f"{A}/textures/block/{tex}.png").convert("RGBA")).astype(float)[:16]
    a = im[..., 3:4]/255; rgb = im[..., :3]*a + np.array(backdrop)*(1 - a)
    lab = skc.rgb2lab(rgb.reshape(1, -1, 3)/255)[0]; m = lab.mean(0); s = rgb.reshape(-1, 3).mean(0).round().astype(int)
    return {"srgb": s.tolist(), "hex": "#%02X%02X%02X" % tuple(s), "lab": [round(float(v), 3) for v in m], "brightness_L": round(float(m[0]), 3),
            "l_stddev": round(float(lab[:, 0].std()), 3)}, bool((a < 1).any())
added = []
for td in [b for b in B["blocks"] if b["shape"] == "trapdoor" and not b["id"].startswith("waxed_")]:
    did = td["id"].replace("_trapdoor", "_door")
    import os
    if not os.path.exists(f"{A}/textures/block/{did}_bottom.png"): continue
    d = copy.deepcopy(td); d.update(id=did, display_name=td["display_name"].replace("Trapdoor", "Door"), shape="door", subfamily="door",
                                    model=f"minecraft:block/{did}_bottom_left", state={"facing": "north", "half": "lower", "hinge": "left", "open": "false"})
    lo, cut = stats(f"{did}_bottom"); up, cut2 = stats(f"{did}_top")
    d["textures"] = {"top": [f"minecraft:block/{did}_bottom"], "side": [f"minecraft:block/{did}_bottom"], "bottom": [f"minecraft:block/{did}_bottom"],
                     "side_upper": [f"minecraft:block/{did}_top"]}
    for k in ("overall",): d[k].update(lo); d[k]["has_cutout"] = cut or cut2
    d["faces"] = {f: dict(d["faces"].get(f, {}), **lo) for f in ("top", "side", "bottom")}; d["faces"]["side_upper"] = up
    d["has_cutout"] = cut or cut2
    if did in BL: B["blocks"][[b["id"] for b in B["blocks"]].index(did)] = d
    else: B["blocks"].append(d)
    added.append(did)
ex = [e for e in E["blocks"] if e["id"] not in added]
if len(ex) != len(E["blocks"]):
    E["blocks"] = ex; E["count"] = len(ex)
    E["by_reason"] = {k: v for k, v in ((k, sum(1 for e in ex if e["reason"] == k)) for k in E["by_reason"]) if v}
    json.dump(E, open("excluded.json", "w"), indent=1)
json.dump(B, open("blocks.json", "w"), indent=1)
print("doors:", len(added), added)
