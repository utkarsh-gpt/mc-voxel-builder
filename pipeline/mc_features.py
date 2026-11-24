"""Per-voxel features for block mapping: material, shade, blend, target colour, region noise, openness/AO, up/sun facing,
edge/corner/trim flags, and the sub-block shape. Inputs: art/final/{n}_voxels_textured.json + _texture_labels.json + _noise.json."""
import json, numpy as np
import subblock
STAIR_SKIP = {"sail_white", "glass_dark", "door_red", "dark_detail", "window_dark", "water", "foam", "coral", "coral_pink", "fan"}   # thin/detail parts stay as they are
from scipy import ndimage
SUN = np.array([-0.5, 1.0, 0.6]); SUN /= np.linalg.norm(SUN)
def features(n):
    T = json.load(open(f"art/final/{n}_voxels_textured.json")); Lb = json.load(open(f"art/final/meta/{n}_texture_labels.json")); Nz = json.load(open(f"art/final/meta/{n}_noise.json"))
    mats0 = {(v["x"], v["y"], v["z"]): v["m"] for v in Lb["voxels"]}
    T["stairs_added"] = subblock.stairify(T["voxels"], mats0, STAIR_SKIP)   # sub-block stair pass (block grid)
    W, H, D = T["size"]; occ = np.zeros((W, H, D), bool); occw = np.zeros((W, H, D)); mat = np.full((W, H, D), "", object)
    for v in T["voxels"]:
        occ[v["x"], v["y"], v["z"]] = True; s = v.get("s"); occw[v["x"], v["y"], v["z"]] = s.get("size", 1.0) if s else 1.0
    for v in Lb["voxels"]: mat[v["x"], v["y"], v["z"]] = v["m"]
    g = ndimage.gaussian_filter(occ.astype(float), 1.0); Nrm = -np.stack(np.gradient(g), -1); Nrm /= np.linalg.norm(Nrm, axis=-1, keepdims=True) + 1e-9
    openness = np.clip((0.50 - ndimage.gaussian_filter(occw, 1.2))/0.15, -1, 1)
    pad = np.pad(occ, 1)
    exposed = {}
    for ax in range(3):
        for s in (1, -1):
            nb = np.roll(pad, -s, ax)[1:-1, 1:-1, 1:-1]; exposed[(ax, s)] = occ & ~nb
    lab = {(v["x"], v["y"], v["z"]): v for v in Lb["voxels"]}; nz = {(v["x"], v["y"], v["z"]): v["noise"] for v in Nz["voxels"]}
    out = []
    for v in T["voxels"]:
        x, y, z = v["x"], v["y"], v["z"]; L = lab[(x, y, z)]
        ex = [k for k, e in exposed.items() if e[x, y, z]]; axes = {k[0] for k in ex}
        sl = (slice(max(x-1, 0), x+2), slice(max(y-1, 0), y+2), slice(max(z-1, 0), z+2))
        others = set(mat[sl][occ[sl]]) - {L["m"]}
        out.append({"x": x, "y": y, "z": z, "s": v.get("s"), "hex": T["palette"][v["c"]], "m": L["m"], "p": L.get("p") or v.get("p"), "sh": L["sh"], "surf": L["surf"], "blend": L.get("blend"),
                    "noise": nz.get((x, y, z)), "open": float(openness[x, y, z]), "up": float(max(0, Nrm[x, y, z, 1])), "sun": float(Nrm[x, y, z] @ SUN),
                    "n_exposed": len(ex), "edge": len(axes) >= 2, "corner": len(axes) >= 3, "boundary": sorted(others),
                    "under_open": bool((1, -1) in ex), "top_open": bool((1, 1) in ex)})
    return T, out
