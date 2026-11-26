#!/usr/bin/env python3
"""Map the textured voxel finals to Minecraft 26.3 blocks (rules: MC_BLOCK_RULES.md).
cost(block | slot) = dE2000(target, block face colour) + W_N * noise mismatch + W_T * (1 - technique score) + guards,
slots = (material, shade, role); roles: trim->outline, shadow->hatching/cross-hatching, rough->stippling/scumbling, smooth->glazing.
usage: python mc_map.py [windmill cottage bonsai]"""
import json, sys, collections, os, numpy as np
from pathlib import Path
from skimage import color as skc
import mc_features, mc_render, detail_metrics
_REPO = Path(__file__).resolve().parent.parent
MC = os.environ.get("MC_BLOCKS", str(_REPO / "mc-blocks"))
D = json.load(open(f"{MC}/blocks.json")); BL = {b["id"]: b for b in D["blocks"]}
EXC = json.dumps(json.load(open(f"{MC}/excluded.json")))
CHAINS = D["gradient_chains"]
W_N, W_T, TECH_SLACK, NOISE_SCALE = 1.2, 4.0, 8.0, 0.5
CRISP = {"windmill": {("stone", "dark_detail"), ("cap_slate", "sail_white"), ("stone", "sail_white")},
         "cottage": {("wall_white", "door_red"), ("wall_white", "glass_dark"), ("thatch", "door_red"), ("door_red", "glass_dark")},
         "bonsai": {("pot", "soil"), ("pot", "foliage"), ("pot", "moss")}}
BAN_FAM = {"ore", "utility", "glazed_terracotta", "coral", "sculk", "light", "froglight", "ice", "gourd", "concrete_powder", "metal"}
BAN_ID = {"bookshelf", "chiseled_bookshelf", "tnt", "jukebox", "note_block", "sponge", "wet_sponge", "beehive", "bee_nest", "barrel", "melon",
          "pumpkin", "carved_pumpkin", "jack_o_lantern", "slime_block", "honey_block", "magma_block", "shroomlight", "crying_obsidian",
          "gold_block", "diamond_block", "emerald_block", "lapis_block", "iron_block", "netherite_block", "raw_gold_block", "raw_iron_block",
          "raw_copper_block", "lodestone", "reinforced_deepslate", "bedrock", "budding_amethyst", "suspicious_sand", "suspicious_gravel",
          "dried_kelp_block", "crimson_nylium", "warped_nylium", "mycelium", "podzol", "respawn_anchor", "potent_sulfur", "chiseled_resin_bricks", "petrified_oak_slab"}
# material -> block families builders would use for it (out-of-family blocks pay W_FAM; keeps stone looking like stone)
FAMILIES = {
 "stone": {"stone", "andesite", "tuff", "diorite", "calcite", "deepslate", "dripstone", "sandstone", "mud", "basalt", "granite", "end_stone"},
 "cap_slate": {"deepslate", "blackstone", "basalt", "tuff", "stone", "andesite", "concrete", "terracotta", "wool"},
 "sail_white": {"wood", "quartz", "calcite", "wool", "concrete", "diorite", "snow", "terracotta"},
 "dark_detail": {"deepslate", "blackstone", "basalt", "concrete", "wool", "wood", "obsidian", "terracotta"},
 "wall_white": {"concrete", "wool", "quartz", "calcite", "snow", "terracotta", "diorite"},
 "thatch": {"wood", "mud", "tuff", "stone", "terracotta", "wool", "organic", "sandstone", "moss", "andesite", "dripstone", "soil"},
 "moss": {"moss", "terracotta", "wool", "concrete", "organic", "stone", "soil"},
 "door_red": {"wood", "terracotta", "concrete", "wool", "brick", "nether_brick", "granite"},
 "glass_dark": {"deepslate", "blackstone", "concrete", "wool", "obsidian", "basalt"},
 "chimney_brick": {"brick", "mud", "terracotta", "granite", "nether_brick", "wood"},
 "foliage": {"moss", "wool", "concrete", "terracotta", "organic"},
 "trunk": {"wood", "mud", "terracotta", "soil", "granite", "dripstone"},
 "pot": {"terracotta", "brick", "nether_brick", "wool", "concrete", "wood", "granite"},
 "soil": {"soil", "mud", "wood", "terracotta", "wool"},
 # new set (cathedral / landscape / turtle)
 "limestone": {"sandstone", "mud", "terracotta", "dripstone", "granite", "end_stone", "calcite"},   # warm honey stone: no greys
 "roof_slate": {"deepslate", "blackstone", "basalt", "tuff", "stone", "andesite", "concrete", "terracotta"},
 "window_dark": {"deepslate", "blackstone", "basalt", "concrete", "wool", "obsidian", "terracotta", "wood"},
 "grass": {"moss", "soil", "terracotta", "wool", "concrete", "organic"},
 "rock_grey": {"stone", "andesite", "tuff", "diorite", "deepslate", "dripstone", "calcite", "basalt", "granite", "mud"},
 "rock_ochre": {"sandstone", "red_sandstone", "terracotta", "mud", "dripstone", "granite", "stone"},
 "rock_dark": {"deepslate", "blackstone", "basalt", "tuff", "stone", "andesite"},
 "sand": {"sandstone", "soil", "terracotta", "wool", "concrete", "calcite", "end_stone"},
 "water": {"prismarine", "concrete", "terracotta", "wool", "copper", "glazed_terracotta"},
 "foam": {"quartz", "calcite", "wool", "concrete", "snow", "diorite"},
 "shell": {"wood", "mud", "terracotta", "soil", "dripstone", "tuff", "stone", "granite", "moss"},
 "skin": {"stone", "andesite", "tuff", "terracotta", "wool", "concrete", "mud", "dripstone", "diorite", "calcite"},
 "coral": {"terracotta", "wool", "concrete", "copper", "resin", "brick", "granite"},
 "coral_pink": {"terracotta", "wool", "concrete", "granite", "brick", "cherry", "wood"},
 "algae": {"moss", "terracotta", "wool", "concrete", "organic"},
 "fan": {"purpur", "terracotta", "wool", "concrete", "amethyst"},
 # Little Hagia Sophia (brick + stone masonry, rendered drum, lead roofs)
 "masonry": {"brick", "mud", "terracotta", "granite", "stone", "andesite", "tuff", "dripstone", "nether_brick"},
 "drum_render": {"terracotta", "brick", "granite", "mud", "concrete", "dripstone"},
 "lead_roof": {"stone", "andesite", "tuff", "deepslate", "concrete", "terracotta", "basalt", "calcite", "diorite"},
 # suburban house (painted lap siding, dark wood trim, asphalt shingles)
 "siding": {"wood", "sandstone", "end_stone", "terracotta", "wool", "concrete", "calcite", "quartz"},
 "trim_brown": {"wood", "terracotta", "mud", "brick", "granite", "soil"},
 "roof_shingle": {"brick", "terracotta", "granite", "mud", "nether_brick", "wood", "red_sandstone", "resin"}}
W_FAM = 10.0
LEGACY = os.environ.get("MC_LEGACY", "0") == "1"   # A/B switch: 1 = the mapper as it was before DETAIL_DISCOVERY P0
ACCENT_MAX_DE = float(os.environ.get("MC_ACCENT_MAX_DE", 20.0 if LEGACY else 10.0))   # was 20: white_terracotta on sandstone (16 dE) read as pink patches
NATURAL_OK = {"grass_block"}                  # biome-tinted, but the dataset stores its plains-tinted colours; only used via NATURAL
NATURAL = {"grass": {"grass_block": 10.0}}
NATURAL_TOP = {"grass": "grass_block"}   # top-exposed voxels of the material use the natural block (its top face is what is seen)    # builder prior (dE bonus): terrain materials prefer the vanilla natural block
SAT_CAP = False                               # new set: reject blocks far more saturated than the target (no garish lime/orange)
STRICT = {"cathedral": {"limestone", "roof_slate", "window_dark"}, "hagia": {"masonry", "drum_render", "lead_roof", "window_dark"}, "house": {"siding", "trim_brown", "roof_shingle", "window_dark"}, "landscape": {"rock_grey", "rock_ochre", "rock_dark", "sand", "foam", "water"}, "turtle": {"skin"}}
STRICT_NOW = set()   # set per run: materials whose out-of-family blocks are not allowed at all
MAX_STEP = 15.0   # a new ramp block must be within this dE2000 of a block already in the material's ramp
TECH = {"trim": ["outline"], "shadow": ["hatching", "cross_hatching"], "rough": ["stippling", "scumbling"], "smooth": ["glazing"], "plain": []}
def allowed(b):
    return (b["shape"] == "full_block" and not b["emits_light"] and not b["partially_transparent"] and not b["gravity"] and not b["animated"]
            and (not b["biome_tinted"] or b["id"] in NATURAL_OK) and b["family"] not in BAN_FAM and b["id"] not in BAN_ID and not b["id"].startswith("waxed_")
            and "infested" not in b["id"] and not (b.get("sides_differ"))
            and (b["id"] in NATURAL_OK or not (b.get("faces_differ") and (b.get("face_delta_e00") or 0) > 15 and b.get("subfamily") not in ("log", "wood", "stripped_log", "stripped_wood"))))
CAND = [b for b in D["blocks"] if allowed(b)]
def lab_of(b, face): return np.array(b["faces"][face]["lab"] if face in b.get("faces", {}) else b["overall"]["lab"], float)
def dE(a, b): return float(skc.deltaE_ciede2000(np.asarray(a, float)[None], np.asarray(b, float)[None])[0])
def hex2lab(h): return skc.rgb2lab(np.array([[[int(h[i:i+2], 16) for i in (1, 3, 5)]]], float)/255)[0, 0]
def lch(l): return l[0], float(np.hypot(l[1], l[2])), float(np.degrees(np.arctan2(l[2], l[1])) % 360)
def hue_ok(t, c):
    _, Ct, ht = lch(t); _, Cb, hb = lch(c)
    if Ct < 12:                                   # near-neutral target: greys, or low-chroma blocks of a similar hue
        return Cb < Ct + 10 and (Cb < 6 or abs((hb - ht + 180) % 360 - 180) < 50)
    if Cb < 0.35*Ct: return False                 # do not grey out a coloured material
    return abs((hb - ht + 180) % 360 - 180) < 40
def face_lab(b, f_top): return f_top*lab_of(b, "top") + (1 - f_top)*lab_of(b, "side")
def tech_score(b, role):
    ts = TECH[role]; T = b.get("pattern", {}).get("techniques", {})
    return max(T.get(t, 0) for t in ts) if ts else None
def ramp_hood(base):
    """blocks that can extend the base block's ramp: same family/subfamily, shared gradient chains, 2-hop nearest graph"""
    out = {base}
    for c in CHAINS:
        if base in c["blocks"]: out |= set(c["blocks"])
    nb = {n["id"] for n in BL[base].get("nearest", [])} if isinstance(BL[base].get("nearest"), list) else set()
    for n in list(nb): out |= {m["id"] for m in BL.get(n, {}).get("nearest", [])} if n in BL and isinstance(BL[n].get("nearest"), list) else set()
    out |= nb; fam = BL[base]["family"]; out |= {b["id"] for b in CAND if b["family"] == fam}
    return out
HATCH_POOL = {b["id"] for b in CAND if max(b.get("pattern", {}).get("techniques", {}).get(t, 0) for t in ("hatching", "cross_hatching")) >= 0.3}
def slot_cost(b, s, base_L=None, used=()):
    """base_L: L* of the block chosen for the next shade toward the base (same sign), so the ramp stays monotonic"""
    c = face_lab(b, s["f_top"]); de = dE(s["lab"], c)
    if not hue_ok(s["lab"], c): return 1e9, de
    noise = W_N*min(3.0, abs(s["lstd"] - b["overall"]["l_stddev"])/3.0)
    ts = tech_score(b, s["role"]); tech = W_T*(1 - ts) if ts is not None else 0.0
    mono = 0.0
    if base_L is not None:
        L = c[0]
        if s["sh"] < 0 and L > base_L + 1: mono = 10
        if s["sh"] > 0 and L < base_L - 1: mono = 10
    reuse = -2.0 if b["id"] in used else 0.0
    fam = 0.0 if b["family"] in FAMILIES.get(s["m"], {b["family"]}) else (1e9 if s["m"] in STRICT_NOW else W_FAM)
    if b["id"] in NATURAL_OK and b["id"] not in NATURAL.get(s["m"], {}): return 1e9, de
    fam -= NATURAL.get(s["m"], {}).get(b["id"], 0.0)
    if SAT_CAP:
        Ct, Cb = float(np.hypot(*s["lab"][1:])), float(np.hypot(*c[1:]))
        if Ct >= 12 and Cb > 1.6*Ct + 8: return 1e9, de
    sp = shape_pen(b["id"], s.get("need"))
    return de + noise + tech + mono + reuse + fam + sp, de - NATURAL.get(s["m"], {}).get(b["id"], 0.0) + sp   # natural prior + shape penalty count in the technique slack
def choose(s, pool, base_L=None, used=()):
    sc = [(slot_cost(BL[i], s, base_L, used), i) for i in pool if i in BL and allowed(BL[i])]
    ok = [x for x in sc if x[0][0] < 1e8]
    if not ok:   # hue guard rejected everything: plain nearest colour (in-family first for strict materials)
        fam_ok = [x for x in sc if s["m"] not in STRICT_NOW or BL[x[1]]["family"] in FAMILIES.get(s["m"], set())] or sc
        return min(((x[0][1], x[1]) for x in fam_ok), default=(None, None))[1]
    sc = ok
    best_de = min(x[0][1] for x in sc)
    sc = [x for x in sc if x[0][1] <= best_de + TECH_SLACK]          # technique may never cost more than +8 dE
    return min(sc)[1]
# ---------- shapes ----------
TEX_SLAB = {}
for b in D["blocks"]:
    if b["shape"] == "slab" and b["id"] not in BAN_ID: TEX_SLAB.setdefault((tuple(b["textures"]["side"]), tuple(b["textures"]["top"])), b["id"])
def slab_of(bid):
    b = BL[bid]; return TEX_SLAB.get((tuple(b["textures"]["side"]), tuple(b["textures"]["top"])))
def trapdoor_of(bid):
    b = BL[bid]
    if b["family"] == "wood" and b.get("wood_type"):
        t = f"{b['wood_type']}_trapdoor"; return t if t in BL else None
    if b["family"] == "copper":
        for ox in ("oxidized", "weathered", "exposed"):
            if bid.startswith(ox) or bid.startswith("waxed_" + ox): return f"{ox}_copper_trapdoor" if f"{ox}_copper_trapdoor" in BL else None
        return "copper_trapdoor"
    return None
TEX_STAIRS = {}
for b in D["blocks"]:
    if b["shape"] == "stairs" and not b["id"].startswith("waxed_"): TEX_STAIRS.setdefault((tuple(b["textures"]["side"]), tuple(b["textures"]["top"])), b["id"])
def stairs_of(bid):
    b = BL[bid]; return TEX_STAIRS.get((tuple(b["textures"]["side"]), tuple(b["textures"]["top"])))
stairs_exists = stairs_of
TEX_WALL = {}
for b in D["blocks"]:
    if b["shape"] == "wall": TEX_WALL.setdefault(b["textures"]["side"][0], b["id"])
def wall_of(bid):
    b = BL[bid]; return TEX_WALL.get(b["textures"]["side"][0]) if b["shape"] in ("full_block", "slab", "stairs") else None
PANES = [b["id"] for b in D["blocks"] if b["shape"] == "pane"]
# ---------- shape-aware block choice (DETAIL_DISCOVERY.md P0.1) ----------
# A block that cannot take the shapes its voxels need flattens them to full cubes (white_terracotta has no stairs/slabs).
# Each slot records the share of its voxels that need a slab / stairs / thin vertical piece; a block pays W_SHAPE per unit of
# share it cannot realise. The penalty also counts inside the technique slack, so a shape-capable block may win over a
# slightly closer colour.
W_SHAPE = 0.0 if LEGACY else float(os.environ.get("MC_W_SHAPE", 30.0))
def shape_kind(s):
    if not s: return None
    t = s.get("type")
    if t == "slab": return "slab"
    if t == "stairs": return "stairs"
    if t == "vslab" and not s.get("backed"): return "vthin"
    return None
def can_shape(bid, kind):
    if kind == "slab": return slab_of(bid) is not None or trapdoor_of(bid) is not None
    if kind == "stairs": return stairs_of(bid) is not None
    if kind == "vthin": return wall_of(bid) is not None or trapdoor_of(bid) is not None
    return True
def shape_pen(bid, need):
    return W_SHAPE*sum(f for k, f in (need or {}).items() if not can_shape(bid, k))
FACE_OPP = {"south": "north", "north": "south", "east": "west", "west": "east"}
_PLACE = {}
def place(bid, shape, mat_blocks, target, mat=None):
    key = (bid, json.dumps(shape, sort_keys=True), tuple(mat_blocks), tuple(np.round(np.asarray(target)/2)), mat)
    if key not in _PLACE: _PLACE[key] = _place(bid, shape, mat_blocks, target, mat)
    return _PLACE[key]
def _place(bid, shape, mat_blocks, target, mat=None):
    """(block id, props, note) for a voxel's sub-block shape"""
    if not shape: return bid, {}, "full"
    t = shape.get("type"); size = shape.get("size", 0.5)
    if t == "slab":
        half = "top" if shape.get("align") == "top" else "bottom"
        td = trapdoor_of(bid)
        if size <= 0.3 and td and dE(target, lab_of(BL[td], "top")) <= 10: return td, {"half": half, "open": "false", "facing": "north"}, "trapdoor"
        sl = slab_of(bid)
        if not sl:   # nearest material block that has a slab, if close in colour
            fam = FAMILIES.get(mat, set())
            for pool in (set(mat_blocks), {b["id"] for b in CAND if b["family"] in fam}):     # material's own ramp first, then its families
                alt = sorted([(dE(target, lab_of(BL[m], "top" if half == "bottom" else "side")), m) for m in pool if slab_of(m)])
                if alt and alt[0][0] <= 6: sl = slab_of(alt[0][1]); break
        return (sl, {"type": half}, "slab") if sl else (bid, {}, "full (no slab)")
    if t == "vslab":
        if LEGACY:
            if size > 0.3: return bid, {}, "full (half-width vertical piece)"
        elif shape.get("backed"):
            # a skin layer on a wall (solid cell behind its flush side): round to the nearest whole block instead of
            # inflating a 1/4 skin into a full cube (that inflation is what made surfaces lumpy)
            if size <= 0.3 and not trapdoor_of(bid): return None, {}, "dropped (1/4 skin)"
            if size > 0.3: return bid, {}, "full (half-width skin)"
        else:
            # free-standing thin piece (mullion, pinnacle, spire edge, fin): stone gets its wall block, centred
            wl = wall_of(bid)
            if not wl:
                for pool in (set(mat_blocks), {b["id"] for b in CAND if b["family"] in FAMILIES.get(mat, set())}):
                    alt = sorted([(dE(target, lab_of(BL[m], "side")), m) for m in pool if wall_of(m)])
                    if alt and alt[0][0] <= 10: wl = wall_of(alt[0][1]); break
            if wl and not trapdoor_of(bid): return wl, {}, "wall (thin piece)"
            if size > 0.3: return bid, {}, "full (half-width vertical piece)"
        td = trapdoor_of(bid)
        if td and dE(target, lab_of(BL[td], "side")) > 10: td = None
        if not td:   # a trapdoor of a close-coloured wood/copper block (e.g. pale oak for white sails)
            alt = sorted([(dE(target, lab_of(BL[t], "side")), t) for t in BL if BL[t]["shape"] == "trapdoor" and not t.startswith("waxed_")
                          and BL[t]["family"] in FAMILIES.get(mat, set())])     # only trapdoor families that suit this material
            if alt and alt[0][0] <= 10: td = alt[0][1]
        if td: return td, {"open": "true", "facing": FACE_OPP.get(shape.get("align"), "north"), "half": "bottom"}, "trapdoor (vertical)"
        return bid, {}, "full (no vertical piece)"
    if t == "stairs":
        props = {"facing": shape["facing"], "half": shape.get("half", "bottom"), "shape": shape.get("shape", "straight")}
        st = stairs_of(bid)
        if not st:   # the stair of the material's closest block that has one (own ramp first, then its families)
            fam = FAMILIES.get(mat, set())
            for pool in (set(mat_blocks), {b["id"] for b in CAND if b["family"] in fam}):
                alt = sorted([(dE(target, lab_of(BL[m], "side")), m) for m in pool if stairs_of(m)])
                if alt and alt[0][0] <= 12: st = stairs_of(alt[0][1]); break
        return (st, props, "stairs") if st else (bid, {}, "full (no stairs for material)")
    if t in ("wall", "fence"):   # shape_fit.py thin posts; connect() sets the arms afterwards
        if t == "wall":
            wl = wall_of(bid)
            if not wl:
                for pool in (set(mat_blocks), {b["id"] for b in CAND if b["family"] in FAMILIES.get(mat, set())}):
                    alt = sorted([(dE(target, lab_of(BL[m], "side")), m) for m in pool if wall_of(m)])
                    if alt and alt[0][0] <= 10: wl = wall_of(alt[0][1]); break
            if wl: return wl, {}, "wall"
        fences = sorted([(dE(target, lab_of(BL[f], "side")), f) for f in BL if BL[f]["shape"] == "fence"])
        if fences and fences[0][0] <= 12: return fences[0][1], {}, "fence"
        return None, {}, "dropped (no thin block close in colour)"
    return bid, {}, "full"
# ---------- window kit (DETAIL_DISCOVERY.md P0.3) ----------
# A dark window cluster at least 2 blocks tall becomes: glass pane in the wall plane (2/16 thick, so it reads recessed),
# a dark backing block behind it, an upside-down stair hood above (in the wall plane, step toward the inside) and a
# top-slab sill one block out under it. Single dark specks are noise from the paint stage and go back to the wall block.
WINDOW_KIT = not LEGACY and os.environ.get("MC_WINDOW_KIT", "1") == "1"
WINDOW_MATS = {"window_dark", "glass_dark"}
BACKING = "polished_blackstone"
DIR4 = {(1, 0, 0): "east", (-1, 0, 0): "west", (0, 0, 1): "south", (0, 0, -1): "north"}
N6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
def _add(p, d): return (p[0]+d[0], p[1]+d[1], p[2]+d[2])
def _components(cells):
    cells, seen, out = set(cells), set(), []
    for p in cells:
        if p in seen: continue
        st, comp = [p], []; seen.add(p)
        while st:
            q = st.pop(); comp.append(q)
            for d in N6:
                r = _add(q, d)
                if r in cells and r not in seen: seen.add(r); st.append(r)
        out.append(comp)
    return out
def window_kit(G, base_of, mat_blocks, size):
    W, H, D = size; log = collections.Counter()
    def inb(p): return 0 <= p[0] < W and 0 <= p[1] < H and 0 <= p[2] < D
    def full(g): return BL[g["id"]]["shape"] == "full_block" and not g["props"]
    for comp in _components([p for p, g in G.items() if g["m"] in WINDOW_MATS]):
        ys = [p[1] for p in comp]; out = collections.Counter(d for p in comp for d in DIR4 if _add(p, d) not in G)
        if max(ys) - min(ys) + 1 < 2 or not out:      # speck: back to the surrounding wall material
            for p in comp:
                nb = collections.Counter(G[_add(p, d)]["m"] for d in N6 if _add(p, d) in G and G[_add(p, d)]["m"] not in WINDOW_MATS)
                m2 = nb.most_common(1)[0][0] if nb else None
                if m2 and m2 in base_of: G[p] = dict(G[p], id=base_of[m2], props={}, m=m2); log["specks_reverted"] += 1
            continue
        d_out = out.most_common(1)[0][0]; d_in = (-d_out[0], 0, -d_out[2]); inward = DIR4[d_in]
        lab = np.mean([G[p]["lab"] for p in comp], 0)
        pane = min(PANES, key=lambda b: dE(lab, lab_of(BL[b], "side")))
        cs = set(comp)
        for p in comp:
            G[p] = dict(G[p], id=pane, props={}, m="glass"); log["panes"] += 1
            q = _add(p, d_in)
            if q in G and q not in cs and all(_add(q, d) in G for d in N6) and BACKING in BL:
                G[q] = dict(G[q], id=BACKING, props={}); log["backing"] += 1
        for p in comp:
            a = _add(p, (0, 1, 0))
            if a in cs or a not in G or G[a]["m"] in WINDOW_MATS or not full(G[a]) or _add(a, d_out) in G: continue
            st, props, note = place(G[a]["id"], {"type": "stairs", "facing": inward, "half": "top"}, mat_blocks.get(G[a]["m"], [G[a]["id"]]), G[a]["lab"], G[a]["m"])
            if note == "stairs": G[a] = dict(G[a], id=st, props=props); log["hoods"] += 1
        for p in comp:
            b = _add(p, (0, -1, 0)); s_ = _add(b, d_out)
            if b in cs or b not in G or s_ in G or not inb(s_) or not full(G[b]): continue
            sl, props, note = place(G[b]["id"], {"type": "slab", "size": 0.5, "align": "top"}, mat_blocks.get(G[b]["m"], [G[b]["id"]]), G[b]["lab"], G[b]["m"])
            if note == "slab": G[s_] = dict(G[b], id=sl, props=props); log["sills"] += 1
        log["windows"] += 1
    return dict(log)
CONN = {"wall", "pane", "bars", "fence"}
def connect(G):
    """Blockstate props for connecting blocks from their neighbours (Minecraft's rules, simplified: full blocks + same group)."""
    n = 0
    for (x, y, z), g in G.items():
        sh = BL[g["id"]]["shape"]
        if sh not in CONN: continue
        props, above = {}, G.get((x, y+1, z))
        tall = bool(above) and BL[above["id"]]["shape"] in ("full_block", "wall")
        for side, (dx, dz) in (("north", (0, -1)), ("south", (0, 1)), ("west", (-1, 0)), ("east", (1, 0))):
            q = G.get((x+dx, y, z+dz)); c = False
            if q:
                qs = BL[q["id"]]["shape"]
                c = (qs == "full_block" and not q["props"]) or qs == sh or ({qs, sh} <= {"pane", "bars", "wall"})
            props[side] = (("tall" if tall else "low") if c else "none") if sh == "wall" else ("true" if c else "false")
        if sh == "wall":
            arms = {s for s in ("north", "south", "west", "east") if props[s] != "none"}
            props["up"] = "false" if arms in ({"north", "south"}, {"east", "west"}) and not (above and BL[above["id"]]["shape"] == "wall") else "true"
        props["waterlogged"] = "false"; g["props"] = props; n += 1
    return n
def tech_label(b, role):
    """which technique this block actually serves in this role (only if its texture scores >= 0.25 for it)"""
    if not TECH[role]: return "colour match"
    t = max(TECH[role], key=lambda x: BL[b].get("pattern", {}).get("techniques", {}).get(x, 0)); sc = BL[b].get("pattern", {}).get("techniques", {}).get(t, 0)
    return f"{t} ({sc:.2f})" if sc >= 0.25 else f"colour only (wanted {'/'.join(TECH[role])}, best {sc:.2f})"
# ---------- main ----------
WARM = {"windmill": {"stone": ("#958f81", "#a89f8c")}}   # (palette base, photo stone tone): chroma shift only, L ramp kept
ACCENT_ALL = {"cathedral", "landscape", "turtle", "hagia", "house"}   # every material may get a low-contrast accent toward its photo base
def run(n):
    global STRICT_NOW, SAT_CAP; STRICT_NOW = STRICT.get(n, set()); SAT_CAP = n in ACCENT_ALL
    T, F = mc_features.features(n)
    if n in ACCENT_ALL:
        bases = json.load(open(f"art/final/meta/{n}_texture_labels.json")).get("bases", {})
        WARM[n] = {}
        for mm, bhex in bases.items():
            tgt_shift = None
            for v in F:
                if v["m"] == mm: v["accent_target"] = bhex
    for mm, (src, dst) in WARM.get(n, {}).items():
        shift = hex2lab(dst) - hex2lab(src); shift[0] = 0
        for v in F:
            if v["m"] == mm: v["warm_shift"] = shift.tolist()
    # vslab context: 'backed' = the cell behind its flush side is solid (skin layer), otherwise a free-standing thin piece
    occ_set = {(v["x"], v["y"], v["z"]) for v in F}; AXV = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}
    for v in F:
        s = v.get("s")
        if s and s.get("type") == "vslab":
            dx, dz = AXV[s["align"]]; v["s"] = dict(s, backed=(v["x"]+dx, v["y"], v["z"]+dz) in occ_set)
    LBL = json.load(open(f"art/final/meta/{n}_texture_labels.json")); zones = LBL["zones"]
    crisp = CRISP.get(n) or {tuple(p) for p in LBL.get("crisp", [])}
    for v in F:
        v["lab"] = hex2lab(v["hex"]); lstd = NOISE_SCALE*(v["noise"] if v["noise"] is not None else 8.0); v["lstd"] = lstd
        partner = any((v["m"], o) in crisp or (o, v["m"]) in crisp for o in v["boundary"])
        lip = n in ("windmill", "cottage", "bonsai") and (n == "windmill" and v["m"] == "cap_slate" and v["under_open"]) or (n == "cottage" and v["m"] == "thatch" and v["under_open"] and v["y"] == zones["ye"]) \
              or (n == "bonsai" and v["m"] == "pot" and v["top_open"] and v["y"] >= zones["yp"])
        if not v["surf"]: role = "plain"
        elif (partner or lip) and v["m"] not in ("sail_white", "foliage"): role = "trim"
        elif v["sh"] <= -2 or v["open"] < -0.35 or (v["sh"] < 0 and v["under_open"]) or (v.get("blend") and v["blend"][0] in ("thatch", "cap_slate", "soil")): role = "shadow"
        elif lstd >= 6.0: role = "rough"
        elif lstd <= 3.5: role = "smooth"
        else: role = "plain"
        v["role"] = role
    # slots
    slots = collections.defaultdict(list)
    for v in F:
        key = (v["m"], "blend:" + v["blend"][0] + f"{v['blend'][1]}/{v['blend'][2]}" if v.get("blend") else v["sh"], v["role"]); slots[key].append(v)
    S = {}
    for k, vs in slots.items():
        S[k] = {"m": k[0], "sh": k[1] if isinstance(k[1], int) else 0, "blend": not isinstance(k[1], int), "role": k[2], "n": len(vs),
                "lab": np.mean([v["lab"] for v in vs], 0), "lstd": float(np.mean([v["lstd"] for v in vs])),
                "f_top": float(np.mean([v["top_open"] for v in vs])),
                "need": {kk: c/max(1, sum(1 for v in vs if v["surf"])) for kk, c in collections.Counter(shape_kind(v["s"]) for v in vs).items() if kk}}   # share of the slot's visible voxels
    mats = sorted({v["m"] for v in F}, key=lambda m: -sum(1 for v in F if v["m"] == m))
    choice, base_of, used_by_mat, log = {}, {}, {}, []
    for m in mats:
        ks = [k for k in S if k[0] == m and not S[k]["blend"]]
        if not ks: continue
        k0 = max([k for k in ks if S[k]["sh"] == 0] or ks, key=lambda k: S[k]["n"])
        # the base block serves the whole material, so it is judged on the material's shape needs (not just its own slot's)
        vis = [v for v in F if v["m"] == m and v["surf"]]
        need_m = {kk: c/max(1, len(vis)) for kk, c in collections.Counter(shape_kind(v["s"]) for v in vis).items() if kk}
        base = choose(dict(S[k0], need=need_m), [b["id"] for b in CAND]); base_of[m] = base; used = {base}; choice[k0] = base
        bL = face_lab(BL[base], S[k0]["f_top"])[0]; hood = ramp_hood(base)
        for k in sorted(ks, key=lambda k: (abs(S[k]["sh"]), -S[k]["n"])):     # grow the ramp outward from the base
            if k in choice: continue
            pool = hood | (HATCH_POOL if S[k]["role"] == "shadow" else set())
            pool |= {b["id"] for b in CAND if S[k]["role"] in ("trim", "rough", "smooth") and dE(S[k]["lab"], lab_of(b, "side")) < 12}
            pool = {p for p in pool if p in BL and (p in used or min(dE(lab_of(BL[p], "side"), lab_of(BL[u], "side")) for u in used) <= MAX_STEP)}
            prevs = [kk for kk in ks if kk in choice and S[kk]["sh"] == S[k]["sh"] - np.sign(S[k]["sh"])]
            refL = float(np.mean([face_lab(BL[choice[kk]], S[kk]["f_top"])[0] for kk in prevs])) if prevs and S[k]["sh"] != 0 else bL
            choice[k] = choose(S[k], pool, refL, used) or base; used.add(choice[k])
        # cap: <= 5 blocks per material (drop the least used, reassign its slots)
        while True:
            cnt = collections.Counter()
            for k in ks: cnt[choice[k]] += S[k]["n"]
            if len(cnt) <= 5: break
            drop = min((b for b in cnt if b != base), key=lambda b: cnt[b]); keep = [b for b in cnt if b != drop]
            for k in ks:
                if choice[k] == drop: choice[k] = choose(S[k], keep, bL, set(keep)) or base
        used_by_mat[m] = sorted({choice[k] for k in ks}, key=lambda b: lab_of(BL[b], "side")[0])
    # blends: pick from both materials' blocks + chain blocks between their bases (max 2 new per pair)
    for k in [k for k in S if S[k]["blend"]]:
        A = k[0]; Bm = k[1][6:].split("/")[0].rstrip("0123456789"); pool = set(used_by_mat.get(A, [])) | set(used_by_mat.get(Bm, []))
        for c in CHAINS:
            if base_of.get(A) in c["blocks"] and base_of.get(Bm) in c["blocks"]: pool |= set(c["blocks"])
        pool |= {b["id"] for b in CAND if dE(S[k]["lab"], lab_of(b, "side")) < 6}
        choice[k] = choose(S[k], pool, None, set(used_by_mat.get(A, []))) or base_of[A]
    # warm dither: no vanilla stone sits at the photo's warm-limestone tone, so sprinkle a family-legal warm accent through the
    # base block's plain/rough voxels (ordered 3D dither, fraction p) so the wall's average colour moves toward the photo tone
    warm_info = {}
    acc_mats = list(WARM.get(n, {})) + ([mm for mm in base_of if any(v["m"] == mm and "accent_target" in v for v in F)] if n in ACCENT_ALL else [])
    for mm in acc_mats:
        vs = [v for v in F if v["m"] == mm and ("warm_shift" in v or "accent_target" in v)]
        if len(vs) < 30 or mm not in base_of: continue
        if "accent_target" in vs[0]:   # photo base of the material, with the material's own mean ramp offset (keeps value)
            tgt = hex2lab(vs[0]["accent_target"]) + (np.mean([v["lab"] for v in vs], 0) - np.mean([v["lab"] for v in vs if v["sh"] == 0] or [v["lab"] for v in vs], 0))
        else: tgt = np.mean([v["lab"] + np.array(v["warm_shift"]) for v in vs], 0)
        base = base_of[mm]; bl = lab_of(BL[base], "side")
        if "accent_target" in vs[0] and dE(bl, tgt) <= 5: continue    # base block already close enough
        best = (dE(bl, tgt), None, 0.0)
        for b in CAND:
            if b["family"] not in FAMILIES[mm] or b["id"] == base or abs(lab_of(b, "side")[0] - bl[0]) > 12: continue   # low-contrast accents only (no spots)
            if dE(lab_of(b, "side"), bl) > ACCENT_MAX_DE or dE(lab_of(b, "side"), tgt) > 20: continue   # an accent must sit between base and target and stay low-contrast (a 16 dE accent reads as patches)
            if not hue_ok(tgt, lab_of(b, "side")): continue   # never grey out (or recolour) the material
            if b["id"] in NATURAL_OK: continue
            for p in (0.1, 0.15, 0.2, 0.25, 0.3, 0.35):
                e = dE((1-p)*bl + p*lab_of(b, "side"), tgt)
                if e < best[0] - 0.3: best = (e, b["id"], p)
        warm_info[mm] = {"target_lab": [round(float(c), 1) for c in tgt], "base": base, "base_dE": round(dE(bl, tgt), 1), "accent": best[1], "fraction": best[2], "mix_dE": round(best[0], 1)}
    BAYER = lambda x, y, z: ((x*7 + y*3 + z*5) % 8 + 0.5)/8 if False else (((x*37 + y*61 + z*17) * 2654435761) % 1000)/1000
    # per-voxel placement with shapes -> block grid G (post-passes edit G before the palette is built)
    shape_log, tech_use, G = collections.Counter(), collections.defaultdict(collections.Counter), {}
    for v in F:
        key = (v["m"], "blend:" + v["blend"][0] + f"{v['blend'][1]}/{v['blend'][2]}" if v.get("blend") else v["sh"], v["role"]); bid = choice[key]
        wi = warm_info.get(v["m"])
        if wi and wi["accent"] and bid == wi["base"] and v["role"] in ("plain", "rough") and not v["s"] and BAYER(v["x"], v["y"], v["z"]) < wi["fraction"]: bid = wi["accent"]
        if v["m"] in NATURAL_TOP and v["top_open"] >= 0.5 and dE(v["lab"], face_lab(BL[NATURAL_TOP[v["m"]]], 1.0)) <= 25: bid = NATURAL_TOP[v["m"]]   # vanilla terrain: grass_block wherever the grass layer sees the sky
        pid, props, note = place(bid, v["s"], used_by_mat.get(v["m"], [bid]), v["lab"], v["m"]); shape_log[note] += 1
        if pid is None: continue
        tech_use[(v["m"], bid)][v["role"]] += 1
        G[(v["x"], v["y"], v["z"])] = {"id": pid, "props": dict(props), "m": v["m"], "role": v["role"], "lab": v["lab"]}
    detail_log = {}
    if WINDOW_KIT: detail_log["windows"] = window_kit(G, base_of, used_by_mat, T["size"])
    detail_log["connected"] = connect(G)
    pal, vox_out = {}, []
    for (x, y, z), g in sorted(G.items()):
        pid, props = g["id"], g["props"]
        state = "minecraft:" + pid + ("[" + ",".join(f"{a}={b}" for a, b in sorted(props.items())) + "]" if props else "")
        if state not in pal:
            pal[state] = {"key": f"b{len(pal)}", "id": pid, "props": props, "state": state, "material": g["m"], "count": 0, "techniques_served": collections.Counter()}
        p = pal[state]; p["count"] += 1; p["techniques_served"][g["role"]] += 1
        vox_out.append({"x": x, "y": y, "z": z, "b": p["key"]})
    palette = {}
    for st, p in pal.items():
        k = p.pop("key"); ts = p.pop("techniques_served"); p["roles"] = dict(ts)
        role = ts.most_common(1)[0][0]; t = TECH[role]
        p["technique"] = tech_label(p["id"], role)
        palette[k] = p
    # summary: ramps + jumps + stairs availability
    summary = {"materials": {}, "shapes": dict(shape_log), "detail_pass": detail_log, "w_shape": W_SHAPE, "stairs": {"placed": shape_log.get("stairs", 0), "detected": T.get("stairs_added", 0),
               "by_shape": dict(collections.Counter(p["props"]["shape"] for p in palette.values() for _ in range(p["count"]) if p["props"].get("shape")))},
               "warm": warm_info, "noise_scale": NOISE_SCALE, "weights": {"W_N": W_N, "W_T": W_T, "tech_slack_dE": TECH_SLACK}}
    for mm, wi in warm_info.items():
        if wi["accent"] and wi["accent"] not in used_by_mat[mm]: used_by_mat[mm] = sorted(used_by_mat[mm] + [wi["accent"]], key=lambda b: lab_of(BL[b], "side")[0])
    for m, bl in used_by_mat.items():
        Ls = [round(float(lab_of(BL[b], "side")[0]), 1) for b in bl]
        jumps = [round(dE(lab_of(BL[a], "side"), lab_of(BL[b], "side")), 1) for a, b in zip(bl, bl[1:])]
        roles = {b: dict(tech_use[(m, b)]) for b in bl}
        summary["materials"][m] = {"base": base_of[m], "ramp_dark_to_light": bl, "L": Ls, "adjacent_dE": jumps, "roles": roles,
                                   "techniques": {b: {r: tech_label(b, r) for r in rr} for b, rr in roles.items()},
                                   "slab": {b: slab_of(b) for b in bl}, "trapdoor": {b: trapdoor_of(b) for b in bl}, "stairs_variant": {b: stairs_exists(b) for b in bl}}
    summary["blends"] = {f"{k[0]}<-{k[1][6:]}": choice[k] for k in S if S[k]["blend"]}
    out = {"name": f"{n}_mc_blocks", "minecraft_version": "26.3", "size": T["size"], "camera": T.get("camera", {"azim": 30, "elev": 20}),
           "palette": palette, "voxels": vox_out, "summary": summary, "source": f"art/final/{n}_voxels_textured.json", "rules": "MC_BLOCK_RULES.md"}
    out["summary"]["detail_metrics"] = detail_metrics.metrics(detail_metrics.cells_of(out))
    out = mc_render.attach_bake(out)
    open(f"art/final/{n}_mc_blocks.json", "w").write(json.dumps(out))
    mc_render.export(f"art/final/{n}_mc_blocks.json", f"art/final/schematics/{n}_mc_blocks")
    nb = len({p["id"] for p in palette.values()})
    print(n, "blockstates", len(palette), "block ids", nb, "shapes", dict(shape_log), "detail", detail_log)
    print("   detail metrics", out["summary"]["detail_metrics"])
    for m, s in summary["materials"].items(): print("  ", m, s["ramp_dark_to_light"], "dE", s["adjacent_dE"], s["techniques"])
    print("   blends", summary["blends"])
    return out
if __name__ == "__main__":
    for n in sys.argv[1:] or ["windmill", "cottage", "bonsai"]: run(n)
