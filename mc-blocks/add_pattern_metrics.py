#!/usr/bin/env python3
"""Adds texture-pattern fields to blocks.json / blocks.csv (computed on the side texture, the face that shows most):
  pattern.coherence     structure-tensor orientation coherence 0..1 (1 = all edges parallel = line pattern)
  pattern.orientation   'horizontal' | 'vertical' | 'diagonal' | 'none'  (direction the LINES run)
  pattern.line_period   px between parallel lines (FFT peak across the lines), null if no clear lines
  pattern.scale_px      power-weighted mean wavelength in px (16 px texture) = size of grain/blobs
  pattern.hf_energy     share of luminance variance above 1/4 Nyquist (fine grain)
  pattern.hatch_score   0..1  coherence x contrast x line regularity: how much the block reads like hatched shading
Self-contained: numpy + Pillow."""
import json, csv, os, numpy as np
from PIL import Image
ROOT = os.path.dirname(os.path.abspath(__file__)); TEX = os.path.join(ROOT, "assets/assets/minecraft/textures/block")
def srgb2L(rgb):
    c = rgb/255.0; lin = np.where(c <= 0.04045, c/12.92, ((c+0.055)/1.055)**2.4)
    Y = lin @ np.array([0.2126, 0.7152, 0.0722]); f = np.where(Y > 0.008856, np.cbrt(Y), 7.787*Y + 16/116); return 116*f - 16
def load_L(name):
    p = os.path.join(TEX, name.split("/")[-1] + ".png"); im = Image.open(p).convert("RGBA"); a = np.asarray(im).astype(float)
    w = a.shape[1]; a = a[:w]                                     # first frame of animated strips
    L = srgb2L(a[..., :3]); m = a[..., 3] > 0; return L, m
def metrics(L, m):
    if m.mean() < 0.5: return None
    Lf = np.where(m, L, L[m].mean())
    gx = (np.roll(Lf, -1, 1) - np.roll(Lf, 1, 1))/2; gy = (np.roll(Lf, -1, 0) - np.roll(Lf, 1, 0))/2   # wrap: textures tile
    Jxx, Jyy, Jxy = (gx*gx).sum(), (gy*gy).sum(), (gx*gy).sum(); tr = Jxx + Jyy + 1e-9
    coh = float(np.sqrt((Jxx-Jyy)**2 + 4*Jxy**2)/tr)
    ang = 0.5*np.degrees(np.arctan2(2*Jxy, Jxx-Jyy))               # dominant GRADIENT direction; lines run perpendicular
    if coh < 0.25: ori = "none"
    elif abs(ang) < 22.5 or abs(ang) > 157.5: ori = "vertical"      # gradient along x -> lines run vertically
    elif 67.5 < abs(ang) < 112.5: ori = "horizontal"
    else: ori = "diagonal"
    F = np.abs(np.fft.fft2(Lf - Lf.mean()))**2; n = Lf.shape[0]; fy, fx = np.meshgrid(np.fft.fftfreq(n), np.fft.fftfreq(n), indexing="ij")
    r = np.hypot(fx, fy); tot = F.sum() + 1e-9; hf = float(F[r > 0.125].sum()/tot)
    period, regular = None, 0.0
    if ori in ("horizontal", "vertical"):
        prof = F.sum(1 if ori == "horizontal" else 0)               # energy vs frequency across the lines
        f1 = np.abs(np.fft.fftfreq(n)); k = int(np.argmax(prof[1:n//2])) + 1
        period = round(1/f1[k], 2); regular = float(prof[k]/(prof[1:n//2].sum() + 1e-9))
    ac = np.real(np.fft.ifft2(F)); ac /= ac[0, 0] + 1e-9
    rad = np.array([ac[(np.round(r*n) == k) | (np.round(r*n) == -k)].mean() if k else 1 for k in range(n//2)])
    rr = np.array([[min(i, n-i)**2 + min(j, n-j)**2 for j in range(n)] for i in range(n)])**0.5
    radial = [ac[(rr >= k-0.5) & (rr < k+0.5)].mean() for k in range(n//2)]
    scale = round(float(1/((r*F).sum()/tot + 1e-9)), 2)          # power-weighted mean wavelength (px): size of the grain/blobs
    contrast = float(np.clip(L[m].std()/10, 0, 1))
    hatch = float(np.clip(coh, 0, 1) * contrast * (0.5 + 0.5*min(1, regular*3)) * (1.0 if ori in ("horizontal", "vertical") else 0.6))
    tech = techniques(L, m, Lf, coh, ori, regular, n, F, f_axes=(fx, fy))
    return dict(coherence=round(coh, 3), orientation=ori, techniques=tech, technique=max(tech, key=tech.get), line_period=period, line_regularity=round(regular, 3), scale_px=scale,
                hf_energy=round(hf, 3), hatch_score=round(min(1.0, hatch*1.6), 3))
def techniques(L, m, Lf, coh, ori, regular, n, F, f_axes):
    """Which classic drawing technique the texture can mimic (0..1 each):
    hatching      parallel lines in one direction (orientation coherence x line regularity x contrast)
    cross_hatch   grid / woven: periodic line energy along BOTH axes (bricks, tiles, chiseled), coherence not dominant
    stippling     fine isolated dots: share of pixels that are small (<=2 px) light/dark specks vs a 3x3 median
    scumbling     broken colour / mottled: mid-size blotches (3-24 px components) of off-tone, irregular (low coherence)
    glazing       flat smooth colour: 1 - L* spread
    outline       framed border: contrast between the 1-2 px border ring and the interior, consistent around the edge"""
    from scipy import ndimage as nd
    std = float(L[m].std()); con = float(np.clip(std/10, 0, 1))
    # edge-orientation histogram (strong edges only, wrap-around gradients because textures tile)
    gx = (np.roll(Lf, -1, 1) - np.roll(Lf, 1, 1))/2; gy = (np.roll(Lf, -1, 0) - np.roll(Lf, 1, 0))/2; mag = np.hypot(gx, gy)
    strong = (mag > max(2.5, 0.6*std)) & m; ne = strong.sum() + 1e-9
    hz = float((strong & (np.abs(gy) > 2*np.abs(gx))).sum()/ne)    # edges of horizontal lines
    vt = float((strong & (np.abs(gx) > 2*np.abs(gy))).sum()/ne)    # edges of vertical lines
    dg = max(0.0, 1 - hz - vt); dens = float(np.clip(strong.mean()*3, 0, 1))
    # lines must be long: mean run length of edge pixels along their line direction
    def runs(mask, axis):
        r = mask.astype(int); tot = r.sum(); 
        if tot == 0: return 0.0
        starts = (r & ~np.roll(r, 1, axis)).sum(); return float(tot/max(starts, 1))
    run_h = runs(strong & (np.abs(gy) > 2*np.abs(gx)), 1); run_v = runs(strong & (np.abs(gx) > 2*np.abs(gy)), 0)
    lng = lambda rl: float(np.clip((rl - 1.5)/4, 0, 1))
    hatching = float(np.clip(coh, 0, 1) * con * (0.5 + 0.5*min(1, regular*3)) * (1.0 if ori in ("horizontal", "vertical") else 0.6))
    hatching = min(1.0, hatching*1.6) * (0.6 + 0.4*max(lng(run_h), lng(run_v)))
    cross = float(np.clip(4*hz*vt, 0, 1) * (1 - dg) * con * dens * (0.5 + 0.5*max(lng(run_h), lng(run_v))) * 1.8)
    cross = min(1.0, cross)
    # off-tone blobs vs a smoothed base; area share in small specks (stipple) vs mid blotches (scumble)
    med = nd.median_filter(Lf, 5, mode="wrap"); dev = np.abs(Lf - med); off = (dev > max(4.0, 1.0*std)) & m
    lab_, k = nd.label(off); sizes = np.array(nd.sum(off, lab_, range(1, k+1))) if k else np.array([0.0])
    big = np.abs(nd.gaussian_filter(Lf, 1.2, mode="wrap") - np.median(Lf[m])) > max(3.0, 0.7*std)
    lab2, k2 = nd.label(big & m); s2 = np.array(nd.sum(big, lab2, range(1, k2+1))) if k2 else np.array([0.0])
    area = m.sum() + 1e-9; speck = float(sizes[sizes <= 3].sum()/area); blot = float(s2[(s2 >= 5) & (s2 <= 120)].sum()/area)
    straight = max(hatching, cross)
    stippling = float(np.clip(speck*6, 0, 1) * np.clip(std/6, 0, 1) * (1 - 0.8*straight) * (1 - 0.5*np.clip(blot*2.5, 0, 1)))
    scumbling = float(np.clip(blot*2.5, 0, 1) * np.clip(std/7, 0, 1) * (1 - 0.8*straight) * (1 - 0.3*np.clip(speck*6, 0, 1)))
    glazing = float(np.clip(1 - std/7, 0, 1))
    ring = np.zeros_like(m); ring[:2] = ring[-2:] = True; ring[:, :2] = ring[:, -2:] = True; inner = np.zeros_like(m); inner[3:-3, 3:-3] = True
    if (ring & m).sum() > 20 and (inner & m).sum() > 20:
        dL = abs(float(Lf[ring & m].mean() - Lf[inner & m].mean()))
        sides = [Lf[:2].mean(), Lf[-2:].mean(), Lf[:, :2].mean(), Lf[:, -2:].mean()]; consist = 1 - np.clip(np.std(sides)/(dL + 1e-6), 0, 1)
        outline = float(np.clip(dL/12, 0, 1) * consist)
    else: outline = 0.0
    return {k_: round(v, 3) for k_, v in dict(hatching=hatching, cross_hatching=cross, stippling=stippling, scumbling=scumbling, glazing=glazing, outline=outline).items()}
d = json.load(open(os.path.join(ROOT, "blocks.json"))); rows = {}
for b in d["blocks"]:
    side = b["textures"]["side"][0]; top = b["textures"]["top"][0]
    try: ms = metrics(*load_L(side)); mt = metrics(*load_L(top))
    except FileNotFoundError: ms = mt = None
    b["pattern"] = (ms or {}) | {"top": mt}; rows[b["id"]] = ms or {}
d["meta"].setdefault("notes", []); 
if isinstance(d["meta"]["notes"], list): d["meta"]["notes"].append("pattern.* fields added by add_pattern_metrics.py (side texture; pattern.top = top face)")
json.dump(d, open(os.path.join(ROOT, "blocks.json"), "w"), indent=1)
R = list(csv.DictReader(open(os.path.join(ROOT, "blocks.csv")))); keys = ["coherence", "orientation", "line_period", "scale_px", "hf_energy", "hatch_score", "technique"]
TK = ["hatching", "cross_hatching", "stippling", "scumbling", "glazing", "outline"]
with open(os.path.join(ROOT, "blocks.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(R[0].keys()) + ["pattern_" + k for k in keys] + ["tech_" + k for k in TK]); w.writeheader()
    for r in R: w.writerow(r | {"pattern_" + k: rows.get(r["id"], {}).get(k) for k in keys} | {"tech_" + k: rows.get(r["id"], {}).get("techniques", {}).get(k) for k in TK})
top = sorted(d["blocks"], key=lambda b: -(b["pattern"].get("hatch_score") or 0))
for b in top[:0]: print(b["id"], b["pattern"]["hatch_score"], b["pattern"]["orientation"], b["pattern"]["line_period"], b["overall"]["hex"], b["overall"]["busyness"])
