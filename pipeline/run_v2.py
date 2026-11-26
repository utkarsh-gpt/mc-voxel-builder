#!/usr/bin/env python3
"""v2 subject runs (2026-11-25): flat-albedo sheets chosen by shading_check (+ one nano-banana edit pass that removes
shading), one Hyper3D lowpoly mesh, ortho_paint + tone, shape_fit, explicit OPEN parts carved from the drawings,
palette_generic -> feature_detect (Haiku) -> colour_albedo (deshade) -> mc_map (albedo) + schematics, then free checks:
shading_check, shape_compare, colour_score and blueprint.count_openings vs a short parts list (meta/NAME_parts.json).
No Haiku retry loops: the mesh is generated once (a manual re-roll only if it is visibly broken).
usage: python run_v2.py NAME STAGE [STAGE ...]   stages: sheets mesh paint shape carve sails squash colour zones map grad check   (or: all)
fal spend is logged in out/v2_ledger.json (cap $1.50 for the three subjects)."""
import argparse, fcntl, json, os, subprocess, sys, time, urllib.request
import numpy as np
from PIL import Image
from scipy import ndimage
import fal_client, ortho_clean, ortho_verify, shading_check

LEDGER, CAP = os.environ.get("V2_LEDGER", "out/v2_ledger.json"), float(os.environ.get("V2_CAP", 1.50))   # fix round: out/v2fix_ledger.json, $0.80
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

def stage_sails(n):
    """windmill: the mesh came back with sails on BOTH faces (front and back) and broken up. Strip every voxel outside the
    tower's z range (parts.json rebuild_sails.keep_z) and rebuild ONE clean sail cross in a single plane in front of the
    cap: 4 stocks (spars) through the hub at +/-angle, each with a lattice sail on its trailing side (thin vslab, faces the
    tower), and an axle block between hub and cap. Geometry comes from the front drawing (hub, arm length, angle measured
    on the drawing / previous sail voxels). Writes art/NAME_shapefit.json in place (copy kept as _presails)."""
    P = json.load(open(f"art/final/meta/{n}_parts.json")); S = P.get("rebuild_sails")
    if not S: return
    src = f"art/{n}_shapefit.json"; keep = f"art/{n}_shapefit_presails.json"
    d = json.load(open(src)); json.dump(d, open(keep, "w")); W, H, D = d["size"]
    z0, z1 = S["keep_z"]; hx, hy = S["hub"]; L, ang, wid, inner, zs = S["length"], np.radians(S["angle_deg"]), S["width"], S["inner"], S["z"]
    before = len(d["voxels"]); d["voxels"] = [v for v in d["voxels"] if z0 <= v["z"] <= z1]
    d["palette"]["sail"] = S.get("sail_hex", "#e8e6df"); d["palette"]["spar"] = S.get("spar_hex", "#5b4a3a")
    add = {}
    for a in (ang, np.pi - ang, np.pi + ang, -ang):
        u = np.array([np.cos(a), np.sin(a)])
        for x in range(W):
            for y in range(1, H):
                p = np.array([x + 0.5 - hx, y + 0.5 - hy]); t = p @ u; c = u[0]*p[1] - u[1]*p[0]
                if 0 <= t <= L and abs(c) <= 0.75: add[(x, y, zs)] = ("spar", None)
                elif inner*L <= t <= L and 0.75 < c <= 0.75 + wid and (x, y, zs) not in add:
                    add[(x, y, zs)] = ("sail", {"type": "vslab", "size": 0.1875, "axis": "z", "align": "north"})
    for dz in range(z1 + 1, zs): add[(int(hx), int(hy), dz)] = ("spar", None)        # axle: cap -> hub
    for (x, y, z), (c, sh) in add.items():
        v = {"x": x, "y": y, "z": z, "c": c}
        if sh: v["s"] = sh
        d["voxels"].append(v)
    rep = {"removed_outside_z": before - (len(d["voxels"]) - len(add)), "spar": sum(c == "spar" for c, _ in add.values()), "sail": sum(c == "sail" for c, _ in add.values()), "params": S}
    d["sails_rebuilt"] = rep; json.dump(d, open(src, "w")); json.dump(rep, open(f"out/v2/{n}_sails.json", "w"), indent=1); print(n, "sails", json.dumps(rep))

def stage_squash(n):
    """gate: the mesh (from a sheet whose side/top views were wrong) came back about half as deep as it is wide; the
    reference is a thin gatehouse wall. Resample the voxel grid along z to parts.json squash_z.depth blocks (nearest
    neighbour, every new layer keeps the union of the old layers it covers, so the front/back faces, buttresses, roofs and
    the carved arches keep their place and proportion). Run after carve; writes art/NAME_shapefit.json in place (_presquash kept)."""
    P = json.load(open(f"art/final/meta/{n}_parts.json")); S = P.get("squash_z")
    if not S: return
    src = f"art/{n}_shapefit.json"; d = json.load(open(src)); json.dump(d, open(f"art/{n}_shapefit_presquash.json", "w"))
    W, H, D = d["size"]; zs = [v["z"] for v in d["voxels"]]; z0, z1 = min(zs), max(zs); old = z1 - z0 + 1; new = int(S["depth"])
    f = new / old; best = {}
    for v in d["voxels"]:
        c = (v["z"] - z0 + 0.5) * f - 0.5; zn = int(round(c)); zn = min(max(zn, 0), new - 1)
        k = (v["x"], v["y"], zn + 1); e = abs(c - zn)
        if k not in best or e < best[k][0]: best[k] = (e, v)
    out = []
    for (x, y, z), (_, v) in best.items():
        vv = dict(v, z=z); out.append(vv)
    d["voxels"] = out; d["size"] = [W, H, new + 2]
    rep = {"old_depth": old, "new_depth": new, "factor": round(f, 3), "voxels_before": len(zs), "voxels_after": len(out), "why": S.get("why")}
    d["squashed_z"] = rep; json.dump(d, open(src, "w")); json.dump(rep, open(f"out/v2/{n}_squash.json", "w"), indent=1); print(n, "squash", json.dumps(rep))

def filter_features(n):
    """keep only feature kinds the parts list names, at most the listed count each (highest evidence first): the detector
    otherwise turns sail tips into spires, a pole into a door, tower tops into chimneys"""
    P = json.load(open(f"art/final/meta/{n}_parts.json")); allow = P.get("feature_kinds")
    if allow is None: return
    p = f"art/final/meta/{n}_features.json"; F = json.load(open(p)); keep, drop = [], {}
    faces = {q["id"]: set(q["faces"]) for q in P["parts"] if len(q.get("faces", [])) < 4}   # a part listed on some faces only
    for f in sorted(F["features"], key=lambda f: -(f.get("evidence") or 0)):
        k = f["kind"]
        if k in faces and f.get("view") and f["view"] not in faces[k]: drop[k + "@" + f["view"]] = drop.get(k + "@" + f["view"], 0) + 1; continue
        if k in allow and sum(g["kind"] == k for g in keep) < allow[k]: keep.append(f)
        else: drop[k] = drop.get(k, 0) + 1
    for kk, ki in F.get("kits", {}).items():   # hand overrides from the parts list (e.g. a red-framed window, not the detector's "none")
        ov = P.get("kit_overrides", {}).get(ki.get("kind"))
        if ov: ki.update(ov); ki["overridden"] = sorted(ov)
    F["features"] = keep; F["parts_filter"] = {"allowed": allow, "dropped": drop}
    F["counts"] = {k: sum(f["kind"] == k for f in keep) for k in allow}; json.dump(F, open(p, "w"), indent=1); print(n, "features kept", F["counts"], "dropped", drop)

def stage_colour(n):
    import palette_generic; palette_generic.run(n)
    tag = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"]
    for cmd in (["feature_detect.py", n, "--sheet", tag], ["colour_albedo.py", n, "--sheet", tag, "--mesh", f"out/{n}_lowpoly.glb", "--dark-rules"], ["noise_measure.py", n]):
        if cmd[0] == "feature_detect.py" and os.environ.get("V2_KEEP_FEATURES") == "1" and os.path.exists(f"art/final/meta/{n}_features.json"):
            print(n, "feature_detect skipped (V2_KEEP_FEATURES=1, reusing the filtered features)"); continue
        r = subprocess.run([sys.executable] + cmd, capture_output=True, text=True); print(r.stdout[-1500:], r.stderr[-2500:])
        if r.returncode: raise SystemExit(cmd[0] + " failed")
        if cmd[0] == "feature_detect.py": filter_features(n)

def stage_zones(n):
    """hand zone paint from the parts list (parts.json "zones"), applied after colour_albedo when the drawing projection is
    unreliable (cottage: low white walls under a deep thatch eave). Geometry rules, per surface block:
      chimney   y >= chimney_y                                   -> chimney material
      gable     exposed to +-x, on the end-wall planes, y <= gable_top -> wall
      eave wall exposed to +-z, on the long-wall planes, y <= wall_top -> wall
      openings  front-exposed blocks inside a front door/window rect (+1 column), y <= rect top -> wall (the feature pass builds them)
      other surface -> roof material; interior -> roof material (unseen)
    Rewrites the material labels and colours, then re-runs noise_measure."""
    P = json.load(open(f"art/final/meta/{n}_parts.json")); Z = P.get("zones")
    if not Z: return
    T = json.load(open(f"art/final/{n}_voxels_textured.json")); Lb = json.load(open(f"art/final/meta/{n}_texture_labels.json"))
    W, H, D = T["size"]; occ = np.zeros((W, H, D), bool)
    for v in T["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    def solid(x, y, z): return 0 <= x < W and 0 <= y < H and 0 <= z < D and occ[x, y, z]
    if Z.get("drop_ground_props"):   # drawn benches / steps / planters: ground-level blocks outside the walls' footprint (layer y = 2)
        fx = np.nonzero(occ[:, 2, :].any(1))[0]; fz = np.nonzero(occ[:, 2, :].any(0))[0]
        gone = {(v["x"], v["y"], v["z"]) for v in T["voxels"] if v["y"] <= 1 and not (fx[0] <= v["x"] <= fx[-1] and fz[0] <= v["z"] <= fz[-1])}
        T["voxels"] = [v for v in T["voxels"] if (v["x"], v["y"], v["z"]) not in gone]; Lb["voxels"] = [v for v in Lb["voxels"] if (v["x"], v["y"], v["z"]) not in gone]
        for x, y, z in gone: occ[x, y, z] = False
        print(n, "zones: dropped ground props", len(gone))
    xs = np.nonzero(occ[:, 0, :].any(1))[0]; zs = np.nonzero(occ[:, 0, :].any(0))[0]
    xw, zw = {int(xs[0]), int(xs[-1])}, set(range(int(zs[0]), int(zs[0]) + 2)) | set(range(int(zs[-1]) - 1, int(zs[-1]) + 1))
    F = json.load(open(f"art/final/meta/{n}_features.json"))["features"]
    rects = [f["rect"] for f in F if f.get("rect") and f.get("view") == "front"]
    if Z.get("mode") == "force":
        # windmill: the sail lattice is see-through in the drawing, so the sail plane took the tower's stone colour
        k = 0
        for v in Lb["voxels"]:
            for r in Z["rules"]:
                if v[r["axis"]] == r["eq"] and all(lo <= v[a] <= hi for a, (lo, hi) in r.get("within", {}).items()): v["m"] = r["m"]; v["sh"] = 0; k += 1; break
        M = {(v["x"], v["y"], v["z"]): v["m"] for v in Lb["voxels"]}; bases = Lb["bases"]; pal = {}
        for v in T["voxels"]:
            h = bases[M[(v["x"], v["y"], v["z"])]]; v["c"] = pal.setdefault(h, f"p{len(pal)}")
        T["palette"] = {kk: h for h, kk in pal.items()}; Lb["zones_override"] = dict(Z, relabelled=k)
        json.dump(T, open(f"art/final/{n}_voxels_textured.json", "w")); json.dump(Lb, open(f"art/final/meta/{n}_texture_labels.json", "w"))
        r = subprocess.run([sys.executable, "noise_measure.py", n], capture_output=True, text=True)
        if r.returncode: print(r.stderr[-1500:]); raise SystemExit("noise_measure failed")
        print(n, "zones: forced", k); return
    if Z.get("mode") == "roof_not_under_wall":
        # gate: the drawings' dark arch outlines / shaded soffits label vertical stone as roof. A roof never sits under
        # wall: going down each column, a roof-labelled block directly under a wall block becomes wall.
        roof, wall = Z["roof"], Z["wall"]; lab = {(v["x"], v["y"], v["z"]): v for v in Lb["voxels"]}; k = 0
        for v in sorted(Lb["voxels"], key=lambda v: -v["y"]):
            a = lab.get((v["x"], v["y"] + 1, v["z"]))
            if v["m"] == roof and a is not None and a["m"] == wall: v["m"] = wall; v["sh"] = 0; k += 1
        M = {(v["x"], v["y"], v["z"]): v["m"] for v in Lb["voxels"]}; bases = Lb["bases"]; pal = {}
        for v in T["voxels"]:
            h = bases[M[(v["x"], v["y"], v["z"])]]; v["c"] = pal.setdefault(h, f"p{len(pal)}")
        T["palette"] = {kk: h for h, kk in pal.items()}; Lb["zones_override"] = dict(Z, relabelled=k)
        json.dump(T, open(f"art/final/{n}_voxels_textured.json", "w")); json.dump(Lb, open(f"art/final/meta/{n}_texture_labels.json", "w"))
        r = subprocess.run([sys.executable, "noise_measure.py", n], capture_output=True, text=True)
        if r.returncode: print(r.stderr[-1500:]); raise SystemExit("noise_measure failed")
        print(n, "zones: roof under wall -> wall", k); return
    wall, roof, chim = Z["wall"], Z["roof"], Z["chimney"]; M = {}
    for v in Lb["voxels"]:
        x, y, z = v["x"], v["y"], v["z"]
        if y >= Z["chimney_y"]: m = chim
        elif any(not solid(x + d, y, z) for d in (-1, 1)) and x in xw and y <= Z["gable_top"]: m = wall
        elif any(not solid(x, y, z + d) for d in (-1, 1)) and (z in zw or not solid(x, y, z + 1)) and y <= Z["wall_top"] and (z in zw): m = wall
        elif not solid(x, y, z + 1) and any(r["u"][0] <= x <= r["u"][1] and y <= r["y"][1] for r in rects): m = wall
        else: m = roof
        M[(x, y, z)] = m; v["m"] = m; v["sh"] = 0; v.pop("blend", None)
    bases = Lb["bases"]; pal = {}
    for v in T["voxels"]:
        h = bases[M[(v["x"], v["y"], v["z"])]]; v["c"] = pal.setdefault(h, f"p{len(pal)}")
    T["palette"] = {k: h for h, k in pal.items()}; T["colour_source"] += " + run_v2 zones (parts.json)"
    Lb["zones_override"] = {k: v for k, v in Z.items()}
    import collections; cnt = collections.Counter(M[(v["x"], v["y"], v["z"])] for v in Lb["voxels"] if v["surf"])
    json.dump(T, open(f"art/final/{n}_voxels_textured.json", "w")); json.dump(Lb, open(f"art/final/meta/{n}_texture_labels.json", "w"))
    r = subprocess.run([sys.executable, "noise_measure.py", n], capture_output=True, text=True)
    if r.returncode: print(r.stderr[-1500:]); raise SystemExit("noise_measure failed")
    print(n, "zones", dict(cnt), "wall planes x", sorted(xw), "z", sorted(zw))

def stage_map(n):
    r = subprocess.run([sys.executable, "mc_map.py", n], capture_output=True, text=True); print(r.stdout[-1500:], r.stderr[-2500:])
    if r.returncode: raise SystemExit("mc_map failed")
    P = json.load(open(f"art/final/meta/{n}_parts.json"))
    if P.get("drop_lone_posts"):   # thin wall/fence posts the shape fit left standing alone on a roof edge (not spires)
        import mc_render
        p = f"art/final/{n}_mc_blocks.json"; d = json.load(open(p)); occ = {(v["x"], v["y"], v["z"]) for v in d["voxels"]}; gone = []
        for v in d["voxels"]:
            q = d["palette"][v["b"]]
            if (q["id"].endswith("_wall") or q["id"].endswith("_fence")) and q.get("material") != "spire":
                x, y, z = v["x"], v["y"], v["z"]
                if sum((x + a, y, z + b) in occ for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))) <= 1: gone.append((x, y, z))
        if gone:
            g = set(gone); d["voxels"] = [v for v in d["voxels"] if (v["x"], v["y"], v["z"]) not in g]
            used = {v["b"] for v in d["voxels"]}
            for k_, q in d["palette"].items(): q["count"] = sum(1 for v in d["voxels"] if v["b"] == k_) if k_ in used else 0
            d["summary"]["lone_posts_dropped"] = len(gone); d.pop("bake", None); d = mc_render.attach_bake(d)
            open(p, "w").write(json.dumps(d)); mc_render.export(p, f"art/final/schematics/{n}_mc_blocks")
        print(n, "lone posts dropped", len(gone))
    if os.environ.get("MC_SHADE_GRADIENT") == "1": stage_grad(n)   # SME-14: also write the <n>_grad gradient variant

GRAD = {"windmill_v2": ("windmill_grad", 0.5, 0.5), "cottage_v2": ("cottage_grad", 0.25, 0.75), "gate": ("gate_grad", 0.5, 0.5)}
def stage_grad(n):
    """SME-14: hybrid shadow/highlight block gradients on top of the finished model (shade_gradient.py). Writes
    art/final/<n>_grad_mc_blocks.json + schematics; the flat v2 model is not touched. The cottage's drawing projection is
    unreliable (zones override it), so its texture signal is down-weighted."""
    import shade_gradient
    out, wt, wg = GRAD.get(n, (n.replace("_v2", "") + "_grad", 0.5, 0.5))
    pp = f"art/final/meta/{n}_parts.json"; g = json.load(open(pp)).get("grad", {}) if os.path.exists(pp) else {}
    # optional per-subject extras: "photo" = front-photo shadow projection, "eyebrows" = recessed eyebrow-arch rebuild
    shade_gradient.run(n, out, wt, wg, photo=g.get("photo"), eyebrows=g.get("eyebrows"))

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

STAGES = {"sheets": stage_sheets, "mesh": stage_mesh, "paint": stage_paint, "shape": stage_shape, "carve": stage_carve, "sails": stage_sails, "squash": stage_squash,
          "colour": stage_colour, "zones": stage_zones, "map": stage_map, "grad": stage_grad, "check": stage_check}
if __name__ == "__main__":
    os.makedirs("out/v2", exist_ok=True)
    n, *st = sys.argv[1:]
    for s in (list(STAGES) if st == ["all"] else st): print("==", n, s); STAGES[s](n)
