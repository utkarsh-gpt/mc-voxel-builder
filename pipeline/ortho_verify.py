#!/usr/bin/env python3
"""Cheap verification layer for ortho sheets: (a) geometric cross-view checks, (b) vision-LLM sanity check (claude CLI, Haiku only: claude-haiku-5-5).
Generates a sheet, verifies, regenerates up to 2x with the found issues appended to the prompt, picks the best attempt and
drops views still flagged bad. usage: python ortho_verify.py NAME [--tries 3]   -> out/NAME_verify.json (+ ortho/NAME_v{k}_* files)
Only nano-banana/edit (~$0.039/sheet) is spent here."""
import argparse, json, os, re, subprocess, numpy as np
from PIL import Image
from skimage.transform import resize
import ortho_carve, ortho_clean
COM = ("Match the photo EXACTLY in shape, proportions, number of parts and colours; do not stylise, simplify, beautify or add anything. "
       "Draw ONLY the main object: no props, ground lines, walls or base plates. Colours must be sampled from the photo. No labels, text or panel frames.")
SPEC = {
 "windmill": ("stone tower windmill", "Specifics: cylindrical buff-grey limestone tower (about #A89F8C), height about 1.3x its diameter; lower half an open arcade of arches on "
   "square stone piers; one small dark window on the upper drum; shallow dark slate-grey dome cap. Four WHITE open-lattice sails in an X in the FRONT and BACK views only, "
   "attached to a hub on the front of the cap. CRITICAL: the sails lie in one flat vertical plane at the FRONT of the tower. In the RIGHT SIDE panel they are seen exactly "
   "edge-on: ONE thin straight vertical bar just in front of (to the left of) the tower, as tall as the sail span; do NOT draw an X or any lattice in the right side panel. "
   "In the TOP panel look straight down: the dome is a plain filled grey circle and the sails are ONE thin straight horizontal bar just below (in front of) the circle, "
   "as wide as the sail span; do NOT draw any tower, arches or X in the top panel."),
 "cottage": ("thatched cottage", "Specifics: a LONG, LOW Danish thatched cottage. Building length is about 3x its depth. White-painted concrete block walls that are low (wall height "
   "about half the roof height). Thick pale grey-green mossy thatched roof with a long, nearly flat ridge running about 75% of the length, rounded hipped ends and a deep "
   "overhang over the walls. Two arched thatch eyebrows on the front eave: one over a red arched door left of centre and one over a red multi-pane window right of centre. "
   "One dark brick chimney on the ridge near the middle. Side view: narrow hipped end, depth about one third of the front width. Top plan: a long rounded rectangle with the ridge line."),
 "bonsai": ("bonsai tree", "Specifics: a juniper bonsai with a WIDE, flat UMBRELLA-shaped canopy about 2x as wide as it is tall, with a slightly ragged flat underside and wispy edges, "
   "made of bright yellow-green needle foliage (about #6FB83A, darker green in the gaps). A slender orange-brown trunk with a gentle S-curve that forks into a Y just below the "
   "canopy; the trunk is clearly visible below the canopy for about one third of the total height. A shallow OVAL glossy OXBLOOD-RED pot (about #7A2418) whose width is about "
   "0.55 of the canopy width, filled with dark brown soil. No stand, table or label.")}
SPEC.update({
 "cathedral": ("Gothic stone cathedral", "Specifics: warm honey limestone/sandstone (about #C9A46A, shadows #8A6A40) Gothic cathedral. FRONT = the west facade: two tall square towers "
   "each with a slender pointed spire (spire tips are the highest points, about 1.6x the nave roof ridge height), a round rose window between the towers, three pointed portals. "
   "The nave runs straight back from the facade; it is about 2.2x as long as the facade is wide, with a steep dark grey slate pitched roof, buttresses and pinnacles on the sides. "
   "RIGHT SIDE: the long nave elevation with the towers at the LEFT (front) end. TOP: towers at the bottom (front), the long roof ridge running up the panel. Include the thin flat plinth."),
 "landscape": ("coastal cliff terrain diorama block", "Specifics: a rectangular terrain block about 2x as wide as tall and about 1.2x as wide as deep: green grass top, layered grey and "
   "ochre rock strata on the cut sides, a stream on top flowing to the front edge where a white waterfall falls down the front cliff face into a turquoise pool and sea at the front-right, "
   "a small sandy beach, a sea cave. The cut-away sides are straight vertical. TOP: grass with the stream, the sea area turquoise along the front."),
 "turtle": ("coral-encrusted sea turtle", "Specifics: a sea turtle seen as a sculpture-like single animal: domed olive-brown shell (about #7A6A45) with hexagonal scutes, patches of orange/pink coral, "
   "purple sea fans and green algae on top; grey-green scaly head pointing to the FRONT; two long front flippers spread sideways, two short back flippers. FRONT view = looking at the "
   "head; RIGHT SIDE = profile with the head on the LEFT; TOP = the shell from above with the head at the bottom of the panel, flippers spread left and right. The BACK panel is a REAR elevation at the same eye level as the FRONT (looking at the tail end, shell dome seen edge-on, same height as FRONT); it is NOT a view from above.")})
LLM_PROMPT = """You are checking an AI-generated orthographic reference sheet before it is used to build a 3D model.
Read the sheet image {sheet} (2x2 panels: top-left FRONT, top-right RIGHT SIDE, bottom-left BACK, bottom-right TOP plan with the front at the bottom)
and the reference photo {photo} of the real object ({hint}).
Check physical and semantic sense, mutual consistency and faithfulness:
- parts attach where they physically belong (e.g. windmill sails are mounted on the FRONT of the cap; in the RIGHT SIDE view they must be edge-on as a thin vertical bar at the front edge, never an X crossing the middle of the building; in the TOP view a thin bar at the front);
- heights agree between front/side/back, widths agree between front/back/top, the side-view depth equals the top-view depth;
- the back view is the mirror silhouette of the front;
- each panel is a straight-on orthographic view (not perspective/oblique), the top view really looks straight down;
- no extra props, ground, labels, frames; proportions and colours match the photo.
Automatic geometric checks already found: {geo}
Reply with ONLY a JSON object: {{"pass": true/false, "bad_views": [subset of "front","right","back","top"], "issues": ["short specific fix instructions for the image generator"]}}"""
VIEWS = ("front", "right", "back", "top")

def geo_checks(prefix):
    M = {v: ortho_carve.mask_of(f"ortho/{prefix}_{v}.png")[0] for v in VIEWS}
    hw = {v: M[v].shape for v in VIEWS}; issues, bad = [], set()
    r = lambda a, b: max(a, b)/max(min(a, b), 1)
    Hf, Wf = hw["front"]; Hb, Wb = hw["back"]; Hs, Ws = hw["right"]; Ht, Wt = hw["top"]
    if r(Hs, (Hf+Hb)/2) > 1.12: issues.append(f"side view height {Hs}px differs from front/back {Hf}/{Hb}px"); bad.add("right")
    if r(Hf, Hb) > 1.12: issues.append(f"front height {Hf}px vs back {Hb}px"); bad.add("back")
    if r(Wf, Wb) > 1.12: issues.append(f"front width {Wf}px vs back {Wb}px"); bad.add("back")
    if r(Wt, (Wf+Wb)/2) > 1.15: issues.append(f"top view width {Wt}px differs from front/back width {Wf}/{Wb}px"); bad.add("top")
    if r(Ws, Ht) > 1.15: issues.append(f"side-view depth {Ws}px does not match top-view depth {Ht}px"); bad.update({"right", "top"} if not bad & {"right", "top"} else set())
    fb = resize(M["back"][:, ::-1].astype(float), M["front"].shape, order=1) > .5
    iou = float((fb & M["front"]).sum() / (fb | M["front"]).sum())
    if iou < 0.75: issues.append(f"back silhouette is not the mirror of the front (IoU {iou:.2f})"); bad.add("back")
    return {"sizes_hw": {v: list(map(int, hw[v])) for v in VIEWS}, "front_back_mirror_iou": round(iou, 3), "issues": issues, "bad_views": sorted(bad)}

VERIFY_MODEL = "claude-haiku-5-5"   # Haiku-only verification (Sonnet confirm pass removed for cost)
def llm_check(n, prefix, geo, model=VERIFY_MODEL):
    p = LLM_PROMPT.format(sheet=os.path.abspath(f"ortho/{prefix}_sheet.png"), photo=os.path.abspath(f"refs/{n}.jpg"), hint=SPEC[n][0],
                          geo="; ".join(geo["issues"]) or "none")
    out = subprocess.run(["claude", "-p", "--model", model, p, "--allowedTools", "Read"], capture_output=True, text=True, timeout=300).stdout
    m = re.search(r"\{.*\}", out, re.S)
    try: return json.loads(m.group(0))
    except Exception: return {"pass": False, "bad_views": [], "issues": ["unparseable LLM reply"], "raw": out[-500:]}

def gen(n, tag, extra):
    hint, spec = SPEC[n]
    r = subprocess.run(["python", "ortho_gen.py", n, hint, "--tag", tag, "--with-photo", "--extra", f"{COM} {spec}{extra}"], capture_output=True, text=True)
    if r.returncode: raise SystemExit(r.stderr[-800:])
    for v in VIEWS: ortho_clean.clean(f"ortho/{n}{tag}_{v}.png")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--tries", type=int, default=3); ap.add_argument("--start", type=int, default=1); a = ap.parse_args(); n = a.name
    attempts, extra = [], ""
    if a.start > 1:   # continue an earlier run: keep its attempts, feed the last attempt's fixes into the next sheet
        attempts = json.load(open(f"out/{n}_verify.json"))["attempts"]; last = attempts[-1]
        fixes = last["geo"]["issues"] + last["llm"].get("issues", [])
        extra = " FIX THESE PROBLEMS FOUND IN THE PREVIOUS ATTEMPT: " + " ".join(f"({i+1}) {f}." for i, f in enumerate(fixes[:8]))
    for k in range(a.start, a.start + a.tries):
        tag = f"_v{k}"; gen(n, tag, extra); prefix = n + tag
        geo = geo_checks(prefix); llm = llm_check(n, prefix, geo)
        bad = sorted(set(geo["bad_views"]) | set(v for v in llm.get("bad_views", []) if v in VIEWS))
        ok = bool(llm.get("pass")) and not geo["issues"]
        att = {"tag": tag, "geo": geo, "llm": llm, "bad_views": bad, "pass": ok}; attempts.append(att)
        print(n, tag, "PASS" if ok else "FAIL", "bad:", bad, "| geo:", geo["issues"], "| llm:", llm.get("issues"), flush=True)
        if ok: break
        fixes = geo["issues"] + llm.get("issues", [])
        extra = " FIX THESE PROBLEMS FOUND IN THE PREVIOUS ATTEMPT: " + " ".join(f"({i+1}) {f}." for i, f in enumerate(fixes[:8]))
    best = min(attempts, key=lambda t: (not t["pass"], "front" in t["bad_views"], len(t["bad_views"]), len(t["geo"]["issues"]) + len(t["llm"].get("issues", []))))
    keep = [v for v in VIEWS if v == "front" or v not in best["bad_views"]]
    readmit = []
    if len(keep) < 2:   # front alone gives no depth: re-admit views that only Haiku flagged (geometry-clean), Haiku over-flags cosmetics
        readmit = [v for v in VIEWS if v not in keep and v not in best["geo"]["bad_views"]]; keep = [v for v in VIEWS if v in keep or v in readmit]
    res = {"name": n, "chosen": best["tag"], "chosen_pass": best["pass"], "views_used": keep, "views_dropped": [v for v in VIEWS if v not in keep], "readmitted_geometry_clean": readmit,
           "sheets_generated": len(attempts), "haiku_calls": len(attempts), "verify_model": VERIFY_MODEL, "cost_usd": round(0.039*len(attempts), 3), "attempts": attempts}
    json.dump(res, open(f"out/{n}_verify.json", "w"), indent=1)
    print(n, "chosen", best["tag"], "views", keep, "sheets", len(attempts))
