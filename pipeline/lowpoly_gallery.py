import json
from PIL import Image, ImageDraw
import vox, run_subject
LIGHT=(-0.25,0.8,0.55)
FINAL={"windmill":"windmill_lowpoly","cottage":"cottage_lowpoly_fbt","bonsai":"bonsai_lowpoly"}
def R(o,c,a,e,s=512): return vox.render(o,c,a,e,s,light=LIGHT)[0]
S=json.load(open("out/verified_lowpoly_scores.json"))
# gallery
Sz = 230; Wd = 6*Sz + 5*10 + 20; Hr = Sz + 50; G = Image.new("RGB", (Wd, Hr*3 + 10), "white"); dr = ImageDraw.Draw(G)
for i, n in enumerate(FINAL):
    k = FINAL[n]; s = S[n]; _, o, c, _ = vox.load(f"art/{k}_half_sub_fine.json", seed=0)
    items = [("reference photo", run_subject.masked_ref(f"refs/{n}.jpg")), (f"verified sheet {s['verify']['chosen']} (used: {'/'.join(s['verify']['views_used'])})", Image.open(f"ortho/{n}{s['verify']['chosen']}_sheet.png")),
             ("front", R(o, c, 0, 10)), ("side", R(o, c, 90, 10)), ("back", R(o, c, 180, 10)), ("3/4", R(o, c, 35, 25))]
    y = i*Hr + 5
    dr.text((10, y), f"{n} - 3D: Hyper3D low-poly (hyper3d/lowpoly/image-to-3d, $0.20) -> ortho colour -> half size {s['grid'][0]}x{s['grid'][1]}x{s['grid'][2]} "
            f"with slabs/vslabs/stairs ({s['pct_sub']}%)   auto {s['auto']:.1f} / judge {s['judge']}/10", fill="black")
    for j, (lab, im) in enumerate(items):
        im = im.convert("RGB"); im.thumbnail((Sz, Sz)); x = 10 + j*(Sz+10)
        G.paste(im, (x + (Sz-im.width)//2, y + 18 + (Sz-im.height)//2)); dr.text((x, y + Sz + 22), lab, fill="gray")
G.save("out/verified_lowpoly_gallery.png")
