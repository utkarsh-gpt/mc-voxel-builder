#!/usr/bin/env python3
"""Wall-clock benchmark of the local (no fal / no Claude) pipeline stages for one subject.
usage: python bench.py NAME [--label before] [--stages paint,tone,shapefit,palette,noise,map] [--mesh out/proxy/NAME_lowpoly.glb]
writes out/bench_NAME_<label>.json. Each stage runs as its own process (cold start included, like a real run).
shape_fit runs with --tag bench so the committed art/NAME_shapefit.json is not replaced; the stages after it read the committed file."""
import argparse, json, os, subprocess, sys, time
ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--label", default="run")
ap.add_argument("--stages", default="paint,tone,shapefit,palette,noise,map"); ap.add_argument("--mesh"); ap.add_argument("--bpm")
a = ap.parse_args(); n = a.name
views = json.load(open(f"art/final/meta/{n}_views.json"))["chosen"] if os.path.exists(f"art/final/meta/{n}_views.json") else "_v1"
bpm = a.bpm or json.load(open(f"art/{n}_shapefit.json")).get("scale", {}).get("blocks_per_metre", 1.0)
mesh = a.mesh or (f"out/{n}_lowpoly.glb" if os.path.exists(f"out/{n}_lowpoly.glb") else f"out/proxy/{n}_lowpoly.glb")
CMD = {"paint": ["ortho_paint.py", n, views, f"--model={n}_lowpoly"], "tone": ["tone_to_ref.py", f"{n}_lowpoly"],
       "shapefit": ["shape_fit.py", n, "--mesh", mesh, "--bpm", str(bpm), "--tag", "bench"],
       "palette": ["palette_generic.py", n], "noise": ["noise_measure.py", n], "map": ["mc_map.py", n],
       "features": ["feature_detect.py", n]}
res = {"name": n, "label": a.label, "stages": {}}
for s in a.stages.split(","):
    t = time.perf_counter(); p = subprocess.run([sys.executable] + CMD[s], capture_output=True, text=True)
    dt = time.perf_counter() - t; res["stages"][s] = {"seconds": round(dt, 2), "rc": p.returncode}
    print(f"{n:8s} {s:9s} {dt:7.2f}s rc={p.returncode}", flush=True)
    if p.returncode: print(p.stderr[-1500:]); break
res["total_seconds"] = round(sum(v["seconds"] for v in res["stages"].values()), 2); print(f"{n:8s} TOTAL     {res['total_seconds']:7.2f}s")
os.makedirs("out", exist_ok=True); json.dump(res, open(f"out/bench_{n}_{a.label}.json", "w"), indent=1)
