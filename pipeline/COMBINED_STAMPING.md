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
   meta/N_parts.json ............. optional: built_as overrides, open parts, normalised boxes, "organic"
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
