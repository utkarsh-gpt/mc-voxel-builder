#!/usr/bin/env python3
"""v2 subject runs (2026-11-25): flat-albedo sheets chosen by shading_check (+ one nano-banana edit pass that removes
shading), one Hyper3D lowpoly mesh, ortho_paint + tone, shape_fit, explicit OPEN parts carved from the drawings,
palette_generic -> feature_detect (Haiku) -> colour_albedo (deshade) -> mc_map (albedo) + schematics, then free checks:
shading_check, shape_compare, colour_score and blueprint.count_openings vs a short parts list (meta/NAME_parts.json).
No Haiku retry loops: the mesh is generated once (a manual re-roll only if it is visibly broken).
usage: python run_v2.py NAME STAGE [STAGE ...]   stages: sheets mesh paint shape carve colour map check   (or: all)
fal spend is logged in out/v2_ledger.json (cap $1.50 for the three subjects)."""
import argparse, fcntl, json, os, subprocess, sys, time, urllib.request
import numpy as np
from PIL import Image
from scipy import ndimage
import fal_client, ortho_clean, ortho_verify, shading_check

LEDGER, CAP = "out/v2_ledger.json", 1.50
COST = {"fal-ai/nano-banana/edit": 0.039, "hyper3d/lowpoly/image-to-3d": 0.20}
STRONG = ("ABSOLUTE LIGHTING RULE (this sheet is checked by a program that rejects any shading): colour it like an UNLIT flat-colour game "
          "texture. Every face of one material is filled with ONE flat colour and the same lightness, whether it faces up, sideways or away; "
          "undersides, recesses, arch soffits, the inside of window reveals and the area under every roof edge are NOT darker. "
          "No cast shadows at all, no ambient occlusion, no gradients, no rim light, no specular highlights, no vignetting. "
          "Only genuinely dark materials (glass, dark slate, openings into a dark interior) are dark. Thin dark outlines are allowed.")
EDIT = ("This image is an orthographic 2x2 reference sheet (front, right side, back, top plan). Repaint it as FLAT ALBEDO colour: remove every "
        "shadow, shading gradient, ambient occlusion, darkened underside, darkened recess and directional lighting so that each material has "
        "one uniform colour and lightness in all four panels (the roof in the top plan as bright as in the front view). Keep EVERYTHING else "
        "exactly: the same 2x2 layout, panel positions, scale, outlines, shapes, proportions, number of parts, openings, windows and genuinely "
        "dark materials. Open see-through arches stay filled with the white background. Pure white background, no text, labels or frames.")
VIEWS = ("front", "right", "back", "top")

def spend(item, usd):
    os.makedirs("out", exist_ok=True)
    with open(LEDGER + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {"fal_usd": 0.0, "haiku_usd": 0.0, "items": []}
        if item.startswith("haiku"): d["haiku_usd"] = round(d["haiku_usd"] + usd, 4)
        else: d["fal_usd"] = round(d["fal_usd"] + usd, 4)
        d["items"].append({"item": item, "usd": usd, "t": time.strftime("%H:%M:%S")}); json.dump(d, open(LEDGER, "w"), indent=1)
        return d

def fal_left():
    d = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {"fal_usd": 0.0}
    return CAP - d["fal_usd"]

def fal_call(model, args, item):
    if fal_left() < COST[model] - 1e-9: raise SystemExit(f"fal cap ${CAP} would be exceeded by {item}")
    spend(f"fal {item}", COST[model]); return fal_client.subscribe(model, arguments=args)

def split(n, tag):
    im = Image.open(f"ortho/{n}{tag}_sheet.png").convert("RGB"); W, H = im.size
    for k, box in {"front": (0, 0, W//2, H//2), "right": (W//2, 0, W, H//2), "back": (0, H//2, W//2, H), "top": (W//2, H//2, W, H)}.items():
        im.crop(box).save(f"ortho/{n}{tag}_{k}.png")
    for v in VIEWS: ortho_clean.clean(f"ortho/{n}{tag}_{v}.png")

def shade_score(r):   # lower = flatter
    return r["shadow_share"] + 0.02*r["gradient_std"] + 0.01*abs(r["top_vs_front_dL"] or 0)

def gen_sheet(n, tag, with_photo):
    import ortho_gen
    hint, spec = ortho_verify.SPEC[n]
    urls = [fal_client.upload_file(f"refs/{n}_fal_in.png")] + ([fal_client.upload_file(f"refs/{n}.jpg")] if with_photo else [])
    prompt = ortho_gen.PROMPT.format(hint=hint, extra=" " + ortho_verify.COM + " " + spec + " " + STRONG)
    res = fal_call("fal-ai/nano-banana/edit", {"prompt": prompt, "image_urls": urls, "aspect_ratio": "1:1", "output_format": "png", "num_images": 1}, f"sheet {n}{tag}")
    urllib.request.urlretrieve(res["images"][0]["url"], f"ortho/{n}{tag}_sheet.png"); split(n, tag)
    open(f"out/v2/{n}{tag}_prompt.txt", "w").write(prompt)

def edit_sheet(n, src, tag):
    url = fal_client.upload_file(f"ortho/{n}{src}_sheet.png")
    res = fal_call("fal-ai/nano-banana/edit", {"prompt": EDIT, "image_urls": [url], "aspect_ratio": "1:1", "output_format": "png", "num_images": 1}, f"deshade-edit {n}{tag}")
    urllib.request.urlretrieve(res["images"][0]["url"], f"ortho/{n}{tag}_sheet.png"); split(n, tag)

def stage_sheets(n, k=2):
    with_photo = n != "gate"   # the gate photo has trees / rocks: only the cut-out goes to fal
    rows = {}
    for i in range(1, k + 1):
        t = f"_s{i}"
        if not os.path.exists(f"ortho/{n}{t}_sheet.png"): gen_sheet(n, t, with_photo)
        rows[t] = shading_check.check(n, t)
    best = min(rows, key=lambda t: shade_score(rows[t]))
    te = best + "e"
    if not os.path.exists(f"ortho/{n}{te}_sheet.png"): edit_sheet(n, best, te)
    rows[te] = shading_check.check(n, te)
    chosen = min(rows, key=lambda t: shade_score(rows[t]))
    geo = {t: ortho_verify.geo_checks(n + t) for t in rows}
    bad = [v for v in geo[chosen]["bad_views"] if v != "front"]
    used = [v for v in VIEWS if v not in bad]
    out = {"chosen": chosen, "views_used": used, "views_dropped": bad, "candidates": {t: {k_: rows[t][k_] for k_ in ("top_vs_front_dL", "shadow_share", "gradient_std", "shaded")} | {"score": round(shade_score(rows[t]), 4), "geo_issues": geo[t]["issues"]} for t in rows},
           "note": "v2 run: sheets _s1.._sK with the STRONG lighting rule, _sKe = nano-banana edit pass (remove shading) on the flattest; chosen = flattest by shading_check"}
    json.dump(out, open(f"out/{n}_verify.json", "w"), indent=1); json.dump(out, open(f"art/final/meta/{n}_views.json", "w"), indent=1)
    print(n, "chosen", chosen, json.dumps(out["candidates"][chosen]), "views", used)

def stage_mesh(n):
    if fal_left() < COST["hyper3d/lowpoly/image-to-3d"]: raise SystemExit("fal cap")
    spend(f"fal mesh {n}", COST["hyper3d/lowpoly/image-to-3d"])
    r = subprocess.run([sys.executable, "ortho_lowpoly.py", n], capture_output=True, text=True); print(r.stdout[-600:], r.stderr[-1500:])
    if r.returncode: raise SystemExit("mesh failed")

def stage_paint(n):
    tag = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"]
    r = subprocess.run([sys.executable, "ortho_paint.py", n, tag, f"--model={n}_lowpoly"], capture_output=True, text=True); print(r.stdout[-400:], r.stderr[-1500:])
    import tone_to_ref; tone_to_ref.tone(f"art/{n}_lowpoly_rendered.json", f"refs/{n}.jpg", f"art/{n}_lowpoly_rendered_toned.json")

def stage_shape(n):
    import shape_fit; tag = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"]
    shape_fit.run(n, f"out/{n}_lowpoly.glb", sheet=tag)

# ---------- explicit OPEN parts ----------
def see_through(n, tag, occ, view, K=8):
    """block cells (row, col) of this view where the drawing shows white background INSIDE the structure's outline
    (arch passages): the outline is closed along the ground so arches standing on it count as enclosed"""
    import feature_detect as fd
    hit, xyz, _ = fd.view_maps(occ, view); al = fd.align(n, tag, view, hit, K)
    if al is None: return None
    r0, r1, c0, c1 = al["box"]; rgb = al["rgb"]; h, w = r1 - r0, c1 - c0
    nonwhite = (rgb.min(-1) < 232) | (np.ptp(rgb, -1) > 18)
    cell = nonwhite.reshape(h, K, w, K).mean((1, 3))              # share of drawn pixels per block cell
    drawn = cell >= 0.35
    closed = np.vstack([drawn, np.ones((1, w), bool)])             # close the outline along the ground
    inside = ndimage.binary_fill_holes(closed)[:-1] & ~drawn
    inside = ndimage.binary_opening(inside, np.ones((2, 1)))       # >= 2 blocks tall
    lab, k = ndimage.label(inside); keep = np.zeros_like(inside)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        m = lab[sl] == i
        if m.sum() >= 3 and (sl[1].stop - sl[1].start) >= 1: keep[sl] |= m
    full = np.zeros(hit.shape, bool); full[r0:r1, c0:c1] = keep
    return {"cells": full, "xyz": xyz, "iou": al["iou"], "mirrored": al["mirrored"], "components": int(ndimage.label(keep)[1])}

def stage_carve(n):
    """remove the voxels of every see-through drawing cell through the full depth of the model (front and back must
    agree; for the right view the left view is its mirror). Writes art/NAME_shapefit.json in place (copy kept as _uncarved)."""
    tag = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"]; P = json.load(open(f"art/final/meta/{n}_parts.json"))
    src = f"art/{n}_shapefit.json"; keep = f"art/{n}_shapefit_uncarved.json"
    if not os.path.exists(keep): os.rename(src, keep)
    d = json.load(open(keep)); W, H, D = d["size"]; occ = np.zeros((W, H, D), bool)
    for v in d["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    rep = {"tag": tag, "axes": {}}; remove = np.zeros_like(occ)
    for axis, (va, vb) in {"z": ("front", "back"), "x": ("right", None)}.items():
        if axis not in P.get("carve_axes", ["z"]): continue
        A = see_through(n, tag, occ, va)
        if A is None: continue
        cells = A["cells"]
        if vb:
            B = see_through(n, tag, occ, vb)
            if B is not None: cells = cells & B["cells"][:, ::-1] if cells.shape == B["cells"].shape else cells
        rr, cc = np.nonzero(cells); n_cells = 0
        for r, c in zip(rr, cc):
            x, y, z = A["xyz"][r, c]
            if axis == "z": remove[x, y, :] = True
            else: remove[:, y, z] = True
            n_cells += 1
        rep["axes"][axis] = {"view": va, "cells": n_cells, "components": A["components"], "align_iou": A["iou"]}
    # never carve below the first layer that is fully open in the drawing's lowest row: passages start at ground level, keep y >= 0
    gone = occ & remove; rep["voxels_removed"] = int(gone.sum())
    d["voxels"] = [v for v in d["voxels"] if not remove[v["x"], v["y"], v["z"]]]
    bg = P.get("bridge_gaps")   # a mesh shell that came back detached (e.g. a facade layer 1-2 blocks in front of the body): fill the gap
    if bg:
        ax = "xyz".index(bg["axis"]); A = np.moveaxis(occ & ~remove, ax, -1); add = np.zeros_like(A)
        for g in range(1, bg["max"] + 1):
            for s in range(A.shape[-1] - g - 1):
                gap = A[..., s] & A[..., s + g + 1] & ~A[..., s + 1:s + g + 1].any(-1)
                for t in range(1, g + 1): add[..., s + t] |= gap
        add = np.moveaxis(add, -1, ax); have = {(v["x"], v["y"], v["z"]) for v in d["voxels"]}; c0 = d["voxels"][0]["c"]
        for x, y, z in np.argwhere(add):
            if (x, y, z) not in have: d["voxels"].append({"x": int(x), "y": int(y), "z": int(z), "c": c0})
        rep["bridged"] = int(add.sum())
    d["carved_open"] = rep; json.dump(d, open(src, "w")); json.dump(rep, open(f"out/v2/{n}_carve.json", "w"), indent=1); print(n, "carve", json.dumps(rep))

def filter_features(n):
    """keep only feature kinds the parts list names, at most the listed count each (highest evidence first): the detector
    otherwise turns sail tips into spires, a pole into a door, tower tops into chimneys"""
    P = json.load(open(f"art/final/meta/{n}_parts.json")); allow = P.get("feature_kinds")
    if allow is None: return
    p = f"art/final/meta/{n}_features.json"; F = json.load(open(p)); keep, drop = [], {}
    for f in sorted(F["features"], key=lambda f: -(f.get("evidence") or 0)):
        k = f["kind"]
        if k in allow and sum(g["kind"] == k for g in keep) < allow[k]: keep.append(f)
        else: drop[k] = drop.get(k, 0) + 1
    F["features"] = keep; F["parts_filter"] = {"allowed": allow, "dropped": drop}
    F["counts"] = {k: sum(f["kind"] == k for f in keep) for k in allow}; json.dump(F, open(p, "w"), indent=1); print(n, "features kept", F["counts"], "dropped", drop)

def stage_colour(n):
    import palette_generic; palette_generic.run(n)
    tag = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"]
    for cmd in (["feature_detect.py", n, "--sheet", tag], ["colour_albedo.py", n, "--sheet", tag, "--mesh", f"out/{n}_lowpoly.glb", "--dark-rules"], ["noise_measure.py", n]):
        r = subprocess.run([sys.executable] + cmd, capture_output=True, text=True); print(r.stdout[-1500:], r.stderr[-2500:])
        if r.returncode: raise SystemExit(cmd[0] + " failed")
        if cmd[0] == "feature_detect.py": filter_features(n)

def stage_map(n):
    r = subprocess.run([sys.executable, "mc_map.py", n], capture_output=True, text=True); print(r.stdout[-1500:], r.stderr[-2500:])
    if r.returncode: raise SystemExit("mc_map failed")

def stage_check(n):
    import blueprint, colour_score, shape_compare
    tag = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"]; P = json.load(open(f"art/final/meta/{n}_parts.json"))
    d = json.load(open(f"art/final/{n}_mc_blocks.json")); W, H, D = d["size"]; occ = np.zeros((W, H, D), bool)
    for v in d["voxels"]:
        b = d["palette"][v["b"]]["id"] if isinstance(d["palette"], dict) else d["palette"][v["b"]]
        occ[v["x"], v["y"], v["z"]] = True
    oc = blueprint.count_openings(occ)
    req = {f: {"recess": 0, "open": 0} for f in ("front", "right", "back", "left")}
    for p in P["parts"]:
        if p["built_as"] not in ("open", "set_back"): continue          # proud / outline parts are not openings
        for f in p["faces"]: req[f]["open" if p["built_as"] == "open" else "recess"] += p["count"]
    dc = {f: {"found_recess": oc[f]["recess"], "found_open": oc[f]["open"], "listed_recess": req[f]["recess"], "listed_open": req[f]["open"]} for f in req}
    out = {"sheet": tag, "shading": shading_check.check(n, tag), "depth_count": dc, "depth_detail": oc}
    json.dump(out, open(f"out/v2/{n}_check.json", "w"), indent=1, default=str)
    print(n, json.dumps(dc)); print(n, "shading", json.dumps({k: out["shading"][k] for k in ("top_vs_front_dL", "shadow_share", "gradient_std", "shaded")}))

STAGES = {"sheets": stage_sheets, "mesh": stage_mesh, "paint": stage_paint, "shape": stage_shape, "carve": stage_carve,
          "colour": stage_colour, "map": stage_map, "check": stage_check}
if __name__ == "__main__":
    os.makedirs("out/v2", exist_ok=True)
    n, *st = sys.argv[1:]
    for s in (list(STAGES) if st == ["all"] else st): print("==", n, s); STAGES[s](n)
