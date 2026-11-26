# Feature identification and the feature pass

`feature_detect.py` finds windows, doors, arched windows and small parts (chimneys, spires, minaret tips) on the verified ortho drawings, groups openings into repeating rows, and locates each one on the block grid. `mc_map.feature_pass` then builds them as Minecraft detail. Output: `art/final/meta/NAME_features.json` and the overlay `out/NAME_features_debug.png`.

```
python feature_detect.py house hagia        # Haiku-assisted (default), replies cached in out/cache/fd_haiku_*.json
python feature_detect.py house --no-llm     # image-only detector (weaker, see below)
python mc_map.py house hagia                # feature_pass runs when NAME_features.json exists (MC_FEATURES=0 turns it off)
python feature_gallery.py house hagia       # out/features_gallery.png (before vs after) + out/features_detect.png
```

## How detection works

1. **Align.** Each elevation drawing (front, right, back; left is the mirrored right drawing, as in `ortho_paint`) is resampled onto the block model's silhouette bounding box from that side at 8 px per block. The mirror is chosen by IoU.
2. **Part list (Haiku).** The aligned drawing is redrawn with a numbered 1-block grid (`out/features/NAME_TAG_VIEW_grid.png`). `claude-haiku-5-5` lists every opening (window / door / arched_window / round_window / porch_opening) and small part, each as inclusive grid-cell ranges. That is 4 calls per subject (about $0.005–0.007 each), run in parallel. Replies are cached by image hash, so reruns are free.
3. **Tidy (repetition).** Duplicate boxes are dropped. Openings are grouped into rows: same kind and arch flag, with sill and height within 1 block. Each row gets one height, sill line and width (within ±1), so every bay is built from the same kit. A row of 3 or more equal openings with even spacing is tagged with its period. A single missing bay in an otherwise regular run is filled in and flagged `inferred`.
4. **3D.** Each box goes onto the model's facade plane: the modal hit depth of the box's cells from that side. It is stored as `rect` = {axis, plane, u-range, y-range}.
5. **Protrusions (geometry).** Drawing silhouette that sits above the model's top surface marks parts the mesh lost. A part ≥ 0.75 block wide is a chimney; a thinner one is a spire. Haiku's part list renames it when one overlaps (chimney / spire / finial / minaret). Depth comes from the perpendicular view matched by height, else from Haiku's front/back part at that height, else from the ridge. Mirrored stand-in drawings add no parts.

### What did not work (image-only)

Colour segmentation of "wall vs opening" was tried in three variants:
- dark pixels against a local median
- k-means wall clusters with holes
- half-block patch-mean clusters with a morphological opening

None of them was reliable. The house front's dominant lower colour is the porch and roof trim, not the siding. Hagia's light glazing with grilles is about the same colour as its stone. Trim lines join windows to the roof outline. The best variant found 8 house and 9 hagia openings with many misses. It is kept as `--no-llm`.

A ±1-block "nudge" of Haiku boxes toward the local-contrast peak was also tried. It made results worse: boxes snapped onto siding lines and frames. Haiku's grid reading alone was better, so the contrast score is only recorded (`evidence`).

## The feature pass (mc_map.py)

| feature | blocks |
|---|---|
| window | Glass pane in the wall plane, one pane colour per repeating row (kit). Polished-blackstone backing behind it. Upside-down stair hood above. Top-slab sill one block out. |
| arched window (≥ 2 wide) | Upside-down stairs in the two head corners, solid half toward the wall, so the head reads rounded. |
| door | Open wooden trapdoors flush with the inner face (a recessed leaf; doors are not in the dataset). Upside-down stair lintel above. |
| chimney | Full-block column of the nearest brick/stone family block that has a slab, from the roof to the drawn top, with a slab cap. |
| spire | Wall-post column (antenna, finial, minaret tip). |

The pass runs before `window_kit`, which then only handles the dark clusters that the features did not cover.

## Results (sheet `_v1` house, `_v2` hagia)

| subject | detected | built |
|---|---|---|
| house (22×20×23, 2 blocks/m) | 34 windows in 5 kits, 1 door, 2 porch openings (not built), 1 chimney | 148 panes, 13 hoods, 25 sills, 8 door leaves + lintel, 2 chimney blocks. Before: 1 window kit, 5 panes. detail_score 72.3 |
| hagia (37×31×41, 1 block/m) | 26 windows (13 arched, regular rows with periods 6–8.5 blocks), 1 door, 1 spire | 122 panes, 22 arch-corner stairs, 24 hoods, 23 sills, 1 spire block (plus 11 legacy window_kit windows) |

Time: about 0.7–0.9 s per subject with a cached Haiku reply. A cold run is about 20–80 s, dominated by the Haiku CLI latency; the 4 views run in parallel.

## Next steps

- Doors and windows on the left side reuse the mirrored right drawing. Ask Haiku about the real left drawing when the sheet has one.
- Porch openings / arcades are detected but not built. Ideas: fence or wall posts plus a slab beam.
- Cross-view consistency: front/back rows at the same height could share one kit across views.
- A verification pass: render the built facade, ask Haiku "does every listed window appear?" (William's blueprint check).
