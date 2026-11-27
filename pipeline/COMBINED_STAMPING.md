# Combined stamping (SME-15)

William Lam's geometry stamping (`stamp_parts.py`, branch `cathedral-experiment`, commit f5a1ee7) carved the cathedral
with hand-placed drawing-pixel landmarks. `stamp_generic.py` keeps his primitives and drops every subject coordinate:
positions come from the generic feature detector and the parts list, and wall planes are measured in the voxels.
`run_combined.py` chains it with our colour mapping and shadow sampling. All of it costs $0: no fal calls and no LLM.

## William's fixes ported from f5a1ee7

| file | fix |
|---|---|
| `orient.py` (new) | `facade_flip`: hyper3d/blueprint meshes put the facade on either end. The tall end (spires and towers, \|z-0.5\| > 0.1) is the facade. Otherwise the right-elevation IoU decides, with a 0.02 margin. Also adds `flip_occ` / `flip_voxel_dict` (180° about y). |
| `shape_fit.py` | `run(..., facade=True)` turns the mesh 180° when `orient.facade_flip` says the facade is on -z. Adds the CLI flag `--no-facade-flip`. |
| `blueprint.py` | `voxels()` applies the same facade check before writing (`d["orientation"]`), and `haiku_check` goes through `llm.ask`. |
| `llm.py` (new) | `llm.ask(prompt, images, model)` uses the claude CLI and falls back to codex (env `LLM` / `LLM_MODEL`). It returns `(text, usd)`. |
| `mc_map.py` | Variant names lost the subject's STRICT / ACCENT_ALL settings (his fix: add `cathedral_stamped`). The general form is `subject_key()`: `X_stamped` / `X_combined` inherit X's STRICT, ACCENT_ALL, PREFER_SUBJ, WARM, CRISP and lip settings. |

Regression checks (Nov 26):
- `orient.facade_flip` returns *keep* for windmill, windmill_v2, cottage, cottage_v2, gate, house, turtle and bonsai, so shape_fit's new default does not turn any existing subject.
- `mc_map gate` (MC_GLASS=windows) is byte-identical to the b116429 glass map.
- `windmill_v2` differs only by the lone posts that `stage_map` drops afterwards.
- `shade_gradient` reproduces `gate_grad` exactly.

## How the pieces connect

```
N_voxels_textured + labels + noise        (from run_v2: sheets -> mesh -> shape_fit -> colour)
        |
   orient.facade_flip ............ verdict logged; --orient-apply turns a raw mesh (features are then re-detected)
        |
   meta/N_features.json .......... cached, else feature_detect.detect(N, llm=False) (image-only, $0)
   meta/N_parts.json ............. optional: built_as overrides, open parts, normalised boxes, "organic".
                                  Written automatically by parts_list.py (steps 1-2 of specs/detailed-parts.md)
                                  from the reference photo, BEFORE the ortho sheet is requested; hand-written
                                  files (windmill_v2, cottage_v2, gate) are left untouched. Accepts both the
                                  legacy list-of-parts schema and the new dict-of-parts blueprint schema.
        |
   organic? ---- yes ------------------------------------------------------------.
        | no                                                                     |
   stamp_generic.stamp(occ, features, parts)                                     |
     window / arched / rose / door -> set_back 1 (rose 2) into the LOCAL wall    |
        plane (median surface of a 2-ring around the opening), one backing block |
        kept; rect / pointed / disc mask. rect.plane moves to the recess back.   |
     arch / arcade -> open, only if the parts list names an open part or the     |
        opposite face shows an arcade: the cut is the OVERLAP of both boxes;     |
        an unconfirmed arcade is left as built                                   |
     parts boxes (normalised [x0,y0,x1,y1] of the view's outline -> face a,b     |
        via the silhouette bbox): proud (buttress / pilaster / trim / hood),     |
        outline = flat (gable / battlement), open, set_back                      |
     spire / chimney protrusions -> mc_map's protrusion builder (unchanged)      |
        |                                                                        |
   N_combined alias files (new cells copy colour + label from the nearest cell) <'
        |
   mc_map N_combined, MC_GLASS=windows -> feature pass builds the frame / door / pane INSIDE the recess (skin()
        searches plane-1..plane+2 from the moved plane); panes only in feature-pass window cells; lit kits get an
        enclosed shroomlight backing
        |
   shade_gradient(sheet_subject=N, auto=True) -> shaded ortho sheets of N + 3D AO / sun / eave / soffit; no photo
        projection. Materials without a curated zone (siding, shell, skin, limestone ...) get an automatic ladder:
        2 dark + 2 light steps of 6 L*, any block family within 12 a*b* of the base (same family preferred), and no
        blocks whose top face differs from the side (grass_block, logs)
        |
   art/final/N_combined_mc_blocks.json + schematics, out/combined/N_combined_report.json (audit)
```

Face mapping for a feature_detect rect (`axis`, `plane`, `u`, `y`):

| out | face | a | n |
|---|---|---|---|
| +z | front | u | plane |
| -z | back | W-1-u | D-1-plane |
| +x | right | D-1-u | plane |
| -x | left | u | W-1-plane |

## Parts list (steps 1-2, before the ortho sheet)

`parts_list.py` implements "Look and list" and "Check the list" from `specs/detailed-parts.md`, so a new subject
gets a verified parts list + detailed architectural notes from its reference photo(s) before nano-banana draws
the orthographic sheet.

```
python parts_list.py house            # Haiku, ~two calls (list + check), cached by image hash
python parts_list.py turtle --force   # re-generate; organic subjects write {"organic": true, "parts": {}}
python run_v2.py house parts          # same step, also the first stage of `run_v2.py house all`
```

- **Step 1 (`generate`)** reads `refs/<n>_fal_in.png` and/or `refs/<n>.jpg`, classifies organic vs structure, and
  writes a blueprint: `subject`, `summary`, `organic`, and `parts` as `{id: {kind, count, parent, face, where, notes, built_as}}`.
- **Step 2 (`verify`)** is a programmatic schema check (valid `kind`, `count >= 1`, non-empty `where` / `notes` /
  `built_as` in `{set_back, open, proud, outline}`) plus a second Haiku read of the pictures. One revision is
  allowed; the file records `verified`, `verify_notes`, and `cost_usd`.
- **`prompt_block`** formats the verified list in the same per-part style as `blueprint.prompt_parts` (run A) and
  is injected into the sheet prompt by `run_v2.gen_sheet`, `ortho_verify.gen`, and `ortho_gen.py` (auto-load;
  `--no-parts` to skip; empty for organic subjects).
- **`ensure`** is merge-safe: if `meta/<n>_parts.json` already exists it is returned at $0 and hand-written keys
  (`grad`, `zones`, `rebuild_sails`, `squash_z`, `feature_kinds`, `boxes`, ...) are never clobbered. `--force`
  regenerates the blueprint but still keeps those operational keys.
- `stamp_generic.py` and `run_v2.py` read both schemas through `parts_list.iter_parts` / `has_built` (legacy
  `built_as: "open"` and the new `built_as: ["open"]` list; `"organic": true` still wins in `is_organic`).

This stage is *upstream* of `run_combined.py`. The combined runner itself stays $0: it only reads the file.

## Organic models (turtle, bonsai, creatures, trees)

Organic models have no flat facade to cut into, and the detector's "windows" on them are shell plates or leaf gaps.
So stamping is skipped entirely: no recesses, no openings, no chimneys or spires, and no glass. The model goes
straight to mc_map, then shade_gradient (auto zones + sheet shading + AO). The bypass triggers on:

- `--organic` on the command line;
- `"organic": true` in `meta/N_parts.json` (`false` forces stamping);
- or automatically, from the **flat-wall share**: the share of the four side views' silhouette pixels whose depth is
  constant over their 3x3 neighbourhood.
  - It is organic below 0.03, even when the detector reported openings.
  - It is also organic below 0.08 when no openings were detected.
  - Measured values: turtle 0.000, bonsai 0.011, windmill 0.047 (round tower), windmill_v2 0.121, gate 0.179,
    cathedral 0.174-0.190, cottage_v2 0.215, house 0.325, hagia 0.42.

Detection for an organic subject never writes `meta/N_features.json`, so the subject's own pipeline is unaffected.

## Run

```
python run_combined.py gate house turtle            # $0
python run_combined.py bonsai --organic
python run_combined.py cathedral --orient-apply     # raw blueprint mesh: flip if needed, re-detect features
```

## Results (Nov 26, 2026)

| model | dE mean | dE p90 | outlier % | palette EMD | glass | notes |
|---|---|---|---|---|---|---|
| gate_grad (before) | 13.86 | 23.73 | 3.93 | 17.19 | 265 yellow panes + 218 shroomlight | |
| gate_combined | 13.15 | 20.46 | 3.36 | 17.06 | 259 yellow panes + 218 shroomlight, 0 stray | 71 windows set back 1; back wing arches cut through (overlap of front and back boxes); main arch still open |
| house (featured house_albedo = same scores) | 14.18 | 34.19 | 3.36 | 10.95 | 143 light-gray + 4 brown panes | |
| house_combined | 12.61 | 28.29 | 3.91 | 12.20 | 142 light-gray panes, 0 stray | 34 windows + door set back 1; 2 one-sided "arcades" left as built |
| turtle (before) | 17.97 | 28.43 | 17.19 | 15.40 | 0 | |
| turtle_combined | 15.57 | 24.90 | 13.08 | 17.15 | 0 | organic bypass (flat-wall share 0.000) |

Scores come from colour_score.py with `--no-photo` against the chosen sheets (gate _s1, house _v1, turtle _v2,
picked by IoU). All models have 0 creaking_heart.

Cathedral (optional) was tried with features re-detected image-only and the `_bpB3` sheet. It is not deployed: the
image-only detector reports 4 chimneys and 7 spires on the old 13x26x32 model, and mc_map's protrusion builder turns
them into brown poles. It needs a parts list (or William's higher-resolution mesh) first.

## House "black spots" fix (Nov 26, 2026)

**Cause.** All 147 of the neutral-dark blocks (L* < 45, C* < 8) on the house_combined exterior were `trim_brown`:
119 pale_oak_wood, 20 acacia_wood, 4 tuff_brick_stairs, 3 gray_wool_stairs and 1 cracked_deepslate_bricks.
- The de-shaded albedo trim colour is #534039, a dull brown (L* 29, C* 10). `mc_map` matched it to pale_oak_wood, which
  is grey bark (C* 4.7) and the nearest block by dE2000 among the preferred wood family. On the pale siding it reads as
  black.
- The automatic shade ladder in `shade_gradient` then added grey steps (acacia, tuff, gray wool, deepslate) within 12
  a*b* of that grey base.
- The flat house_mc_blocks had the same problem (132 pale_oak_wood).

These were **not** the cause:
- No backing block (polished_blackstone) touches open air in either version. The 64 visible ones sit behind window
  glass or frames, by design.
- `stamp_generic` added 0 new cells on the house.

A separate artefact: the door's transom panel was warped_nylium, a teal stripe. Its top differs from its side, and the
door panel picker didn't exclude it.

**Fix (general).**
- `mc_map` chroma guard: a dark (L* < 45), chromatic (C* >= 8) target may not be matched by a block with less than half
  its chroma. Turn it off with `MC_CHROMA_GUARD=0`. house trim_brown → poplar_log.
  - The guard changes nothing in gate, windmill_v2, cottage_v2 or turtle (checked block by block).
- `mc_map` door panels and other `nearest()` picks skip *_nylium.
- `shade_gradient` auto ladders:
  - the same chroma rule;
  - no step darker than 0.75 × the base L*;
  - no terrain blocks (soil, organic, moss, mushroom) unless the base is terrain, so there is no dirt on a roof.
  - Curated zones (gate, windmill, cottage) are unchanged.

**Result.** Neutral-dark exterior blocks went from 147 to **0**, with 0 backing exposed to air, 142 window-only glass
panes (0 stray) and 0 creaking_heart. dE mean 12.61 → 12.54 and p90 28.29 → 28.22.

## Above-mesh peaks: tower caps, turrets, spires and chimneys the mesh clipped (Nov 26, 2026)

**Flaw.** `feature_detect.align()` stretches each drawing onto the mesh's bounding box. When the mesh clipped a peak
that the drawing shows, the drawing is squashed to fit, so the missing part never shows up as a difference. The
gate's two central tower caps are taller than the gable in the drawing, but in the mesh they were ragged 1-2 wide
stubs ending below it. The parts list had no boxes for them, so `tower_cap: outline` was skipped.

**Detector: `feature_detect.above_mesh_peaks(n, tag, occ)`** ($0, no LLM). It runs on the front and back views.

1. **Registration.** The drawing is scaled by the mesh **width** and anchored at the ground. The vertical scale is
   fitted within ±25%, by IoU over the rows the mesh has. Anything drawn above the mesh then lands in rows it lacks.
2. **Seeds.** A seed is a 4-connected group of drawing cells above the mesh's column top, at least 4 cells.
3. **Profile.** Each peak is rebuilt **whole**. Starting from the drawn tip, it walks down the run that contains the
   tip until the outline widens by 3 or more in one row (the shoulder where it meets the roof, gable or wider body).
   - It is shifted -1, 0 or +1 column to sit on the mesh stub it replaces.
   - Widths never grow going up, and every row is centred on the peak's median axis.
   - Tapering peaks (top width ≤ 0.6 × the base, or ≤ 2) become `tower_cap`, built as `outline`, with a linear taper
     to a 1×1 apex. Others become `chimney`, built as `proud`.
4. **Depth.** It takes the supporting voxels' z-run on that facade. Depth = min(the run's length, the peak's width),
   and each row's depth scales with its width, so a square cap stays square instead of stretching across the
   building.
5. **Colour and material.** The drawn colour is sampled per row, and the nearest subject material is used: a slate cap
   gets `roof_slate`, a stone turret body under it gets `gate_stone`.

**No stray poles (guards):**
- **Support.** At least 60% of the peak's base row must have mesh solid in the 3 rows directly under it (±1 column).
  A strip drawn beside a wing with nothing under it is dropped.
- **No shoulder means no peak.** A run that reaches the ground is a wall, not a peak.
- **Registration quality.** The view's drawing-to-mesh IoU must be at least 0.65.
- **Size.** At least 2 wide somewhere and 3 rows tall.
- **Two-view confirmation.** When front and back drawings both exist, both must show the peak (x overlap within 1).
  The front view's peak is the one built.

**Stamping: `stamp_generic.stamp_peaks`.** Inside each peak's box (its x range, the support z-run, the rows above its
base), mesh voxels outside the profile are removed (the ragged stub) and profile cells are filled. Cells with nothing
of the peak above them get stairs stepping down outward; the 1×1 apex column stays full blocks as the finial.
`run_combined` re-materials the cells per row and records them in `meta/N_combined_features.json` under `stamp.peaks`
and `stamp.peaks_cells`. `--no-peaks` turns it off; organic subjects skip it.

**Results.**
- **Gate:** 2 `tower_cap`s at x 15..19 and 38..42, base y 39, top y 48, z-run 3..11 with depth 5.
  - Widths from the base up: 5, 3, 3, 2, 2, 2, 2, 1, 1. Rows 40-41 are stone, rows 42-48 slate.
  - Each cap: 49 voxels added, 5 stub voxels removed, 61 cells.
  - Occupancy changes only inside the two cap boxes. The model is one connected piece, all 3 arches are open,
    there is 0 stray glass and 0 creaking_heart.
- **Sanity checks (0 peaks):**
  - house: 0 above-mesh regions survive.
  - windmill_v2 and cottage_v2: 0.
  - windmill v1: 3 sail and lattice slivers dropped (front IoU 0.63, back not confirmed).
  - turtle: organic, so it is skipped. Run directly, its head would be dropped as too short or thin.
  - cathedral: 0.
