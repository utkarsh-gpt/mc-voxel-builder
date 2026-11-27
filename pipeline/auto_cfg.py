#!/usr/bin/env python3
"""Auto-derive a palette_generic CFG + mc_map FAMILIES/PREFER for unseen subjects.

Lab clustering of the masked reference photo ($0, no LLM). Roles are named from where
each colour sits on the painted voxel surface when a mesh/voxel file exists, otherwise
from vertical position in the cut-out. Caches art/final/meta/<n>_autocfg.json.

    python auto_cfg.py SUBJECT [--force]
"""
import json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.cluster.vq import kmeans2
from skimage import color as skc

META = "art/final/meta"
WINDOW_DARK = ("#2e2a2a", (-1, 0, 5, 0, "neutral"), {"db_dn": 0.5}, None, "dark")
ROLE_FAMS = {
    "wall":  {"stone", "andesite", "tuff", "diorite", "sandstone", "terracotta", "mud", "calcite", "end_stone", "granite"},
    "body":  {"stone", "andesite", "tuff", "diorite", "sandstone", "terracotta", "mud", "calcite", "wood"},
    "roof":  {"deepslate", "blackstone", "basalt", "tuff", "stone", "andesite", "concrete", "terracotta", "wool", "brick"},
    "ground": {"soil", "mud", "stone", "terracotta", "sandstone", "dripstone"},
    "foliage": {"moss", "terracotta", "wool", "concrete", "organic"},
    "trim":  {"wood", "terracotta", "mud", "brick", "granite", "soil"},
    "accent": {"terracotta", "wool", "concrete", "brick", "wood", "granite"},
    "window_dark": {"deepslate", "blackstone", "basalt", "concrete", "wool", "obsidian", "terracotta", "wood"},
}

def colour_fams(L, a, b):
    C = float(np.hypot(a, b)); h = float(np.degrees(np.arctan2(b, a)) % 360)
    if C < 10:
        if L >= 75: return {"quartz", "calcite", "wool", "concrete", "diorite", "snow", "end_stone"}
        if L <= 30: return {"deepslate", "blackstone", "basalt", "obsidian", "concrete"}
        return {"stone", "andesite", "tuff", "diorite", "concrete", "terracotta"}
    if 70 <= h < 170: return {"moss", "organic", "terracotta", "wool", "concrete"}
    if 170 <= h < 260: return {"prismarine", "concrete", "wool", "terracotta", "copper"}
    if 260 <= h < 330: return {"purpur", "terracotta", "wool", "concrete", "amethyst"}
    if h >= 330 or h < 20: return {"brick", "nether_brick", "terracotta", "red_sandstone", "wood", "granite"}
    if 20 <= h < 50: return {"wood", "terracotta", "mud", "brick", "granite", "soil"}
    return {"sandstone", "end_stone", "terracotta", "wool", "concrete", "calcite"}

def path_of(n): return f"{META}/{n}_autocfg.json"
def load(n):
    p = path_of(n)
    return json.load(open(p)) if os.path.exists(p) else None
def src_path(n):
    for p in (f"art/{n}_shapefit.json", f"art/{n}_lowpoly_rendered_toned.json",
              f"art/{n}_lowpoly_rendered.json", f"art/{n}_lowpoly.json"):
        if os.path.exists(p): return p
    return f"art/{n}_shapefit.json"

def _hex(lab):
    rgb = np.clip(skc.lab2rgb(np.asarray(lab, float).reshape(1, 1, 3))[0, 0], 0, 1)
    return "#%02x%02x%02x" % tuple((rgb * 255).round().astype(int))

def _photo_lab(n):
    import scorer
    im = None
    for p in (f"refs/{n}.jpg", f"refs/{n}.png"):
        if os.path.exists(p): im = Image.open(p).convert("RGB"); break
    if im is None: raise FileNotFoundError(f"no reference photo for {n}")
    m = scorer.ref_mask(im); a = np.asarray(im)
    lab = skc.rgb2lab(a.astype(float) / 255.0)
    ys, xs = np.nonzero(m)
    if len(ys) < 50:
        m = (a.min(-1) < 250); ys, xs = np.nonzero(m)
    if len(ys) < 20: raise RuntimeError(f"{n}: too few masked photo pixels to cluster")
    hfrac = 1.0 - (ys - ys.min()) / max(int(ys.max() - ys.min()), 1)
    return lab[m], hfrac, int(m.sum())

def _cluster(lab, k=8, seed=0):
    w = np.array([1.0, 1.2, 1.2]); X = lab * w
    k = int(min(k, max(2, len(X) // 30)))
    for attempt in range(4):
        try:
            C, labels = kmeans2(X, k, minit="++", seed=seed + attempt, iter=25)
            if np.isnan(C).any(): raise ValueError("nan centre")
            break
        except Exception:
            if attempt == 3:
                qs = np.linspace(0, 100, k + 1); edges = np.unique(np.percentile(lab[:, 0], qs))
                labels = np.clip(np.digitize(lab[:, 0], edges[1:-1]), 0, k - 1)
                C = np.zeros((k, 3))
                for i in range(k):
                    sel = lab[labels == i]
                    C[i] = (sel * w).mean(0) if len(sel) else np.array([50, 0, 0]) * w
            else:
                continue
    centres = C / w; live = list(range(len(centres))); labels = labels.copy()
    while True:
        best = None
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                d = float(np.linalg.norm(centres[a] - centres[b]))
                if best is None or d < best[0]: best = (d, a, b)
        if best is None or best[0] >= 12: break
        _, a, b = best
        na, nb = int((labels == a).sum()), int((labels == b).sum())
        centres[a] = (centres[a] * na + centres[b] * nb) / max(na + nb, 1)
        labels[labels == b] = a; live.remove(b)
    changed = True; n = len(labels)
    while changed:
        changed = False
        for a in list(live):
            if (labels == a).mean() < 0.015 and len(live) > 2:
                others = [b for b in live if b != a]
                b = min(others, key=lambda j: float(np.linalg.norm(centres[a] - centres[j])))
                labels[labels == a] = b; live.remove(a); changed = True
    out = []
    for i, a in enumerate(live):
        px = lab[labels == a]; share = len(px) / n
        med = np.array([np.percentile(px[:, 0], 62), np.median(px[:, 1]), np.median(px[:, 2])])
        out.append({"lab": med, "share": float(share), "hex": _hex(med), "idx": i})
    out.sort(key=lambda c: -c["share"]); return out

def _voxel_stats(n, clusters):
    src = src_path(n)
    if not os.path.exists(src): return None
    try:
        import palette_texture as PT
        d, occ, occw, lab0 = PT.load(src)
    except Exception:
        return None
    surf = PT.surface(occ)
    if not surf.any(): return None
    Y = np.indices(occ.shape)[1]
    ys = np.nonzero(occ.any((0, 2)))[0]; y0, y1 = int(ys.min()), int(ys.max())
    hfrac = (Y - y0) / max(y1 - y0, 1)
    g = ndimage.gaussian_filter(occ.astype(float), 1.0)
    Nrm = -np.stack(np.gradient(g), -1); Nrm /= np.linalg.norm(Nrm, axis=-1, keepdims=True) + 1e-9
    up = np.clip(Nrm[..., 1], 0, 1); sloped = (up > 0.25) & (up < 0.9)
    centres = np.array([c["lab"] for c in clusters]); wt = np.array([0.3, 1.2, 1.2])
    dist = ((lab0[surf][:, None, :] - centres[None]) ** 2 * wt).sum(-1); lab = dist.argmin(1)
    stats = []
    for i, c in enumerate(clusters):
        sel = lab == i
        if sel.sum() < 4:
            stats.append({"hfrac": None, "up": None, "sloped": None, "vox_share": 0.0, "n": int(sel.sum())}); continue
        hf, u, sl = hfrac[surf][sel], up[surf][sel], sloped[surf][sel]
        stats.append({"hfrac": float(np.median(hf)), "up": float(np.median(u)),
                      "sloped": float(sl.mean()), "vox_share": float(sel.mean()), "n": int(sel.sum())})
    return stats

def _is_green(lab):
    L, a, b = lab; C = float(np.hypot(a, b)); h = float(np.degrees(np.arctan2(b, a)) % 360)
    return C >= 12 and 70 <= h < 170

def _is_building(n):
    try:
        import parts_list
        P = parts_list.load(n)
        if P and P.get("organic"): return False
    except Exception:
        pass
    return True

def _name_roles(n, clusters, vox_stats, photo_h):
    building = _is_building(n); info = []; roles = [None] * len(clusters); taken = set()
    for i, c in enumerate(clusters):
        st = (vox_stats or [None] * len(clusters))[i] or {}
        hf = st.get("hfrac"); 
        if hf is None: hf = photo_h[i] if photo_h else 0.5
        info.append({"i": i, "c": c, "hf": hf, "up": st.get("up"), "sl": st.get("sloped") or 0.0,
                     "green": _is_green(c["lab"]), "C": float(np.hypot(*c["lab"][1:])),
                     "L": float(c["lab"][0]), "share": c["share"]})
    for it in info:
        if it["green"]:
            roles[it["i"]] = "foliage"; taken.add(it["i"])
    for it in sorted(info, key=lambda x: -(x["hf"] or 0)):
        if it["i"] in taken: continue
        high = (it["hf"] or 0) > 0.6
        sloped = (it["sl"] or 0) >= 0.25 or (it["up"] is not None and 0.25 <= it["up"] <= 0.9)
        if high and (sloped or vox_stats is None):
            roles[it["i"]] = "roof"; taken.add(it["i"]); break
    if not building:
        for it in sorted(info, key=lambda x: (x["hf"] or 1)):
            if it["i"] in taken: continue
            if (it["hf"] or 1) < 0.25:
                roles[it["i"]] = "ground"; taken.add(it["i"]); break
    body_role = "body" if not building else "wall"
    rest = [it for it in info if it["i"] not in taken]
    if rest:
        main = max(rest, key=lambda x: x["share"]); roles[main["i"]] = body_role; taken.add(main["i"])
    for it in sorted((x for x in info if x["i"] not in taken), key=lambda x: -x["share"]):
        roles[it["i"]] = "accent" if (it["C"] >= 12 and it["share"] < 0.12) else ("trim" if it["L"] < 50 or it["share"] < 0.18 else "accent")
        taken.add(it["i"])
    order = sorted(range(len(clusters)), key=lambda i: (0 if roles[i] in ("wall", "body", "roof") else 1, -clusters[i]["share"]))
    used, out = {}, []
    for rank, i in enumerate(order[:5]):
        role = roles[i] or body_role
        used[role] = used.get(role, 0) + 1
        name = role if used[role] == 1 else f"{role}_{used[role]-1}"
        prior = "high" if role == "roof" else None
        hint_only = rank >= 2
        share = clusters[i]["share"]; max_share = None
        if role == "foliage" and building:
            hint_only = True; max_share = 0.12
        elif hint_only:
            max_share = float(np.clip(1.5 * share, 0.04, 0.18))
        out.append((name, clusters[i], role, prior, hint_only, max_share))
    return out

def _mat_entry(cluster, role, prior):
    L, a, b = cluster["lab"]; C = float(np.hypot(a, b))
    mode = "chromatic" if C > 12 else "neutral"
    if mode == "chromatic":
        kw = dict(dh=4, cd=0.05, cu=0.04)
        ramp = (-2, 2, 6, 5, "chromatic") if role not in ("trim", "accent") else (-1, 1, 5, 4, "chromatic")
        if role == "roof": ramp = (-2, 1, 5, 6, "chromatic")
        if role == "foliage": ramp = (-1, 1, 6, 6, "chromatic"); kw = dict(dh=7, cd=0.05, cu=0.05)
    else:
        kw = dict(db_up=1.0, db_dn=1.0) if role in ("wall", "body") else dict(db_up=-1.0, db_dn=0.5)
        ramp = (-2, 1, 5, 6, "neutral") if role == "roof" else (-2, 2, 6, 5, "neutral")
        if role in ("trim", "accent"): ramp = (-1, 1, 5, 4, "neutral")
    placement = "DEF_HIGH" if role == "roof" else ("DEF" if role in ("wall", "body", "ground") else None)
    return (cluster["hex"], ramp, kw, placement, prior)

def _families_prefer(named):
    families, prefer = {}, {}
    for name, cluster, role, prior, hint_only, max_share in named:
        role_set = set(ROLE_FAMS.get(role, ROLE_FAMS["wall"])); col_set = colour_fams(*cluster["lab"])
        families[name] = sorted(role_set | col_set)
        inter = role_set & col_set
        if inter: prefer[name] = sorted(inter)
        elif role in ("roof", "trim", "foliage"): prefer[name] = sorted(role_set)
    families["window_dark"] = sorted(ROLE_FAMS["window_dark"]); return families, prefer

def prep(n):
    existing = load(n)
    if existing and existing.get("clusters"): return existing
    lab, hfrac, _ = _photo_lab(n); clusters = _cluster(lab)
    rec = {"subject": n, "auto": True, "partial": True,
           "clusters": [{"hex": c["hex"], "lab": [round(float(x), 2) for x in c["lab"]], "share": round(c["share"], 4)} for c in clusters]}
    os.makedirs(META, exist_ok=True)
    if not existing: json.dump(rec, open(path_of(n), "w"), indent=1)
    return rec

def build(n, force=False):
    if not force:
        existing = load(n)
        if existing and existing.get("mats") and not existing.get("partial"): return existing
    lab, photo_hfrac, n_px = _photo_lab(n); clusters = _cluster(lab)
    vox_stats = _voxel_stats(n, clusters)
    centres = np.array([c["lab"] for c in clusters]); wt = np.array([1.0, 1.2, 1.2])
    idx = ((lab[:, None, :] - centres[None]) ** 2 * wt).sum(-1).argmin(1)
    photo_h = [float(np.median(photo_hfrac[idx == i])) if (idx == i).any() else 0.5 for i in range(len(clusters))]
    named = _name_roles(n, clusters, vox_stats, photo_h)
    mats, hint_only, max_share, roles = {}, [], {}, {}
    for name, cluster, role, prior, ho, ms in named:
        hx, ramp, kw, pl, pr = _mat_entry(cluster, role, prior)
        mats[name] = {"hint": hx, "ramp": list(ramp), "kw": kw, "placement": pl, "prior": pr,
                      "role": role, "photo_share": round(cluster["share"], 4)}
        roles[name] = role
        if ho: hint_only.append(name)
        if ms is not None: max_share[name] = round(float(ms), 3)
    mats["window_dark"] = {"hint": WINDOW_DARK[0], "ramp": list(WINDOW_DARK[1]), "kw": dict(WINDOW_DARK[2]),
                           "placement": None, "prior": "dark", "role": "window_dark", "photo_share": 0.0}
    roles["window_dark"] = "window_dark"
    families, prefer = _families_prefer(named)
    bases = [k for k, r in roles.items() if r in ("wall", "body")]
    others = [k for k in mats if k != "window_dark"]; crisp = []
    for a in others: crisp.append((a, "window_dark"))
    for a in bases:
        for b in others:
            if b != a and roles[b] in ("roof", "trim", "accent", "foliage"): crisp.append((a, b))
    rec = {"subject": n, "auto": True, "partial": False, "src": src_path(n), "mats": mats,
           "hint_only": hint_only, "max_share": max_share, "blend": [], "crisp": [list(p) for p in crisp],
           "families": families, "prefer": prefer, "roles": roles,
           "clusters": [{"hex": c["hex"], "lab": [round(float(x), 2) for x in c["lab"]], "share": round(c["share"], 4)} for c in clusters],
           "voxel_roles": vox_stats is not None}
    os.makedirs(META, exist_ok=True); json.dump(rec, open(path_of(n), "w"), indent=1)
    return rec

def as_cfg(rec):
    import palette_texture as PT
    ORG = dict(PT.DEF, w_open=1.1, w_up=0.6, w_dir=0.4, w_n=1.0, scale=3, q=(0.05, 0.12, 0.10, 0.03))
    mats = {}
    for k, v in rec["mats"].items():
        if isinstance(v, dict):
            hx = v.get("hint") or v.get("base"); ramp = tuple(v["ramp"]); kw = dict(v.get("kw") or {})
            pl, prior = v.get("placement"), v.get("prior")
        else:
            hx, ramp, kw, pl, prior = v[0], tuple(v[1]), dict(v[2] or {}), v[3], v[4]
        if pl in ("DEF", "default"): pl = PT.DEF
        elif pl == "DEF_HIGH": pl = dict(PT.DEF, w_h=0.2)
        elif pl == "ORG": pl = ORG
        elif isinstance(pl, dict): pl = pl
        else: pl = None
        mats[k] = (hx, ramp, kw, pl, prior)
    return {"src": rec.get("src") or src_path(rec.get("subject", "")), "mats": mats,
            "hint_only": tuple(rec.get("hint_only") or ()), "max_share": dict(rec.get("max_share") or {}),
            "blend": [tuple(x) for x in (rec.get("blend") or [])],
            "crisp": [tuple(x) for x in (rec.get("crisp") or [])],
            "families": rec.get("families") or {}, "prefer": rec.get("prefer") or {},
            "roles": rec.get("roles") or {}, "auto": True}

if __name__ == "__main__":
    force = "--force" in sys.argv
    for n in [a for a in sys.argv[1:] if not a.startswith("--")]:
        rec = build(n, force=force)
        print(n, json.dumps({"src": rec.get("src"), "roles": rec.get("roles"),
                             "mats": {k: (v.get("hint") if isinstance(v, dict) else v[0]) for k, v in rec["mats"].items()},
                             "hint_only": rec.get("hint_only"), "voxel_roles": rec.get("voxel_roles")}))
