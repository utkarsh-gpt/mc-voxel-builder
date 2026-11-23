"""Optional last step of the colour stage: shift every palette colour by alpha * (photo mean Lab - render mean Lab).
Mean shift only (no std scaling), so ramp steps and gradient chains keep their contrast."""
import json, sys, numpy as np
from PIL import Image
from skimage import color as skc
import vox, scorer
def match(n, alpha, src, dst, cam):
    ref = Image.open(f"refs/{n}.jpg"); rm = scorer.ref_mask(ref); rl = skc.rgb2lab(np.asarray(ref.convert("RGB"))/255)[rm]
    _, o, c, _ = vox.load(src.replace(".json", "_fine.json"), seed=0); im, m = vox.render(o, c, cam[0], cam[1], 512, light=(-0.25, 0.8, 0.55))
    ml = skc.rgb2lab(np.asarray(im.convert("RGB"))/255)[m]
    shift = alpha*(rl.mean(0) - ml.mean(0)); d = json.load(open(src))
    for k, h in d["palette"].items():
        l = skc.rgb2lab(np.array(vox.hex2rgb(h), float)[None, None]/255)[0, 0] + shift
        d["palette"][k] = "#%02x%02x%02x" % tuple((np.clip(skc.lab2rgb(l[None, None])[0, 0], 0, 1)*255).round().astype(int))
    d.setdefault("texture", {})["photo_match"] = {"alpha": alpha, "lab_shift": [round(float(x), 2) for x in shift]}
    json.dump(d, open(dst, "w")); import subblock; subblock.expand(dst, dst.replace(".json", "_fine.json")); return shift
if __name__ == "__main__":
    n, a = sys.argv[1], float(sys.argv[2]); cam = json.load(open("out/textured_pass_scores.json"))[n]["camera"]
    src = f"art/final/{n}_voxels_textured.json"; print(n, a, match(n, a, src, sys.argv[3] if len(sys.argv) > 3 else src, cam))
