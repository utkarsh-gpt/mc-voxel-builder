#!/usr/bin/env python3
"""voxel_ai: AI voxel JSON -> multi-angle previews + Minecraft exports.

Input JSON (any mix of the three geometry sections; later ones overwrite earlier):
{
  "name": "cottage",
  "size": [W, H, D],                     # x (east), y (up), z (south)
  "palette": {".": "minecraft:air", "P": "minecraft:oak_planks", ...},
  "boxes":  [{"from":[x,y,z], "to":[x,y,z], "block":"P", "hollow":false}],
  "layers": [ ["row z=0 (W chars)", ...D rows], ...H layers, y=0 first ],
  "blocks": [{"x":0,"y":0,"z":0,"block":"P"}]
}
"block" may be a palette key or a full id like "minecraft:oak_stairs[facing=north]".

Usage:
  python voxel_ai.py build examples/cottage.json --out out/cottage
  python voxel_ai.py mesh model.glb --size 32 --out out/thing   # mesh -> voxel JSON (+ build)
"""
import argparse, json, math, os, re, sys, colorsys, hashlib
import numpy as np

AIR = "minecraft:air"

# Approximate average texture colours for common blocks (RGB 0-255).
BLOCK_COLORS = {
 "stone":(125,125,125),"cobblestone":(122,122,122),"mossy_cobblestone":(110,118,95),"stone_bricks":(122,121,122),
 "mossy_stone_bricks":(115,121,105),"andesite":(136,136,137),"polished_andesite":(132,135,134),"diorite":(189,188,189),
 "granite":(149,103,85),"deepslate":(80,80,82),"deepslate_bricks":(70,70,71),"deepslate_tiles":(54,54,55),
 "cobbled_deepslate":(77,77,80),"blackstone":(42,36,41),"bricks":(150,97,83),"sandstone":(216,203,155),
 "smooth_stone":(158,158,158),"tuff":(108,109,102),"calcite":(223,224,220),"gravel":(131,127,126),
 "dirt":(134,96,67),"coarse_dirt":(119,85,59),"grass_block":(95,159,53),"podzol":(91,63,24),"sand":(219,207,163),
 "clay":(160,166,179),"snow_block":(249,254,254),"ice":(145,183,253),"packed_ice":(141,180,250),
 "oak_planks":(162,130,78),"spruce_planks":(114,84,48),"birch_planks":(192,175,121),"dark_oak_planks":(66,43,20),
 "jungle_planks":(160,115,80),"acacia_planks":(168,90,50),"cherry_planks":(226,178,172),"mangrove_planks":(117,54,48),
 "oak_log":(109,85,50),"spruce_log":(58,37,16),"birch_log":(216,215,210),"dark_oak_log":(60,46,26),
 "stripped_oak_log":(177,144,86),"stripped_spruce_log":(115,89,52),"cherry_log":(54,33,44),
 "oak_leaves":(60,120,30),"spruce_leaves":(48,80,48),"birch_leaves":(96,140,60),"dark_oak_leaves":(50,100,25),
 "cherry_leaves":(228,170,200),"azalea_leaves":(90,117,44),"flowering_azalea_leaves":(100,111,61),
 "glass":(200,220,230),"glass_pane":(200,220,230),"white_stained_glass":(255,255,255),"light_blue_stained_glass":(102,153,216),
 "white_wool":(234,236,237),"red_wool":(161,39,35),"blue_wool":(53,57,157),"yellow_wool":(249,198,40),
 "white_concrete":(207,213,214),"gray_concrete":(55,58,62),"black_concrete":(8,10,15),"red_concrete":(142,33,33),
 "terracotta":(152,94,68),"red_terracotta":(143,61,47),"brown_terracotta":(77,51,36),
 "water":(63,118,228),"lava":(207,92,20),"glowstone":(171,131,84),"lantern":(200,150,70),"torch":(255,200,80),
 "wall_torch":(255,200,80),"sea_lantern":(172,199,190),"shroomlight":(240,146,70),"campfire":(160,90,40),
 "iron_block":(220,220,220),"gold_block":(246,208,61),"copper_block":(192,107,79),"hay_block":(166,139,12),
 "bookshelf":(117,94,59),"crafting_table":(120,73,42),"furnace":(110,110,110),"chest":(162,115,48),
 "white_bed":(220,220,220),"red_bed":(160,40,40),"flower_pot":(120,68,50),"poppy":(200,30,30),"dandelion":(240,220,40),
 "short_grass":(100,160,60),"fern":(90,140,60),"moss_block":(89,109,45),"moss_carpet":(89,109,45),
 "vine":(60,110,30),"lily_pad":(40,120,40),"pumpkin":(198,118,24),"melon":(111,145,30),
}
SUFFIX_BASE = ["_stairs","_slab","_wall","_fence_gate","_fence","_door","_trapdoor","_button","_pressure_plate","_pane","_carpet"]

def base_name(block_id):
    b = block_id.split("[")[0].replace("minecraft:","")
    return b

def color_of(block_id):
    b = base_name(block_id)
    if b in BLOCK_COLORS: return BLOCK_COLORS[b]
    for s in SUFFIX_BASE:
        if b.endswith(s):
            root = b[:-len(s)]
            for cand in (root, root+"s", root+"_planks", root.replace("brick","bricks")):
                if cand in BLOCK_COLORS: return BLOCK_COLORS[cand]
    for k,v in BLOCK_COLORS.items():          # fuzzy: shares a word
        if k in b or b in k: return v
    h = int(hashlib.md5(b.encode()).hexdigest()[:6],16)   # stable fallback colour
    r,g,bb = colorsys.hsv_to_rgb((h%360)/360, .45, .75)
    return (int(r*255),int(g*255),int(bb*255))

def is_translucent(block_id):
    b = base_name(block_id)
    return "glass" in b or b in ("water","ice") or b.endswith("leaves")

def norm_id(b):
    b = b.strip()
    if b in ("", "air", ".", " "): return AIR
    return b if ":" in b.split("[")[0] else "minecraft:" + b

# ---------------------------------------------------------------- load / validate
def load_structure(path_or_obj):
    d = path_or_obj if isinstance(path_or_obj, dict) else json.load(open(path_or_obj))
    pal = {k: norm_id(v) for k, v in d.get("palette", {}).items()}
    pal.setdefault(".", AIR); pal.setdefault(" ", AIR)
    W, H, D = d["size"]
    grid = np.full((W, H, D), AIR, dtype=object)
    warn = []
    def resolve(tok):
        if tok in pal: return pal[tok]
        if len(tok) > 1: return norm_id(tok)
        warn.append(f"unknown palette key {tok!r} -> air"); return AIR
    def put(x, y, z, b):
        if 0 <= x < W and 0 <= y < H and 0 <= z < D: grid[x, y, z] = b
        else: warn.append(f"out of bounds {(x,y,z)} dropped")
    for bx in d.get("boxes", []):
        (x0,y0,z0),(x1,y1,z1) = bx["from"], bx["to"]; b = resolve(bx["block"])
        xs,ys,zs = sorted((x0,x1)),sorted((y0,y1)),sorted((z0,z1))
        for x in range(xs[0],xs[1]+1):
            for y in range(ys[0],ys[1]+1):
                for z in range(zs[0],zs[1]+1):
                    if bx.get("hollow") and xs[0]<x<xs[1] and zs[0]<z<zs[1] and ys[0]<y<ys[1]: continue
                    put(x,y,z,b)
    for y, layer in enumerate(d.get("layers", [])):
        if y >= H: warn.append(f"extra layer {y} dropped"); break
        for z, row in enumerate(layer):
            if z >= D: warn.append(f"layer {y}: extra row {z} dropped"); break
            if len(row) != W: warn.append(f"layer {y} row {z}: len {len(row)} != {W}")
            for x, ch in enumerate(row[:W]):
                if ch in (".", " "): continue
                put(x, y, z, resolve(ch))
    for bl in d.get("blocks", []):
        put(bl["x"], bl["y"], bl["z"], resolve(bl["block"]))
    n = int((grid != AIR).sum())
    return d.get("name", "structure"), grid, warn, n

# ---------------------------------------------------------------- render
def render(grid, out_prefix, title=""):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    W, H, D = grid.shape
    filled = grid != AIR
    # matplotlib axes: X=x(east), Y=z(south), Z=y(up)
    filled_m = np.transpose(filled, (0, 2, 1))
    cols = np.zeros(filled_m.shape + (4,))
    ec = np.zeros(filled_m.shape + (4,))
    cache = {}
    for (x, y, z), b in np.ndenumerate(grid):
        if b == AIR: continue
        if b not in cache:
            r, g, bb = color_of(b); a = .45 if is_translucent(b) else 1.0
            cache[b] = (r/255, g/255, bb/255, a)
        c = cache[b]; cols[x, z, y] = c
        ec[x, z, y] = (c[0]*.6, c[1]*.6, c[2]*.6, min(1, c[3]+.2))
    views = [("iso_a", 20, -60), ("iso_b", 20, -120), ("iso_c", 20, 120),
             ("iso_d", 20, 60), ("top", 85, -90), ("side_level", 5, -90)]
    paths = []
    fig = plt.figure(figsize=(18, 11))
    for i, (nm, elev, azim) in enumerate(views):
        ax = fig.add_subplot(2, 3, i+1, projection="3d")
        ax.voxels(filled_m, facecolors=cols, edgecolors=ec, linewidth=0.3)
        ax.view_init(elev=elev, azim=azim)
        ax.set_box_aspect((W, D, H)); ax.invert_yaxis()
        ax.set_xlabel("x (E)"); ax.set_ylabel("z (S)"); ax.set_zlabel("y (up)")
        ax.set_title(f"{nm} (elev {elev}, azim {azim})")
    fig.suptitle(title or os.path.basename(out_prefix)); fig.tight_layout()
    p = f"{out_prefix}_views.png"; fig.savefig(p, dpi=90); plt.close(fig); paths.append(p)
    # individual hero shots
    for nm, elev, azim in views[:4]:
        fig = plt.figure(figsize=(8, 8)); ax = fig.add_subplot(111, projection="3d")
        ax.voxels(filled_m, facecolors=cols, edgecolors=ec, linewidth=0.3)
        ax.view_init(elev=elev, azim=azim); ax.set_box_aspect((W, D, H)); ax.invert_yaxis(); ax.set_axis_off()
        p = f"{out_prefix}_{nm}.png"; fig.savefig(p, dpi=100, bbox_inches="tight"); plt.close(fig); paths.append(p)
    return paths

# ---------------------------------------------------------------- exports
def export_mcfunction(grid, path, origin="~ ~ ~"):
    """Relative-coord setblock/fill commands. Merges runs along x into `fill`.
    Run as the player/command source; build starts at (~1, ~, ~1) i.e. just SE of you."""
    W, H, D = grid.shape
    lines = [f"# generated by voxel_ai: {W}x{H}x{D}, origin = executor position + (1,0,1)",
             f"fill ~1 ~ ~1 ~{W} ~{H-1} ~{D} minecraft:air"]
    def needs_support(b):  # place fragile blocks last
        nb = base_name(b)
        return any(s in nb for s in ("torch","door","lantern","carpet","flower","pot","button","vine","bed","lily","grass","fern","poppy","dandelion","sign","rail"))
    for phase in (0, 1):
        for y in range(H):
            for z in range(D):
                x = 0
                while x < W:
                    b = grid[x, y, z]
                    if b == AIR or needs_support(b) != bool(phase): x += 1; continue
                    x2 = x
                    while x2+1 < W and grid[x2+1, y, z] == b: x2 += 1
                    if x2 == x: lines.append(f"setblock ~{x+1} ~{y} ~{z+1} {b}")
                    else: lines.append(f"fill ~{x+1} ~{y} ~{z+1} ~{x2+1} ~{y} ~{z+1} {b}")
                    x = x2 + 1
    open(path, "w").write("\n".join(lines) + "\n")
    return path, len(lines)

def _parse_state(b):
    m = re.match(r"^([^\[]+)(?:\[(.*)\])?$", b)
    bid, props = m.group(1), {}
    if m.group(2):
        for kv in m.group(2).split(","):
            if "=" in kv: k, v = kv.split("=", 1); props[k.strip()] = v.strip()
    return bid, props

def export_schem(grid, path):
    import mcschematic
    s = mcschematic.MCSchematic()
    for (x, y, z), b in np.ndenumerate(grid):
        if b != AIR: s.setBlock((x, y, z), b)
    folder, fn = os.path.split(os.path.abspath(path))
    s.save(folder, fn.replace(".schem", ""), mcschematic.Version.JE_1_21_5)
    return path

def export_litematic(grid, path, name):
    from litemapy import Region, BlockState
    W, H, D = grid.shape
    reg = Region(0, 0, 0, W, H, D)
    cache = {}
    for (x, y, z), b in np.ndenumerate(grid):
        if b == AIR: continue
        if b not in cache:
            bid, props = _parse_state(b); cache[b] = BlockState(bid, **props)
        reg[x, y, z] = cache[b]
    reg.as_schematic(name=name, author="voxel_ai", description="AI-generated", mc_version=4325).save(path)
    return path

def build(src, out_prefix):
    name, grid, warn, n = load_structure(src)
    os.makedirs(os.path.dirname(out_prefix) or ".", exist_ok=True)
    for w in warn[:20]: print("WARN:", w)
    if len(warn) > 20: print(f"WARN: ...{len(warn)-20} more")
    W, H, D = grid.shape
    uniq = sorted(set(grid[grid != AIR].tolist()))
    print(f"{name}: {W}x{H}x{D}, {n} blocks, {len(uniq)} block types")
    pngs = render(grid, out_prefix, f"{name} - {W}x{H}x{D}, {n} blocks")
    mcf, nl = export_mcfunction(grid, out_prefix + ".mcfunction")
    res = {"previews": pngs, "mcfunction": mcf, "mcfunction_lines": nl}
    try: res["schem"] = export_schem(grid, out_prefix + ".schem")
    except Exception as e: print("schem export failed:", e)
    try: res["litematic"] = export_litematic(grid, out_prefix + ".litematic", name)
    except Exception as e: print("litematic export failed:", e)
    json.dump({"name": name, "size": [W, H, D], "warnings": warn, **res}, open(out_prefix + "_report.json", "w"), indent=2)
    print(json.dumps(res, indent=2))
    return res

# ---------------------------------------------------------------- mesh -> voxels
PALETTE_FOR_MESH = ["white_concrete","light_gray_concrete","gray_concrete","black_concrete","brown_concrete","red_concrete",
 "orange_concrete","yellow_concrete","lime_concrete","green_concrete","cyan_concrete","light_blue_concrete","blue_concrete",
 "purple_concrete","magenta_concrete","pink_concrete","oak_planks","spruce_planks","dark_oak_planks","birch_planks",
 "stone","cobblestone","stone_bricks","bricks","sandstone","dirt","grass_block","oak_leaves","terracotta","snow_block"]
EXTRA = {"light_gray_concrete":(125,125,115),"brown_concrete":(96,60,32),"orange_concrete":(224,97,1),"yellow_concrete":(241,175,21),
 "lime_concrete":(94,169,24),"green_concrete":(73,91,36),"cyan_concrete":(21,119,136),"light_blue_concrete":(36,137,199),
 "blue_concrete":(45,47,143),"purple_concrete":(100,32,156),"magenta_concrete":(169,48,159),"pink_concrete":(214,101,143)}
BLOCK_COLORS.update(EXTRA)

def mesh_to_json(mesh_path, size=32, name=None):
    import trimesh
    sc = trimesh.load(mesh_path)
    mesh = sc.to_geometry() if isinstance(sc, trimesh.Scene) else sc
    # Most image-to-3D GLBs are Y-up already (Minecraft is Y-up too).
    ext = mesh.extents.max(); pitch = ext / (size - 1)
    vg = mesh.voxelized(pitch).fill()
    mat = vg.matrix  # (X,Y,Z)
    pts = vg.points  # centers of filled voxels, same order as sparse indices
    idx = vg.sparse_indices
    # colour: nearest surface point -> its colour
    try:
        vis = mesh.visual.to_color() if hasattr(mesh.visual, "to_color") else mesh.visual
        vcol = np.asarray(vis.vertex_colors)[:, :3].astype(float)
    except Exception:
        vcol = np.full((len(mesh.vertices), 3), 160.0)
    from scipy.spatial import cKDTree
    tree = cKDTree(mesh.vertices); _, vi = tree.query(pts)
    cols = vcol[vi]
    pal = np.array([color_of(b) for b in PALETTE_FOR_MESH], float)
    def lab(c):  # cheap perceptual-ish: weighted RGB ("redmean")
        return c
    r = (cols[:, None, 0] + pal[None, :, 0]) / 2
    dif = cols[:, None, :] - pal[None, :, :]
    dist = (2 + r/256)*dif[..., 0]**2 + 4*dif[..., 1]**2 + (2 + (255-r)/256)*dif[..., 2]**2
    choice = dist.argmin(1)
    W, H, D = mat.shape
    blocks = [{"x": int(i[0]), "y": int(i[1]), "z": int(i[2]), "block": "minecraft:" + PALETTE_FOR_MESH[c]} for i, c in zip(idx, choice)]
    return {"name": name or os.path.splitext(os.path.basename(mesh_path))[0], "size": [int(W), int(H), int(D)], "palette": {}, "blocks": blocks}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("json"); b.add_argument("--out", required=True)
    m = sub.add_parser("mesh"); m.add_argument("mesh"); m.add_argument("--size", type=int, default=32); m.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "build": build(a.json, a.out)
    else:
        d = mesh_to_json(a.mesh, a.size); os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump(d, open(a.out + ".json", "w")); print("voxel json:", a.out + ".json"); build(d, a.out)
