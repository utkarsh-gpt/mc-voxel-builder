"""Add stair variants for every stairs block whose texture matches a block already in the dataset.
Stats (colour, texture, pattern/technique) are copied from the same-texture source block (slab or full block);
shape metadata describes the blockstate. Re-runnable (idempotent)."""
import json, csv, copy, os
A = "assets/assets/minecraft"
B = json.load(open("blocks.json")); E = json.load(open("excluded.json"))
blocks = [b for b in B["blocks"] if b["shape"] != "stairs"]
def model_tex(name):
    tex = {}
    while name:
        m = json.load(open(f"{A}/models/block/{name.split('/')[-1]}.json"))
        for k, v in m.get("textures", {}).items(): tex.setdefault(k, v)
        name = m.get("parent", "").replace("minecraft:", "")
        if name in ("block/stairs", "block/block", ""): break
    return tex
def tkey(t): return tuple(sorted((k, (v[0] if isinstance(v, list) else v).replace("minecraft:", "")) for k, v in t.items() if k in ("top", "side", "bottom")))
by_tex = {}
for b in blocks:
    k = tkey(b["textures"])
    if b["shape"] in ("slab", "full_block") and (k not in by_tex or (b["shape"] == "full_block" and by_tex[k]["shape"] != "full_block")):
        by_tex[k] = b
side_only = {}
for b in blocks:
    if b["shape"] == "full_block" and not b.get("faces_differ"): side_only.setdefault((b["textures"]["side"][0]).replace("minecraft:", ""), b)
added, missing = [], []
for e in [x for x in E["blocks"] if x["reason"] == "stairs"]:
    sid = e["id"]; bs = json.load(open(f"{A}/blockstates/{sid}.json"))
    v = next(iter(bs["variants"].values())); v = v[0] if isinstance(v, list) else v
    mt = model_tex(v["model"].replace("minecraft:", ""))
    k = tkey({kk: mt[kk] for kk in ("top", "side", "bottom") if kk in mt})
    src = by_tex.get(k) or side_only.get(mt.get("side", "").replace("minecraft:", ""))
    if not src: missing.append(sid); continue
    n = copy.deepcopy(src)
    n.update(id=sid, display_name=sid.replace("_", " ").title(), shape="stairs", model=v["model"],
             state={"facing": "north", "half": "bottom", "shape": "straight"},
             textures={kk: [mt[kk]] for kk in ("top", "side", "bottom")})
    n["stairs"] = {"source_block": src["id"], "volume_fraction": 0.75,
                   "props": {"facing": ["north", "south", "east", "west"], "half": ["bottom", "top"],
                             "shape": ["straight", "inner_left", "inner_right", "outer_left", "outer_right"]},
                   "note": "facing = side of the tall step; half=top is upside-down"}
    added.append((n, src["id"]))
blocks += [a for a, _ in added]
blocks.sort(key=lambda b: b["id"]); B["blocks"] = blocks
ids = {a["id"] for a, _ in added}
E["blocks"] = [x for x in E["blocks"] if x["id"] not in ids]; E["count"] = len(E["blocks"])
E["by_reason"]["stairs"] = len(missing)
if not missing: E["by_reason"].pop("stairs")
m = B["meta"]; m["included_count"] = len(blocks); m["excluded_count"] = E["count"]
sc = {}; [sc.__setitem__(b["shape"], sc.get(b["shape"], 0) + 1) for b in blocks]; m["shape_counts"] = sc
m.setdefault("excluded_reason_counts", {}).update({"stairs": len(missing)}) if missing else m["excluded_reason_counts"].pop("stairs", None)
json.dump(B, open("blocks.json", "w"), indent=1); json.dump(E, open("excluded.json", "w"), indent=1)
rows = list(csv.DictReader(open("blocks.csv"))); fields = list(rows[0].keys())
for f in ("stairs_source_block", "stairs_volume_fraction"):
    if f not in fields: fields.append(f)
rows = [r for r in rows if r["shape"] != "stairs"]; byid = {r["id"]: r for r in rows}
for n, s in added:
    r = dict(byid[s]); r.update(id=n["id"], display_name=n["display_name"], shape="stairs", stairs_source_block=s, stairs_volume_fraction="0.75"); rows.append(r)
rows.sort(key=lambda r: r["id"])
w = csv.DictWriter(open("blocks.csv", "w", newline=""), fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
print("added", len(added), "missing", missing, "total", len(blocks), sc)
