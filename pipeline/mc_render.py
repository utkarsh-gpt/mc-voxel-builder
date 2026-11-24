"""Minecraft-block model helpers: block geometry, textured orthographic preview (real 16x16 block textures on every face),
4x baked colour grid for the scorer/viewer, and .schem/.litematic export.
Model JSON (art/final/{n}_mc_blocks.json): {"size":[W,H,D], "palette":{"b0":{"id":"stone_bricks","props":{...},"state":"minecraft:..."}}, "voxels":[{"x","y","z","b"}]}"""
import json, math, os, numpy as np
from PIL import Image, ImageDraw
import vox
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
MC = os.environ.get("MC_BLOCKS", str(_REPO / "mc-blocks"))
TEXDIR = f"{MC}/assets/assets/minecraft/textures/block"
_B = None
def blocks():
    global _B
    if _B is None: _B = {b["id"]: b for b in json.load(open(f"{MC}/blocks.json"))["blocks"]}
    return _B
_T = {}
def tex(name):
    """16x16 RGBA texture (first frame of animated strips)."""
    name = name.split("/")[-1]
    if name not in _T:
        im = Image.open(f"{TEXDIR}/{name}.png").convert("RGBA"); w = im.width; im = im.crop((0, 0, w, w))
        if w != 16: im = im.resize((16, 16), Image.NEAREST)
        _T[name] = im
    return _T[name]
def face_tex(bid, face):
    t = blocks()[bid]["textures"][face]; im = tex(t[0])
    if len(t) > 1:   # overlay (e.g. grass side): composite, tinted plains grass
        ov = tex(t[1]); a = np.asarray(ov).astype(float); a[..., :3] *= np.array([145, 189, 89])/255; im = Image.alpha_composite(im, Image.fromarray(a.astype(np.uint8)))
    if blocks()[bid].get("biome_tinted") and face == "top":
        a = np.asarray(im).astype(float); a[..., :3] *= np.array([145, 189, 89])/255; im = Image.fromarray(a.astype(np.uint8))
    return im

def boxes(bid, props):
    """Block-space boxes [(x0,y0,z0,x1,y1,z1)] in 0..1 for a blockstate."""
    shape = blocks()[bid]["shape"]; t = 3/16
    if shape == "slab":
        ty = props.get("type", "bottom")
        return [(0, 0, 0, 1, .5, 1)] if ty == "bottom" else [(0, .5, 0, 1, 1, 1)] if ty == "top" else [(0, 0, 0, 1, 1, 1)]
    if shape == "shelf":
        f = props.get("facing", "north"); d = 5/16   # about five pixels, flush to the face opposite facing
        return [{"north": (0, 0, 1-d, 1, 1, 1), "south": (0, 0, 0, 1, 1, d), "west": (1-d, 0, 0, 1, 1, 1), "east": (0, 0, 0, d, 1, 1)}[f]]
    if shape == "trapdoor":
        if props.get("open") == "true":   # panel against the side opposite to 'facing'
            f = props.get("facing", "north")
            return [{"north": (0, 0, 1-t, 1, 1, 1), "south": (0, 0, 0, 1, 1, t), "west": (1-t, 0, 0, 1, 1, 1), "east": (0, 0, 0, t, 1, 1)}[f]]
        return [(0, 0, 0, 1, t, 1)] if props.get("half", "bottom") == "bottom" else [(0, 1-t, 0, 1, 1, 1)]
    if shape == "stairs": return stair_boxes(props)
    return [(0, 0, 0, 1, 1, 1)]
def stair_boxes(props):
    """Minecraft stairs: half-block base + the step on the 'facing' side; outer = one quarter step at facing+left/right corner,
    inner = facing half + the left/right half. half=top mirrors vertically."""
    f = props.get("facing", "north"); sh = props.get("shape", "straight"); top = props.get("half", "bottom") == "top"
    cw = {"north": "east", "east": "south", "south": "west", "west": "north"}; ccw = {v: k for k, v in cw.items()}
    half = {"north": (0, 0, 1, .5), "south": (0, .5, 1, 1), "west": (0, 0, .5, 1), "east": (.5, 0, 1, 1)}   # (x0,z0,x1,z1)
    base = (0, .5, 0, 1, 1, 1) if top else (0, 0, 0, 1, .5, 1); y0, y1 = (0, .5) if top else (.5, 1)
    def box(r): return (r[0], y0, r[1], r[2], y1, r[3])
    def isect(a, b): return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    if sh == "straight": steps = [half[f]]
    elif sh.startswith("outer"): steps = [isect(half[f], half[ccw[f] if sh.endswith("left") else cw[f]])]
    else:
        o = half[ccw[f] if sh.endswith("left") else cw[f]]; steps = [half[f], isect(o, half[{"north": "south", "south": "north", "east": "west", "west": "east"}[f]])]
    return [base] + [box(r) for r in steps]

FACES = [((0, 1, 0), "top"), ((0, -1, 0), "bottom"), ((1, 0, 0), "side"), ((-1, 0, 0), "side"), ((0, 0, 1), "side"), ((0, 0, -1), "side")]
def face_quad(b, n):
    """corners (p0 = texture top-left, p1 = top-right, p3 = bottom-left) and texture sub-rect (u0,v0,u1,v1 in px)."""
    x0, y0, z0, x1, y1, z1 = b
    if n == (0, 1, 0): return np.array([[x0, y1, z0], [x1, y1, z0], [x0, y1, z1]]), (x0*16, z0*16, x1*16, z1*16)
    if n == (0, -1, 0): return np.array([[x0, y0, z1], [x1, y0, z1], [x0, y0, z0]]), (x0*16, (1-z1)*16, x1*16, (1-z0)*16)
    if n == (0, 0, 1): return np.array([[x0, y1, z1], [x1, y1, z1], [x0, y0, z1]]), (x0*16, (1-y1)*16, x1*16, (1-y0)*16)
    if n == (0, 0, -1): return np.array([[x1, y1, z0], [x0, y1, z0], [x1, y0, z0]]), ((1-x1)*16, (1-y1)*16, (1-x0)*16, (1-y0)*16)
    if n == (1, 0, 0): return np.array([[x1, y1, z1], [x1, y1, z0], [x1, y0, z1]]), ((1-z1)*16, (1-y1)*16, (1-z0)*16, (1-y0)*16)
    return np.array([[x0, y1, z0], [x0, y1, z1], [x0, y0, z0]]), (z0*16, (1-y1)*16, z1*16, (1-y0)*16)

def load_model(path):
    d = json.load(open(path)) if isinstance(path, str) else path
    cells = {}
    for v in d["voxels"]:
        p = d["palette"][v["b"]]; cells[(v["x"], v["y"], v["z"])] = (p["id"], p.get("props", {}))
    return d, cells

def render(path, azim=30, elev=20, size=512, light=(-0.25, 0.8, 0.55), ss=2, bg=(255, 255, 255)):
    """Textured orthographic render with the same camera/framing convention as vox.render. Returns (PIL RGB, mask)."""
    d, cells = load_model(path); W, H, D = d["size"]; R = vox.cam_R(azim, elev); ctr = np.array([W, H, D])/2
    Lw = np.array(light, float); Lw /= np.linalg.norm(Lw)
    full = {k for k, (bid, pr) in cells.items() if boxes(bid, pr) == [(0, 0, 0, 1, 1, 1)] and not blocks()[bid].get("has_cutout")}
    polys = []
    for (x, y, z), (bid, pr) in cells.items():
        for b in boxes(bid, pr):
            for n, fname in FACES:
                ncam = R @ np.array(n, float)
                if ncam[2] <= 1e-6: continue
                on_bound = (n[0] == 1 and b[3] == 1) or (n[0] == -1 and b[0] == 0) or (n[1] == 1 and b[4] == 1) or (n[1] == -1 and b[1] == 0) or (n[2] == 1 and b[5] == 1) or (n[2] == -1 and b[2] == 0)
                if on_bound and (x+n[0], y+n[1], z+n[2]) in full: continue
                q, uv = face_quad(b, n); q = q + np.array([x, y, z]); cam = (q - ctr) @ R.T
                ctr_face = (q[0] + q[1] + q[2] + (q[1] + q[2] - q[0]))/4
                depth = float(((ctr_face - ctr) @ R.T)[2])
                shade = 0.55 + 0.45*max(0.0, float(np.array(n) @ Lw))
                polys.append((depth, cam[:, :2], bid, fname, uv, shade))
    S = size*ss
    gc = np.array([[a, b, c] for a in (0, W) for b in (0, H) for c in (0, D)], float)
    allp = np.concatenate([p[1] for p in polys]); allp = np.concatenate([allp, allp[:0]])
    mn, mx = allp.min(0), allp.max(0)
    # include the 4th corner of every face in the extent
    p4 = np.array([p[1][1] + p[1][2] - p[1][0] for p in polys]); mn = np.minimum(mn, p4.min(0)); mx = np.maximum(mx, p4.max(0))
    sc = 0.9*S/max(mx - mn); off = (S - (mx - mn)*sc)/2
    img = Image.new("RGBA", (S, S), bg + (255,)); mimg = Image.new("L", (S, S), 0)
    to_px = lambda p: np.array([(p[0]-mn[0])*sc + off[0], S - ((p[1]-mn[1])*sc + off[1])])
    cache = {}
    for depth, pts, bid, fname, uv, shade in sorted(polys, key=lambda t: t[0]):
        p0, p1, p3 = to_px(pts[0]), to_px(pts[1]), to_px(pts[2]); p2 = p1 + p3 - p0
        quad = [tuple(p0), tuple(p1), tuple(p2), tuple(p3)]
        xs = [q[0] for q in quad]; ys = [q[1] for q in quad]; bx0, by0 = int(math.floor(min(xs))), int(math.floor(min(ys))); bx1, by1 = int(math.ceil(max(xs)))+1, int(math.ceil(max(ys)))+1
        if bx1 - bx0 < 1 or by1 - by0 < 1: continue
        key = (bid, fname, uv)
        if key not in cache:
            t = face_tex(bid, fname); u0, v0, u1, v1 = uv
            sub = t.crop((int(round(u0)), int(round(v0)), max(int(round(u1)), int(round(u0))+1), max(int(round(v1)), int(round(v0))+1))); cache[key] = sub
        sub = cache[key]; sw, sh = sub.size
        e1, e2 = p1 - p0, p3 - p0; M = np.array([[e1[0], e2[0]], [e1[1], e2[1]]])
        if abs(np.linalg.det(M)) < 1e-6: continue
        Mi = np.linalg.inv(M)   # (s,t) = Mi @ (p - p0)
        a, b_ = Mi[0]*sw; c_, d_ = Mi[1]*sh
        cx = -(a*(p0[0]-bx0) + b_*(p0[1]-by0)); cy = -(c_*(p0[0]-bx0) + d_*(p0[1]-by0))
        patch = sub.transform((bx1-bx0, by1-by0), Image.AFFINE, (a, b_, cx, c_, d_, cy), resample=Image.NEAREST)
        arr = np.asarray(patch).astype(float); arr[..., :3] *= shade; patch = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        pm = Image.new("L", patch.size, 0); ImageDraw.Draw(pm).polygon([(q[0]-bx0, q[1]-by0) for q in quad], fill=255)
        alpha = Image.fromarray(np.minimum(np.asarray(pm), np.asarray(patch)[..., 3]).astype(np.uint8))
        img.paste(patch, (bx0, by0), alpha); mimg.paste(255, (bx0, by0), alpha)
    img = img.convert("RGB").resize((size, size), Image.LANCZOS); m = np.array(mimg.resize((size, size), Image.NEAREST)) > 0
    return img, m

def bake_fine(path, dst, F=4):
    """4x colour grid: every block becomes FxFxF cells (shape-accurate to 1/4), each coloured from the 4x4-downsampled face texture
    that would show there (top texture on top-exposed cells, side texture elsewhere). Standard voxel JSON for scorer/viewer."""
    d, cells = load_model(path); W, H, D = d["size"]; pal = {}; vs = []
    def ds(im):  # 16x16 -> FxF mean colour of opaque pixels
        a = np.asarray(im).astype(float); k = 16//F; out = np.zeros((F, F, 3))
        for i in range(F):
            for j in range(F):
                blk = a[j*k:(j+1)*k, i*k:(i+1)*k]; w = blk[..., 3:4]/255
                out[i, j] = (blk[..., :3]*w).sum((0, 1))/max(w.sum(), 1e-6) if w.sum() > 0 else blk[..., :3].mean((0, 1))
        return out   # out[u, v]: u = texture x, v = texture y (down)
    occ = np.zeros((W*F, H*F, D*F), bool); owner = {}
    for (x, y, z), (bid, pr) in cells.items():
        for b in boxes(bid, pr):
            sl = [int(round(c*F)) for c in b]
            if sl[3] == sl[0]: sl[3] += 1
            if sl[4] == sl[1]: sl[4] += 1
            if sl[5] == sl[2]: sl[5] += 1
            for i in range(sl[0], sl[3]):
                for j in range(sl[1], sl[4]):
                    for k in range(sl[2], sl[5]): occ[x*F+i, y*F+j, z*F+k] = True; owner[(x*F+i, y*F+j, z*F+k)] = (bid, i, j, k)
    cache = {}
    for (fx, fy, fz), (bid, i, j, k) in owner.items():
        up_open = fy+1 >= H*F or not occ[fx, fy+1, fz]
        side_x = (fx+1 >= W*F or not occ[fx+1, fx and fy, fz]) if False else None
        if up_open: key = (bid, "top"); u, v = i, k
        else:
            ex = (fx+1 >= W*F or not occ[fx+1, fy, fz]) or (fx-1 < 0 or not occ[fx-1, fy, fz])
            key = (bid, "side"); u, v = (k if ex else i), F-1-j
        if key not in cache: cache[key] = ds(face_tex(*key))
        c = cache[key][u, v]; h = "#%02x%02x%02x" % tuple(np.clip(c, 0, 255).astype(int))
        pk = pal.setdefault(h, f"c{len(pal)}"); vs.append({"x": fx, "y": fy, "z": fz, "c": pk})
    json.dump({"name": d.get("name", "mc") + "_baked", "size": [W*F, H*F, D*F], "camera": d.get("camera", {"azim": 30, "elev": 20}),
               "palette": {v: k for k, v in pal.items()}, "voxels": vs}, open(dst, "w"))
    return len(pal)

def export(path, out_base):
    """.schem (Sponge, via mcschematic) and .litematic (via litemapy). Returns written paths."""
    d, cells = load_model(path); W, H, D = d["size"]; written = []
    states = {k: (v["state"] if "state" in v else "minecraft:" + v["id"]) for k, v in d["palette"].items()}
    try:
        import mcschematic
        s = mcschematic.MCSchematic()
        for v in d["voxels"]: s.setBlock((v["x"], v["y"], v["z"]), states[v["b"]])
        folder, name = os.path.dirname(out_base), os.path.basename(out_base)
        s.save(folder, name, mcschematic.Version.JE_1_21_5 if hasattr(mcschematic.Version, "JE_1_21_5") else list(mcschematic.Version)[-1]); written.append(out_base + ".schem")
    except Exception as e: written.append(f"schem failed: {e}")
    try:
        from litemapy import Schematic, Region, BlockState
        reg = Region(0, 0, 0, W, H, D); sch = reg.as_schematic(name=d.get("name", "build"), author="voxel-ai", description="voxel-ai block pass")
        for v in d["voxels"]:
            st = states[v["b"]]; bid, _, props = st.partition("[")
            pr = dict(p.split("=") for p in props.rstrip("]").split(",")) if props else {}
            reg[v["x"], v["y"], v["z"]] = BlockState(bid, **pr)
        sch.save(out_base + ".litematic"); written.append(out_base + ".litematic")
    except Exception as e: written.append(f"litematic failed: {e}")
    return written

def attach_bake(d, F=4):
    """Adds per-palette-entry viewer data: 'boxes' (block-space boxes) and 'bake' = FxF hex grids of the top/side/bottom
    textures (row-major, row 0 = texture top). Lets the web viewer draw block textures without shipping Mojang PNGs."""
    for k, p in d["palette"].items():
        p["boxes"] = [list(map(float, b)) for b in boxes(p["id"], p.get("props", {}))]
        bk = {}
        for face in ("top", "side", "bottom"):
            a = np.asarray(face_tex(p["id"], face)).astype(float); s = 16//F; rows = []
            for j in range(F):
                for i in range(F):
                    blk = a[j*s:(j+1)*s, i*s:(i+1)*s]; w = blk[..., 3:4]/255
                    c = (blk[..., :3]*w).sum((0, 1))/max(w.sum(), 1e-6) if w.sum() > 0 else blk[..., :3].mean((0, 1))
                    rows.append("#%02x%02x%02x" % tuple(np.clip(c, 0, 255).astype(int)) if w.mean() > 0.3 else None)   # None = cut-out cell
            bk[face] = rows
        p["bake"] = bk
    d["format"] = "mc_blocks"; d["bake_res"] = F
    return d
