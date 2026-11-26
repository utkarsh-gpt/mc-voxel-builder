# Colour vs ortho: score, brown-block diagnosis, prototype (house)

## What already scores shape vs the ortho (nothing scored colour vs the ortho before this)
| tool | measures | views | metric | house now |
|---|---|---|---|---|
| `ortho_verify.geo_checks` | the sheet itself (before any build): panel sizes agree, back = mirrored front | F/R/B/top | px ratio > 1.12/1.15, mirror IoU < 0.75 | mirror IoU 0.856; flags top (width 362 vs 401/438 px) |
| `shape_compare.py` | build silhouette vs drawing, bbox-normalised | front, right, top | IoU + aspect error | front 0.772, right 0.487, top 0.835, mean 0.698; aspect err 3.6/17.1/12.1 % |
| `feature_detect.align` (carve mask) | the same silhouette with the carve mask | F/R/B | IoU | front 0.828, right 0.780, back 0.923 |
| `detail_metrics.py` | geometry vocabulary, not vs ortho (vs Little Hagia target band) | - | % non-full, overhang, hollowness | non-full 48 %, overhang 13.4 %, hollowness 35, detail 74.6 |
| `scorer.py` / `mc_score.py` | colour vs the PHOTO (one camera) | photo view | pixel dE, palette dE, hist | see colour_score `photo` |

Caveat: `shape_compare` masks the sheet with `gray < 235`, which drops the pale siding, so house right reads 0.487 vs 0.780
with the carve mask.

## colour_score.py (new, free, scripts only)
`python colour_score.py NAME [--model PATH] [--label L] [--no-photo]` -> `out/colour/NAME_L.json`, per-view tiles, `_sheet.png`.
Alignment = feature_detect (first hit per view, bbox + mirror by IoU, 8 px per block). Per block cell of the drawing:
* drawing colour = median Lab of the drawing's pixels in that cell (mask >= 0.5)
* build "as seen" = real-texture render (mc_render, lit from the camera) resampled onto the drawing, per-cell median
  (partial blocks show what is behind them); `*_block` = one dataset colour per block
* `de_mean/median/p90` = CIEDE2000 over cells both cover; `palette_emd` = EMD between 6 k-means clusters (Lab, linprog);
  `outlier_pct` = visible cells whose dE to every drawing cell in the 3x3 neighbourhood is > 20 (a colour that does not
  exist nearby = "random block"); outliers are blamed to block id and material
* summary = mean over front / right / back (left uses the mirrored right drawing and is shown but not averaged)
* `photo` = scorer.view_metrics at the fitted camera (pixel dE, palette dE, histogram intersection)
Tiles: drawing | build as seen (magenta = outlier) | dE map (green 0 .. red 40).

## Where the brown blocks come from (house, front/right/back visible cells; `out/colour/house_stage_trace.json`)
| stage | median dE | % cells dE > 20 | dark brown on light drawing |
|---|---|---|---|
| 1 ortho_paint (48 grid) | 3.3 | 7.8 | 3.1 % |
| 2 tone_to_ref | 5.0 | 8.9 | 3.0 % |
| 3 shape_fit transfer + 32-colour k-means | 13.0 | 33.6 | 4.9 % |
| 4 palette_generic zoning + ramps | 10.9 | 32.8 | **9.0 %** |
| 5 mc_map (no features) | 10.5 | 28.3 | 6.3 % |
| 6 mc_map + features | 13.6 | 32.2 | 12.8 % |
* Painting is fine; colour fidelity is lost when the 48-grid paint is moved onto the block grid and quantised (stage 3).
* The brown specks are made by zoning (stage 4): `WT=[0.3,1.2,1.2]` weighs lightness at 0.3, and roof (#7c5040) vs trim
  (#4a2c22) differ mostly in L, so mid-brown roof cells and shaded siding go to trim_brown. Of 119 visible trim_brown
  cells only 19 are trim in the ortho; 75 were moved there by zoning, 25 were already dark after stage 3.
* mc_map adds scattered blocks: accent dither (mud_bricks ~20 % of roof, brown_terracotta ~30 % of trim) and role pools
  (creaking_heart, granite, mangrove pulled in by dE < 12).
* The feature frames add intentional dark trim (12.8 vs 6.3 %); polished_blackstone under siding is the window backing.

## Prototype: colour_proto.py (does not touch the default pipeline; writes out/proto only)
1. target colour per surface block sampled from the aligned orthos on the final grid (best-facing view, top drawing x0.6)
2. bases locked to the ortho: Lloyd on the sampled colours, seeded by the material hints, full-Lab distance, two
   extra grey centres (dark panes -> window material, light foundation/shade -> siding); no height prior
3. surface majority filter + lone trim/roof specks (<= 2) reassigned
4. shade from target L in 8-L steps, clamped to -1..+1 (trim 0), majority-smoothed
5. mc_map with `MC_ACCENTS=0 MC_MAX_BLOCKS=3 MC_ROLE_POOLS=0` (new env knobs; defaults unchanged)

| house (F/R/B mean) | dE mean | dE median | dE p90 | outliers | palette EMD | block dE | block outliers | photo pixel dE |
|---|---|---|---|---|---|---|---|---|
| current default | 18.52 | 13.51 | 42.38 | 7.84 % | 12.86 | 20.99 | 9.91 % | 31.8 |
| mc_map knobs only | 18.51 | 13.48 | 42.38 | 7.99 % | 12.90 | 21.01 | 9.91 % | 31.8 |
| proto colours, default mc_map | 14.31 | 8.25 | 33.61 | 2.97 % | 11.54 | 17.12 | 6.91 % | 31.5 |
| **proto full** | **14.31** | **8.22** | **33.61** | **2.97 %** | **11.56** | **17.12** | **6.91 %** | 31.5 |
Remaining outliers in the prototype are mostly feature frames (dark_oak_shelf/trapdoor, 18 of 24).
Open points: the roof picks granite (closest to the drawing's #825949) instead of bricks; creaking_heart still enters
the roof ramp through ramp_hood (deny-list candidate); the left view (mirrored right drawing) gets worse.
