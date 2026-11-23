#!/usr/bin/env python3
"""After fal_shape.py: colour-transfer -> wide camera fit -> refine.py texturing -> score (+Sonnet judge) -> images.
usage: python run_fal.py NAME"""
import sys, json, os, numpy as np
from PIL import Image
from skimage import color as skc
import vox, scorer, refine, run_subject

OLD = {"mushroom": ("art/mushroom_v2_refined2.json", "out/mushroom_refined2_score.json")}
def old_paths(n): return OLD.get(n, (f"art/{n}_refined.json", f"out/{n}_refined_score.json"))

def colour_transfer(model, ref, out):
    """Reinhard-style Lab mean/std transfer of the Trellis texture colours toward the reference subject."""
    d = json.load(open(model)); im = Image.open(ref); m = scorer.ref_mask(im)
    Lr = skc.rgb2lab(np.asarray(im.convert("RGB"))[m].astype(float)[None]/255)[0]
    keys = list(d["palette"]); P = np.array([vox.hex2rgb(d["palette"][k]) for k in keys], float)/255
    cnt = np.bincount([keys.index(v["c"]) for v in d["voxels"]], minlength=len(keys)).astype(float)
    Lp = skc.rgb2lab(P[None])[0]; mu = (Lp*cnt[:, None]).sum(0)/cnt.sum(); sd = np.sqrt(((Lp-mu)**2*cnt[:, None]).sum(0)/cnt.sum())+1e-6
    Ln = (Lp-mu)/sd*Lr.std(0) + Lr.mean(0)
    rgb = (np.clip(skc.lab2rgb(Ln[None])[0], 0, 1)*255).round().astype(int)
    d["palette"] = {k: "#%02x%02x%02x" % tuple(c) for k, c in zip(keys, rgb)}; json.dump(d, open(out, "w")); return out

def fit_cardinal(ref_img, occ, col):
    """Trellis output front is one of the 4 cardinal directions. Search +-40 deg around each, elev -35..35,
    objective = silhouette IoU + colour agreement - small penalty for extreme elevation (stops 'view from top' optima)."""
    from skimage import color as skc
    rr, rm, _ = scorer.normalize(np.asarray(ref_img.convert("RGB")), scorer.ref_mask(ref_img)); L1 = skc.rgb2lab(rr)
    def obj(a, e):
        img, m = vox.render(occ, col, a, e, 160)
        vr, vm, _ = scorer.normalize(np.asarray(img), m); both = rm & vm
        iou = both.sum()/(rm | vm).sum()
        dE = np.linalg.norm(L1[both]-skc.rgb2lab(vr)[both], axis=1).mean() if both.any() else 100
        return iou + 0.5*max(0, 1-dE/50) - 0.002*abs(e - 5)
    best = max((obj(a, e), a, e) for a in range(0, 360, 10) for e in range(-35, 36, 10))
    _, a0, e0 = best
    best = max([best] + [(obj(a, e), a, e) for a in range(a0-6, a0+7, 3) for e in range(e0-6, e0+7, 3)])
    return best[1] % 360, best[2]

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "--cam-only":
        n = sys.argv[1]; d, occ, col, _ = vox.load(f"art/{n}_fal_v0t.json"); print(n, fit_cardinal(Image.open(f"refs/{n}.jpg"), occ, col)); sys.exit()
    n = sys.argv[1]; ref = f"refs/{n}.jpg"; S = {}
    p0 = colour_transfer(f"art/{n}_fal_v0.json", ref, f"art/{n}_fal_v0t.json")
    d, occ, col, _ = vox.load(p0); ri = Image.open(ref)
    # Trellis puts the input view at the model front (azim ~0); a wide 360 search picked wrong optima (e.g. bonsai from the top)
    az, el = fit_cardinal(ri, occ, col)
    dd = json.load(open(p0)); dd["camera"] = {"azim": az, "elev": el}; json.dump(dd, open(p0, "w"))
    r0 = scorer.score(ref, p0, f"out/{n}_fal_v0", az, el, fit=False); S["fal_v0_auto"] = r0["auto_total"]
    print(n, "camera", az, el, "fal v0 auto", r0["auto_total"], flush=True)
    refine.refine(ref, p0, f"art/{n}_fal_refined.json", fit=True)
    rr = scorer.score(ref, f"art/{n}_fal_refined.json", f"out/{n}_fal_refined", fit=False, use_judge=True)
    S.update({"new_auto": rr["auto_total"], "new_judge": rr.get("judge", {}).get("overall"), "new_judge_scores": rr.get("judge", {}).get("scores"),
              "new_parts": rr["auto_parts"], "camera": rr["camera"], "fixes": rr.get("judge", {}).get("fixes")})
    om, osc = old_paths(n); o = json.load(open(osc)); S["old_auto"] = o["auto_total"]
    S["old_judge"] = o.get("judge", {}).get("overall") if n != "mushroom" else 4
    if S["old_judge"] is None and os.path.exists(f"out/{n}_summary.json"): S["old_judge"] = json.load(open(f"out/{n}_summary.json"))["refined"]["judge"]
    print(n, "old", S["old_auto"], S["old_judge"], "new", S["new_auto"], S["new_judge"], flush=True)
    _, oocc, ocol, _ = vox.load(om); _, nocc, ncol, _ = vox.load(f"art/{n}_fal_refined.json")
    oc, nc = o["camera"], rr["camera"]
    tiles = [("reference", run_subject.masked_ref(ref)),
             (f"OLD (Claude shape) ref cam\nauto {S['old_auto']} / judge {S['old_judge']}/10", vox.render(oocc, ocol, oc["azim"], oc["elev"], 512)[0]),
             ("OLD opposite angle", vox.render(oocc, ocol, oc["azim"]+180, 20, 512)[0]),
             (f"NEW (fal Trellis shape) ref cam\nauto {S['new_auto']} / judge {S['new_judge']}/10", vox.render(nocc, ncol, nc["azim"], nc["elev"], 512)[0]),
             ("NEW opposite angle", vox.render(nocc, ncol, nc["azim"]+180, 20, 512)[0])]
    run_subject.label_strip(tiles, f"out/{n}_fal_compare.png", 280)
    run_subject.turntable(f"art/{n}_fal_refined.json", nc["azim"], f"out/{n}_fal_turntable.png")
    json.dump(S, open(f"out/{n}_fal_summary.json", "w"), indent=2); print(n, "done", flush=True)
