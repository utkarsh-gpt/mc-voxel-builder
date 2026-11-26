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
