#!/usr/bin/env python3
"""Cheap verification layer for ortho sheets: (a) geometric cross-view checks, (b) vision-LLM sanity check (claude CLI, Haiku only: claude-haiku-5-5).
Generates a sheet, verifies, regenerates up to 2x with the found issues appended to the prompt, picks the best attempt and
drops views still flagged bad. usage: python ortho_verify.py NAME [--tries 3]   -> out/NAME_verify.json (+ ortho/NAME_v{k}_* files)
Only nano-banana/edit (~$0.039/sheet) is spent here."""
import argparse, json, os, re, subprocess, sys, numpy as np
from PIL import Image
from skimage.transform import resize
import ortho_carve, ortho_clean, shading_check
from scipy import ndimage
COM = ("Match the photo EXACTLY in shape, proportions, number of parts and colours; do not stylise, simplify, beautify or add anything. "
       "Draw ONLY the main object: no props, ground lines, walls or base plates. Colours must be sampled from the photo. No labels, text or panel frames. "
       "Flat albedo colours with NO shadows, shading, ambient occlusion or directional light: the same material has the same colour in every panel.")
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
 "house": ("two-storey American suburban house", "Specifics: the two-and-a-half-storey wood-frame house exactly as in the photo. A rectangular main block whose front "
   "facade (the long side with the porch, on the RIGHT of the photo) is about 1.25x as wide as the side wall is deep. Walls of pale butter-yellow horizontal lap siding (about #EDE3A6) "
   "with dark chocolate-brown trim (about #5A3428) at the corners, window frames, fascia and eaves. Side-gabled roof of red-brown asphalt shingles (about #8E5444), ridge parallel to the "
   "front, moderate pitch, deep eave overhangs, a gable end on each narrow side with one small attic window in each gable. Two front-facing gabled dormers on the front roof slope, "
   "each with one window. One red brick chimney (about #9A4B3C) on the ridge near the left gable. Upper floor front: two pairs of tall double-hung windows. A full-width one-storey "
   "front porch with a shallow shed roof in the same shingles, carried by five square dark-brown posts on low red-brick piers, a front door and a large window behind it, and a few "
   "concrete steps up to the porch at the right end. Side walls: two windows per floor. Plain grey concrete foundation strip. "
   "FRONT = the porch facade viewed straight on; RIGHT SIDE = the right gable end with the porch projecting on the LEFT (front); BACK = the plain rear wall; "
   "TOP = the roof with the ridge running left-right, the two dormers on the lower (front) slope and the porch roof along the bottom (front) edge. "
   "Draw ONLY the house: no detached garage, hedge, bushes, trees, power lines, lawn, driveway or sidewalk; complete the parts the garage and hedge hide."),
 "hagia": ("Byzantine domed church (Little Hagia Sophia)", "Specifics: the Little Hagia Sophia in Istanbul exactly as in the photo, seen from the east. A nearly square two-storey main block "
   "of mixed red-brown brick and pale grey stone courses (about #8C6A5E brick, #9A8F84 stone), with thin projecting brick cornices at the roof line, rows of rectangular windows in pale stone frames "
   "and a few round-arched windows with white lattice grilles on the narrow end. Above it a low OCTAGONAL DRUM in pinkish rendered brick (about #B07A6E) with a flat buttress pier at every corner, "
   "one round-arched window between each pair of piers, and stepped cornices on top of each pier; on the drum a shallow ribbed lead-grey dome (about #8E9497) with a small gold finial. "
   "On the narrow end a lower lead-grey half-dome leans against the drum, and shallow lead-grey roofs cover the rest of the block. "
   "FRONT = the narrow end on the LEFT of the photo (two large arched grilled windows, half-dome above); RIGHT SIDE = the long flank with the front end on the LEFT; "
   "BACK = the opposite narrow end; TOP = square block with the round dome in the middle and the half-dome toward the bottom (front). "
   "Draw ONLY the church: no small tiled-roof tomb building, minaret, fences, walls, trees, lamp posts, lawn or graves."),
 "landscape": ("coastal cliff terrain diorama block", "Specifics: a rectangular terrain block about 2x as wide as tall and about 1.2x as wide as deep: green grass top, layered grey and "
   "ochre rock strata on the cut sides, a stream on top flowing to the front edge where a white waterfall falls down the front cliff face into a turquoise pool and sea at the front-right, "
   "a small sandy beach, a sea cave. The cut-away sides are straight vertical. TOP: grass with the stream, the sea area turquoise along the front."),
 "turtle": ("coral-encrusted sea turtle", "Specifics: a sea turtle seen as a sculpture-like single animal: domed olive-brown shell (about #7A6A45) with hexagonal scutes, patches of orange/pink coral, "
   "purple sea fans and green algae on top; grey-green scaly head pointing to the FRONT; two long front flippers spread sideways, two short back flippers. FRONT view = looking at the "
   "head; RIGHT SIDE = profile with the head on the LEFT; TOP = the shell from above with the head at the bottom of the panel, flippers spread left and right. The BACK panel is a REAR elevation at the same eye level as the FRONT (looking at the tail end, shell dome seen edge-on, same height as FRONT); it is NOT a view from above.")})
# v2 reruns (2026-11-25) and the gate: same subjects as windmill / cottage from the same reference photos, new sheets
SPEC["windmill_v2"] = (SPEC["windmill"][0], SPEC["windmill"][1] + " The lower arcade arches are OPEN passages: you can see straight through them, so draw the "
   "white background inside each arch opening (no dark interior).")
SPEC["cottage_v2"] = SPEC["cottage"]
SPEC["gate"] = ("fantasy gothic stone gatehouse", "Specifics: a Minecraft-style fantasy gothic GATEHOUSE, symmetric, drawn as a free-standing structure. "
   "Pale warm-grey stone walls (about #B8A99C) with darker stone trim. In the middle a very tall POINTED ARCHWAY that is an OPEN passage you can see straight through "
   "(draw the white background inside it, from the ground up to the point of the arch), under a steep stone gable with a small pointed gable window and tracery. "
   "The gable is flanked by two slim square towers with pointed dark slate caps (about #5A4E48) that are the highest points. Left and right of the towers a lower side wing "
   "with a dark slate roof, a smaller OPEN pointed arch (white background visible through it) and a slim corner tower with a pointed slate cap at each outer end. "
   "Many small narrow slit windows lit warm yellow (about #E8B860) in the towers and wings. The gatehouse is THIN: its depth is about one fifth of its width. "
   "FRONT and BACK = the arch facade viewed straight on; RIGHT SIDE = the narrow end (an end tower and the wing roof end, depth about 1/5 of the width); "
   "TOP = a long thin plan with the slate caps as squares. Draw ONLY the gatehouse: NO trees, branches, leaves, grass, ground, rocks, cliffs, sky or clouds, "
   "and nothing behind the open arches.")
SPEC["rapunzel_tower"] = ("Rapunzel's tower from Tangled", "Specifics: a very TALL, SLENDER fairy-tale stone TOWER, isolated, no cliffs, trees, ground, grass, sky or water. "
   "CRITICAL PROPORTION (do not crop): the building is a LONG STONE COLUMN with a small room on top. In the FRONT, RIGHT and BACK panels the warm tan limestone SHAFT (about #C6A47A) must be fully drawn from the ground line up to the red corbels and must occupy about 55-65% of the tower's total height (from ground to the green finial). "
   "The shaft is a plain tapering cylinder, wider at the base, with climbing ivy (about #4E7A3A). It is several times taller than the upper room. NEVER crop the shaft, NEVER sit the upper room on the bottom of the panel, NEVER replace the shaft with a short stub. "
   "The shaft is topped by a RING of short reddish-terracotta corbels (about #B45A45) that carry a wider, circular timber-framed upper room. The upper room has cream plaster walls (about #E8D5B0), "
   "dark brown timber framing (about #5A3A28) in an X and post-and-beam pattern around the lower storey of the room, flower boxes and hanging baskets, a large dark arched window opening on the front, "
   "and smaller dark windows on the sides. A small side turret with its own pointed slate cap juts from the left (front-left) of the upper room; a tiny crenellated chimney-stack sits on the right roof slope. "
   "The main roof is a tall pointed CONICAL roof of blue-lavender slate (about #7A6B9A) with a thin finial topped by a green sphere. One or two small dormer windows sit in the roof cone. "
   "FRONT = the facade with the large arched window facing us; RIGHT SIDE = the same tower turned 90 degrees (the side turret is toward the back of that panel); "
   "BACK = the rear of the upper room (more windows, no large balcony opening if the front had one); TOP = a circular plan, the conical roof as a filled circle, the side turret as a smaller circle on one side. "
   "Proportions are critical: the upper room is wider than the shaft (it jettes out on corbels); the shaft is a plain cylinder; the roof spire is the highest point. "
   "Draw ONLY the tower: no canyon walls, waterfalls, trees, rocks, people, hair, or ground.")
LLM_PROMPT = """You are checking an AI-generated orthographic reference sheet before it is used to build a 3D model.
Read the sheet image {sheet} (2x2 panels: top-left FRONT, top-right RIGHT SIDE, bottom-left BACK, bottom-right TOP plan with the front at the bottom)
and the reference photo {photo} of the real object ({hint}).
Check physical and semantic sense, mutual consistency and faithfulness:
- parts attach where they physically belong (e.g. windmill sails are mounted on the FRONT of the cap; in the RIGHT SIDE view they must be edge-on as a thin vertical bar at the front edge, never an X crossing the middle of the building; in the TOP view a thin bar at the front);
- heights agree between front/side/back, widths agree between front/back/top, the side-view depth equals the top-view depth;
- the back view is the mirror silhouette of the front;
- each panel is a straight-on orthographic view (not perspective/oblique), the top view really looks straight down;
- no extra props, ground, labels, frames; proportions and colours match the photo;
- colours are flat albedo: no cast shadows (e.g. under eaves or a porch roof), no darkened corners, no gradients, no directional light; the same material is equally bright in every panel (the TOP plan roof is as bright as the FRONT roof).
Automatic geometric checks already found: {geo}
Reply with ONLY a JSON object: {{"pass": true/false, "bad_views": [subset of "front","right","back","top"], "issues": ["short specific fix instructions for the image generator"]}}"""
VIEWS = ("front", "right", "back", "top")

def auto_spec(n, parts=None):
    """Fallback (hint, specifics) so unseen subjects never KeyError on SPEC[n]."""
    if n in SPEC: return SPEC[n]
    hint = n.replace("_", " ")
    summary = ""
    try:
        import parts_list
        P = parts if parts is not None else parts_list.load(n)
        if P: summary = (P.get("summary") or "").strip()
    except Exception:
        P = parts; summary = ((P or {}).get("summary") or "").strip()
    spec = (summary[:400] + " Draw ONLY the subject, isolated, no extra props, ground, sky or labels.") if summary else (
        f"Draw the {hint} exactly as in the photo: isolated, complete, no extra props, ground, sky or labels. Colours sampled from the photo.")
    return hint, spec

def get_spec(n, parts=None):
    return SPEC[n] if n in SPEC else auto_spec(n, parts)

def _bbox(m):
    ys, xs = np.nonzero(m)
    if len(ys) == 0: return None
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())

def framing_check(prefix, n=None):
    """Fail a sheet whose elevations are cropped, squashed, or inconsistent with each other.

    The old test compared the front ELEVATION's aspect with the 3/4-view photo cut-out, which measures a different
    projection (and a cut-out rembg may have clipped). Proportions are now checked by INTERNAL panel consistency:
      hard (fail the sheet -> buys sheet 2): an elevation touching any panel edge / filling > 92% of it, side height vs
        front height > 8%, front vs back aspect (h/w) > 25%
      soft (rank only + mark the top plan bad): front width vs top width, right width vs top depth > 25%
    `aspect_error` (the _sheet_key tie-break) = the largest ln-ratio among the elevation pairs (+ top pairs within 25%).
    `bad_views` lists every framing problem; `drop_views` is the narrower set unusable as a Hyper3D input (missing
    panels, or a top plan whose scale is clearly wrong)."""
    import math, ortho_carve
    issues, soft, bad, drop = [], [], set(), set()
    n = n or prefix.rsplit("_", 1)[0]
    M, bb = {}, {}
    for v in VIEWS:
        path = f"ortho/{prefix}_{v}.png"
        if not os.path.exists(path):
            issues.append(f"{v} panel missing"); bad.add(v); drop.add(v); continue
        im = np.asarray(Image.open(path).convert("RGB"))
        m, _ = ortho_carve.mask_of(path); M[v] = (m, im.shape[:2])
        # mask_of returns the mask CROPPED to the subject (so a bbox of it always touches its own edges, which made
        # every sheet fail framing): locate the subject inside the full panel from its non-white extent instead
        full = ndimage.binary_closing(im.min(-1) < 235, np.ones((5, 5)))
        lab, k = ndimage.label(full)
        if k:
            sz = np.bincount(lab.ravel()); sz[0] = 0; full = sz[lab] >= 0.04 * sz.max()
        bbf = _bbox(full)
        bb[v] = (0, m.shape[0] - 1, 0, m.shape[1] - 1) if bbf is None else bbf
        bb[v + "_wh"] = (m.shape[1], m.shape[0])
    rec = {"pass": True, "aspect_error": None, "check": "internal panel consistency"}
    wh = lambda v: bb.get(v + "_wh")
    ratios = {}
    def pair(key, a, b):
        if a and b: ratios[key] = round(abs(math.log(a / b)), 3)
    if wh("front") and wh("back"):
        af = wh("front")[1] / wh("front")[0]; ab = wh("back")[1] / wh("back")[0]
        rec["a_front"], rec["a_back"] = round(af, 3), round(ab, 3); pair("front_back_aspect", af, ab)
        if ratios["front_back_aspect"] > math.log(1.25):
            issues.append(f"front aspect {af:.2f} vs back {ab:.2f} differ by more than 25%"); bad.add("back")
    if wh("front") and wh("right"):
        hf, hs = wh("front")[1], wh("right")[1]; pair("front_right_height", hf, hs)
        rec["side_vs_front_h"] = round(hs / max(hf, 1), 3)
        if max(hf, hs) / max(min(hf, hs), 1) > 1.08:
            issues.append(f"side height {hs}px differs from front {hf}px by more than 8%"); bad.add("right")
    if wh("top"):
        tw, th = wh("top")
        if wh("front"):
            pair("front_top_width", wh("front")[0], tw)
            if ratios["front_top_width"] > math.log(1.25): soft.append(f"top width {tw}px vs front width {wh('front')[0]}px differ by more than 25%"); bad.add("top")
        if wh("right"):
            pair("right_top_depth", wh("right")[0], th)
            if ratios["right_top_depth"] > math.log(1.25): soft.append(f"top depth {th}px vs side width {wh('right')[0]}px differ by more than 25%"); bad.add("top")
    rec["consistency_ln"] = ratios
    # rank on the elevations; the top plan counts only while it is consistent (an inconsistent top is marked bad and
    # dropped from the mesh, so it must not decide between two sheets)
    rank = {k: v for k, v in ratios.items() if not k.endswith(("top_width", "top_depth")) or v <= math.log(1.25)}
    rec["aspect_error"] = round(max(rank.values()), 3) if rank else 99.0
    for v in ("front", "right", "back"):
        if v not in M: continue
        h, w = M[v][1]; y0, y1, x0, x1 = bb[v]
        if y0 <= 1 or y1 >= h - 2:
            issues.append(f"{v} silhouette touches the top or bottom of the panel (cropped)"); bad.add(v)
        if x0 <= 1 or x1 >= w - 2:
            issues.append(f"{v} silhouette touches the left or right side of the panel (cropped)"); bad.add(v)
        sw, sh = wh(v); long = max(h, w); subj = max(sh, sw)
        if subj / long > 0.92:
            issues.append(f"{v} silhouette fills {100*subj/long:.0f}% of the panel's long axis (need >=10% margin)"); bad.add(v)
    if wh("top") and (wh("front") or wh("right")):
        tw, th = wh("top"); top_long = max(tw, th)
        fw = wh("front")[0] if wh("front") else 0; sw = wh("right")[0] if wh("right") else 0
        cap = 1.15 * max(fw, sw, 1)
        rec["top_long"], rec["top_cap"] = int(top_long), round(cap, 1)
        if top_long > cap:
            issues.append(f"top-view largest dim {top_long}px > 1.15 * max(front_w {fw}, side_w {sw})"); bad.add("top"); drop.add("top")
    rec["issues"] = issues + soft; rec["soft_issues"] = soft; rec["bad_views"] = sorted(bad); rec["drop_views"] = sorted(drop)
    rec["pass"] = not issues
    return rec

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
    sc = shading_check.check(prefix.rsplit("_", 1)[0], "_" + prefix.rsplit("_", 1)[1])   # flat-albedo check (image only, free)
    issues += sc["issues"]
    n = prefix.rsplit("_", 1)[0]
    fr = framing_check(prefix, n)
    issues += fr["issues"]; bad |= set(fr.get("drop_views") or [])
    # The "back" panel is sometimes drawn as a second top plan; drop it and flag the sheet.
    bt = resize(M["back"].astype(float), M["top"].shape, order=1) > .5
    denom = float((bt | M["top"]).sum()) or 1.0
    iou_bt = float((bt & M["top"]).sum()) / denom
    rec_extra = {"back_top_iou": round(iou_bt, 3)}
    if iou_bt >= 0.60 and iou < 0.75:
        issues.append(f"back panel looks like a second top plan (IoU with top {iou_bt:.2f}), not a rear elevation")
        bad.add("back")
        rec_extra["back_is_top"] = True
    return {"sizes_hw": {v: list(map(int, hw[v])) for v in VIEWS}, "front_back_mirror_iou": round(iou, 3), "issues": issues, "bad_views": sorted(bad),
            "shading": {k: sc[k] for k in ("top_vs_front_dL", "shadow_share", "gradient_std", "shaded")},
            "framing": fr, **rec_extra}

VERIFY_MODEL = "claude-haiku-5-5"   # Haiku-only verification (Sonnet confirm pass removed for cost)
def llm_check(n, prefix, geo, model=VERIFY_MODEL):
    p = LLM_PROMPT.format(sheet=os.path.abspath(f"ortho/{prefix}_sheet.png"), photo=os.path.abspath(f"refs/{n}.jpg"), hint=get_spec(n)[0],
                          geo="; ".join(geo["issues"]) or "none")
    out = subprocess.run(["claude", "-p", "--model", model, p, "--allowedTools", "Read"], capture_output=True, text=True, timeout=300).stdout
    m = re.search(r"\{.*\}", out, re.S)
    try: return json.loads(m.group(0))
    except Exception: return {"pass": False, "bad_views": [], "issues": ["unparseable LLM reply"], "raw": out[-500:]}

def parts_extra(n, parts_prompt=None):
    """parts-list + detailed notes for the sheet prompt; empty for organic subjects or when no list exists."""
    if parts_prompt is not None: return ("\n" + parts_prompt) if parts_prompt else ""
    try:
        import parts_list; block = parts_list.prompt_for(n)
    except Exception: block = ""
    return ("\n" + block) if block else ""

def gen(n, tag, extra, parts_prompt=None):
    hint, spec = get_spec(n)
    # --no-parts: we already inlined the auto-loaded block into --extra, so ortho_gen must not append it a second time
    r = subprocess.run([sys.executable, "ortho_gen.py", n, hint, "--tag", tag, "--with-photo", "--no-parts",
                        "--extra", f"{COM} {spec}{extra}{parts_extra(n, parts_prompt)}"], capture_output=True, text=True)
    if r.returncode: raise SystemExit(r.stderr[-800:])
    for v in VIEWS: ortho_clean.clean(f"ortho/{n}{tag}_{v}.png")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--tries", type=int, default=3); ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--tag-base", default="_v", help="sheet tag prefix: _v -> _v1, _v2 ...; e.g. _a for a fresh albedo series that keeps the old sheets")
    a = ap.parse_args(); n = a.name
    attempts, extra = [], ""
    if a.start > 1:   # continue an earlier run: keep its attempts, feed the last attempt's fixes into the next sheet
        attempts = json.load(open(f"out/{n}_verify.json"))["attempts"]; last = attempts[-1]
        fixes = last["geo"]["issues"] + last["llm"].get("issues", [])
        extra = " FIX THESE PROBLEMS FOUND IN THE PREVIOUS ATTEMPT: " + " ".join(f"({i+1}) {f}." for i, f in enumerate(fixes[:8]))
    for k in range(a.start, a.start + a.tries):
        tag = f"{a.tag_base}{k}"; gen(n, tag, extra); prefix = n + tag
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
    os.makedirs("art/final/meta", exist_ok=True)   # small checked-in copy: later stages need the chosen sheet even when out/ is gone
    json.dump({"chosen": best["tag"], "views_used": keep, "views_dropped": res["views_dropped"]}, open(f"art/final/meta/{n}_views.json", "w"), indent=1)
    print(n, "chosen", best["tag"], "views", keep, "sheets", len(attempts))
