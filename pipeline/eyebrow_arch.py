"""Recessed eyebrow arches for thatched cottages (SME-14 follow-up).

The v2 cottage had its door and window as flush rectangles punched through the eave, and the window was a solid
polished_deepslate box. In the photo both sit *recessed* under curved thatch "eyebrows": the thatch lifts over each
opening and juts 2-3 blocks out past the recessed door/window, leaving a dark shadow ring (soffit + reveal) around the
arched top, not a black fill.

apply(d, spec) rebuilds each bay from a clean neighbouring column, then:
  - cuts an arched opening through the wall/eave (z >= wall_z) so the door/window plane sits 1 block back (z = wall_z - 1)
  - door bay: red stripped_mangrove_log leaf with a mangrove door, arched top; dark recess ring above the arch
  - window bay: red frame ring + centre mullion + sill (top slab), 2x3 panes as a recess (air) with a soft cool-grey
    back (cyan_terracotta / polished_deepslate) one block deeper: no glass, no panes, no flat black box
  - a thatch eyebrow lip over the arch (z wall_z .. wall_z + 2, one row above the opening), filled behind so it reads
    as a hood; lip undersides and thatch reveals become "soffit" (tuff, protected), the arch ring "recess" (deepslate_tiles)
spec (from art/final/meta/<n>_parts.json "eyebrows"):
  {"wall_z": 14, "bays": [{"kind": "door", "cx": 15, "ref_x": 12, "heal": [13, 17]},
                          {"kind": "window", "cx": 26, "ref_x": 23, "heal": [24, 28]}]}
"""
import copy

DOOR_HALF = {"lower": "minecraft:mangrove_door[facing=south,half=lower,hinge=left,open=false,powered=false]",
             "upper": "minecraft:mangrove_door[facing=south,half=upper,hinge=left,open=false,powered=false]"}

def _state(bid, props=None):
    props = props or {}
    return "minecraft:" + bid + ("[" + ",".join(f"{a}={b}" for a, b in sorted(props.items())) + "]" if props else "")

def _profile(kind):
    """opening cells (dx, y) cut through the front, and what goes on the recessed plane"""
    O, plane, back = {}, {}, {}
    if kind == "door":
        for y in range(0, 5):
            for dx in (-1, 0, 1): O[(dx, y)] = 1
        O[(0, 5)] = 1
        for dx in (-1, 0, 1):
            for y in range(0, 4): plane[(dx, y)] = ("stripped_mangrove_log", {}, "door")
        plane[(0, 0)] = ("mangrove_door", {"facing": "south", "half": "lower", "hinge": "left", "open": "false", "powered": "false"}, "door")
        plane[(0, 1)] = ("mangrove_door", {"facing": "south", "half": "upper", "hinge": "left", "open": "false", "powered": "false"}, "door")
        plane[(0, 4)] = ("stripped_mangrove_log", {}, "door")                     # arched top of the leaf
        for c in ((-1, 4), (1, 4), (0, 5)): plane[c] = ("deepslate_tiles", {}, "recess")
    else:
        for y in range(1, 6):
            for dx in range(-2, 3): O[(dx, y)] = 1
        for dx in (-1, 0, 1): O[(dx, 6)] = 1
        for dx in range(-2, 3): plane[(dx, 1)] = ("stripped_mangrove_log", {}, "frame")          # bottom rail
        for y in (2, 3, 4):
            plane[(-2, y)] = plane[(2, y)] = ("stripped_mangrove_log", {}, "frame")           # jambs
            plane[(0, y)] = ("mangrove_planks", {}, "frame")                                   # centre mullion
        for dx in (-1, 1):
            plane[(dx, 3)] = ("mangrove_planks", {}, "frame")                                  # transom: red cross bars
            back[(dx, 4)] = ("cyan_terracotta", {}, "glass")                                    # 4 panes = open recess with a
            back[(dx, 2)] = ("polished_deepslate", {}, "glass")                                 # soft back (sky-lit top, darker low)
        for dx in (-1, 0, 1): plane[(dx, 5)] = ("stripped_mangrove_log", {}, "frame")          # arched head
        for c in ((-2, 5), (2, 5), (-1, 6), (0, 6), (1, 6)): plane[c] = ("deepslate_tiles", {}, "recess")
    return O, plane, back

def apply(d, spec, log=print):
    d = copy.deepcopy(d); W, H, D = d["size"]; pal = d["palette"]
    g = {(v["x"], v["y"], v["z"]): pal[v["b"]] for v in d["voxels"]}
    wz = spec["wall_z"]; new = {}                                   # (x,y,z) -> (id, props, material) for created cells
    def put(p, bid, props, mat): g[p] = None; new[p] = (bid, props, mat)
    def thatch_like(ref_x):
        for y in range(H):
            for z in range(D):
                q = g.get((ref_x, y, z))
                if q and q.get("material") == "thatch" and q["id"].endswith("wool"): return q
    for bay in spec["bays"]:
        cx, kind, rx = bay["cx"], bay["kind"], bay["ref_x"]
        lo, hi = bay["heal"]
        # 1. heal: copy the clean neighbour column over the old flush door/window (removes stray wall stairs, black box)
        for x in range(lo, hi + 1):
            for y in range(0, 9):
                for z in range(wz - 2, D):
                    src = g.get((rx, y, z))
                    if (x, y, z) in new: del new[(x, y, z)]
                    if src is None: g.pop((x, y, z), None)
                    else: g[(x, y, z)] = src
        th = thatch_like(rx); th_id = th["id"]
        O, plane, back = _profile(kind)
        top = {}
        for (dx, y) in O: top[dx] = max(top.get(dx, -1), y)
        # 2. eyebrow hood: the clean eave profile of the reference column, lifted so its lip sits one row above the
        #    opening; shoulders step back down to the eave line so the hood reads as a curved swell, not a box
        m = max(abs(k) for k in top); yl = {}
        for dx in range(-m - 2, m + 3):
            yl[dx] = top[dx] + 1 if dx in top else top[(m if dx > 0 else -m)] + 1 - (abs(dx) - m)
        for dx, y0 in yl.items():
            x = cx + dx; sh = y0 - 3
            if sh <= 0 or not (0 <= x < W): continue
            for y in range(3, y0):
                if (dx, y) in O: continue
                for z in range(wz, wz + 3):
                    if g.get((x, y, z)) is None and (x, y, z) not in new: put((x, y, z), th_id, {}, "thatch")
            for y in range(y0, min(H, y0 + 4)):                                         # only the eave rows
                for z in range(wz - 1, D):
                    q = g.get((rx, y - sh, z))
                    if q and q.get("material") == "thatch" and g.get((x, y, z)) is None and (x, y, z) not in new:
                        g[(x, y, z)] = q
        # 3. cut the opening (air in front of the recessed plane), then the plane and the pane backs
        for (dx, y) in O:
            for z in range(wz, D):
                p = (cx + dx, y, z); g.pop(p, None); new.pop(p, None)
        for (dx, y), (bid, props, mat) in plane.items(): put((cx + dx, y, wz - 1), bid, props, mat)
        for (dx, y), (bid, props, mat) in back.items():
            g.pop((cx + dx, y, wz - 1), None); new.pop((cx + dx, y, wz - 1), None)          # pane = open recess
            put((cx + dx, y, wz - 2), bid, props, mat)
        if kind == "window":
            for dx in range(-2, 3): put((cx + dx, 1, wz), "mangrove_slab", {"type": "top", "waterlogged": "false"}, "frame")  # sill lip
        # 4. shadow ring inside the recess: the innermost reveal/lip cells (z = wall_z) beside and over the opening
        for (dx, y) in O:
            for ddx, ddy in ((-1, 0), (1, 0), (0, 1)):
                if (dx + ddx, y + ddy) in O or y + ddy < 3: continue
                p = (cx + dx + ddx, y + ddy, wz); q0 = g.get(p); q = new.get(p)
                mat = q[2] if q else (q0.get("material") if q0 else None)
                if mat == "thatch": put(p, "tuff", {}, "soffit")
        log("eyebrow", kind, "cx", cx, "opening", len(O), "plane", len(plane), "pane backs", len(back))
    # rebuild palette/voxels
    states, vox = {}, []
    def key(bid, props, mat, q=None):
        st = _state(bid, props)
        k = (st, mat)
        if k not in states:
            e = {"key": f"e{len(states)}", "id": bid, "props": props, "state": st, "material": mat, "count": 0,
                 "roles": (q or {}).get("roles", {}), "technique": (q or {}).get("technique", "eyebrow_arch")}
            states[k] = e
        states[k]["count"] += 1; return states[k]["key"]
    for p in sorted(set(g) | set(new)):
        if p in new: bid, props, mat = new[p]; b = key(bid, props, mat)
        elif g.get(p) is not None: q = g[p]; b = key(q["id"], q.get("props", {}), q.get("material"), q)
        else: continue
        vox.append({"x": p[0], "y": p[1], "z": p[2], "b": b})
    d["palette"] = {e["key"]: e for e in states.values()}; d["voxels"] = vox
    assert not any("pane" in e["id"] for e in states.values())
    return d
