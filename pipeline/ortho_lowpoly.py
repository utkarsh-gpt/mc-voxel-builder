#!/usr/bin/env python3
"""fal hyper3d/lowpoly/image-to-3d ($0.20/gen) from the verified ortho views (labelled F/R/B/U) -> GLB -> 48-grid voxels.
usage: python ortho_lowpoly.py NAME [--faces 4000]   reads out/NAME_verify.json; writes out/NAME_lowpoly.glb, art/NAME_lowpoly.json"""
import argparse, json, urllib.request, fal_client, fal_shape, ortho_verify
LAB = {"front": "F", "right": "R", "back": "B", "top": "U"}
ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--faces", type=int, default=4000); ap.add_argument("--views", default=""); ap.add_argument("--suffix", default="")
a = ap.parse_args(); n = a.name
V = json.load(open(f"out/{n}_verify.json")); tag = V["chosen"]
if a.views: V["views_used"] = a.views.split(",")   # override (A/B test of the drop policy)
urls = [fal_client.upload_file(f"ortho/{n}{tag}_{v}.png") for v in V["views_used"]]
res = fal_client.subscribe("hyper3d/lowpoly/image-to-3d", arguments={
    "image_urls": urls, "image_labels": [LAB[v] for v in V["views_used"]], "prompt": ortho_verify.SPEC[n][0],
    "face_count": a.faces, "geometry_file_format": "glb", "material": "Shaded"})
glb = f"out/{n}_lowpoly{a.suffix}.glb"; urllib.request.urlretrieve(res["model_mesh"]["url"], glb)
d = fal_shape.voxelize(glb, 48); d["name"] = n + "_lowpoly" + a.suffix; d["camera"] = {"azim": 0, "elev": 10}
json.dump(d, open(f"art/{n}_lowpoly{a.suffix}.json", "w")); print(n, "views", V["views_used"], "voxels", len(d["voxels"]), d["size"])
