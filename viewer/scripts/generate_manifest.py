#!/usr/bin/env python3
"""Build manifest.json from models/*.json and refs/."""
import json, os, re, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
REFS = ROOT / "refs"
OUT = ROOT / "manifest.json"

# Newest / "final" passes the user cares about — highlighted in the picker.
HIGHLIGHT_SUFFIXES = (
    "_mc_blocks",
    "_voxels_textured",
    "_voxels_subblocks",
    "_t2_half_sub",
    "_t_half_sub",
    "_t2_hymv",
    "_t_hymv",
    "_hymv",
    "_t2_rendered_toned",
    "_t_rendered_toned",
    "_rendered_toned",
    "_fal_refined",
)
# Prefer these as the default featured model per subject (first match wins).
FEATURED_PRIORITY = (
    "_mc_blocks",
    "_voxels_textured",
    "_voxels_subblocks",
    "_t2_half_sub",
    "_t_half_sub",
    "_half_sub",
    "_t2_hymv",
    "_t_hymv",
    "_hymv",
    "_fal_refined",
    "_rendered_toned",
    "_best",
)

SUBJECTS = ("bonsai", "cottage", "windmill", "mushroom", "lighthouse", "lantern", "teapot")

def subject_of(stem):
    for s in sorted(SUBJECTS, key=len, reverse=True):
        if stem == s or stem.startswith(s + "_"):
            return s
    return stem.split("_")[0]

def kind_of(stem, subject):
    if stem == subject:
        return "base"
    if stem.startswith(subject + "_"):
        return stem[len(subject) + 1:]
    return stem

def ref_for(subject):
    for name in (f"{subject}.jpg", f"{subject}.png", f"{subject}_fal_in.png"):
        if (REFS / name).exists():
            return f"refs/{name}"
    return None

def credit_for(subject):
    """optional refs/<subject>_credit.json {text, url, license_url}: attribution shown under the reference photo"""
    p = REFS / f"{subject}_credit.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def is_derived(stem):
    """4x fine expansions and baked intermediates: never featured or highlighted."""
    return "_fine" in stem or "_baked" in stem

def is_highlight(stem):
    if is_derived(stem):
        return False
    return any(stem.endswith(suf) for suf in HIGHLIGHT_SUFFIXES)

def is_full_cube(entry):
    boxes = entry.get("boxes") or [[0, 0, 0, 1, 1, 1]]
    return len(boxes) == 1 and list(boxes[0][:6]) == [0, 0, 0, 1, 1, 1]

def mc_stats(data):
    """(voxelCount, subCount, paletteSize) for a format=mc_blocks model."""
    palette = data.get("palette") or {}
    voxels = [v for v in data.get("voxels") or [] if isinstance(v, dict) and v.get("b") in palette]
    sub = sum(1 for v in voxels if not is_full_cube(palette[v["b"]]))
    used = {v["b"] for v in voxels}
    return len(voxels), sub, len(used)

def main():
    items = []
    for path in sorted(MODELS.glob("*.json")):
        stem = path.stem
        try:
            data = json.loads(path.read_text())
        except Exception as e:
            print(f"skip {path.name}: {e}")
            continue
        size = data.get("size") or [0, 0, 0]
        fmt = "mc_blocks" if data.get("format") == "mc_blocks" else "voxels"
        palette_size = None
        if fmt == "mc_blocks":
            count, sub, palette_size = mc_stats(data)
            has_shapes = False
        else:
            voxels = data.get("voxels") or []
            count = len(voxels)
            sub = sum(1 for v in voxels if isinstance(v, dict) and v.get("s") and v["s"].get("type") not in (None, "full"))
            # shape-only early models: voxel list is sparse; flag it
            has_shapes = bool(data.get("shapes"))
        subj = subject_of(stem)
        kind = kind_of(stem, subj)
        mtime = path.stat().st_mtime
        items.append({
            "id": stem,
            "file": f"models/{path.name}",
            "name": data.get("name") or stem,
            "subject": subj,
            "kind": kind,
            "format": fmt,
            "size": size,
            "voxelCount": count if not has_shapes else None,
            "hasShapes": has_shapes,
            "subCount": sub,
            "subPct": round(100 * sub / count, 1) if count and sub else (0.0 if count else None),
            **({"paletteSize": palette_size} if palette_size is not None else {}),
            "highlight": is_highlight(stem),
            "featured": False,
            "ref": ref_for(subj),
            **({"refCredit": credit_for(subj)} if credit_for(subj) else {}),
            "mtime": int(mtime),
            "bytes": path.stat().st_size,
        })

    # Pick one featured model per subject, preferring the newest tuned half-sub builds.
    by_subj = {}
    for it in items:
        by_subj.setdefault(it["subject"], []).append(it)
    for subj, group in by_subj.items():
        chosen = None
        for suf in FEATURED_PRIORITY:
            # exact suffix match, never the 4x fine expansion or baked intermediates
            hits = [g for g in group if g["id"].endswith(suf) and not is_derived(g["id"])]
            if hits:
                chosen = max(hits, key=lambda g: g["mtime"])   # newest final wins (e.g. house_mc_blocks over house_1m_mc_blocks)
                break
        if not chosen:
            non_fine = [g for g in group if not is_derived(g["id"])]
            if non_fine:
                chosen = sorted(non_fine, key=lambda g: g["mtime"], reverse=True)[0]
        if chosen:
            chosen["featured"] = True

    # Featured first, then other highlights, then the rest, grouped by subject.
    def sort_key(it):
        return (0 if it["featured"] else 1 if it["highlight"] else 2, it["subject"], it["kind"])
    items.sort(key=sort_key)

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "default_id": next((it["id"] for it in items if it["featured"] and it["subject"] == "windmill"), None),
        "models": items,
    }
    if not manifest["default_id"]:
        manifest["default_id"] = next((it["id"] for it in items if it["featured"]), items[0]["id"] if items else None)
    OUT.write_text(json.dumps(manifest, indent=2))
    print(f"wrote {OUT} ({len(items)} models), default={manifest['default_id']}")

if __name__ == "__main__":
    main()
