#!/usr/bin/env python3
"""Generate new reference images with fal nano-banana (text-to-image, ~$0.039 each) and prepare them for the pipeline:
refs/NAME.jpg (image), refs/NAME_mask.png (rembg isnet subject mask), refs/NAME_fal_in.png (masked subject on white, 768 square).
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
def prep(n):
    from rembg import remove, new_session
    im = Image.open(f"refs/{n}.jpg").convert("RGB")
    m = np.asarray(remove(im, session=new_session("isnet-general-use"), only_mask=True)) > 127
    m = ndimage.binary_fill_holes(ndimage.binary_opening(m, iterations=2)); lab, k = ndimage.label(m)
    if k: sz = np.bincount(lab.ravel()); sz[0] = 0; m = sz[lab] >= 0.05*sz.max()
    Image.fromarray((m*255).astype(np.uint8)).save(f"refs/{n}_mask.png")
    a = np.asarray(im).copy(); a[~m] = 255; ys, xs = np.nonzero(m); a = a[ys.min():ys.max()+1, xs.min():xs.max()+1]
    s = int(round(max(a.shape[:2]) / 0.70)); c = Image.new("RGB", (s, s), "white"); c.paste(Image.fromarray(a), ((s-a.shape[1])//2, (s-a.shape[0])//2))  # long axis fills ~70% (was 91%)
    c.resize((768, 768), Image.LANCZOS).save(f"refs/{n}_fal_in.png"); print(n, "mask cover", round(float(m.mean()), 3))
if __name__ == "__main__":
    for n in [x for x in sys.argv[1:] if not x.startswith("--")]:
        if "--force" in sys.argv or not os.path.exists(f"refs/{n}.jpg"):
            res = fal_client.subscribe("fal-ai/nano-banana", arguments={"prompt": PROMPTS[n] + STYLE, "num_images": 1, "output_format": "jpeg", "aspect_ratio": "4:3"})
            urllib.request.urlretrieve(res["images"][0]["url"], f"refs/{n}.jpg"); print(n, "generated", Image.open(f"refs/{n}.jpg").size)
        prep(n)
