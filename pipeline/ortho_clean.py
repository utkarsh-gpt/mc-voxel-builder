"""Remove panel frames / ground lines / labels from split ortho views (in place; raw copy kept as *_raw.png).
A 'line' row/col = >40% of it darker than 215 while the rows/cols 5 px either side are mostly background (thin, long, isolated).
If lines exist near all 4 edges (a frame) crop inside it; other isolated lines are whitened."""
import sys, os, shutil, numpy as np
from PIL import Image
def lines(dark, axis):
    f = dark.mean(axis); n = len(f); out = []
    for i in range(n):
        side = [f[j] for j in (i-6, i+6) if 0 <= j < n]
        if f[i] > 0.5 and side and max(side) < f[i] - 0.3: out.append(i)
    return np.array(out, int)
def normalize_bg(a):
    """strip near-black padding bars at the edges, then whiten a uniform non-white page (grey studio background) that touches the border."""
    from scipy import ndimage
    m = a.mean(-1)
    rows = np.nonzero(m.mean(1) > 25)[0]; cols = np.nonzero(m.mean(0) > 25)[0]
    if len(rows) and len(cols): a = a[rows[0]:rows[-1]+1, cols[0]:cols[-1]+1]
    border = np.concatenate([a[:3].reshape(-1, 3), a[-3:].reshape(-1, 3), a[:, :3].reshape(-1, 3), a[:, -3:].reshape(-1, 3)]).astype(float)
    bg = np.median(border, 0)
    if bg.min() < 240 and np.abs(border - bg).max(1).mean() < 12:
        near = np.abs(a.astype(float) - bg).max(-1) < 16
        lab, _ = ndimage.label(near); edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])); edge = edge[edge > 0]
        a = a.copy(); a[np.isin(lab, edge)] = 255
    return a
def clean(path):
    raw = path.replace(".png", "_raw.png")
    if not os.path.exists(raw): shutil.copy(path, raw)
    a = np.asarray(Image.open(raw).convert("RGB")).copy(); H, W = a.shape[:2]
    dark = a.mean(-1) < 215
    rows, cols = lines(dark, 1), lines(dark, 0)
    t, b, l, r = 0, H, 0, W
    tr, br, lc, rc = rows[rows < H*.3], rows[rows > H*.7], cols[cols < W*.3], cols[cols > W*.7]
    if len(tr) and len(br) and len(lc) and len(rc): t, b, l, r = tr.max()+4, br.min()-3, lc.max()+4, rc.min()-3
    a = a[t:b, l:r]
    a = normalize_bg(a)
    dark = a.mean(-1) < 215
    # isolated ground lines are left in place (they close wall outlines); the mask step removes them by opening
    Image.fromarray(a).save(path); return (int(t), int(b), int(l), int(r))
if __name__ == "__main__":
    for n in sys.argv[1:]:
        for v in ("front", "right", "back", "top"): print(n, v, clean(f"ortho/{n}_{v}.png"))
