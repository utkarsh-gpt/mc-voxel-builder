#!/usr/bin/env python3
"""Generate new reference images with fal nano-banana (text-to-image, ~$0.039 each) and prepare them for the pipeline:
refs/NAME.jpg (image), refs/NAME_mask.png (rembg isnet subject mask), refs/NAME_fal_in.png (masked subject on white, 768 square),
refs/NAME_crop.png (loose crop of the ORIGINAL photo around the rembg box, background intact: the ortho-sheet input) and
art/final/meta/NAME_prep.json (boxes, aspects, mask_suspect).
The mask / fal_in stay the colour inputs (scorer.ref_mask, tone_to_ref, auto_cfg); geometry consumers (parts_list, the
ortho sheet) look at the photo / loose crop, because rembg routinely drops pale walls, columns and bases against a bright sky.
usage: python gen_refs.py NAME [NAME...]   (skips the fal call if refs/NAME.jpg exists; --force regenerates)"""
import sys, os, urllib.request, numpy as np, fal_client
from PIL import Image
from scipy import ndimage
STYLE = (" Photorealistic, natural daylight from the upper left, soft shadows. The whole subject is fully visible, centred, seen from a 3/4 front view "
         "slightly from above, isolated on a plain seamless light-grey studio background with nothing else in the frame: no people, no text, no frame, no sky, no horizon.")
PROMPTS = {
 "cathedral": "A Gothic cathedral built of warm honey-coloured limestone and sandstone: two tall square west towers each topped by a slender pointed stone spire, "
   "a large round rose window of stained glass between the towers above three pointed-arch portals, a long nave with a steep pitched dark grey slate roof, "
   "flying buttresses and pinnacles along the side, tall pointed-arch windows. Shown as a complete free-standing building model on a thin flat stone plinth.",
 "landscape": "A dramatic coastal headland landscape section shown as an isolated terrain diorama block: tall layered grey and ochre sea cliffs topped with green grass, "
   "a big natural stone sea arch standing out in the water at one end, a white waterfall pouring from a stream on the cliff top down the cliff face into a turquoise sea pool "
   "with white surf, and a small sandy beach. Wide and large, the terrain block is about twice as wide as it is tall, with straight cut-away soil and rock sides.",
 "turtle": "A large ancient sea turtle swimming, its domed olive-brown shell with clear hexagonal scute plates encrusted with patches of orange and pink coral, "
   "purple sea fans, barnacles and bright green algae; wrinkled grey-green scaly head and long front flippers spread wide, short back flippers. "
   "A single complete animal, no water, no seabed."}
DIL = {"left": 0.25, "right": 0.25, "top": 0.25, "bottom": 0.35}   # loose-crop dilation of the rembg box (fraction of box size)

def photo_path(n):
    for ext in (".jpg", ".png", ".jpeg"):
        if os.path.exists(f"refs/{n}{ext}"): return f"refs/{n}{ext}"
    raise SystemExit(f"no reference photo refs/{n}.jpg")

def _bbox(m):
    ys, xs = np.nonzero(m)
    return (int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1) if len(ys) else None

def loose_crop(n, m=None, raw=None, im=None):
    """refs/N_crop.png: the original photo cropped to the rembg box dilated +25% left/right/top and +35% bottom (clamped to
    the image; the background is kept, nothing painted white) so a pale column or the base rembg dropped is still in frame.
    mask_suspect: the mask touches the image border, or a looser threshold on rembg's soft mask (raw > 30 vs > 127)
    grows the box or the area a lot (rembg was unsure about a big region). Works from refs/N_mask.png when called alone ($0)."""
    import json
    im = im or Image.open(photo_path(n)).convert("RGB")
    if m is None: m = np.asarray(Image.open(f"refs/{n}_mask.png").convert("L")) > 127
    H, W = m.shape; bb = _bbox(m); why = []
    if bb is None: bb = (0, H, 0, W); why.append("empty rembg mask (whole photo used)")
    y0, y1, x0, x1 = bb; bh, bw = y1 - y0, x1 - x0
    cy0 = max(0, int(round(y0 - DIL["top"]*bh))); cy1 = min(H, int(round(y1 + DIL["bottom"]*bh)))
    cx0 = max(0, int(round(x0 - DIL["left"]*bw))); cx1 = min(W, int(round(x1 + DIL["right"]*bw)))
    im.crop((cx0, cy0, cx1, cy1)).save(f"refs/{n}_crop.png")
    if y0 <= 2 or x0 <= 2 or x1 >= W - 2 or y1 >= H - 2: why.append("mask touches the image border")
    if raw is not None:
        loose = raw > 30
        if loose.any():
            ly0, ly1, lx0, lx1 = _bbox(loose); grow = ((ly1 - ly0)*(lx1 - lx0)) / max(bh*bw, 1)
            area = loose.sum() / max(m.sum(), 1)
            if grow > 1.15: why.append(f"loose threshold grows the box x{grow:.2f}")
            if area > 1.25: why.append(f"loose threshold grows the mask area x{area:.2f}")
    meta = {"image_wh": [W, H], "rembg_box_xyxy": [x0, y0, x1, y1], "crop_box_xyxy": [cx0, cy0, cx1, cy1],
            "rembg_aspect_hw": round(bh / bw, 3), "crop_aspect_hw": round((cy1 - cy0) / (cx1 - cx0), 3),
            "crop_area_frac": round((cy1 - cy0)*(cx1 - cx0) / (H*W), 3), "mask_cover": round(float(m.mean()), 3),
            "mask_suspect": bool(why), "mask_suspect_why": why, "dilation": DIL}
    os.makedirs("art/final/meta", exist_ok=True); json.dump(meta, open(f"art/final/meta/{n}_prep.json", "w"), indent=1)
    return meta

def prep(n):
    from rembg import remove, new_session
    im = Image.open(photo_path(n)).convert("RGB")
    raw = np.asarray(remove(im, session=new_session("isnet-general-use"), only_mask=True))
    m = raw > 127
    if not m.any(): m = np.ones_like(m)          # rembg found nothing: keep the whole photo rather than crash
    m = ndimage.binary_fill_holes(ndimage.binary_opening(m, iterations=2)); lab, k = ndimage.label(m)
    if k: sz = np.bincount(lab.ravel()); sz[0] = 0; m = sz[lab] >= 0.05*sz.max()
    Image.fromarray((m*255).astype(np.uint8)).save(f"refs/{n}_mask.png")
    a = np.asarray(im).copy(); a[~m] = 255; ys, xs = np.nonzero(m); a = a[ys.min():ys.max()+1, xs.min():xs.max()+1]
    s = int(round(max(a.shape[:2]) / 0.70)); c = Image.new("RGB", (s, s), "white"); c.paste(Image.fromarray(a), ((s-a.shape[1])//2, (s-a.shape[0])//2))  # long axis fills ~70% (was 91%)
    c.resize((768, 768), Image.LANCZOS).save(f"refs/{n}_fal_in.png")
    meta = loose_crop(n, m, raw, im); print(n, "mask cover", meta["mask_cover"], "crop", meta["crop_box_xyxy"], "suspect", meta["mask_suspect_why"] or False)
if __name__ == "__main__":
    for n in [x for x in sys.argv[1:] if not x.startswith("--")]:
        if "--force" in sys.argv or not os.path.exists(f"refs/{n}.jpg"):
            res = fal_client.subscribe("fal-ai/nano-banana", arguments={"prompt": PROMPTS[n] + STYLE, "num_images": 1, "output_format": "jpeg", "aspect_ratio": "4:3"})
            urllib.request.urlretrieve(res["images"][0]["url"], f"refs/{n}.jpg"); print(n, "generated", Image.open(f"refs/{n}.jpg").size)
        prep(n)
