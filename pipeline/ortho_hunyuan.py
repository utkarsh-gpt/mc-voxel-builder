"""Hunyuan3D v3.1 Pro multi-view (ortho views) -> GLB -> voxels.
usage: python ortho_hunyuan.py NAME [TAG] [--views front,back,right,top]
writes out/NAME{TAG}_hymv.glb, art/NAME{TAG}_hymv.json (older pass without TAG: out/NAME_hymv.*)"""
import sys, json, argparse, urllib.request, fal_client, fal_shape
ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("tag", nargs="?", default=""); ap.add_argument("--views", default="front,back,right,top")
a = ap.parse_args(); n, tag = a.name, a.tag; key = n + tag if tag.startswith("_t") else n
up = lambda k: fal_client.upload_file(f"ortho/{n}{tag}_{k}.png")
args = {"input_image_url": up("front")}
for v in a.views.split(","):
    if v != "front": args[f"{v}_image_url"] = up(v)
res = fal_client.subscribe("fal-ai/hunyuan-3d/v3.1/pro/image-to-3d", arguments=args)
glb = f"out/{key}_hymv.glb"; urllib.request.urlretrieve(res["model_glb"]["url"], glb)
d = fal_shape.voxelize(glb, 48); d["name"] = key + "_hymv"; d["camera"] = {"azim": 0, "elev": 10}
json.dump(d, open(f"art/{key}_hymv.json", "w")); print(key, "views", a.views, "voxels", len(d["voxels"]), d["size"])
