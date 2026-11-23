#!/usr/bin/env python3
"""Reference-driven voxel loop: Claude generates colour-voxel JSON from an inspiration image,
scorer renders it from the reference camera, Claude judges, Claude revises. Keeps the best.
usage: python loop.py refs/mushroom.jpg --name mushroom --iters 2 [--grid 32] [--model sonnet]"""
import argparse, json, os, re, subprocess, shutil
import scorer, vox

CRAFT = """VOXEL ART CRAFT RULES (follow all):
- Silhouette first: match the reference outline and proportions exactly from the reference camera; then make the
  unseen sides plausible (the model must look finished from every angle, top and below included).
- Curves are stepped: build round forms from ellipsoids/cylinders, then add/carve single voxels to break perfect
  symmetry and give an organic outline (dents, lips, irregular rims).
- Palette: sample hues from the reference. Per material use a value ramp of 3-5 colours (shadow -> base -> highlight)
  with hue shifting (shadows cooler, highlights warmer), saturation peaking in the midtones.
- Bake lighting into colours like a voxel artist: darker ramp step on undersides, crevices and where parts meet
  (contact shadow / AO), lighter step on top edges facing the light. Use "shell_shade" for this.
- Texture: use list-valued palette entries (2-4 close shades) for natural per-voxel noise on organic materials;
  keep man-made surfaces flatter. Add small high-contrast details the reference shows (spots, pores, stains, streaks).
- Edges: rims and lips one voxel proud of the surface; insets for openings. No floating voxels; everything connected.
- Fill the grid well: the subject should span ~80-90% of the grid in its largest dimension."""

SCHEMA = vox.__doc__

def claude(prompt, model):
    r = subprocess.run(["claude", "-p", "--model", model, prompt, "--allowedTools", "Read"], capture_output=True, text=True, timeout=900)
    return r.stdout

def extract_json(t):
    t = re.sub(r"```(json)?", "", t); s = t[t.find("{"): t.rfind("}")+1]; return json.loads(s)

def gen_prompt(ref, grid):
    return f"""You are an expert voxel artist (MagicaVoxel style). Read the inspiration image {os.path.abspath(ref)} with the Read tool.
Recreate the main subject as a TRUE 3D colour voxel model in a {grid}x{grid}x{grid} grid, as close to the reference as possible.
Also estimate the reference's camera: azim (degrees around the vertical axis; 0 = looking at the model's +z face) and
elev (degrees; positive = camera above looking down, negative = camera below looking up) and put it in "camera".

{CRAFT}

FORMAT (output ONE JSON object only, no prose, no markdown). Schema:
{SCHEMA}
Prefer shapes + shell_shade + noise palettes; use "voxels" only for small details. Keep output under ~20k characters."""

def rev_prompt(ref, prev_json, res, grid):
    j = res.get("judge", {})
    return f"""You are an expert voxel artist revising your model to match an inspiration image more closely.
Read these images with the Read tool:
- reference: {os.path.abspath(ref)}
- comparison strip (reference | your render from the matched camera | silhouette overlap: red = missing, blue = extra): {os.path.abspath(res['files']['compare'])}
- your model from 6 angles: {os.path.abspath(res['files']['sheet'])}
Matched camera: {json.dumps(res['camera'])}. Automatic scores (0-100, higher better): {json.dumps(res['auto_parts'])}
Metrics: {json.dumps(res['view'])}  Craft: {json.dumps(res['craft'])}
Critic scores (1-10): {json.dumps(j.get('scores', {}))}
Critic fixes: {json.dumps(j.get('fixes', []))}

Your previous model JSON:
{json.dumps(prev_json)}

Fix the biggest problems first (silhouette/proportion, then colour/value, then surface detail), apply the critic fixes,
keep what already works. Grid stays {grid}^3. Keep the "camera" field equal to the matched camera unless clearly wrong.

{CRAFT}

Output the COMPLETE revised JSON object only (same schema), no prose."""

def combined(res):
    j = res.get("judge", {}).get("overall")
    return res["auto_total"] if j is None else round(0.5*res["auto_total"] + 5*float(j), 1)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("ref"); ap.add_argument("--name", required=True)
    ap.add_argument("--iters", type=int, default=2); ap.add_argument("--grid", type=int, default=32); ap.add_argument("--model", default="sonnet")
    a = ap.parse_args(); os.makedirs("art", exist_ok=True); os.makedirs("out", exist_ok=True)
    hist = []
    raw = claude(gen_prompt(a.ref, a.grid), a.model); open(f"art/{a.name}_v0.raw.txt", "w").write(raw)
    cur = extract_json(raw)
    for k in range(a.iters + 1):
        path = f"art/{a.name}_v{k}.json"; json.dump(cur, open(path, "w"), indent=1)
        cam = cur.get("camera", {})
        res = scorer.score(a.ref, path, f"out/{a.name}_v{k}", cam.get("azim", 30), cam.get("elev", 20), fit=True, use_judge=True)
        res["combined"] = combined(res); json.dump(res, open(f"out/{a.name}_v{k}_score.json", "w"), indent=2)
        print(f"v{k}: auto={res['auto_total']} judge={res.get('judge',{}).get('overall')} combined={res['combined']} cam={res['camera']}", flush=True)
        hist.append({"v": k, "auto": res["auto_total"], "judge": res.get("judge", {}).get("overall"), "combined": res["combined"],
                     "parts": res["auto_parts"], "judge_scores": res.get("judge", {}).get("scores")})
        if k == a.iters: break
        cur["camera"] = res["camera"]
        raw = claude(rev_prompt(a.ref, cur, res, a.grid), a.model); open(f"art/{a.name}_v{k+1}.raw.txt", "w").write(raw)
        try: cur = extract_json(raw)
        except Exception as e: print("revision parse failed:", e); break
    best = max(hist, key=lambda h: h["combined"]); shutil.copy(f"art/{a.name}_v{best['v']}.json", f"art/{a.name}_best.json")
    json.dump({"history": hist, "best": best}, open(f"out/{a.name}_history.json", "w"), indent=2)
    print("best:", best)
