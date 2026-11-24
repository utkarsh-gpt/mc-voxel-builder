#!/usr/bin/env python3
"""fal Trellis shape stage: masked reference -> Trellis GLB -> textured voxel JSON (art/<name>_fal_v0.json).
usage: python fal_shape.py NAME [--grid 40]   (skips the fal call if out/<name>_trellis.glb already exists)"""
import argparse, json, os, urllib.request, numpy as np
import fal_client, trimesh
from scipy.spatial import cKDTree
import scorer

def get_mesh(name):
    glb = f"out/{name}_trellis.glb"
    if os.path.exists(glb): return glb
    url = fal_client.upload_file(f"refs/{name}_fal_in.png")
    res = fal_client.subscribe("fal-ai/trellis", arguments={"image_url": url, "texture_size": 1024, "mesh_simplify": 0.95})
    urllib.request.urlretrieve(res["model_mesh"]["url"], glb); return glb

def surface_colours(mesh, n=200000, seed=None):
    """dense, even surface samples of a textured mesh -> (points, colours[n,3] 0..255, face index)"""
    try: vcol = np.asarray(mesh.visual.to_color().vertex_colors)[:, :3].astype(float)
    except Exception: vcol = np.full((len(mesh.vertices), 3), 160.)
    # colour each voxel from the nearest *surface* sample (dense surface samples -> better texture detail)
    sp, fi = trimesh.sample.sample_surface_even(mesh, n, seed=seed)
    try:
        uv = mesh.visual.uv; tri = mesh.faces[fi]
        bc = trimesh.triangles.points_to_barycentric(mesh.triangles[fi], sp)
        suv = (uv[tri] * bc[:, :, None]).sum(1)
        mat = mesh.visual.material
        if getattr(mat, "baseColorTexture", None) is None and getattr(mat, "emissiveTexture", None) is not None:
            # 'Shaded' exports (e.g. Hyper3D) put the baked colour in the emissive texture
            tex = np.asarray(mat.emissiveTexture.convert("RGB")); th, tw = tex.shape[:2]
            px = np.clip((suv[:, 0] % 1) * (tw - 1), 0, tw - 1).astype(int); py = np.clip((1 - suv[:, 1] % 1) * (th - 1), 0, th - 1).astype(int)
            scol = tex[py, px].astype(float)
        else:
            scol = np.asarray(mat.to_color(suv))[:, :3].astype(float)
    except Exception:
        scol = vcol[cKDTree(mesh.vertices).query(sp)[1]]
    return sp, scol, fi

def voxelize(glb, grid=40, k=32):
    sc = trimesh.load(glb); mesh = sc.to_geometry() if isinstance(sc, trimesh.Scene) else sc
    pitch = mesh.extents.max() / (grid - 1)
    vg = mesh.voxelized(pitch).fill()
    idx = vg.sparse_indices; pts = vg.points
    sp, scol, _ = surface_colours(mesh)
    cols = scol[cKDTree(sp).query(pts)[1]]
    pal, _ = scorer.kmeans_palette(cols, k=k); lab = ((cols[:, None]-pal[None])**2).sum(-1).argmin(1)
    keys = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    W, H, D = vg.matrix.shape
    return {"size": [int(W), int(H), int(D)], "palette": {keys[i]: "#%02x%02x%02x" % tuple(np.clip(c, 0, 255).astype(int)) for i, c in enumerate(pal)},
            "voxels": [{"x": int(a), "y": int(b), "z": int(c), "c": keys[l]} for (a, b, c), l in zip(idx, lab)]}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--grid", type=int, default=40); a = ap.parse_args()
    glb = get_mesh(a.name); print("mesh:", glb, os.path.getsize(glb), flush=True)
    d = voxelize(glb, a.grid); d["name"] = a.name + "_fal"; d["camera"] = {"azim": 0, "elev": 10}
    json.dump(d, open(f"art/{a.name}_fal_v0.json", "w")); print("voxels:", len(d["voxels"]), "size", d["size"])
