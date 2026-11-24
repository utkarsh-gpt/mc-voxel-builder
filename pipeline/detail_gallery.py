"""Before/after strip for the detail work (DETAIL_DISCOVERY.md): textured Minecraft renders of two mc_blocks models + metrics.
usage: python detail_gallery.py OUT.png "label A" A.json "label B" B.json [...]   (any number of label/model pairs; one row each)"""
import sys, json
from PIL import Image, ImageDraw
import mc_render, detail_metrics
LIGHT = (-0.25, 0.8, 0.55); VIEWS = [("3/4", 35, 25), ("side", 90, 8), ("front", 0, 8), ("back 3/4", 215, 25)]
S = 330
out, pairs = sys.argv[1], list(zip(sys.argv[2::2], sys.argv[3::2]))
G = Image.new("RGB", (10 + len(VIEWS)*(S+10), len(pairs)*(S+46) + 10), "white"); dr = ImageDraw.Draw(G)
for i, (lab, path) in enumerate(pairs):
    d = json.load(open(path)); m = detail_metrics.metrics(detail_metrics.cells_of(d)); y = 10 + i*(S+46)
    dr.text((10, y), f"{lab}  |  {m['size'][0]}x{m['size'][1]}x{m['size'][2]}, {m['blocks']} blocks, {m['blockstates']} states | partial {m['pct_surface_nonfull']}% "
                     f"| upside-down stairs {m['pct_upside_down_stairs']}% | overhang {m['pct_overhang']}% | vocab {','.join(m['detail_vocab']) or '-'} | detail score {m['detail_score']}", fill="black")
    for j, (vn, a, e) in enumerate(VIEWS):
        im, _ = mc_render.render(d, a, e, 2*S, light=LIGHT); im.thumbnail((S, S)); x = 10 + j*(S+10)
        G.paste(im, (x + (S-im.width)//2, y + 16 + (S-im.height)//2)); dr.text((x, y + S + 22), vn, fill="gray")
G.save(out); print(out)
