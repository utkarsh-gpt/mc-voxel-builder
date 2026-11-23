#!/usr/bin/env python3
"""Text -> image (fal flux/schnell) -> 3D mesh (fal trellis) -> voxels -> exports.
usage: python fal_mesh.py <name> "<image prompt>" [--size 32]   (needs FAL_KEY in env)"""
import sys, os, argparse, urllib.request, json, fal_client
import voxel_ai
ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("prompt"); ap.add_argument("--size", type=int, default=32)
ap.add_argument("--model", default="fal-ai/trellis"); a = ap.parse_args()
os.makedirs("out", exist_ok=True)
img = fal_client.subscribe("fal-ai/flux/schnell", arguments={"prompt": a.prompt, "image_size": "square_hd", "num_images": 1})
iurl = img["images"][0]["url"]; urllib.request.urlretrieve(iurl, f"out/{a.name}_input.png"); print("image:", f"out/{a.name}_input.png")
res = fal_client.subscribe(a.model, arguments={"image_url": iurl})
murl = (res.get("model_mesh") or res.get("model_glb"))["url"]
glb = f"out/{a.name}.glb"; urllib.request.urlretrieve(murl, glb); print("mesh:", glb)
d = voxel_ai.mesh_to_json(glb, a.size, a.name)
json.dump(d, open(f"examples/{a.name}.json", "w")); voxel_ai.build(d, f"out/{a.name}")
