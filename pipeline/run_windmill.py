#!/usr/bin/env python3
"""Run the windmill detail test from the saved unstamped build.

Restores the textured windmill from out/part_detail_windmill_before, then runs
part_detail.py. This does not call fal.ai and does not rebuild the mesh.
Without --llm the notes are the ones in specs/part-detail.md. --llm asks Claude
to name the parts, which needs a logged-in claude CLI.

Writes:
  out/windmill_parts_front.png    original | stamped, front
  out/windmill_parts_side.png     original | stamped, side
  out/windmill_parts_compare.png  original | stamped, three-quarter

usage: python run_windmill.py [--llm]
"""
import argparse, os, shutil
import part_detail

def restore(name):
    src = f"out/part_detail_{name}_before"
    if not os.path.isdir(src):
        raise SystemExit(f"missing {src}; run once from an unstamped build so the original can be saved")
    for base, dest in (
        (f"{name}_voxels_textured.json", f"art/final/{name}_voxels_textured.json"),
        (f"{name}_texture_labels.json", f"art/final/meta/{name}_texture_labels.json"),
        (f"{name}_noise.json", f"art/final/meta/{name}_noise.json"),
    ):
        shutil.copy(os.path.join(src, base), dest)

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    restore("windmill")
    doc = part_detail.run("windmill", tries=1, use_llm=a.llm)
    stamps = {i: p.get("op", {}).get("type") for i, p in doc["parts"].items() if p.get("op")}
    print("check", doc["check"])
    print("stamps", stamps)
    print("views", "out/windmill_parts_front.png", "out/windmill_parts_side.png", "out/windmill_parts_compare.png")
