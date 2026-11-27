#!/usr/bin/env python3
"""Generate an orthographic view sheet from a reference photo with fal nano-banana/edit, then split it.
usage: python ortho_gen.py NAME ["subject hint"] [--model fal-ai/nano-banana/edit] [--seed N]"""
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

def sheet_layout(a):
    if a >= 2.0: return "row"
    if a <= 0.5: return "column"
    return "grid"

def layout_of_image(im):
    W, H = im.size
    if W >= int(H * 1.4): return "row"
    if H >= int(W * 1.4): return "column"
    return "grid"

def layout_aspect_ratio(layout):
    return {"row": "16:9", "column": "9:16", "grid": "1:1"}[layout]

def panel_boxes(W, H, layout):
    if layout == "row":
        return {k: (i * W // 4, 0, (i + 1) * W // 4, H) for i, k in enumerate(VIEWS)}
    if layout == "column":
        return {k: (0, i * H // 4, W, (i + 1) * H // 4) for i, k in enumerate(VIEWS)}
    return {"front": (0, 0, W // 2, H // 2), "right": (W // 2, 0, W, H // 2),
            "back": (0, H // 2, W // 2, H), "top": (W // 2, H // 2, W, H)}

def split_sheet(src, dst_prefix=None, layout=None):
    """Crop the four ortho panels from a sheet. Layout is inferred from the sheet aspect if omitted."""
    im = Image.open(src).convert("RGB") if isinstance(src, str) else src.convert("RGB")
    W, H = im.size
    if layout is None: layout = layout_of_image(im)
    if dst_prefix is None:
        if isinstance(src, str) and src.endswith("_sheet.png"):
            dst_prefix = src[:-len("_sheet.png")]
        else:
            raise ValueError("split_sheet needs dst_prefix")
    paths = {}
    for k, box in panel_boxes(W, H, layout).items():
        path = f"{dst_prefix}_{k}.png"; im.crop(box).save(path); paths[k] = path
    return layout, paths

def framing_line(a):
    return (f"CRITICAL FRAMING: the subject's height:width \u2248 {a:.1f}:1. "
            f"Leave at least 10% margin on every side of every panel. Never crop or squash the subject.")

def layout_block(layout):
    if layout == "row":
        return ("Layout: one 16:9 image split into a 1x4 ROW of four equal PORTRAIT panels, pure white background, no grid lines, no text, no labels.\n"
                "- Panel 1 (far left): FRONT elevation (the side facing the camera in the photo), viewed straight on.\n"
                "- Panel 2: RIGHT SIDE elevation (the object's right side, viewed straight on from the right).\n"
                "- Panel 3: BACK elevation, viewed straight on from behind.\n"
                "- Panel 4 (far right): TOP plan view, looking straight down, with the front of the object pointing to the bottom of the panel.")
    if layout == "column":
        return ("Layout: one 9:16 image split into a 4x1 COLUMN of four equal LANDSCAPE panels, pure white background, no grid lines, no text, no labels.\n"
                "- Panel 1 (top): FRONT elevation (the side facing the camera in the photo), viewed straight on.\n"
                "- Panel 2: RIGHT SIDE elevation (the object's right side, viewed straight on from the right).\n"
                "- Panel 3: BACK elevation, viewed straight on from behind.\n"
                "- Panel 4 (bottom): TOP plan view, looking straight down, with the front of the object pointing to the bottom of the panel.")
    return ("Layout: one square image split into a 2x2 grid of four equal square panels, pure white background, no grid lines, no text, no labels.\n"
            "- Top-left panel: FRONT elevation (the side facing the camera in the photo), viewed straight on.\n"
            "- Top-right panel: RIGHT SIDE elevation (the object's right side, viewed straight on from the right).\n"
            "- Bottom-left panel: BACK elevation, viewed straight on from behind.\n"
            "- Bottom-right panel: TOP plan view, looking straight down, with the front of the object pointing to the bottom of the panel.")

RULES = """Rules: true orthographic projection with no perspective and no foreshortening. Exactly the same scale in all four panels.
In the three elevations the base sits on the same horizontal line and the top is at the same height. Each object is centred in its panel with a small margin and fully visible.
Show only the object: no ground, sky, shadows, people or background. Colours match the photo's materials.
LIGHTING RULE: draw flat ALBEDO colour only, as if the object were lit evenly from every direction: no cast shadows (none under eaves, roof overhangs, porches, sills or dormers), no ambient occlusion or darkened corners and crevices, no gradients, no highlights and NO directional lighting. One material has exactly the same colour on every face and in every panel: the roof in the TOP plan is as bright as the roof in the FRONT view, and a wall under an overhang is the same colour as the rest of that wall. Keep genuinely dark materials (dark trim, glass, soot, stains, dark wood) and thin outlines as they are.
Keep every thin part (sails, legs, branches, foliage clumps) with the same proportions as in the photo.
The four views must describe ONE consistent 3D object: widths in the front view equal widths in the top view, depths in the right view equal depths in the top view.
The TOP view is a true plan seen from directly overhead, not tilted: anything lying in a vertical plane (such as windmill sails) appears as a thin straight line.
No frames, borders, captions or labels anywhere."""

def make_prompt(hint, extra="", layout="grid", aspect=1.0):
    frame = framing_line(aspect)
    return f"{frame}\nUsing the {hint} in this photo, draw a clean technical ORTHOGRAPHIC reference sheet of it, like a 3D modeller's blueprint.\n{layout_block(layout)}\n{RULES}{extra}\n{frame}"

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
    urls = [fal_client.upload_file(f"refs/{n}_fal_in.png")]
    if a.with_photo: urls.append(fal_client.upload_file(f"refs/{n}.jpg"))
    parts_prompt = a.parts_prompt
    if parts_prompt is None and not a.no_parts:
        try:
            import parts_list; parts_prompt = parts_list.prompt_for(n)
        except Exception: parts_prompt = ""
    extra = ((" " + a.extra) if a.extra else "") + (("\n" + parts_prompt) if parts_prompt else "")
    aspect = cutout_aspect(n); layout = a.layout or sheet_layout(aspect)
    prompt = make_prompt(a.hint, extra, layout, aspect)
    args = {"prompt": prompt, "image_urls": urls, "aspect_ratio": layout_aspect_ratio(layout), "output_format": "png", "num_images": 1}
    if a.seed is not None: args["seed"] = a.seed
    res = fal_client.subscribe(a.model, arguments=args)
    out = f"ortho/{n}{a.tag}_sheet.png"; urllib.request.urlretrieve(res["images"][0]["url"], out)
    split_sheet(out, f"ortho/{n}{a.tag}", layout)
    im = Image.open(out); print(out, im.size, "layout", layout)
