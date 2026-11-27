#!/usr/bin/env python3
"""Generate an orthographic 2x2 view sheet from a reference photo with fal nano-banana/edit, then split it.
usage: python ortho_gen.py NAME ["subject hint"] [--model fal-ai/nano-banana/edit] [--seed N]"""
import argparse, os, urllib.request, json, fal_client
from PIL import Image
PROMPT = """Using the {hint} in this photo, draw a clean technical ORTHOGRAPHIC reference sheet of it, like a 3D modeller's blueprint.
Layout: one square image split into a 2x2 grid of four equal square panels, pure white background, no grid lines, no text, no labels.
- Top-left panel: FRONT elevation (the side facing the camera in the photo), viewed straight on.
- Top-right panel: RIGHT SIDE elevation (the object's right side, viewed straight on from the right).
- Bottom-left panel: BACK elevation, viewed straight on from behind.
- Bottom-right panel: TOP plan view, looking straight down, with the front of the object pointing to the bottom of the panel.
Rules: true orthographic projection with no perspective and no foreshortening. Exactly the same scale in all four panels.
In the three elevations the base sits on the same horizontal line and the top is at the same height. Each object is centred in its panel with a small margin and fully visible.
Show only the object: no ground, sky, shadows, people or background. Colours match the photo's materials.
LIGHTING RULE: draw flat ALBEDO colour only, as if the object were lit evenly from every direction: no cast shadows (none under eaves, roof overhangs, porches, sills or dormers), no ambient occlusion or darkened corners and crevices, no gradients, no highlights and NO directional lighting. One material has exactly the same colour on every face and in every panel: the roof in the TOP plan is as bright as the roof in the FRONT view, and a wall under an overhang is the same colour as the rest of that wall. Keep genuinely dark materials (dark trim, glass, soot, stains, dark wood) and thin outlines as they are.
Keep every thin part (sails, legs, branches, foliage clumps) with the same proportions as in the photo.
The four views must describe ONE consistent 3D object: widths in the front view equal widths in the top view, depths in the right view equal depths in the top view.
The TOP view is a true plan seen from directly overhead, not tilted: anything lying in a vertical plane (such as windmill sails) appears as a thin straight line.
No frames, borders, captions or labels anywhere.{extra}"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("hint", nargs="?", default="object")
    ap.add_argument("--model", default="fal-ai/nano-banana/edit"); ap.add_argument("--seed", type=int); ap.add_argument("--tag", default="")
    ap.add_argument("--extra", default=""); ap.add_argument("--with-photo", action="store_true")
    ap.add_argument("--parts-prompt", default=None, help="parts-list block to append to the sheet prompt (default: auto-load art/final/meta/<n>_parts.json)")
    ap.add_argument("--no-parts", action="store_true", help="do not auto-load the parts list into the sheet prompt")
    a = ap.parse_args(); n = a.name
    urls = [fal_client.upload_file(f"refs/{n}_fal_in.png")]
    if a.with_photo: urls.append(fal_client.upload_file(f"refs/{n}.jpg"))   # full photo as extra reference
    parts_prompt = a.parts_prompt
    if parts_prompt is None and not a.no_parts:
        try:
            import parts_list; parts_prompt = parts_list.prompt_for(n)
        except Exception: parts_prompt = ""
    extra = ((" " + a.extra) if a.extra else "") + (("\n" + parts_prompt) if parts_prompt else "")
    args = {"prompt": PROMPT.format(hint=a.hint, extra=extra), "image_urls": urls, "aspect_ratio": "1:1", "output_format": "png", "num_images": 1}
    if a.seed is not None: args["seed"] = a.seed
    res = fal_client.subscribe(a.model, arguments=args)
    out = f"ortho/{n}{a.tag}_sheet.png"; urllib.request.urlretrieve(res["images"][0]["url"], out)
    im = Image.open(out).convert("RGB"); W, H = im.size
    for (k, box) in {"front": (0, 0, W//2, H//2), "right": (W//2, 0, W, H//2), "back": (0, H//2, W//2, H), "top": (W//2, H//2, W, H)}.items():
        im.crop(box).save(f"ortho/{n}{a.tag}_{k}.png")
    print(out, im.size)
