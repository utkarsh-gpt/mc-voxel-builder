#!/usr/bin/env python3
"""Blueprint pass, cathedral experiment (specs/detailed-parts.md, "Experiment: the cathedral").
The part list is hand-written (specs/detailed-parts-cathedral.md), so the list / list-check steps are skipped.
  run A: the sheet prompt carries one block per part (count, where, notes, built_as)
  run B: control, only "N x part id" per part
Per attempt: sheet (fal nano-banana/edit, photo + prompt, flat-albedo rule) -> one mesh (hyper3d lowpoly, the
ortho_lowpoly path) -> PLAIN voxelizer (fal_shape.voxelize) at grid 48, again at 72 if a part is lost (same mesh)
-> flat grey renders (no colour; side-lit obliques + straight depth maps) -> Haiku per-part check + a depth-only
opening counter -> retry with the missing part ids named (max 3 retries). Stops at structure (no colour, no mc_map).
usage: python blueprint.py cathedral A|B [--retries 3] [--cap 2.00]
outputs: out/cathedral_exp/{run}{k}_*, art/final/meta/cathedral_blueprint.json, out/cathedral_exp/run_{run}.json"""
import argparse, fcntl, json, os, re, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
import fal_client
import ortho_gen, ortho_verify, ortho_clean, shading_check, fal_shape, vox, orient, llm

SHEET_USD, MESH_USD = 0.039, 0.20
HAIKU = "claude-haiku-5-5"
OUT = "out/cathedral_exp"
LEDGER = f"{OUT}/ledger.json"
VIEWS = ("front", "right", "back", "top")
LAB = {"front": "F", "right": "R", "back": "B", "top": "U"}
GEO = {"set_back": "set back: a recess cut into the wall, the wall face in front of it and its floor deeper than the wall",
       "open": "open: a hole or gap you can see through or past",
       "proud": "proud: a solid standing out of the surface",
       "outline": "outline: it changes the silhouette"}

# ---------- blueprint ----------
def parse_notes(path="../specs/detailed-parts-cathedral.md"):
    txt = open(path).read(); parts = {}
    heads = list(re.finditer(r"^\*\*`(\w+)`\*\* \((mass|feature), count (\d+)(.*?)\)\s*$", txt, re.M))
    for i, h in enumerate(heads):
        body = txt[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(txt)]
        body = re.split(r"\n## |\nDone means", body)[0]
        pid, kind, count, rest = h.group(1), h.group(2), int(h.group(3)), h.group(4)
        par = re.search(r"parent `(\w+)`", rest); face = re.search(r"face (`\w+`|[\w, ]+)", rest)
        where = re.search(r"Where:\s*(.+?)\n\n", body, re.S).group(1).strip()
        notes = re.search(r"Notes:\s*\n(.+?)\n\n", body, re.S).group(1).strip()
        bm = re.search(r"Built as structure \(`built_as`: ([\w, ]+)\):\s*\n(.+?)(\n\n|$)", body, re.S)
        p = {"kind": kind, "count": count, "where": " ".join(where.split()), "notes": " ".join(notes.split()),
             "built_as": [b.strip() for b in bm.group(1).split(",")], "built_note": " ".join(bm.group(2).split())}
        if par: p["parent"] = par.group(1)
        if face: p["face"] = face.group(1).strip("`").replace(" ", "")
        parts[pid] = p
    for pid in [k for k, p in parts.items() if p.get("face") == "right"]:   # side twins (the notes file: "_left ... same notes")
        q = dict(parts[pid]); q["face"] = "left"; q["where"] = q["where"].replace("right side", "left side").replace("on the right", "on the left")
        parts[pid + "_left"] = q
    summary = ("A Gothic stone cathedral with a flat west front between two matching towers with spires, a long nave with aisles "
               "and flying buttresses, one long slate roof, and a rounded east end. Symmetrical left to right.")
    return {"subject": "cathedral", "summary": summary, "source": "specs/detailed-parts-cathedral.md (hand-written; list steps skipped)", "parts": parts}

def prompt_parts(bp, run, missing=None, detail_missing=None):
    P = bp["parts"]
    if run == "B":
        body = "PARTS: " + ", ".join(f"{p['count']} x {k.replace('_', ' ')}" for k, p in P.items()) + "."
        if missing: body += " MISSING LAST TIME, draw each one: " + ", ".join(f"{P[k]['count']} x {k.replace('_', ' ')}" for k in missing) + "."
        return body
    lines = ["THE BUILDING IS MADE OF THESE PARTS. Draw every part below as its own separate shape, at its count, built in depth "
             "the way its BUILT AS says (" + "; ".join(GEO.values()) + "). Every part is its own line here; none is left to appear by chance, "
             "and none may be only a colour or a dark patch on a flat wall."]
    for k, p in P.items():
        face = f", face {p['face']}" if p.get("face") else ""
        lines.append(f"[{k}] {p['count']} x ({p['kind']}{face}). WHERE: {p['where']} NOTES: {p['notes']} "
                     f"BUILT AS {', '.join(p['built_as']).upper()}: {p['built_note']}")
    if missing:
        lines.append("THE LAST 3D BUILD LOST THESE PARTS - draw each one larger and deeper, clearly separated from its neighbours, as real geometry: "
                     + "; ".join(f"{k} ({P[k]['count']} x)" for k in missing) + ".")
    if detail_missing:
        lines.append("DETAIL THE LAST BUILD LOST (make it bold and deep): " + "; ".join(f"{k}: {', '.join(v)}" for k, v in detail_missing.items() if v) + ".")
    return "\n".join(lines)

# ---------- spend ledger (shared by both runs) ----------
def spend(item, usd, cap):
    os.makedirs(OUT, exist_ok=True)
    with open(LEDGER + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        L = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {"fal_usd": 0.0, "haiku_usd": 0.0, "items": []}
        if item.startswith("fal") and L["fal_usd"] + usd > cap + 1e-9: return False
        L["fal_usd" if item.startswith("fal") else "haiku_usd"] = round(L["fal_usd" if item.startswith("fal") else "haiku_usd"] + usd, 4)
        L["items"].append({"item": item, "usd": round(usd, 4), "t": time.strftime("%H:%M:%S")}); json.dump(L, open(LEDGER, "w"), indent=1)
        return True

def can_afford(usd, cap):
    L = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {"fal_usd": 0.0}
    return L["fal_usd"] + usd <= cap + 1e-9

# ---------- sheet / mesh / voxels ----------
def sheet(tag, parts_text, cap):
    prompt = ortho_gen.PROMPT.format(hint="Gothic stone cathedral", extra=" " + ortho_verify.COM + "\n" + parts_text)
    if not spend(f"fal sheet {tag}", SHEET_USD, cap): raise SystemExit("cap")
    urls = [fal_client.upload_file("refs/cathedral_fal_in.png"), fal_client.upload_file("refs/cathedral.jpg")]
    res = fal_client.subscribe("fal-ai/nano-banana/edit", arguments={"prompt": prompt, "image_urls": urls, "aspect_ratio": "1:1", "output_format": "png", "num_images": 1})
    out = f"ortho/cathedral_{tag}_sheet.png"; urllib.request.urlretrieve(res["images"][0]["url"], out)
    im = Image.open(out).convert("RGB"); W, H = im.size
    for k, box in {"front": (0, 0, W//2, H//2), "right": (W//2, 0, W, H//2), "back": (0, H//2, W//2, H), "top": (W//2, H//2, W, H)}.items():
        im.crop(box).save(f"ortho/cathedral_{tag}_{k}.png"); ortho_clean.clean(f"ortho/cathedral_{tag}_{k}.png")
    open(f"{OUT}/{tag}_sheet_prompt.txt", "w").write(prompt)
    try: sc = shading_check.check("cathedral", "_" + tag)
    except Exception as e: sc = {"error": str(e)}
    return {"sheet": out, "prompt_chars": len(prompt), "shading": {k: sc.get(k) for k in ("top_vs_front_dL", "shadow_share", "gradient_std", "shaded")}}

def mesh(tag, cap):
    if not spend(f"fal mesh {tag}", MESH_USD, cap): raise SystemExit("cap")
    with ThreadPoolExecutor(4) as ex: urls = list(ex.map(lambda v: fal_client.upload_file(f"ortho/cathedral_{tag}_{v}.png"), VIEWS))
    res = fal_client.subscribe("hyper3d/lowpoly/image-to-3d", arguments={"image_urls": urls, "image_labels": [LAB[v] for v in VIEWS],
                               "prompt": ortho_verify.SPEC["cathedral"][0], "face_count": 4000, "geometry_file_format": "glb", "material": "Shaded"})
    glb = f"{OUT}/{tag}.glb"; urllib.request.urlretrieve(res["model_mesh"]["url"], glb)
    return glb, res["model_mesh"]["url"]

def voxels(glb, grid, tag):
    d = fal_shape.voxelize(glb, grid); d["name"] = f"cathedral_{tag}_g{grid}"; p = f"{OUT}/{tag}_g{grid}.json"
    W, H, D = d["size"]; occ = np.zeros((W, H, D), bool)
    for v in d["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    if orient.facade_flip(occ, f"ortho/cathedral_{tag}_right.png"):          # facade must be on +z, the face "front" looks at
        d = orient.flip_voxel_dict(d); occ = orient.flip_occ(occ).copy(); d["orientation"] = "flipped 180 about y (facade was on -z)"
    json.dump(d, open(p, "w"))
    return occ, p

# ---------- flat grey renders ----------
AZ = {"front": 0, "right": 270, "back": 180, "left": 90}          # vox.render azimuth that faces the +z / +x / -z / -x side
def depth_map(occ, view):
    """straight-on depth image (rows top->bottom, as seen from that side): distance from the camera plane to the first
    voxel, and a hit mask. Depth only, no colour."""
    W, H, D = occ.shape
    if view == "front": A = occ[:, :, ::-1].transpose(1, 0, 2)                   # [y, x, depth]
    elif view == "back": A = occ[::-1, :, :].transpose(1, 0, 2)
    elif view == "right": A = occ[::-1, :, ::-1].transpose(1, 2, 0)              # looking -x: image left = +z
    else: A = occ.transpose(1, 2, 0)
    hit = A.any(2); dep = np.where(hit, np.argmax(A, 2), -1)
    return dep[::-1], hit[::-1]

def grey_views(occ, tag, size=520):
    col = np.full(occ.shape + (3,), 185, np.uint8); paths = {}
    for view in ("front", "right", "back", "left"):
        az = AZ[view]; a = np.radians(az + 25)
        lit = (np.cos(a + np.pi/2), 0.45, np.sin(a + np.pi/2))                  # light from the side of the camera
        ob, _ = vox.render(occ, col, az + 25, 12, size, light=lit, ao=True)
        dep, hit = depth_map(occ, view)
        g = np.full(dep.shape, 255.0); lo = np.percentile(dep[hit], 2); span = max(6.0, 0.25*occ.shape[0 if view in ("right", "left") else 2])
        g[hit] = 30 + 190*np.clip((dep[hit] - lo)/span, 0, 1)**0.7             # near = dark, deep = light grey, air = white
        dm = Image.fromarray(g.astype(np.uint8)).resize((size*dep.shape[1]//max(dep.shape), size*dep.shape[0]//max(dep.shape)), Image.NEAREST)
        T = Image.new("RGB", (2*size + 10, size + 22), "white"); T.paste(ob, (0, 22)); T.paste(dm.convert("RGB"), (size + 10, 22))
        ImageDraw.Draw(T).text((4, 4), f"{view.upper()}: left = flat grey, side-lit, 25 deg oblique | right = straight-on depth map (near dark, deep light, air white)", fill="black")
        paths[view] = f"{OUT}/{tag}_grey_{view}.png"; T.save(paths[view])
    tq, _ = vox.render(occ, col, 35, 22, size, light=(-0.8, 0.5, 0.3), ao=True)
    T = Image.new("RGB", (size, size + 22), "white"); T.paste(tq, (0, 22)); ImageDraw.Draw(T).text((4, 4), "THREE-QUARTER (front-right), flat grey", fill="black")
    paths["three_quarter"] = f"{OUT}/{tag}_grey_3q.png"; T.save(paths["three_quarter"])
    return paths

# ---------- depth-only opening counter ----------
def count_openings(occ):
    """recessed and open patches per face, from depth alone (never darkness): a cell is recessed when it lies >= 1 voxel
    deeper than the wall plane around it (30th percentile of depth in a 7x7 window), open when it is inside the silhouette
    but no voxel is hit. 4-connected patches of >= 2 cells that do not touch the silhouette edge are counted."""
    res = {}
    for view in ("front", "right", "back", "left"):
        dep, hit = depth_map(occ, view)
        sil = ndimage.binary_fill_holes(hit); open_ = sil & ~hit
        d = np.where(hit, dep, np.nan); ref = ndimage.generic_filter(np.nan_to_num(d, nan=1e3), lambda w: np.percentile(w[w < 1e3], 30) if (w < 1e3).any() else 1e3, size=7)
        rec = hit & (dep - ref >= 1) & (dep - ref <= 6)
        inner = ndimage.binary_erosion(sil, np.ones((3, 3)))
        lab, n = ndimage.label(rec | open_); comps = []
        for i, sl in enumerate(ndimage.find_objects(lab), 1):
            m = lab[sl] == i; a = int(m.sum())
            if a < 2: continue
            if not inner[sl][m].all(): continue                                 # touches the outline: a setback of the mass, not an opening
            if a > 0.08*sil.sum(): continue
            kind = "open" if open_[sl][m].mean() > 0.5 else "recess"
            comps.append({"kind": kind, "cells": a, "row": int((sl[0].start + sl[0].stop)//2), "col": int((sl[1].start + sl[1].stop)//2), "h": sl[0].stop - sl[0].start, "w": sl[1].stop - sl[1].start})
        res[view] = {"patches": len(comps), "recess": sum(c["kind"] == "recess" for c in comps), "open": sum(c["kind"] == "open" for c in comps),
                     "image_hw": list(dep.shape), "list": comps}
    return res

def required_openings(bp):
    """set_back / open features per face (belfry: 2 per tower face seen; side twins on their own face)"""
    req = {"front": 0, "right": 0, "back": 0, "left": 0}
    for k, p in bp["parts"].items():
        if p["kind"] != "feature" or not set(p["built_as"]) & {"set_back", "open"}: continue
        if k == "belfry_opening": req["front"] += 4; req["back"] += 4; req["right"] += 2; req["left"] += 2; continue
        if k == "gallery_arcade": req["front"] += 5; continue
        if k == "front_window": req["front"] += 4; req["right"] += 2; req["left"] += 2; continue
        if k == "parapet": continue
        f = p.get("face")
        if f in req: req[f] += p["count"]
    return req

# ---------- Haiku per-part checker ----------
CHECK = """You check a voxel build against its blueprint, PART BY PART, on STRUCTURE ONLY.
Read these files with the Read tool:
- the photo of the real building: {photo}
- the blueprint (JSON, every part with count, where, notes, built_as): {bp}
- flat grey renders of the voxels, no colour: {renders}
  (front/right/back/left images: left half = flat grey side-lit oblique view, right half = straight-on depth map where
  NEAR is dark grey, DEEPER is lighter grey and AIR is white; a recess is a patch lighter than the wall around it, an
  opening you can see through is white inside the outline)
Rules: a part is present only if it shows in these grey renders as its own shape, at its count, with the geometry its
built_as names (set_back = recessed into the wall; open = see-through gap; proud = solid standing out; outline = changes
the silhouette). Colour does not exist here. A row of openings merged into one band counts as ONE. Never pass a part
because the building looks right overall or because its neighbours are present. count_seen = how many separate
instances you can actually count (0 if absent). detail_missing = elements described in the part's notes that do not show
(e.g. "spokes", "pointed heads", "mullion").
Reply with ONLY one JSON object:
{{"parts": {{"<part id>": {{"present": true/false, "count_seen": <int>, "built_as_seen": [...], "detail_missing": [...]}}, ...every part id...}},
  "summary": "<one sentence>"}}"""

def haiku_check(bp_path, renders, tag):
    p = CHECK.format(photo=os.path.abspath("refs/cathedral.jpg"), bp=os.path.abspath(bp_path), renders=", ".join(os.path.abspath(x) for x in renders.values()))
    text, cost = llm.ask(p, images=[os.path.abspath("refs/cathedral.jpg"), *map(os.path.abspath, renders.values())], model=HAIKU)
    spend(f"haiku check {tag}", cost, 1e9)
    m = re.search(r"\{.*\}", text, re.S)
    try: out = json.loads(m.group(0))
    except Exception: out = {"parts": {}, "summary": "unparseable", "raw": text[-1500:]}
    out["_cost_usd"] = round(cost, 4); json.dump(out, open(f"{OUT}/{tag}_check.json", "w"), indent=1)
    return out

def verdict(bp, chk):
    miss, dm, rows = [], {}, {}
    for k, p in bp["parts"].items():
        c = chk.get("parts", {}).get(k, {}); seen = int(c.get("count_seen") or 0); pres = bool(c.get("present")) and seen >= p["count"]
        rows[k] = {"present": pres, "count": p["count"], "count_seen": seen, "built_as": p["built_as"], "built_as_seen": c.get("built_as_seen", []), "detail_missing": c.get("detail_missing", [])}
        if not pres: miss.append(k)
        if c.get("detail_missing"): dm[k] = c["detail_missing"]
    return miss, dm, rows

# ---------- run ----------
def run(run_id, retries=3, cap=2.0):
    bp = parse_notes(); os.makedirs("art/final/meta", exist_ok=True)
    bp_path = "art/final/meta/cathedral_blueprint.json"; json.dump(bp, open(bp_path, "w"), indent=1)
    req = required_openings(bp); log = {"run": run_id, "attempts": [], "required_openings_per_face": req}
    missing, dmiss = None, None
    for k in range(1, retries + 2):
        tag = f"bp{run_id}{k}"
        if not can_afford(SHEET_USD + MESH_USD, cap): log["stopped"] = "fal cap would be exceeded"; break
        att = {"tag": tag, "named_missing": missing or []}
        att.update(sheet(tag, prompt_parts(bp, run_id, missing, dmiss if run_id == "A" else None), cap))
        glb, url = mesh(tag, cap); att["mesh_url"] = url
        best = None
        for grid in (48, 72):
            occ, vp = voxels(glb, grid, tag); r = grey_views(occ, f"{tag}_g{grid}")
            chk = haiku_check(bp_path, r, f"{tag}_g{grid}"); miss, dm, rows = verdict(bp, chk)
            g = {"grid": grid, "size": list(occ.shape), "voxels": int(occ.sum()), "renders": r, "missing": miss, "detail_missing": dm, "parts": rows,
                 "depth_count": count_openings(occ), "haiku_usd": chk["_cost_usd"], "haiku_summary": chk.get("summary")}
            att.setdefault("grids", []).append(g)
            if best is None or len(miss) < len(best["missing"]): best = g
            print(run_id, tag, "grid", grid, "missing", len(miss), miss, flush=True)
            if not miss: break
        att["grid_used"] = best["grid"]; att["missing"] = best["missing"]; att["detail_missing"] = best["detail_missing"]
        log["attempts"].append(att); json.dump(log, open(f"{OUT}/run_{run_id}.json", "w"), indent=1)
        missing, dmiss = best["missing"], best["detail_missing"]
        if not missing: log["check"] = "passed"; break
    else: pass
    log.setdefault("check", "failed"); log["retries"] = max(0, len(log["attempts"]) - 1)
    json.dump(log, open(f"{OUT}/run_{run_id}.json", "w"), indent=1); return log

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("run", choices=["A", "B"]); ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--cap", type=float, default=2.0); a = ap.parse_args(); run(a.run, a.retries, a.cap)
