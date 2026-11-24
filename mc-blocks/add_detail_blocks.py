"""Re-admit the detail vocabulary builders use (DETAIL_DISCOVERY.md P0.2): walls, glass panes (+ stained), iron bars, fences.
Walls/fences copy colour + pattern stats from the same-texture full block (like add_stairs.py). Glass panes and bars get colour
stats computed from their RGBA texture composited over a dark interior (#1a1a1a), which is how a window reads in a build.
Shape metadata says how the block connects. They are never base-block candidates (mc_map.allowed() requires full blocks);
mc_map places them through wall_of()/pane_for()/the window kit. Re-runnable (idempotent). Needs assets/assets/minecraft."""
import json, csv, copy
import numpy as np
from PIL import Image
from skimage import color as skc
A = "assets/assets/minecraft"
B = json.load(open("blocks.json")); E = json.load(open("excluded.json"))
DETAIL = ("wall", "pane", "bars", "fence")
blocks = [b for b in B["blocks"] if b["shape"] not in DETAIL]
by_side = {}
for b in blocks:
    if b["shape"] == "full_block": by_side.setdefault(b["textures"]["side"][0].replace("minecraft:", ""), b)
def model(name):
    m = json.load(open(f"{A}/models/block/{name.split('/')[-1]}.json"))
    m["textures"] = {k: (v["sprite"] if isinstance(v, dict) else v) for k, v in m.get("textures", {}).items()}
    return m
def first_model(bid):
    bs = json.load(open(f"{A}/blockstates/{bid}.json"))
    parts = bs.get("multipart") or [{"apply": v} for v in bs["variants"].values()]
    a = parts[0]["apply"]; a = a[0] if isinstance(a, list) else a
    return a["model"].replace("minecraft:", "")
def tex_stats(tex, backdrop=(26, 26, 26)):
    im = np.asarray(Image.open(f"{A}/textures/{tex.replace('minecraft:', '')}.png").convert("RGBA")).astype(float)
    im = im[:im.shape[1]]; a = im[..., 3:4]/255; rgb = im[..., :3]*a + np.array(backdrop)*(1 - a)
    lab = skc.rgb2lab(rgb[None].reshape(1, -1, 3)/255)[0]
    m = lab.mean(0); s = rgb.reshape(-1, 3).mean(0).round().astype(int)
    face = {"srgb": s.tolist(), "hex": "#%02X%02X%02X" % tuple(s), "lab": [round(float(v), 3) for v in m], "l_stddev": round(float(lab[:, 0].std()), 3),
            "alpha_coverage": round(float((im[..., 3] > 127).mean()), 3)}
    return face
FLAGS = dict(emits_light=False, light_level=0, gravity=False, biome_tinted=False, tint_type=None, animated=False, faces_differ=False, sides_differ=False,
             face_delta_e00=0.0, side_delta_e00=0.0)
added, missing = [], []
for e in [x for x in E["blocks"] if x["reason"] in ("wall", "glass", "bars", "fence")]:
    bid = e["id"]
    if bid.startswith("waxed_") or "copper" in bid: continue
    try: mname = first_model(bid)
    except FileNotFoundError: missing.append(bid); continue
    mt = model(mname).get("textures", {})
    if e["reason"] == "wall" or e["reason"] == "fence":
        t = (mt.get("wall") or mt.get("texture") or "").replace("minecraft:", "")
        src = by_side.get(t)
        if not src: missing.append(bid); continue
        n = copy.deepcopy(src); shape = "wall" if e["reason"] == "wall" else "fence"
        n.update(id=bid, display_name=bid.replace("_", " ").title(), shape=shape, model="minecraft:" + mname, state={},
                 textures={k: ["minecraft:" + t] for k in ("top", "side", "bottom")})
        n[shape] = {"source_block": src["id"], "volume_fraction": 0.4 if shape == "wall" else 0.2,
                    "props": ({"north": ["none", "low", "tall"], "up": ["true", "false"]} if shape == "wall" else {"north": ["true", "false"]}),
                    "note": "centre post + arms toward connected sides (mc_map.connect)"}
        added.append(n); continue
    if e["reason"] == "glass" and not bid.endswith("_pane"): continue           # full glass blocks stay excluded for now
    # panes and iron bars: stats from the texture over a dark interior
    side = (mt.get("pane") or mt.get("bars") or mt.get("texture") or mt.get("particle") or "").replace("minecraft:", "")
    if not side: missing.append(bid); continue
    edge = (mt.get("edge") or side).replace("minecraft:", "")
    f = tex_stats(side); ft = tex_stats(edge)
    shape = "pane" if bid.endswith("_pane") else "bars"
    dye = bid.replace("_stained_glass_pane", "") if "stained" in bid else None
    n = dict(id=bid, display_name=bid.replace("_", " ").title(), shape=shape, family="glass" if shape == "pane" else "metal", subfamily=shape, dye_color=dye, wood_type=None,
             partially_transparent=True, has_cutout=True, has_translucency="stained" in bid, model="minecraft:" + mname, state={},
             textures={"top": ["minecraft:" + edge], "side": ["minecraft:" + side], "bottom": ["minecraft:" + edge]},
             overall=dict(f, brightness_L=f["lab"][0]), faces={"top": ft, "side": f, "bottom": ft}, pattern={"techniques": {}}, **FLAGS)
    n[shape] = {"volume_fraction": 0.125, "props": {"north": ["true", "false"]}, "backdrop": "#1a1a1a", "note": "colour = texture over a dark interior"}
    added.append(n)
ids = {a["id"] for a in added}
blocks = [b for b in blocks if b["id"] not in ids] + added
blocks.sort(key=lambda b: b["id"]); B["blocks"] = blocks
E["blocks"] = [x for x in E["blocks"] if x["id"] not in ids]; E["count"] = len(E["blocks"])
rc = {}
for x in E["blocks"]: rc[x["reason"]] = rc.get(x["reason"], 0) + 1
E["by_reason"] = rc
m = B["meta"]; m["included_count"] = len(blocks); m["excluded_count"] = E["count"]
sc = {}; [sc.__setitem__(b["shape"], sc.get(b["shape"], 0) + 1) for b in blocks]; m["shape_counts"] = sc; m["excluded_reason_counts"] = rc
json.dump(B, open("blocks.json", "w"), indent=1); json.dump(E, open("excluded.json", "w"), indent=1)
rows = list(csv.DictReader(open("blocks.csv"))); fields = list(rows[0].keys())
rows = [r for r in rows if r["shape"] not in DETAIL]; byid = {r["id"]: r for r in rows}
for n in added:
    src = n.get("wall", n.get("fence", {})).get("source_block")
    r = dict(byid[src]) if src in byid else {k: "" for k in fields}
    r.update(id=n["id"], display_name=n["display_name"], shape=n["shape"], family=n["family"]); rows.append(r)
rows.sort(key=lambda r: r["id"])
w = csv.DictWriter(open("blocks.csv", "w", newline=""), fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
print("added", len(added), {s: sum(1 for a in added if a["shape"] == s) for s in DETAIL}, "missing", missing, "total", len(blocks))
