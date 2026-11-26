# v2 run: windmill, cottage, gate (Nov 25, 2026)

Driver: `run_v2.py <subject> [sheets mesh paint shape carve colour map check]`.
Subjects: `windmill_v2` and `cottage_v2` (rerun from the original refs), `gate` (new, user-provided image; the image
and its sheets are kept out of git via `.git/info/exclude` — only the derived block model is committed).

## Method
1. **Sheets** (nano-banana/edit, $0.039 each): ortho prompt + flat-albedo rule made stronger (`STRONG`), 2 sheets,
   then one edit pass (`EDIT`, "remove all shading") on the flattest. Pick by
   `shadow_share + 0.02*gradient_std + 0.01*|top_vs_front_dL|` (shading_check); deshade.py on the chosen sheet.
   Views that fail geo checks are dropped (front is always kept).
2. **Mesh** hyper3d lowpoly ($0.20) -> ortho_paint + tone_to_ref -> **shape_fit** against the chosen sheet.
3. **Carve**: see-through cells in the drawing (<35% drawn pixels inside the ground-closed outline, >=2 tall),
   front and back must agree; removed through the full depth (`carve_axes` in the parts list).
4. **Colour**: palette_generic -> feature_detect (Haiku) -> features filtered by the hand parts list
   (`feature_kinds` with max counts, highest evidence first) -> colour_albedo `--dark-rules` -> noise_measure.
5. **Map**: mc_map albedo mode (creaking_heart banned, role-family tiebreak) -> `.schem` / `.litematic`.
6. **Check**: depth counter (`blueprint.count_openings`) vs the parts list (`art/final/meta/<n>_parts.json`).

## Results
| subject | chosen sheet | shadow_share | grad std | top-front dL | colour dE mean / p90 / EMD | shape IoU F/R/T (mean) | depth count (found / listed) |
|---|---|---|---|---|---|---|---|
| windmill_v2 | `_s2` | 0.221 | 2.63 | n/a (top dropped) | 11.11 / 16.62 / 11.13 (old 14.63 / 26.62 / 12.29) | 0.596/0.389/0.720 (0.568; old 0.611) | open arches 2/2 on all 4 faces; front drum window recess 0/1 |
| cottage_v2 | `_s1e` (edit pass) | 0.233 | 6.32 | -1.1 | 7.70 / 17.12 / 8.22 (old 11.43 / 29.74 / 10.14) | 0.902/0.581/0.800 (0.761; old 0.751) | front recesses 1/2 (door found, window not) |
| gate | `_s1` (override) | 0.350 | 8.86 | -27.9 (top dropped) | 14.17 / 25.33 / 18.48 | 0.803/0.321/0.467 (0.530) | front: open 3/3, recess 13/13; back: open 3/3, recess 12/13 |

All three chosen sheets are still flagged "shaded" by shading_check. The edit pass did not reliably lower the score
(windmill worse, cottage and gate slightly better), and the check over-reads line art / pixel texture as shading, so
the deshade fit was small (kA 0.04-0.09).

Carving removed 56 voxels (windmill, z and x axes) and 40 (gate, z axis); the meshes already had most arches open.

Sizes: windmill 27x37x17, cottage 27x13x15, gate 59x51x29.

## Code changes
- `mc_map.py`: `GREYISH = {"stone", "gate_stone"}` relaxes the hue guard to C*<16 so grey stone stops mapping to
  sandstone (grey vs sandstone: gate 14.17 vs 17.95, windmill 11.11 vs 12.34). New families gate_stone, window_lit.
- `colour_albedo.py`: opt-in `--dark-rules` (window_dark only; free dark grey becomes a pane only where L<40;
  window_dark patches >12 surface blocks go to the nearest non-dark material). Default off; house output unchanged.
- `blueprint.count_openings`: outline closed along the ground, open and recess patches labelled separately
  (cap 35% open / 8% recess). The cathedral numbers in CATHEDRAL_EXPERIMENT.md came from the old counter.
- `palette_generic.py` CFG for the 3 subjects (cottage_v2 door_red hint = red as drawn in the sheet, #7d3426).
- `ortho_verify.SPEC` for the 3 subjects.
- `viewer/scripts/generate_manifest.py`: `NOT_FEATURED` keeps the original windmill/cottage builds featured.

## Spend
fal $1.151 of $1.50 (9 nano-banana = $0.351, 4 meshes = $0.80 incl. one cottage re-roll after the first mesh had a
detached facade). Haiku (feature_detect only) ~$0.10 estimated.

## Honest visual assessment
- Windmill v2: arcade arches are open, stone colour closer, but the sails are fragmented and the tower reads as white
  diorite; shape score is lower than the old build.
- Cottage v2: solid mesh and better scores; door is red again after the hint fix, but the window surround is
  brick/glass, the chimney is dark deepslate (drawn dark), and the old cottage still looks better overall.
- Gate: silhouette, three open arches and lit slit windows hold; the side/top are weak (right IoU 0.32) because the
  sheet's side/top views were wrong and were dropped.

Files: `results/v2/` (check, carve, shape, colour summaries, ledger, before/after images).

## Fix round (Nov 26, 2026) — user feedback: no glass panes; fix windmill sails, cottage chimney/window/roof, gate depth
fal spend this round: **$0** (no new sheets or meshes; separate cap $0.80 via `V2_LEDGER`/`V2_CAP`, unused). Haiku: one
feature_detect run each for cottage_v2 (after the rescale) and gate (after the squash).

**Glass panes banned** (`mc_map.py`): `PANES` is now a list of solid window-fill blocks (concrete, terracotta, wool,
deepslate, blackstone, obsidian, basalt, tuff; blocks.json has no full glass blocks); a sweep converts anything that is still
a pane before output; door transoms/sidelights become the door's own wood. `MC_ALLOW_PANES=1` restores the old behaviour.
`shape_fit.py`, `feature_detect.py` and the colour stages never place panes. Pane count in the three rebuilt models: 0/0/0.
(Older viewer models built before this — house*, hagia*, cathedral — still contain panes until they are rebuilt.)

New `run_v2.py` stages / options (all driven by the hand parts list, `art/final/meta/<n>_parts.json`):
- `sails` (windmill): strip voxels outside the tower's z range (the mesh had sails on front AND back), rebuild ONE sail
  cross in the plane in front of the cap: 4 stocks at +/-52 deg through the hub (12.75, 19.5), 17.5 long, lattice 3 wide on
  the trailing side as thin vslabs, axle block to the cap.
- `squash` (gate): resample the grid along z to 13 blocks (was 28): thin gatehouse wall like the reference.
- `zones`: `force` (windmill sail plane -> sail_white), `roof_not_under_wall` (gate: no roof label under stone),
  full geometric zone paint (cottage: white walls 3 high under the eave and gable ends to y 7, thatch elsewhere, brick
  chimney, ground props dropped).
- `filter_features`: parts listed on some faces only keep detections from those faces (the cottage had a back door);
  `kit_overrides` (cottage window = red mangrove surround; gate windows = lit fill #d99a40); `drop_lone_posts` after map.
- `V2_KEEP_FEATURES=1` reuses the filtered features (no Haiku call).
Other code: `colour_albedo --dark-rules` no longer sends the free light grey to `names[0]` when there is no siding
(it put the mid-grey thatch on the cottage walls); `mc_map`: doors may stand on y 0, `PREFER_SUBJ` (windmill stone ->
andesite: clean grey masonry instead of speckled diorite), lit-window `fill_colour`, cottage thatch STRICT.
Cottage scale 24 -> 30 m (door/window 4-5 blocks, walls 3).

| model | colour dE mean/p90/EMD (prev) | photo px dE (prev) | shape IoU F/R/T mean (prev; old) | depth count | panes |
|---|---|---|---|---|---|
| windmill_v2 | 12.14 / 20.06 / 12.15 (11.11 / 16.62 / 11.13) | 24.8 (28.5) | 0.598/0.448/0.750 = 0.599 (0.568; old 0.611) | open arches 2/2 all faces; drum window 1/1 | 0 |
| cottage_v2 | 10.15 / 25.74 / 9.72 (7.70 / 17.12 / 8.22) | 17.4 (16.7) | 0.866/0.580/0.796 = 0.747 (0.761; old 0.751) | front recesses 3 found / 2 listed | 0 |
| gate | 14.64 / 24.55 / 19.91 (14.17 / 25.33 / 18.48) | 24.3 (24.8) | 0.791/0.277/0.469 = 0.512 (0.530) | open 3/3 front+back; recess 9/13 front, 9/13 back | 0 |

The gate's right/top IoU is measured against the sheet's side/top views, which are wrong (a deep tower), so a thinner,
reference-like gate scores lower there; depth/width is now 13/59 = 0.22 (was 0.47). The cottage's colour score vs the
drawing went down because the zones overrule the drawing projection, but visually the white walls, red door, red framed
window, brick ridge chimney and clean roof match the reference better than the old cottage (see the before/after image).

## SME-14: shade-gradient experiment (shadows/highlights via block ladders)

`pipeline/shade_gradient.py` (opt-in: `python run_v2.py <n> grad`, or `MC_SHADE_GRADIENT=1` during the `map` stage). The default/non-gradient path is unchanged; v2 models are not overwritten.

Hybrid shade scalar per surface voxel, per zone:
- texture term: best-facing L* on the shaded ortho sheets (no deshade) minus the zone median, /12, clipped +-1.5
- geometry term: local openness AO (5^3), sun direction (front/left lit, back/right shaded), sky-facing tops, under-eave lip, under-overhang, ground darkening (y<3), per-zone height ramp
- r = w_tex*tex + w_geo*geo (windmill .5/.5, cottage .25/.75, gate .5/.5), smoothed 3x over same-zone surface, normalised by p95 -> s in [-1,1], |s|^1.4
- band = s*n + 0.55*(Bayer4 - .5); base band keeps the original v2 block; shaped blocks (stairs/slab/wall/trapdoor) keep their shape via the shaped variant of each ladder step
- protected: door, frame, glass, spire, window_*, backing blackstone; interior unchanged; glass panes asserted 0

Outputs: `art/final/{windmill,cottage,gate}_grad_mc_blocks.json`, schematics, `art/final/meta/*_grad_shade_gradient.json`; scores/images in `results/grad/` (gate image kept local only).

| model | dE mean/median/p90 (v2 -> grad) | photo dE | within-zone r(block L, shade s) | blocks |
|---|---|---|---|---|
| windmill | 12.14/11.98/20.06 -> 12.86/11.38/22.47 | 24.8 -> 25.6 | stone .03 -> .89, cap .00 -> .84 | 19 -> 34 |
| cottage | 10.15/5.34/25.74 -> 10.23/5.65/26.22 | 17.4 -> 17.5 | thatch 0 -> .55, wall 0 -> .83 | 14 -> 22 |
| gate | 14.64/13.03/24.55 -> 13.52/11.90/21.74 | 24.3 -> 23.4 | stone 0 -> .91, roof 0 -> .83 | 10 -> 35 |

Spend: fal $0, Haiku $0.

### SME-14 follow-up: photo-aligned shadows + recessed eyebrow arches (cottage)

- `shade_gradient.run(..., photo=, eyebrows=)`, driven by `"grad"` in `art/final/meta/cottage_v2_parts.json`.
- Photo shadows: the real photo (`refs/cottage_v2.jpg`) is aligned to the front voxel projection with piecewise-linear anchors
  (x: roof edges, door centre, window centre; y: ground, eave, ridge, chimney top); each frontmost thatch/wall block gets the
  photo's mean L*, its deviation from the zone's front median is blended 0.55 photo + 0.45 geometry, smoothed lightly (60% raw kept)
  and normalised separately from the sides/back (which stay sheet + 3D geometry).
- Dither is now face-aware (Bayer indexed in the plane of the exposed face) -> no more 2x2 checker patches on the gable.
- `eyebrow_arch.py`: heals the old flush door/window from a clean neighbour column, cuts arched openings, recesses the door and
  window 1 block, lifts the eave profile into a thatch eyebrow hood over each, dark `recess` ring (deepslate_tiles) and `soffit`
  reveals (tuff); window = red frame + cross bars + top-slab sill, 4 recessed panes with a cyan_terracotta / polished_deepslate back
  (no glass, no panes, no black box).
- Sheet score: dE mean 10.23 -> 9.55, outliers 7.35% -> 4.52%, EMD 9.69 -> 9.05. Photo (scorer camera) pixel dE 17.5 -> 18.1.
  Front-aligned photo check: thatch r(block L, photo L) -0.17 -> 0.68, wall 0.01 -> 0.84, front dE 15.35 -> 13.57. Panes 0. Spend $0.

### SME-14 rerun: glass back in window openings only + ortho-only shadow sampling (all three)

- Reference-photo projection is a special case and is OFF (removed from `cottage_v2_parts.json`); all three models shade from the
  shaded ortho sheets + 3D geometry. The cottage keeps the recessed eyebrow arches.
- `MC_GLASS=windows` (mc_map.py, default for the `grad` stage): stained glass panes only in feature-pass window openings
  (`KIT_GLASS` cells); paint-stage dark clusters, door transoms and everything else stay solid, and the safety sweep removes any
  pane outside those cells. Neutral/dark/warm panes only. Lit kits (gate) get an enclosed shroomlight behind yellow glass.
  `MC_MAP_OUT` writes the rerun to `out/glass/<n>_mc_blocks.json`, so the flat v2 models are untouched.
- shade_gradient asserts every pane/glass block carries material `glass`; eyebrow_arch glazes the cottage window (`"glass"` per bay).
- Glass: windmill 28 light_gray_stained_glass_pane (3 drum windows), cottage 4 gray_stained_glass_pane (right window, behind the red
  cross bars), gate 265 yellow_stained_glass_pane (58 window openings) + 218 shroomlight behind; 0 stray.
- Sheet dE mean / photo pixel dE: windmill 13.05 / 25.5, cottage 9.85 / 17.5, gate 13.86 / 24.7. $0 fal, $0 Haiku.
