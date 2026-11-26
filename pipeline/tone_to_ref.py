"""Partial (alpha) Reinhard Lab transfer of a voxel palette toward the reference photo's colours (surface voxels weighted)."""
import sys, json, numpy as np
from PIL import Image
from skimage import color as skc
import vox, scorer
def tone(model, ref, out, alpha=0.6):
    d = json.load(open(model)); im = Image.open(ref); m = scorer.ref_mask(im)
    Lr = skc.rgb2lab(np.asarray(im.convert("RGB"))[m].astype(float)[None]/255)[0]
    _, occ, _, _ = vox.load(d); pad = np.pad(occ, 1)
    exposed = lambda v: not all(pad[v["x"]+1+dx, v["y"]+1+dy, v["z"]+1+dz] for dx, dy, dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)))
    keys = list(d["palette"]); P = np.array([vox.hex2rgb(d["palette"][k]) for k in keys], float)/255
    cnt = np.bincount([keys.index(v["c"]) for v in d["voxels"] if exposed(v)], minlength=len(keys)).astype(float)
    Lp = skc.rgb2lab(P[None])[0]; mu = (Lp*cnt[:, None]).sum(0)/cnt.sum(); sd = np.sqrt(((Lp-mu)**2*cnt[:, None]).sum(0)/cnt.sum())+1e-6
    Ln = (1-alpha)*Lp + alpha*((Lp-mu)/sd*Lr.std(0) + Lr.mean(0))
    rgb = (np.clip(skc.lab2rgb(Ln[None])[0], 0, 1)*255).round().astype(int)
    d["palette"] = {k: "#%02x%02x%02x" % tuple(c) for k, c in zip(keys, rgb)}; d["name"] += "_toned"; open(out, "w").write(json.dumps(d)); return out
if __name__ == "__main__":
    for k in sys.argv[1:]:
        n = k.split("_")[0]; tone(f"art/{k}_rendered.json", f"refs/{n}.jpg", f"art/{k}_rendered_toned.json")
