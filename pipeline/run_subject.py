#!/usr/bin/env python3
"""Full no-fal pipeline for one reference photo (4 Sonnet calls):
 1 generate v0 shape   2 judge v0   3 craft/repair pass -> v1   4 refine.py (geometry fit + photo projection + palette)
 5 judge refined.  Then: before/after strip + 4-angle turntable.
usage: python run_subject.py NAME "short subject description" [--max 40]"""
import argparse, json, os, numpy as np
from PIL import Image, ImageDraw
import loop, scorer, refine, vox

def gen_prompt(ref, desc, mx):
    return f"""You are an expert voxel artist (MagicaVoxel style). Read the inspiration photo {os.path.abspath(ref)} with the Read tool.
Subject: {desc}. Recreate ONLY this subject (no ground, sky, people or background) as a TRUE 3D colour voxel model,
as close to the photo as possible. Choose "size" [W,H,D] (each <= {mx}) to fit the subject's real proportions; the
subject should fill ~90% of its longest axis. Model plausible unseen sides (back, other walls, roof slopes).
Estimate the photo's camera into "camera": azim (deg around vertical; 0 = looking at the model's +z face) and
elev (deg; positive = camera above looking down).

{loop.CRAFT}

FORMAT (output ONE JSON object only, no prose, no markdown). Schema:
{loop.SCHEMA}
Prefer shapes + shell_shade + noise palettes; "voxels" only for small details (windows, handles, trim).
Keep output under ~20k characters."""

def label_strip(items, path, S=300):
    out = Image.new("RGB", (S*len(items)+10*(len(items)-1), S+44), "white"); d = ImageDraw.Draw(out)
    for i, (t, im) in enumerate(items):
        im = im.convert("RGB"); im.thumbnail((S, S)); x = i*(S+10)
        out.paste(im, (x+(S-im.width)//2, 44+(S-im.height)//2)); d.text((x+2, 2), t, fill=(0, 0, 0))
    out.save(path); return path

def masked_ref(ref):
    im = Image.open(ref).convert("RGB"); m = scorer.ref_mask(Image.open(ref))
    a = np.array(im); a[~m] = 255; ys, xs = np.nonzero(m)
    return Image.fromarray(a[ys.min():ys.max()+1, xs.min():xs.max()+1])

def turntable(model, az, path, S=300):
    d, occ, col, _ = vox.load(model)
    ims = [(f"azim {int(az+k)%360}", vox.render(occ, col, az+k, 20, 512)[0]) for k in (0, 90, 180, 270)]
    return label_strip(ims, path, S)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("desc"); ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--model", default="sonnet"); a = ap.parse_args()
    ref = f"refs/{a.name}.jpg"; n = a.name; log = {}
    raw = loop.claude(gen_prompt(ref, a.desc, a.max), a.model); open(f"art/{n}_v0.raw.txt", "w").write(raw)
    v0 = loop.extract_json(raw); json.dump(v0, open(f"art/{n}_v0.json", "w"))
    c = v0.get("camera", {})
    r0 = scorer.score(ref, f"art/{n}_v0.json", f"out/{n}_v0", c.get("azim", 30), c.get("elev", 15), fit=True, use_judge=True)
    log["v0"] = {"auto": r0["auto_total"], "judge": r0.get("judge", {}).get("overall"), "judge_scores": r0.get("judge", {}).get("scores")}
    print(n, "v0", log["v0"], flush=True)
    v0["camera"] = r0["camera"]
    raw = loop.claude(loop.rev_prompt(ref, v0, r0, a.max), a.model); open(f"art/{n}_v1.raw.txt", "w").write(raw)
    try: v1 = loop.extract_json(raw)
    except Exception as e: print("craft pass parse failed", e); v1 = v0
    json.dump(v1, open(f"art/{n}_v1.json", "w"))
    refine.refine(ref, f"art/{n}_v1.json", f"art/{n}_refined.json")
    rr = scorer.score(ref, f"art/{n}_refined.json", f"out/{n}_refined", fit=False, use_judge=True)
    log["refined"] = {"auto": rr["auto_total"], "judge": rr.get("judge", {}).get("overall"), "judge_scores": rr.get("judge", {}).get("scores"),
                      "camera": rr["camera"], "parts": rr["auto_parts"], "fixes": rr.get("judge", {}).get("fixes")}
    print(n, "refined", {k: log["refined"][k] for k in ("auto", "judge")}, flush=True)
    label_strip([("reference", masked_ref(ref)),
                 (f"v0 Sonnet shape\nauto {r0['auto_total']} / judge {log['v0']['judge']}/10", Image.open(f"out/{n}_v0_render.png")),
                 (f"refined (craft pass + photo projection)\nauto {rr['auto_total']} / judge {log['refined']['judge']}/10", Image.open(f"out/{n}_refined_render.png"))],
                f"out/{n}_before_after.png")
    turntable(f"art/{n}_refined.json", rr["camera"]["azim"], f"out/{n}_turntable.png")
    json.dump(log, open(f"out/{n}_summary.json", "w"), indent=2); print(n, "done", flush=True)
