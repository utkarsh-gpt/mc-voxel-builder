#!/usr/bin/env python3
"""Hybrid shadow / highlight block gradients (SME-14, Nov 26 2026).

Takes a finished mc_blocks model (geometry, materials and feature kits stay exactly as built) and re-shades every block of
the big material zones along a builder-style block ladder  shadow <- base -> highlight.

Per surface block a shade scalar s in [-1, 1] is the blend of
  (a) TEXTURE: the shaded ortho sheet's lightness at that block (colour_albedo.samples, NO de-shade) minus the zone's
      median lightness, i.e. the shadows / highlights the drawing shows;
  (b) GEOMETRY: ambient occlusion from the occupancy of a 5x5x5 neighbourhood (recessed corners, arch reveals -> dark,
      convex edges -> light), under-eave / soffit darkening (solid within 4 blocks above a side-exposed block), ground
      contact darkening (y 0-1), and sun/sky exposure for highlights (air above, open column to the sky).
s is smoothed over same-zone surface neighbours, normalised per zone (90th percentile of |s| -> 1), then quantised to the
ladder with a 4x4 ordered (Bayer) dither that only acts inside the transition bands, so the result reads as deliberate
banding/gradient, not salt-and-pepper noise. Interior blocks stay on the base.

Ladders: curated per material family (grey stone, dark slate, thatch, plaster, brick, light wood) merged with data-driven
candidates from the block dataset (same allowed() filter as mc_map: no ores, coral, glazed terracotta, gravity blocks,
creaking_heart; full blocks only, so never a glass pane), kept inside the base's hue (a*b* distance), ordered by L*, one
block per lightness step. Each step's stairs / slab / wall / trapdoor variant replaces the same-shaped block; when a step
has no such variant the nearest step toward the base that has one is used.

Protected (never re-shaded): door, frame, glass, spire, window_* materials and the window backing block.

usage: python shade_gradient.py SRC OUT [--w-tex 0.5] [--w-geo 0.5]      e.g. windmill_v2 windmill_grad
       (run_v2.py stage "grad", or MC_SHADE_GRADIENT=1 for run_v2's map stage, writes NAME_grad)"""
import argparse, collections, json, math, os
import numpy as np
from scipy import ndimage
import mc_map as MM, mc_render, colour_albedo as CA

PROTECT = {"door", "frame", "glass", "spire", "window_dark", "window_lit", "glass_dark", "soffit", "recess"}
BACKING = MM.BACKING
# curated ladders (dark -> light); blocks missing from the dataset or failing allowed() are skipped
CURATED = {
    "grey_stone": ["deepslate", "cobbled_deepslate", "tuff", "tuff_bricks", "cobblestone", "stone", "andesite", "stone_bricks",
                   "polished_andesite", "smooth_stone", "diorite", "polished_diorite", "calcite"],
    "warm_stone": ["mud_bricks", "packed_mud", "dripstone_block", "sandstone", "smooth_sandstone", "birch_planks", "bone_block"],
    "dark_slate": ["blackstone", "deepslate_tiles", "polished_deepslate", "deepslate_bricks", "cobbled_deepslate", "gray_concrete",
                   "tuff", "polished_basalt", "stone"],
    # cottage thatch is a neutral grey-green (light_gray_wool base): the greenish tuff and flat light_gray_concrete for the
    # shaded courses, smooth_stone for the sunlit ridge; wool has no mid steps (gray_wool is L 28)
    "thatch": ["tuff", "light_gray_concrete", "light_gray_wool", "smooth_stone", "andesite"],
    "plaster": ["light_gray_concrete", "andesite", "smooth_stone", "diorite", "light_gray_wool", "white_wool", "calcite",
                "white_concrete", "snow_block", "quartz_block"],
    "brick": ["red_terracotta", "bricks", "polished_granite", "granite"],
    "light_wood": ["stripped_oak_wood", "birch_planks", "birch_wood", "stripped_birch_wood", "pale_oak_planks", "pale_oak_wood",
                   "stripped_pale_oak_wood"],
}
# zone material -> (curated ladder, shadow steps, highlight steps, L step, max a*b* distance from the base, family prefs)
ZONES = {
    "stone": ("grey_stone", 3, 2, 7.0, 8.0, {"stone", "andesite", "tuff", "deepslate", "diorite", "calcite"}),
    "gate_stone": ("grey_stone", 3, 2, 7.0, 8.0, {"stone", "andesite", "tuff", "deepslate", "diorite", "calcite"}),
    "cap_slate": ("dark_slate", 2, 2, 6.0, 8.0, {"deepslate", "blackstone", "basalt", "tuff", "concrete"}),
    "roof_slate": ("dark_slate", 2, 2, 6.0, 8.0, {"deepslate", "blackstone", "basalt", "tuff", "concrete"}),
    "thatch": ("thatch", 2, 0, 6.5, 9.0, {"wool", "terracotta", "tuff", "mud", "stone", "andesite"}),
    "wall_white": ("plaster", 2, 2, 5.0, 7.0, {"wool", "concrete", "quartz", "calcite", "snow", "diorite", "stone"}),
    "chimney_brick": ("brick", 1, 1, 9.0, 18.0, {"brick", "mud", "granite", "terracotta"}),
    "sail_white": ("light_wood", 1, 1, 5.0, 10.0, {"wood"}),
}
B4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16.0
SHAPE_OF = {"full_block": None, "stairs": MM.stairs_of, "slab": MM.slab_of, "wall": MM.wall_of, "trapdoor": MM.trapdoor_of}

def L_of(bid): return MM.lab_of(MM.BL[bid], "side")

def _srgb_to_L(rgb):
    c = rgb/255.0; c = np.where(c <= 0.04045, c/12.92, ((c + 0.055)/1.055)**2.4)
    Y = c @ np.array([0.2126, 0.7152, 0.0722]); f = np.where(Y > 0.008856, np.cbrt(Y), 7.787*Y + 16/116)
    return 116*f - 16

def photo_front_L(occ, spec):
    """Mean photo L* for the frontmost (+z) block of every (x, y) column of the front projection.
    The photo is aligned to the voxel front by piecewise-linear anchors (model coordinate -> photo pixel) on x
    (building edges + door / window centres) and y (ground, eave line, ridge, chimney top), so features line up even
    where the model's proportions differ from the photo."""
    from PIL import Image
    im = np.asarray(Image.open(spec["path"]).convert("RGB"), float); Lp = _srgb_to_L(im)
    ax = np.array(spec["x_anchors"], float); ay = np.array(spec["y_anchors"], float)
    fx = lambda x: np.interp(x, ax[:, 0], ax[:, 1]); fy = lambda y: np.interp(y, ay[:, 0], ay[:, 1])
    W, H, D = occ.shape; out = np.full(occ.shape, np.nan); front = np.zeros(occ.shape, bool); sh = spec.get("shrink", 0.15)
    for x in range(W):
        for y in range(H):
            zs = np.nonzero(occ[x, y])[0]
            if not len(zs): continue
            z = zs.max(); u0, u1 = fx(x), fx(x + 1); v0, v1 = fy(y + 1), fy(y)            # image v grows downward
            du, dv = (u1 - u0)*sh, (v1 - v0)*sh
            a, b = int(round(u0 + du)), int(round(u1 - du)); c, e = int(round(v0 + dv)), int(round(v1 - dv))
            if b <= a or e <= c or a < 0 or c < 0 or b > Lp.shape[1] or e > Lp.shape[0]: continue
            out[x, y, z] = Lp[c:e, a:b].mean(); front[x, y, z] = True
    return out, front

def ladder(base, zone):
    """dark -> light list of full blocks around 'base' (index of base returned too)"""
    cur, ns, nh, step, tol, fams = ZONES[zone]
    ok = lambda b: b in MM.BL and MM.allowed(MM.BL[b]) and "pane" not in b and b != "creaking_heart"
    cands = {b for b in CURATED[cur] if ok(b)} | {b["id"] for b in MM.CAND if b["family"] in fams}
    l0 = L_of(base); ab0 = l0[1:]
    def cost(b, t):
        l = L_of(b); dab = float(np.hypot(*(l[1:] - ab0)))
        if dab > tol: return None
        return abs(l[0] - t) + 0.6*dab + (0 if b in CURATED[cur] else 5.0) + (0 if MM.BL[b]["family"] == MM.BL[base]["family"] else 2.0)
    out = {0: base}; used = {base}
    for sgn, k in ((-1, ns), (1, nh)):
        prevL = l0[0]
        for i in range(1, k + 1):
            t = l0[0] + sgn*step*i; best = None
            for b in cands - used:
                lb = L_of(b)[0]
                if (lb - prevL)*sgn < 0.6*step: continue          # strictly monotone, at least ~half a step apart
                c = cost(b, t)
                if c is not None and abs(lb - t) <= 0.9*step and (best is None or c < best[0]): best = (c, b)
            if not best: break
            out[sgn*i] = best[1]; used.add(best[1]); prevL = L_of(best[1])[0]
    ks = sorted(out); ladder.cands[zone] = sorted(b for b in cands if cost(b, L_of(b)[0]) is not None)
    return [out[k] for k in ks], ks.index(0)
ladder.cands = {}

def variant(full, shape):
    f = SHAPE_OF.get(shape)
    if shape == "full_block": return full
    return f(full) if f else None

GLASS_MATS = {"glass"}   # the only material a glass pane may carry (feature-pass / eyebrow window glazing)

def run(src, out, w_tex=0.5, w_geo=0.5, log=print, photo=None, eyebrows=None, model=None):
    """photo: front-photo shadow projection spec (path, x_anchors, y_anchors, w_photo, w_geo, keep) - off by default, the
    general pipeline samples shadows from the shaded ortho sheets + 3D geometry only; eyebrows: eyebrow_arch spec;
    model: alternative source model file (e.g. the MC_GLASS=windows colour-mapping rerun) instead of art/final/SRC_mc_blocks.json"""
    model = model or f"art/final/{src}_mc_blocks.json"
    d = json.load(open(model)); W, H, D = d["size"]; pal = d["palette"]
    if eyebrows:
        import eyebrow_arch; d = eyebrow_arch.apply(d, eyebrows, log=log); pal = d["palette"]
    occ = np.zeros((W, H, D), bool)
    for v in d["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    pad = np.pad(occ, 1)
    def solid(x, y, z): return 0 <= x < W and 0 <= y < H and 0 <= z < D and occ[x, y, z]
    surf = occ & ~ndimage.binary_erosion(pad, np.ones((3, 3, 3)))[1:-1, 1:-1, 1:-1]
    # (a) texture: shaded sheet lightness per block (best-facing sample, no de-shade)
    tag = json.load(open(f"art/final/meta/{src}_views.json"))["chosen"]
    g = ndimage.gaussian_filter(occ.astype(float), 1.0); nrm = -np.stack(np.gradient(g), -1); nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-9
    Lsh = np.full(occ.shape, np.nan); best = np.full(occ.shape, -1.0)
    for r in CA.samples(src, tag, occ, nrm):
        x, y, z = r[:3]
        if r[4] > best[x, y, z]: best[x, y, z] = r[4]; Lsh[x, y, z] = r[5]
    # (b) geometry
    k = np.ones((5, 5, 5)); k[2, 2, 2] = 0
    openf = 1 - ndimage.convolve(occ.astype(float), k, mode="constant", cval=0.0)/k.sum()     # 0 = buried, 1 = isolated
    above_any = np.flip(np.cumsum(np.flip(occ, 1), 1), 1) - occ                              # solid blocks anywhere above
    sky = above_any == 0
    air_up = np.ones_like(occ); air_up[:, :-1, :] = ~occ[:, 1:, :]
    side_exp = np.zeros_like(occ)
    for ax, sh in ((0, 1), (0, -1), (2, 1), (2, -1)):
        nb = np.roll(occ, sh, ax)
        if ax == 0: nb[0 if sh == 1 else -1, :, :] = False
        else: nb[:, :, 0 if sh == 1 else -1] = False
        side_exp |= ~nb
    # sun from the front-left (+z, -x, above): faces toward it are lit, faces away (back, right) in shade
    def exposed(ax, sh):
        nb = np.roll(occ, -sh, ax)
        if ax == 0: nb[-1 if sh == 1 else 0, :, :] = False
        else: nb[:, :, -1 if sh == 1 else 0] = False
        return ~nb
    sun = 0.5*exposed(2, 1).astype(float) + 0.3*exposed(0, -1) - 0.5*exposed(2, -1) - 0.3*exposed(0, 1)
    under = np.zeros(occ.shape, bool)
    for dy in range(1, 4): under[:, :-dy, :] |= occ[:, dy:, :]
    under &= side_exp & ~air_up                                                                # soffits, eaves, arch reveals
    # eave: a side-exposed block whose own column continues up but a block 1-2 above sticks out further (overhang lip)
    over = np.zeros(occ.shape, bool)
    for dy in (1, 2):
        up = np.zeros(occ.shape, bool); up[:, :-dy, :] = occ[:, dy:, :]
        for ax, sh in ((0, 1), (0, -1), (2, 1), (2, -1)):
            out_up = np.roll(up, sh, ax)                                                          # the cell above-and-outward is solid
            over |= out_up & ~np.roll(occ, sh, ax)
    eave = side_exp & over
    yy = np.broadcast_to(np.arange(H)[None, :, None], occ.shape)
    ground = np.clip(1 - yy/3.0, 0, 1)
    ao = (openf - np.median(openf[surf]))/0.12
    geo = 0.45*np.clip(ao, -1.5, 0.3) + 0.35*np.clip(sun, -1, 1) + 0.45*(air_up & sky) + 0.2*(air_up & ~sky) - 0.55*eave - 0.35*(under & ~eave) - 0.5*ground
    # zones
    mats = {}
    for v in d["voxels"]:
        q = pal[v["b"]]; mats[(v["x"], v["y"], v["z"])] = q.get("material")
    M = np.full(occ.shape, "", object)
    for (x, y, z), m in mats.items(): M[x, y, z] = m or ""
    report = {"source": model, "weights": {"tex": w_tex, "geo": w_geo}, "zones": {}}
    Lph, front = (photo_front_L(occ, photo) if photo else (np.full(occ.shape, np.nan), np.zeros(occ.shape, bool)))
    if photo: report["photo"] = {k: v for k, v in photo.items()}; report["photo"]["front_blocks_sampled"] = int(front.sum())
    S = np.zeros(occ.shape)
    for m in ZONES:
        zm = (M == m) & surf
        if not zm.any(): continue
        tex = np.zeros(occ.shape); have = zm & ~np.isnan(Lsh)
        if have.any():
            med = np.median(Lsh[have]); tex[have] = np.clip((Lsh[have] - med)/12.0, -1.5, 1.5)
        ys = np.nonzero(zm.any((0, 2)))[0]; hz = (yy - ys.min())/max(1, ys.max() - ys.min()) - 0.5   # builders: darker foot, lighter crown
        r = w_tex*tex + w_geo*(geo + 0.5*hz)
        fz = zm & front & ~np.isnan(Lph) & (m in (photo or {}).get("zones", ZONES))
        if fz.sum() > 10:   # camera-facing front: the real photo's shadows (eyebrow undersides, thatch bands) + 3D geometry
            pmed = np.median(Lph[fz]); ph = np.zeros(occ.shape); ph[fz] = np.clip((Lph[fz] - pmed)/12.0, -1.5, 1.5)
            r = np.where(fz, photo.get("w_photo", 0.55)*ph + photo.get("w_geo", 0.45)*(geo + 0.5*hz), r)
        raw = r.copy()
        # smooth over same-zone surface neighbours (3 passes, 3x3x3)
        for _ in range(3):
            num = ndimage.uniform_filter(np.where(zm, r, 0.0), 3); den = ndimage.uniform_filter(zm.astype(float), 3)
            r = np.where(zm, 0.5*r + 0.5*num/np.maximum(den, 1e-6), r)
        if photo: r = np.where(fz, photo.get("keep", 0.6)*raw + (1 - photo.get("keep", 0.6))*r, r)   # keep the photo's mottling
        rest = zm & ~fz if fz.sum() > 10 else zm
        for part in ((rest, fz) if fz.sum() > 10 else (zm,)):   # the photo-shaded front is normalised on its own so the
            rz = r[part]; c = np.median(rz); sc = np.percentile(np.abs(rz - c), 95) or 1.0     # photo's darks use the ladder
            S[part] = np.clip((rz - c)/sc, -1, 1)
    # ladders + replacement
    # face-aware dither coordinates: the Bayer cell is indexed in the plane of the block's main exposed face, so a side wall
    # (x = const) dithers over (z, y) instead of repeating 2x2 tiles from the (x + 2z, y + z) index
    ex = {k: exposed(*k) for k in ((2, 1), (2, -1), (0, 1), (0, -1))}
    def dith(x, y, z):
        if ex[(2, 1)][x, y, z] or ex[(2, -1)][x, y, z]: u, v = x, y
        elif ex[(0, 1)][x, y, z] or ex[(0, -1)][x, y, z]: u, v = z, y
        else: u, v = x, z
        return B4[u % 4, v % 4] - 0.5
    newvox = []; states = {}; stats = collections.defaultdict(collections.Counter); ladders = {}
    for m in ZONES:
        ids = [pal[v["b"]]["id"] for v in d["voxels"] if pal[v["b"]].get("material") == m and MM.BL[pal[v["b"]]["id"]]["shape"] == "full_block" and pal[v["b"]]["id"] != BACKING]
        if not ids: continue
        base = collections.Counter(ids).most_common(1)[0][0]; lad, bi = ladder(base, m)
        ladders[m] = {"base": base, "ladder_dark_to_light": lad, "L": [round(float(L_of(b)[0]), 1) for b in lad], "base_index": bi}
    for v in d["voxels"]:
        q = pal[v["b"]]; m = q.get("material"); x, y, z = v["x"], v["y"], v["z"]; bid, props = q["id"], q.get("props", {})
        if m in ladders and m not in PROTECT and bid != BACKING and surf[x, y, z]:
            lad, bi = ladders[m]["ladder_dark_to_light"], ladders[m]["base_index"]; s = S[x, y, z]
            nsd, nhl = bi, len(lad) - 1 - bi
            t = dith(x, y, z)
            s = math.copysign(abs(s)**1.4, s)                                                   # fewer blocks at the ends of the ladder
            pos = s*(nsd if s < 0 else nhl) + 0.55*t                                            # dither only shifts near band edges
            idx = int(np.clip(math.floor(pos + 0.5), -nsd, nhl)) + bi
            shape = MM.BL[bid]["shape"]; pick = None
            for j in sorted(range(len(lad)), key=lambda j: (abs(j - idx), abs(j - bi))):       # nearest step having this shape
                vv = variant(lad[j], shape)
                if not vv and j != bi:   # the step block has no stairs/slab/...: a same-lightness in-hue block that has one
                    lj = L_of(lad[j])[0]; alts = [(abs(L_of(c)[0] - lj), variant(c, shape)) for c in ladder.cands[m] if variant(c, shape)]
                    alts = [a for a in alts if a[0] <= 0.5*ZONES[m][3]]
                    if alts: vv = min(alts)[1]
                if vv: pick = (j, vv); break
            if pick:
                j, nb = pick; band = "shadow" if j < bi else ("highlight" if j > bi else "base")
                if band != "base": bid = nb                                                      # the base band keeps the v2 block (its ramp / trapdoor wood)
            else: band = "kept"
            stats[m][band] += 1; stats[m]["block:" + bid] += 1
        elif m in ladders:
            stats[m]["interior" if not surf[x, y, z] else "kept"] += 1
        st = "minecraft:" + bid + ("[" + ",".join(f"{a}={b}" for a, b in sorted(props.items())) + "]" if props else "")
        sk = (st, m)                                                                             # same block, own material
        if sk not in states:
            states[sk] = {"key": f"b{len(states)}", "id": bid, "props": props, "state": st, "material": m, "count": 0,
                          "roles": q.get("roles", {}), "technique": q.get("technique")}
        states[sk]["count"] += 1; newvox.append({"x": x, "y": y, "z": z, "b": states[sk]["key"]})
    stray = [s["state"] for s in states.values() if ("pane" in s["id"] or "glass" in s["id"]) and s["material"] not in GLASS_MATS]
    assert not stray, f"glass outside window openings: {stray}"
    for m in ladders:
        c = stats[m]; tot = sum(c[b] for b in ("shadow", "base", "highlight"))
        ladders[m]["surface_split_pct"] = {b: round(100*c[b]/tot, 1) for b in ("shadow", "base", "highlight")} if tot else {}
        ladders[m]["blocks"] = {k[6:]: n for k, n in c.most_common() if k.startswith("block:")}
        ladders[m]["counts"] = {k: n for k, n in c.items() if not k.startswith("block:")}
    report["zones"] = ladders
    o = dict(d, name=f"{out}_mc_blocks", palette={s["key"]: s for s in states.values()}, voxels=newvox)
    o["summary"] = dict(d.get("summary", {}), shade_gradient=report)
    o = mc_render.attach_bake(o)
    open(f"art/final/{out}_mc_blocks.json", "w").write(json.dumps(o))
    mc_render.export(f"art/final/{out}_mc_blocks.json", f"art/final/schematics/{out}_mc_blocks")
    os.makedirs("out/grad", exist_ok=True)
    np.savez_compressed(f"out/grad/{out}_shade.npz", S=S, occ=occ, surf=surf, geo=geo, Lsh=np.nan_to_num(Lsh, nan=-1),
                        Lph=np.nan_to_num(Lph, nan=-1), front=front)
    json.dump(report, open(f"art/final/meta/{out}_shade_gradient.json", "w"), indent=1)
    for m, z in ladders.items(): log(out, m, z["ladder_dark_to_light"], z["L"], "split", z["surface_split_pct"])
    return report

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--w-tex", type=float, default=0.5); ap.add_argument("--w-geo", type=float, default=0.5)
    a = ap.parse_args(); run(a.src, a.out, a.w_tex, a.w_geo)
