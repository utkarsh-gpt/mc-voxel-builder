#!/usr/bin/env python3
"""Generate an orthographic view sheet from a reference photo with fal nano-banana/edit, then split it.
usage: python ortho_gen.py NAME ["subject hint"] [--model fal-ai/nano-banana/edit] [--seed N]
The layout (rows, cols, canvas aspect, panel order) is chosen from the subject aspect and saved in ortho/N_TAG_sheet.json."""
import argparse, os, urllib.request, json
from PIL import Image
import numpy as np
from scipy import ndimage

VIEWS = ("front", "right", "back", "top")

def cutout_aspect(n):
    """height/width of the subject after a 3px morphological opening (a thin finial doesn't distort aspect)."""
    m = None
    for p in (f"refs/{n}_mask.png", f"refs/{n}_fal_in.png"):
        if not os.path.exists(p): continue
        im = Image.open(p); a = np.asarray(im)
        if a.ndim == 3:
            m = (a.min(-1) < 250) if a.shape[-1] >= 3 else a[..., 0] > 127
            if a.shape[-1] == 4: m = a[..., 3] > 127
        else:
            m = a > 127
        break
    if m is None: return 1.0
    m = ndimage.binary_opening(m, np.ones((3, 3)))
    ys, xs = np.nonzero(m)
    if len(ys) < 4: return 1.0
    return float(ys.max() - ys.min() + 1) / float(xs.max() - xs.min() + 1)

FAL_ASPECTS = {"21:9": 21/9, "16:9": 16/9, "3:2": 3/2, "4:3": 4/3, "5:4": 5/4, "1:1": 1.0, "4:5": 4/5, "3:4": 3/4, "2:3": 2/3, "9:16": 9/16}
# (layout_name, rows, cols, canvas aspect): every sheet layout we can ask nano-banana for
LAYOUTS = [("grid", 2, 2, "1:1"), ("row", 1, 4, "16:9"), ("row", 1, 4, "4:3"), ("row", 1, 4, "1:1"),
           ("column", 4, 1, "9:16"), ("column", 4, 1, "3:4"), ("column", 4, 1, "1:1")]
MARGIN = 1.25          # panel must be >= 1.25x the subject's aspect along its long axis (10% margin each side + slack)

def panel_hw(rows, cols, canvas):
    """panel height/width for a canvas aspect W:H"""
    return (1.0 / FAL_ASPECTS[canvas]) * cols / rows

TALL, WIDE = 1.8, 0.5   # a_est above TALL -> a 1x4 row, below WIDE -> a 4x1 column, else the 2x2 grid (top plan gets a real panel)

def choose_layout(a):
    """layout + fal canvas for a subject of height:width `a` (already biased taller by estimate_aspect).
    Rows / columns only for very tall / wide subjects; among their canvases pick the one giving the largest subject on a
    fixed-area canvas while the panel still holds the subject with MARGIN along its long axis (16:9 rows only give 2.25:1
    panels, so a 3:1 tower gets a 4:3 or 1:1 canvas); if none fits, the panel that comes closest.
    -> {"layout_name", "rows", "cols", "canvas_aspect", "panel_hw", "order"}"""
    import math
    name = "row" if a > TALL else "column" if a < WIDE else "grid"
    best = closest = None
    for nm, r, c, ca in LAYOUTS:
        if nm != name: continue
        p = panel_hw(r, c, ca); W = FAL_ASPECTS[ca] ** 0.5; pw, ph = W / c, (1 / W) / r
        h = min(0.8 * ph, 0.8 * pw * a); w = h / a                  # subject fitted with a 10% margin per side
        need = a * MARGIN if name == "row" else a / MARGIN if name == "column" else None
        fits = need is None or (p >= need if name == "row" else p <= need)
        rec = {"layout_name": nm, "rows": r, "cols": c, "canvas_aspect": ca, "panel_hw": round(p, 3), "order": list(VIEWS)}
        if fits and (best is None or h * w > best[0] + 1e-12): best = (h * w, rec)
        gap = abs(math.log(p / need)) if need else 0.0
        if closest is None or gap < closest[0]: closest = (gap, rec)
    return (best or closest)[1]

def sheet_layout(a):
    """legacy name -> layout name only"""
    return choose_layout(a)["layout_name"]

def layout_spec(layout_name, canvas=None):
    """spec dict for a legacy layout name (grid 1:1, row 16:9, column 9:16 unless `canvas` given)"""
    r, c = {"grid": (2, 2), "row": (1, 4), "column": (4, 1)}[layout_name]
    ca = canvas or {"grid": "1:1", "row": "16:9", "column": "9:16"}[layout_name]
    return {"layout_name": layout_name, "rows": r, "cols": c, "canvas_aspect": ca, "panel_hw": round(panel_hw(r, c, ca), 3), "order": list(VIEWS)}

def as_spec(layout):
    return layout if isinstance(layout, dict) else layout_spec(layout)

def layout_of_image(im):
    W, H = im.size
    if W >= int(H * 1.4): return "row"
    if H >= int(W * 1.4): return "column"
    return "grid"

def sheet_json_path(sheet_png):
    return sheet_png[:-4] + ".json" if sheet_png.endswith(".png") else sheet_png + ".json"

def save_sheet_json(sheet_png, layout, **extra):
    """persist the layout next to the sheet (ortho/N_TAG_sheet.json) so split / edit never guess it from the image shape"""
    d = dict(as_spec(layout)); d.update(extra)
    if os.path.exists(sheet_png): d["image_wh"] = list(Image.open(sheet_png).size)
    json.dump(d, open(sheet_json_path(sheet_png), "w"), indent=1); return d

def load_sheet_json(sheet_png):
    p = sheet_json_path(sheet_png)
    return json.load(open(p)) if os.path.exists(p) else None

def layout_for_sheet(sheet_png, im=None):
    """the sheet's persisted layout (_sheet.json), else inferred from the image aspect (legacy sheets)"""
    d = load_sheet_json(sheet_png) if isinstance(sheet_png, str) else None
    im = im or Image.open(sheet_png)
    if d and (not d.get("image_wh") or list(im.size) == list(d["image_wh"])): return d    # a hand-replaced PNG falls back to inference
    W, H = im.size; return layout_spec(layout_of_image(im), min(FAL_ASPECTS, key=lambda k: abs(FAL_ASPECTS[k] - W / H)))

def layout_aspect_ratio(layout):
    return as_spec(layout)["canvas_aspect"]

def panel_boxes(W, H, layout):
    sp = as_spec(layout); r, c = sp["rows"], sp["cols"]; order = sp.get("order") or list(VIEWS)
    return {k: ((i % c) * W // c, (i // c) * H // r, (i % c + 1) * W // c, (i // c + 1) * H // r) for i, k in enumerate(order)}

def split_sheet(src, dst_prefix=None, layout=None):
    """Crop the four ortho panels from a sheet. Layout: argument, else the sheet's _sheet.json, else inferred from its aspect."""
    im = Image.open(src).convert("RGB") if isinstance(src, str) else src.convert("RGB")
    W, H = im.size
    if layout is None: layout = layout_for_sheet(src, im) if isinstance(src, str) else layout_of_image(im)
    if dst_prefix is None:
        if isinstance(src, str) and src.endswith("_sheet.png"):
            dst_prefix = src[:-len("_sheet.png")]
        else:
            raise ValueError("split_sheet needs dst_prefix")
    paths = {}
    for k, box in panel_boxes(W, H, layout).items():
        path = f"{dst_prefix}_{k}.png"; im.crop(box).save(path); paths[k] = path
    return as_spec(layout)["layout_name"], paths

def crop_aspect(n):
    """height/width of the loose photo crop (refs/N_crop.png); None if missing, or if the crop was clamped at the photo's
    left/right edge (then its width is short and the aspect inflated; a top/bottom clamp only lowers it, harmless in max())"""
    p = f"refs/{n}_crop.png"
    if not os.path.exists(p): return None
    pj = f"art/final/meta/{n}_prep.json"
    if os.path.exists(pj):
        m = json.load(open(pj)); x0, _, x1, _ = m["crop_box_xyxy"]
        if x0 <= 0 or x1 >= m["image_wh"][0]: return None
    W, H = Image.open(p).size; return H / W

def estimate_aspect(n):
    """layout aspect: max(rembg box aspect, loose-crop aspect) * 1.15, biased taller so panels never crop the subject"""
    a = cutout_aspect(n); c = crop_aspect(n)
    return max(a, c or 0.0) * 1.15

def ensure_crop(n):
    """refs/N_crop.png from the existing refs/N_mask.png when an older prep did not write it ($0, no rembg run)"""
    if os.path.exists(f"refs/{n}_crop.png") or not os.path.exists(f"refs/{n}_mask.png"): return
    import gen_refs; gen_refs.loose_crop(n)

def input_images(n, with_photo=None):
    """sheet inputs: the loose crop of the original photo (background intact) first, and the full photo as image 2 when
    the crop is a small part of it (with_photo=None: crop area < 60% of the photo). Falls back to the cut-out."""
    ensure_crop(n)
    imgs = [f"refs/{n}_crop.png"] if os.path.exists(f"refs/{n}_crop.png") else [f"refs/{n}_fal_in.png"]
    photo = next((f"refs/{n}{e}" for e in (".jpg", ".png", ".jpeg") if os.path.exists(f"refs/{n}{e}")), None)
    if with_photo is None and photo and imgs[0].endswith("_crop.png"):
        W, H = Image.open(photo).size; cw, ch = Image.open(imgs[0]).size; with_photo = (cw*ch) / (W*H) < 0.60
    if with_photo and photo: imgs.append(photo)
    return imgs

ISOLATE = ("Draw ONLY the main building from the photo: isolate it completely, including its full height down to where it meets the "
           "ground (its foundation, plinth or the rock it is built on) and every tower, turret, minaret, column and wing on both sides, "
           "even pale or white parts against a bright sky. Omit the sky, trees, neighbouring buildings and loose surrounding terrain.")

def framing_line(a):
    return (f"CRITICAL FRAMING: the subject's height:width \u2248 {a:.1f}:1. "
            f"Leave at least 10% margin on every side of every panel. Never crop or squash the subject.")

def _canvas_word(sp):
    ca = sp["canvas_aspect"]; return "square" if ca == "1:1" else ca

def layout_block(layout):
    sp = as_spec(layout); r, c = sp["rows"], sp["cols"]; cw = _canvas_word(sp)
    if r == 1:
        return (f"Layout: one {cw} image split into a 1x{c} ROW of four equal tall PORTRAIT panels (each about {sp['panel_hw']:.1f}x as tall as wide), pure white background, no grid lines, no text, no labels.\n"
                "- Panel 1 (far left): FRONT elevation (the side facing the camera in the photo), viewed straight on.\n"
                "- Panel 2: RIGHT SIDE elevation (the object's right side, viewed straight on from the right).\n"
                "- Panel 3: BACK elevation, viewed straight on from behind.\n"
                "- Panel 4 (far right): TOP plan view, looking straight down, with the front of the object pointing to the bottom of the panel.")
    if c == 1:
        return (f"Layout: one {cw} image split into a {r}x1 COLUMN of four equal wide LANDSCAPE panels, pure white background, no grid lines, no text, no labels.\n"
                "- Panel 1 (top): FRONT elevation (the side facing the camera in the photo), viewed straight on.\n"
                "- Panel 2: RIGHT SIDE elevation (the object's right side, viewed straight on from the right).\n"
                "- Panel 3: BACK elevation, viewed straight on from behind.\n"
                "- Panel 4 (bottom): TOP plan view, looking straight down, with the front of the object pointing to the bottom of the panel.")
    return (f"Layout: one {cw} image split into a 2x2 grid of four equal panels, pure white background, no grid lines, no text, no labels.\n"
            "- Top-left panel: FRONT elevation (the side facing the camera in the photo), viewed straight on.\n"
            "- Top-right panel: RIGHT SIDE elevation (the object's right side, viewed straight on from the right).\n"
            "- Bottom-left panel: BACK elevation, viewed straight on from behind.\n"
            "- Bottom-right panel: TOP plan view, looking straight down, with the front of the object pointing to the bottom of the panel.")

def layout_words(layout):
    """short description used by the deshade edit prompt: '1x4 row (front, right side, back, top plan from left to right)'"""
    sp = as_spec(layout); r, c = sp["rows"], sp["cols"]
    if r == 1: return f"1x{c} row of portrait panels (front, right side, back, top plan from left to right)"
    if c == 1: return f"{r}x1 column of landscape panels (front, right side, back, top plan from top to bottom)"
    return "2x2 grid (front top-left, right side top-right, back bottom-left, top plan bottom-right)"

def edit_prompt(layout):
    """deshade edit prompt built from the sheet's real layout (was hardcoded to 2x2, fighting 1x4 rows)"""
    w = layout_words(layout); sp = as_spec(layout); lay = f"{sp['rows']}x{sp['cols']}"
    return (f"This image is an orthographic reference sheet laid out as a {w}. Repaint it as FLAT ALBEDO colour: remove every "
            "shadow, shading gradient, ambient occlusion, darkened underside, darkened recess and directional lighting so that each material has "
            "one uniform colour and lightness in all four panels (the roof in the top plan as bright as in the front view). Keep EVERYTHING else "
            f"exactly: the same {lay} layout, panel positions, scale, outlines, shapes, proportions, number of parts, openings, windows and genuinely "
            "dark materials. Open see-through arches stay filled with the white background. Pure white background, no text, labels or frames.")

RULES = """Rules: true orthographic projection with no perspective and no foreshortening. Exactly the same scale in all four panels.
In the three elevations the base sits on the same horizontal line and the top is at the same height. Each object is centred in its panel with a small margin and fully visible.
Show only the object: no ground, sky, shadows, people or background. Colours match the photo's materials.
LIGHTING RULE: draw flat ALBEDO colour only, as if the object were lit evenly from every direction: no cast shadows (none under eaves, roof overhangs, porches, sills or dormers), no ambient occlusion or darkened corners and crevices, no gradients, no highlights and NO directional lighting. One material has exactly the same colour on every face and in every panel: the roof in the TOP plan is as bright as the roof in the FRONT view, and a wall under an overhang is the same colour as the rest of that wall. Keep genuinely dark materials (dark trim, glass, soot, stains, dark wood) and thin outlines as they are.
Keep every thin part (sails, legs, branches, foliage clumps) with the same proportions as in the photo.
The four views must describe ONE consistent 3D object: widths in the front view equal widths in the top view, depths in the right view equal depths in the top view.
The TOP view is a true plan seen from directly overhead, not tilted: anything lying in a vertical plane (such as windmill sails) appears as a thin straight line.
The BACK panel is always a straight-on rear ELEVATION (same scale and horizon as the front), NEVER a second top plan or a copy of the top-right panel.
No frames, borders, captions or labels anywhere."""

def make_prompt(hint, extra="", layout="grid", aspect=1.0, isolate=False):
    frame = framing_line(aspect); iso = ("\n" + ISOLATE) if isolate else ""
    return f"{frame}\nUsing the {hint} in this photo, draw a clean technical ORTHOGRAPHIC reference sheet of it, like a 3D modeller's blueprint.{iso}\n{layout_block(layout)}\n{RULES}{extra}\n{frame}"

PROMPT = make_prompt("{hint}", "{extra}", "grid", 1.0)

if __name__ == "__main__":
    import fal_client
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("hint", nargs="?", default="object")
    ap.add_argument("--model", default="fal-ai/nano-banana/edit"); ap.add_argument("--seed", type=int); ap.add_argument("--tag", default="")
    ap.add_argument("--extra", default=""); ap.add_argument("--with-photo", action="store_true")
    ap.add_argument("--parts-prompt", default=None)
    ap.add_argument("--no-parts", action="store_true")
    ap.add_argument("--layout", choices=("grid", "row", "column"))
    a = ap.parse_args(); n = a.name
    urls = [fal_client.upload_file(p) for p in input_images(n, True if a.with_photo else None)]
    parts_prompt = a.parts_prompt
    if parts_prompt is None and not a.no_parts:
        try:
            import parts_list; parts_prompt = parts_list.prompt_for(n)
        except Exception: parts_prompt = ""
    extra = ((" " + a.extra) if a.extra else "") + (("\n" + parts_prompt) if parts_prompt else "")
    aspect = estimate_aspect(n); layout = layout_spec(a.layout) if a.layout else choose_layout(aspect)
    prompt = make_prompt(a.hint, extra, layout, aspect, isolate=True)
    args = {"prompt": prompt, "image_urls": urls, "aspect_ratio": layout["canvas_aspect"], "output_format": "png", "num_images": 1}
    if a.seed is not None: args["seed"] = a.seed
    res = fal_client.subscribe(a.model, arguments=args)
    out = f"ortho/{n}{a.tag}_sheet.png"; urllib.request.urlretrieve(res["images"][0]["url"], out)
    save_sheet_json(out, layout, aspect_est=round(aspect, 3))
    split_sheet(out, f"ortho/{n}{a.tag}", layout)
    im = Image.open(out); print(out, im.size, "layout", layout)
