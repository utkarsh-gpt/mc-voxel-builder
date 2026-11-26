"""out/features_gallery.png: per subject, the Minecraft build before the feature pass (git HEAD's NAME_mc_blocks.json or
MC_FEATURES=0) and after it, from the 3/4 view and the four sides; out/features_detect.png stacks the detection overlays.
usage: python feature_gallery.py house hagia [--before PATH_PATTERN]  (pattern like out/{n}_mc_blocks_before.json)"""
import json, sys, subprocess
from PIL import Image, ImageDraw
import mc_render
LIGHT = (-0.25, 0.8, 0.55); S = 300
VIEWS = [("3/4", 35, 25), ("front", 0, 10), ("right", 90, 10), ("back", 180, 10), ("left", 270, 10)]
def main(names, before):
    rows = []
    for n in names:
        b = json.loads(open(before.format(n=n)).read()) if before else json.loads(subprocess.run(["git", "show", f"HEAD:pipeline/art/final/{n}_mc_blocks.json"], capture_output=True, text=True, check=True).stdout)
        a = json.load(open(f"art/final/{n}_mc_blocks.json"))
        fl = a["summary"]["detail_pass"].get("features", {})
        rows.append((n, "before (no feature pass) 3/4", b, VIEWS[0]))
        for v in VIEWS: rows.append((n, f"after {v[0]}", a, v))
        rows.append((n, "INFO", fl, None))
    per = 1 + len(VIEWS); G = Image.new("RGB", (10 + per*(S + 10), 40 + len(names)*(S + 60)), "white"); dr = ImageDraw.Draw(G)
    dr.text((10, 8), "Feature pass (feature_detect.py + mc_map.feature_pass): windows/doors/arches as pane+hood+sill kits per repeating row, chimneys, spires", fill="black")
    k = 0
    for i, n in enumerate(names):
        y = 30 + i*(S + 60)
        for j in range(per):
            _, lbl, d, v = rows[k]; k += 1
            im, _ = mc_render.render(d, v[1], v[2], 2*S, light=LIGHT); im.thumbnail((S, S)); x = 10 + j*(S + 10)
            G.paste(im, (x + (S - im.width)//2, y + (S - im.height)//2)); dr.text((x, y + S + 4), f"{n}: {lbl}", fill="gray")
        _, _, fl, _ = rows[k]; k += 1
        dr.text((10, y + S + 20), "feature pass: " + ", ".join(f"{a}={b}" for a, b in fl.items()), fill="black")
    G.save("out/features_gallery.png")
    tiles = [Image.open(f"out/{n}_features_debug.png") for n in names]
    W = max(t.width for t in tiles); T = Image.new("RGB", (W, sum(t.height for t in tiles)), "white"); yy = 0
    for t in tiles: T.paste(t, (0, yy)); yy += t.height
    T.save("out/features_detect.png"); print("out/features_gallery.png out/features_detect.png")
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; bf = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--before=")), None)
    main(args or ["house", "hagia"], bf)
