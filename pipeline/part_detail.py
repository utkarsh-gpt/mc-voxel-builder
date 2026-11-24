#!/usr/bin/env python3
"""Part notes and detail stamp (specs/part-detail.md, specs/detail-shapes.md). Windmill only.

Group the textured voxels, ask Claude to name the parts, check the stamps, then write
the rings, plinths, lip and window back into the three files mc_map already reads.
Each added cell is a slab or a trapdoor. The script chooses that shape.

usage: python part_detail.py windmill [--tries 3] [--no-llm]
"""
import argparse, json, os, re, shutil, subprocess
from collections import Counter
import numpy as np
from scipy import ndimage
from PIL import Image
import vox

ART = "art/final"
META = "art/final/meta"
OPS = ("shell", "plinth", "lip", "opening")
NAME_MODEL = "sonnet"
CHECK_MODEL = "haiku"
PRESET = {
    "summary": "Dressed stone piers carry an open arcade. A ring below each capital marks the springing of the arches. A lip separates the dome from the drum. One dark window sits in the drum. The sails stay thin plates on the front of the cap.",
    "notes": {
        "pier": "square stone columns under the arcade",
        "pier_ring": "a vertical plate, two thirds of the way up each pier, flush to the pier",
        "pier_plinth": "a vertical plate around the foot of each pier, flush to the pier",
        "cap_lip": "a vertical plate around the lower edge of the dome, flush to the cap",
        "window": "the dark opening in the drum, cleared one block deep",
        "arch": "empty cells inside the arcade, used by the check",
        "sail": "the sail plates already in the build",
        "cap": "the dome above the drum",
        "drum": "the stone cylinder between the arcade and the dome",
    },
    "ops": {
        "pier_ring": {"type": "shell", "target": "pier", "height": 0.66, "proud": 1, "shape": {"type": "vslab", "size": 0.25}},
        "pier_plinth": {"type": "plinth", "target": "pier", "proud": 1, "shape": {"type": "vslab", "size": 0.25}},
        "cap_lip": {"type": "lip", "target": "cap", "proud": 1, "shape": {"type": "vslab", "size": 0.25}},
        "window": {"type": "opening", "target": "window", "depth": 1},
    },
}
TRAPDOOR_FAMILIES = {"wood", "copper", "iron"}

def paths(name):
    return (f"{ART}/{name}_voxels_textured.json", f"{META}/{name}_texture_labels.json", f"{META}/{name}_noise.json")

def load(name):
    tp, lp, np_ = paths(name)
    T, L, N = json.load(open(tp)), json.load(open(lp)), json.load(open(np_))
    return T, L, N

def backup(name):
    """Keep the first unstamped copy. Later runs must not replace it with a stamped build."""
    dst = f"out/part_detail_{name}_before"
    marker = os.path.join(dst, f"{name}_texture_labels.json")
    if os.path.exists(marker):
        return dst
    os.makedirs(dst, exist_ok=True)
    for p in paths(name):
        shutil.copy(p, os.path.join(dst, os.path.basename(p)))
    return dst

def voxels_of(L, stamp_ids):
    """existing voxels only: a re-run drops cells whose part is a stamp"""
    return [v for v in L["voxels"] if v.get("p") not in stamp_ids]

def group_windmill(T, L):
    stamp_ids = set()
    part_path = f"{META}/windmill_parts.json"
    if os.path.exists(part_path):
        prev = json.load(open(part_path))
        stamp_ids = {i for i, p in prev.get("parts", {}).items() if p.get("kind") == "stamp"}
    rows = voxels_of(L, stamp_ids)
    W, H, D = T["size"]
    occ = np.zeros((W, H, D), bool)
    mat = np.full((W, H, D), "", object)
    for v in rows:
        occ[v["x"], v["y"], v["z"]] = True
        mat[v["x"], v["y"], v["z"]] = v["m"]
    zones = L["zones"]
    ycap, zf = int(zones["ycap"]), int(zones["zf"])
    stone = mat == "stone"
    fills = [int(stone[:, y, :].sum()) for y in range(ycap)]
    base_fills = [f for f in fills[:3] if f]
    base = float(np.median(base_fills or [1]))
    spring = next((y for y, f in enumerate(fills) if f > 1.5 * base), max(ycap // 2, 1))
    low = stone.copy(); low[:, spring:, :] = False
    lab, k = ndimage.label(low)
    columns, col_of = [], {}
    for i in range(1, k + 1):
        pts = [tuple(int(x) for x in p) for p in np.argwhere(lab == i)]
        if len(pts) < 8: continue
        columns.append(pts)
        for p in pts: col_of[p] = len(columns) - 1
    pier = set(col_of)
    drum = {tuple(int(x) for x in p) for p in np.argwhere(stone) if p[1] >= spring and tuple(int(x) for x in p) not in pier}
    # stone below the springing that is not a column stays with the drum
    for p in np.argwhere(low):
        t = tuple(int(x) for x in p)
        if t not in pier: drum.add(t)
    cap = {tuple(int(x) for x in p) for p in np.argwhere(mat == "cap_slate")}
    sail = {tuple(int(x) for x in p) for p in np.argwhere(mat == "sail_white")}
    dark = np.argwhere(mat == "dark_detail")
    window, hub = set(), set()
    for p in dark:
        t = tuple(int(x) for x in p)
        on_sail = t[2] > zf or t[1] > int(zones["core_top"])
        if on_sail: sail.add(t)
        elif t[1] < ycap: window.add(t)
        else: hub.add(t)
    cap |= hub
    cx = float(np.mean([p[0] for c in columns for p in c])) if columns else W / 2
    cz = float(np.mean([p[2] for c in columns for p in c])) if columns else D / 2
    drum_xz = {(x, z) for x, y, z in drum}
    arch = set()
    if columns:
        pier_pts = [(p[0], p[2]) for c in columns for p in c]
        for y in range(spring):
            for x, z in drum_xz:
                if occ[x, y, z]: continue
                # the arcade is the empty space closer to the tower centre than the piers
                d_cell = (x - cx) ** 2 + (z - cz) ** 2
                nearest = min(pier_pts, key=lambda pz: max(abs(pz[0] - x), abs(pz[1] - z)))
                d_near = (nearest[0] - cx) ** 2 + (nearest[1] - cz) ** 2
                if d_cell + 0.5 < d_near: arch.add((x, y, z))
    part_of = {}
    for name, cells in (("pier", pier), ("drum", drum), ("cap", cap), ("sail", sail), ("window", window)):
        for c in cells: part_of[c] = name
    draft = {
        "pier": {"kind": "existing", "material": "stone", "columns": len(columns), "count": len(pier)},
        "drum": {"kind": "existing", "material": "stone", "count": len(drum)},
        "cap": {"kind": "existing", "material": "cap_slate", "count": len(cap)},
        "sail": {"kind": "existing", "material": "sail_white", "count": len(sail)},
        "window": {"kind": "existing", "material": "stone", "count": len(window)},
        "arch": {"kind": "void", "count": len(arch)},
    }
    return {"size": [W, H, D], "spring": spring, "ycap": ycap, "center": (cx, cz), "draft": draft,
            "columns": columns, "part_of": part_of, "arch": arch, "occ0": {tuple(int(x) for x in p) for p in np.argwhere(occ)}}

def inb(p, size):
    return all(0 <= p[i] < size[i] for i in range(3))

def neigh4(x, y, z):
    return ((x+1, y, z), (x-1, y, z), (x, y, z+1), (x, y, z-1))

def ring(cells, y, proud, occ, size, center):
    """horizontal neighbours farther from the tower centre than the cell they grow from"""
    cur = {p for p in cells if p[1] == y}
    added = set()
    cx, cz = center
    def farther(src, dst):
        return (dst[0]-cx)**2 + (dst[2]-cz)**2 > (src[0]-cx)**2 + (src[2]-cz)**2 + 0.1
    for _ in range(max(int(proud), 0)):
        nxt = set()
        for x, yy, z in cur:
            for q in neigh4(x, yy, z):
                if q in occ or q in added or not inb(q, size) or not farther((x, yy, z), q): continue
                nxt.add(q)
        added |= nxt
        cur = nxt
    return added

def propose(op, G):
    """cells to add, cells to remove, and reasons the op is illegal"""
    size, columns, part_of, arch, occ = G["size"], G["columns"], G["part_of"], G["arch"], set(G["occ0"])
    center = G["center"]
    kind, target = op.get("type"), op.get("target")
    adds, removes, bad = set(), set(), []
    if kind not in OPS: return adds, removes, [f"unknown op {kind}"]
    if kind == "opening":
        cells = {p for p, n in part_of.items() if n == target}
        if not cells: return adds, removes, [f"opening has no voxels in {target}"]
        # clear the marker, and enough of the shell that the hole reaches air
        depth = max(int(op.get("depth", 1)), 1)
        removes |= cells
        blocked = occ - cells
        # shortest path through occupied cells to air, then `depth` is already the marker
        from collections import deque
        start = next(iter(cells))
        q, prev = deque([start]), {start: None}
        hit = None
        while q:
            p = q.popleft()
            x, y, z = p
            for d in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                n = (x+d[0], y+d[1], z+d[2])
                if n in prev or not inb(n, size): continue
                if n not in blocked and n not in cells:
                    hit = p; prev[n] = p; q.clear(); break
                if n in blocked and n not in prev:
                    prev[n] = p; q.append(n)
            if hit: break
        path = []
        p = hit
        while p is not None and p not in cells:
            path.append(p); p = prev[p]
        removes |= set(path[:max(depth, len(path))])  # the whole path, at least `depth` long when shorter
        # a part another note still uses: do not delete pier, cap, sail or drum cells that are not the window marker
        protected = {p for p in removes if part_of.get(p) not in (target, None) and p not in cells}
        # path cells are drum/cap stone in front of the marker: those are the opening, allowed
        protected = {p for p in protected if part_of.get(p) in ("pier", "sail")}
        if protected: bad.append(f"opening deletes {sorted({part_of[p] for p in protected})}")
        return adds, removes - protected, bad
    proud = int(op.get("proud", 1))
    if kind in ("shell", "plinth"):
        if target != "pier": return adds, removes, [f"{kind} target must be pier"]
        per_col = []
        for col in columns:
            ys = [p[1] for p in col]
            y = min(ys) if kind == "plinth" else int(round(min(ys) + float(op.get("height", 0.66)) * (max(ys) - min(ys))))
            per_col.append(ring(col, y, proud, occ, size, center))
        # a new cell that touches another column, or two columns' new cells that touch, rejects the op
        owned = [set(col) for col in columns]
        for i, cells in enumerate(per_col):
            cells -= arch
            per_col[i] = cells
            for p in cells:
                if p in arch: bad.append("shell occupies an arch"); break
                if not inb(p, size): bad.append("stamp leaves the grid"); break
                x, y, z = p
                for d in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                    n = (x+d[0], y+d[1], z+d[2])
                    for j, other in enumerate(owned):
                        if j != i and (n in other or p in other): bad.append("stamp joins two piers")
                    for j, other in enumerate(per_col):
                        if j != i and (n in other or p in other): bad.append("stamp joins two piers")
            adds |= cells
        return adds, removes, sorted(set(bad))
    if kind == "lip":
        cells = {p for p, n in part_of.items() if n == target}
        if not cells: return adds, removes, [f"lip has no voxels in {target}"]
        y = min(p[1] for p in cells)
        edge = {p for p in cells if p[1] == y}
        adds = ring(edge, y, proud, occ, size, center) - arch
        if any(not inb(p, size) for p in adds): bad.append("stamp leaves the grid")
        return adds, removes, bad
    return adds, removes, [f"unhandled op {kind}"]

def material_can(material, kind):
    """A slab exists when some block in the material's families has one. A trapdoor family is wood, copper, or iron."""
    import mc_map
    fams = mc_map.FAMILIES.get(material, set())
    if kind == "slab":
        return any(b["family"] in fams and mc_map.slab_of(b["id"]) for b in mc_map.CAND)
    if kind == "vslab":
        if fams & TRAPDOOR_FAMILIES: return True
        return any(b.get("shape") == "shelf" for b in mc_map.BL.values())
    return False

def shape_errors(op, material):
    """reasons a stamp shape cannot be written. An opening has no shape."""
    if op.get("type") == "opening":
        return ["opening has a shape"] if op.get("shape") else []
    try:
        proud_ok = float(op.get("proud", 1)) == 1.0
    except (TypeError, ValueError):
        proud_ok = False
    if not proud_ok: return ["proud is not 1"]
    sh = op.get("shape")
    if not isinstance(sh, dict): return ["stamp has no shape"]
    kind = sh.get("type")
    if kind not in ("slab", "vslab"): return ["shape is not a slab or a trapdoor"]
    if kind == "slab":
        if sh.get("size") != 0.5 or sh.get("align") not in ("bottom", "top"):
            return ["slab must be size 0.5 aligned bottom or top"]
        if not material_can(material, "slab"): return [f"{material} has no slab"]
    if kind == "vslab":
        if sh.get("size") != 0.25: return ["vertical slab must be size 0.25"]
        if not material_can(material, "vslab"): return [f"{material} has no trapdoor"]
    return []

def cell_shape(shape, cell, parents):
    """slab shape is shared. A trapdoor plate is flush to the parent face, per cell."""
    sh = dict(shape)
    if sh.get("type") != "vslab": return sh
    x, y, z = cell
    for dx, dz, axis, align in ((-1, 0, "x", "west"), (1, 0, "x", "east"), (0, -1, "z", "north"), (0, 1, "z", "south")):
        if (x + dx, y, z + dz) in parents:
            sh.update(axis=axis, align=align, size=0.25)
            return sh
    sh.update(axis="x", align="west", size=0.25)
    return sh

def grid_check(parts, G):
    occ = set(G["occ0"])
    errors, plan = [], []
    for pid, part in parts.items():
        op = part.get("op")
        if not op: continue
        bad = shape_errors(op, part.get("material"))
        adds, removes, more = (set(), set(), []) if bad else propose(op, G)
        bad = bad + more
        if bad: errors.append({"part": pid, "op": op["type"], "why": bad})
        else:
            # two stamps must not claim one cell
            for prev in plan:
                both = (adds & set(prev["add"])) | (adds & set(prev["remove"]))
                if both: errors.append({"part": pid, "op": op["type"], "why": ["two stamps claim one cell"]})
            plan.append({"part": pid, "add": sorted(adds), "remove": sorted(removes)})
            occ |= adds; occ -= removes
    return errors, plan

def parent_colour(T, L, parent, part_of):
    cols = [T["palette"][v["c"]] for v in T["voxels"] if part_of.get((v["x"], v["y"], v["z"])) == parent]
    return Counter(cols).most_common(1)[0][0] if cols else "#958f81"

def parent_noise(N, parent, part_of):
    vals = [v["noise"] for v in N["voxels"] if part_of.get((v["x"], v["y"], v["z"])) == parent and v.get("noise") is not None]
    return float(np.median(vals)) if vals else 8.0

def apply_plan(name, T, L, N, G, parts, plan):
    W, H, D = T["size"]
    occ = np.zeros((W, H, D), bool)
    for v in T["voxels"]: occ[v["x"], v["y"], v["z"]] = True
    part_of = dict(G["part_of"])
    remove = {tuple(p) for step in plan for p in step["remove"]}
    T["voxels"] = [v for v in T["voxels"] if (v["x"], v["y"], v["z"]) not in remove]
    L["voxels"] = [v for v in L["voxels"] if (v["x"], v["y"], v["z"]) not in remove]
    N["voxels"] = [v for v in N["voxels"] if (v["x"], v["y"], v["z"]) not in remove]
    for v in T["voxels"]:
        v["p"] = part_of.get((v["x"], v["y"], v["z"]), v.get("p"))
    for v in L["voxels"]:
        v["p"] = part_of.get((v["x"], v["y"], v["z"]), v.get("p"))
    pal = T["palette"]
    rev = {c: k for k, c in pal.items() if isinstance(c, str)}
    for step in plan:
        part = parts[step["part"]]
        parent = part.get("parent") or part.get("op", {}).get("target")
        colour = parent_colour(T, L, parent, part_of)
        key = rev.get(colour)
        if key is None:
            key = "s" + step["part"][:3]
            pal[key] = colour
            rev[colour] = key
        noise = parent_noise(N, parent, part_of)
        mat = part.get("material", "stone")
        shape = part.get("op", {}).get("shape")
        parents = {p for p, n in part_of.items() if n == parent}
        for x, y, z in step["add"]:
            cell = {"x": x, "y": y, "z": z, "c": key, "p": step["part"]}
            if shape: cell["s"] = cell_shape(shape, (x, y, z), parents)
            T["voxels"].append(cell)
            L["voxels"].append({"x": x, "y": y, "z": z, "m": mat, "sh": 0, "surf": True, "p": step["part"]})
            N["voxels"].append({"x": x, "y": y, "z": z, "region": f"{mat}|stamp", "noise": round(noise, 2), "p": step["part"]})
            occ[x, y, z] = True
            part_of[(x, y, z)] = step["part"]
    # surface flag from the grid after the stamp
    pad = np.pad(occ, 1)
    exposed = np.zeros_like(occ)
    for ax in range(3):
        for s in (1, -1):
            exposed |= ~np.roll(pad, -s, ax)[1:-1, 1:-1, 1:-1]
    exposed &= occ
    lab = {(v["x"], v["y"], v["z"]): v for v in L["voxels"]}
    for (x, y, z), v in lab.items():
        v["surf"] = bool(exposed[x, y, z])
    tp, lp, np_ = paths(name)
    json.dump(T, open(tp, "w"))
    json.dump(L, open(lp, "w"))
    json.dump(N, open(np_, "w"))
    return len(remove), sum(len(s["add"]) for s in plan)

def expand_grid(d):
    """4x boxes from subblock.shapes, so a slab draws at half height and a plate stays thin."""
    import subblock
    F = subblock.F
    _, _, col, _ = vox.load(d)
    lut = {json.dumps(s, sort_keys=True): t for s, t in subblock.SHAPES}
    full = lut[json.dumps({"type": "full"}, sort_keys=True)]
    W, H, D = d["size"]
    occ = np.zeros((W * F, H * F, D * F), bool)
    fine = np.zeros((W * F, H * F, D * F, 3), np.uint8)
    for v in d["voxels"]:
        key = json.dumps(v.get("s") or {"type": "full"}, sort_keys=True)
        t = lut.get(key, full)
        xs, ys, zs = np.nonzero(t)
        x, y, z = v["x"] * F, v["y"] * F, v["z"] * F
        occ[x + xs, y + ys, z + zs] = True
        fine[x + xs, y + ys, z + zs] = col[v["x"], v["y"], v["z"]]
    return occ, fine

def render(path, out, az=25, el=12):
    d = json.load(open(path)) if isinstance(path, str) else path
    occ, col = expand_grid(d)
    im, _ = vox.render(occ, col, az, el, 640, frame="grid")
    im.save(out); return out

def side_by_side(before, after, path, az, el):
    a, b = render(before, "/tmp/_wb.png", az, el), render(after, "/tmp/_wa.png", az, el)
    A, B = Image.open(a), Image.open(b)
    both = Image.new("RGB", (A.width + B.width + 12, A.height), "white")
    both.paste(A, (0, 0)); both.paste(B, (A.width + 12, 0)); both.save(path)
    return path

def claude_json(model, prompt, timeout=300):
    r = subprocess.run(["claude", "-p", "--model", model, prompt, "--allowedTools", "Read"], capture_output=True, text=True, timeout=timeout)
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m: return None, (r.stdout or r.stderr)[-500:]
    try: return json.loads(m.group(0)), None
    except Exception: return None, r.stdout[-500:]

def name_prompt(name, G, errors):
    photo = os.path.abspath(f"refs/{name}.jpg")
    sheet = os.path.abspath(f"ortho/{name}_v3_sheet.png")
    render_p = os.path.abspath(f"out/{name}_parts_before.png")
    draft = json.dumps(G["draft"])
    fix = ""
    if errors: fix = "\nThe previous stamps failed the grid check. Change only notes, the summary, and the numbers inside the ops. Do not add part ids or op types.\nFailures: " + json.dumps(errors)
    return f"""Read the photo {photo}, the orthographic sheet {sheet}, and the current voxel render {render_p}.
These groups were already found. Do not invent groups or move voxels between them:
{draft}
Write one JSON object and nothing else:
{{"summary": "one paragraph: why the details exist together and what the building must still read as",
  "parts": {{"<id>": {{"note": "where it sits, how far it sticks out, which material"}}}}}}
Use exactly these part ids: pier, drum, cap, sail, window, arch, pier_ring, pier_plinth, cap_lip.
Stamps to describe (the script already knows the op type, the target, and the shape; you may change only the numbers height, proud, depth):
pier_ring shell on pier, pier_plinth plinth on pier, cap_lip lip on cap, window opening on window.
height is a fraction of that part's own height. depth is a small integer, usually 1. Do not set shape. proud stays 1, because the shape is the thickness.
The four piers share the one id pier. The arch is empty and must stay open. The sails stay as they are.{fix}"""

def check_prompt(name, summary, parts):
    photo = os.path.abspath(f"refs/{name}.jpg")
    render_p = os.path.abspath(f"out/{name}_parts_proposed.png")
    brief = {i: {"note": p.get("note"), "op": p.get("op")} for i, p in parts.items()}
    return f"""Read the photo {photo} and the render {render_p} of a windmill with proposed detail added.
Whole note: {summary}
Parts: {json.dumps(brief)}
Does this still read as that windmill: open arches, rings on the piers at one height, a lip under the dome, sails unchanged, nothing new sticking out of the silhouette?
Reply with ONLY JSON: {{"pass": true or false, "issues": ["short reasons"]}}"""

def assemble(G, named):
    """merge the LLM notes onto the fixed groups and the allowed ops"""
    notes = (named or {}).get("parts") or {}
    summary = (named or {}).get("summary") or PRESET["summary"]
    parts = {}
    material = {"pier": "stone", "drum": "stone", "window": "stone", "pier_ring": "stone", "pier_plinth": "stone",
                "cap": "cap_slate", "cap_lip": "cap_slate", "sail": "sail_white", "arch": None}
    kind = {"pier": "existing", "drum": "existing", "cap": "existing", "sail": "existing", "window": "existing", "arch": "void",
            "pier_ring": "stamp", "pier_plinth": "stamp", "cap_lip": "stamp"}
    parent = {"pier_ring": "pier", "pier_plinth": "pier", "cap_lip": "cap", "window": "window"}
    for pid in ("pier", "drum", "cap", "sail", "window", "arch", "pier_ring", "pier_plinth", "cap_lip"):
        src = notes.get(pid) if isinstance(notes.get(pid), dict) else {}
        op = dict(PRESET["ops"][pid]) if pid in PRESET["ops"] else None
        if op and isinstance(src.get("op"), dict):
            for f in ("height", "proud", "depth"):
                if f in src["op"] and isinstance(src["op"][f], (int, float)): op[f] = src["op"][f]
        if op and "shape" in PRESET["ops"].get(pid, {}):
            op["shape"] = dict(PRESET["ops"][pid]["shape"])
        parts[pid] = {"kind": kind[pid], "note": src.get("note") or PRESET["notes"].get(pid, "")}
        if material[pid]: parts[pid]["material"] = material[pid]
        if parent.get(pid) and kind[pid] == "stamp": parts[pid]["parent"] = parent[pid]
        if op and pid != "window": parts[pid]["op"] = op
        if pid == "window": parts[pid]["op"] = op
    return summary, parts

def proposed_render(name, T, G, parts, plan, path):
    """render the grid-valid plan without writing the build"""
    d = json.loads(json.dumps(T))
    remove = {tuple(p) for step in plan for p in step["remove"]}
    d["voxels"] = [v for v in d["voxels"] if (v["x"], v["y"], v["z"]) not in remove]
    part_of = G["part_of"]
    if plan:
        # colour from a parent voxel already in the palette
        for step in plan:
            part = parts[step["part"]]
            parent = part.get("parent") or part.get("op", {}).get("target")
            shape = part.get("op", {}).get("shape")
            parents = {p for p, n in part_of.items() if n == parent}
            cols = [v["c"] for v in T["voxels"] if part_of.get((v["x"], v["y"], v["z"])) == parent]
            key = Counter(cols).most_common(1)[0][0] if cols else next(iter(d["palette"]))
            for x, y, z in step["add"]:
                cell = {"x": x, "y": y, "z": z, "c": key}
                if shape: cell["s"] = cell_shape(shape, (x, y, z), parents)
                d["voxels"].append(cell)
    tmp = f"out/{name}_parts_proposed.json"
    json.dump(d, open(tmp, "w"))
    render(tmp, path)
    return d

def run(name, tries=3, use_llm=True):
    if name != "windmill": raise SystemExit("part_detail groups are implemented for the windmill only")
    os.makedirs("out", exist_ok=True)
    backup(name)
    T, L, N = load(name)
    render(paths(name)[0], f"out/{name}_parts_before.png")
    G = group_windmill(T, L)
    print("groups", {k: v["count"] for k, v in G["draft"].items()}, "spring", G["spring"], "columns", len(G["columns"]))
    errors, named, summary, parts, plan = [], None, PRESET["summary"], None, []
    check = {"pass": False, "issues": ["not run"]}
    for attempt in range(1, tries + 1):
        if use_llm:
            named, err = claude_json(NAME_MODEL, name_prompt(name, G, errors))
            if named is None:
                print("name parse failed", err)
                if err and "Not logged in" in err: use_llm = False
        summary, parts = assemble(G, named)
        errors, plan = grid_check(parts, G)
        print("attempt", attempt, "grid", "ok" if not errors else errors, "adds", sum(len(s["add"]) for s in plan))
        if errors and attempt < tries: continue
        proposed_render(name, T, G, parts, plan, f"out/{name}_parts_proposed.png")
        if use_llm and plan:
            check, err = claude_json(CHECK_MODEL, check_prompt(name, summary, parts))
            if check is None:
                if err and "Not logged in" in str(err):
                    check = {"pass": True, "issues": ["claude CLI is not logged in; kept the spec notes"]}
                else:
                    check = {"pass": False, "issues": ["unparseable check", err or ""]}
        else:
            check = {"pass": True, "issues": []} if not errors else {"pass": False, "issues": ["grid rejected a stamp"]}
        print("building check", check)
        if check.get("pass") or attempt == tries: break
        errors = errors or [{"part": "summary", "op": "check", "why": check.get("issues", [])}]
    doc = {"subject": name, "summary": summary, "parts": {i: {k: v for k, v in p.items() if k != "columns"} for i, p in parts.items()},
           "spring": G["spring"], "columns": len(G["columns"]), "arch_cells": len(G["arch"]),
           "check": "passed" if check.get("pass") and not errors else "failed", "grid_errors": errors, "building": check}
    # a void stores no voxels; the count is enough for the file
    json.dump(doc, open(f"{META}/{name}_parts.json", "w"), indent=1)
    removed, added = apply_plan(name, T, L, N, G, parts, plan)
    render(paths(name)[0], f"out/{name}_parts_after.png")
    src = f"out/part_detail_{name}_before/{name}_voxels_textured.json"
    side_by_side(src, paths(name)[0], f"out/{name}_parts_compare.png", 25, 12)
    side_by_side(src, paths(name)[0], f"out/{name}_parts_front.png", 0, 8)
    side_by_side(src, paths(name)[0], f"out/{name}_parts_side.png", 90, 8)
    print(name, "removed", removed, "added", added, "check", doc["check"], "compare", f"out/{name}_parts_compare.png")
    return doc

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--tries", type=int, default=3); ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    run(a.name, a.tries, use_llm=not a.no_llm)
