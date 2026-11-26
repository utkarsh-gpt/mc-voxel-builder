# Cathedral experiment: Run A (one block per part) vs Run B ("N x part id")

Specs: `../specs/detailed-parts.md` (Experiment section) and `../specs/detailed-parts-cathedral.md` (hand-written notes).
Script: `blueprint.py` (`python blueprint.py cathedral A|B [--retries 3] [--cap 2.00]`). Run 2026-11-25, about 22:00 to 22:45 America/Toronto.
Results: `results/cathedral_exp/` (run_A.json, run_B.json, table.json, ledger.json, prompts, images). Raw voxels and renders: `out/cathedral_exp/` (gitignored).

## Method (the same for A and B except the parts text)
- Blueprint: `parse_notes()` reads the 24 part ids from the notes file and adds the 5 `_left` twins the notes ask for, giving **29 ids** (the brief said 26). Written to `art/final/meta/cathedral_blueprint.json`. List and list-check steps skipped (the notes are hand-written).
- Sheet: nano-banana/edit from `refs/cathedral.jpg` (+ the masked fal input). Prompt = `ortho_gen.PROMPT` (with the no-shadow / flat albedo rule) + `ortho_verify.COM` + the parts text.
  - **A**: one block per part: `[id] N x (kind, face). WHERE ... NOTES ... BUILT AS ...` (26.6k chars on the first try; 27.7k–28.6k chars on retries).
  - **B**: `PARTS: 1 x plinth, ..., 10 x pinnacle left.` (3.1k chars including the shared header; the parts text alone is 523 chars).
- Mesh: hyper3d/lowpoly/image-to-3d (the current ortho_lowpoly path), 4000 faces, F/R/B/U views.
- Voxels: plain `fal_shape.voxelize`, grid 48, then grid 72 on the same mesh if anything was missing. The grid with fewer missing parts is kept.
- Check, structure only, no colour:
  - Haiku (claude-haiku-5-5) reads the photo, the blueprint and the flat-grey renders: front, right, back and left (each a side-lit 25° oblique plus a straight depth map), and a three-quarter view. Per part it reports present, count_seen, built_as_seen and detail_missing.
  - A part passes only if Haiku says present AND count_seen ≥ count.
  - Separately, `count_openings()` counts recessed and see-through patches per face from depth alone, never from darkness.
- Retry: up to 3 retries per run. Each retry names the missing ids (A also names its detail_missing) in the next sheet prompt. Shared ledger, fal cap $2.00.
- Stopped at structure: no colour, no mc_map, no block shaping (stairs, walls and fences stayed allowed but were not used).

## Per run
| | Run A | Run B |
|---|---|---|
| attempts (retries) | 4 (3) | 4 (3) |
| missing of 29, per check (g48, g72 per attempt) | 14,17 / 9,14 / 14,**8** / 13,18 | 19,20 / 17,**13** / 19,14 / 22,18 |
| mean missing per check | 13.4 | 17.8 |
| best attempt | bpA3, grid 72, 8 missing | bpB2, grid 72, 13 missing |
| grid used per attempt | 48, 48, 72, 48 | 48, 72, 72, 72 |
| meshes with the full long nave + apse | 3 of 4 (A2 collapsed) | 1 of 4 (B1, B3 and B4 came out short or front-only) |
| key-part passes over all 8 checks (20 key ids × 8) | 68 / 160 | 38 / 160 |
| detail_missing items on key parts (best attempt) | 16 | 26 |
| final check | failed (parts still missing) | failed |
| fal | $0.956 | $0.956 |

## Key pass parts (best attempt: present / count seen; then passes over all 8 checks)
| part (count) | A best | A passes/8 | B best | B passes/8 |
|---|---|---|---|---|
| portal_main (1, middle wider) | Y 1 | 7 | Y 1 | 7 |
| portal_side (2) | Y 2 | 5 | Y 2 | 4 |
| rose (1, hub + spokes) | – 0 | **0** | – 0 | 1 |
| front_window (4) | Y 4 | 4 | – 2 | 4 |
| gallery_arcade (1 row of 5) | – 0 | 5 | – 0 | 2 |
| aisle_window (11) / _left | Y 11 / Y 11 | 2 / 2 | – 10 / – 10 | 0 / 0 |
| clerestory_window (10) / _left | – 0 / – 0 | 0 / 0 | Y 10 / Y 10 | 1 / 1 |
| side_buttress (10) / _left | Y 10 / Y 10 | 6 / 6 | Y 10 / Y 10 | 2 / 2 |
| pinnacle (10) / _left | Y 10 / Y 10 | 4 / 4 | – 8 / – 8 | 1 / 1 |
| flying_buttress (10) / _left | Y 10 / Y 10 | 5 / 5 | Y 10 / Y 10 | 1 / 1 |
| belfry_opening (16) | – 0 | **0** | – 4 | 1 |
| parapet (2 battlements) | – 0 | 3 | – 0 | 2 |
| apse (faceted) | Y 1 | 6 | Y 1 | 6 |
| apse_window (3) | Y 3 | 2 | – 0 | 1 |
| apse_flying_buttress (7) | Y 7 | 2 | – 5 | 0 |
| gallery_balustrade (open) | – 0 | **0** | – 0 | **0** |

Typical detail_missing on the best A build: rose "circular recess, raised ring, twelve-spoke tracery"; arcade "five separate pointed lights, columns between lights"; front windows "mullions, head tracery"; belfry "slats"; portals "doors, gable crockets".

## Depth-only counter (recessed, open patches per face; required from the notes: front 19, right 35, back 14, left 35)
| check | front | right | back | left |
|---|---|---|---|---|
| A best (bpA3 g72) | 8, 0 | 14, 0 | 3, 0 | 14, 0 |
| B best (bpB2 g72) | 10, 0 | 17, 0 | 5, 0 | 18, 0 |
| A mean over 8 checks | 8.3 recessed | 9.6 | 3.9 | 8.9 |
| B mean over 8 checks | 5.3 recessed | 8.9 | 5.9 | 8.3 |
- **No see-through opening survived in any of the 16 voxelizations**, apart from one stray cell in B1 g72.
- Both runs reach about half the required recesses on the long sides and about 40% on the front.
- A has somewhat more front recesses on average. On the sides the two runs are the same within noise.

## Did the claim hold?
**Weakly, and in direction only.**
- By the spec's rule ("A has more pass parts present, or the same with more detail"), A wins:
  - best attempt 21 of 29 present vs 16 of 29 for B
  - 14 vs 9 of the 20 key ids
  - fewer detail_missing items (16 vs 26)
  - key-part passes over every check 68 vs 38
  - A also kept the long nave and apse silhouette more reliably (3 of 4 meshes vs 1 of 4)
- The evidence is soft:
  1. **Haiku is noisy.** The same mesh at grid 48 and grid 72 differs by up to 6 missing parts (A3: 14 vs 8). Its counts often equal the blueprint numbers exactly (11, 10, 10), which suggests it partly reads the counts from the blueprint instead of counting shapes.
  2. **n = 4 meshes per run**, and the Hyper3D mesh-to-mesh variance (whole nave lost or kept) is larger than the prompt effect.
  3. **The objective depth counter barely separates A from B** (front 8.3 vs 5.3 mean recesses; sides equal).
- Neither run passed: in both, every opening-type part with sub-block detail is missing.

## Where it failed and why
- **Sub-block parts: rose spokes, belfry slats, balustrade, pinnacles, the 5-light arcade, mullions and tracery.**
  - At grid 72 the 67–72-voxel-long building puts about 1.5 m into a voxel.
  - Rose spokes, slats and balusters are well under a voxel. The five arcade lights and their columns would need 10+ voxels across the centre section, which has about 12.
  - These merge into one band or vanish, exactly as the spec predicted.
- **"Open" never survives.** Hyper3D lowpoly (4000 faces) makes a closed shell, so belfry openings, flying-buttress gaps, the balustrade and battlement gaps are filled solid. The depth counter found zero see-through patches. This is a mesh-stage failure, not a voxel one: no grid fixes it.
- **Repeated window rows.** 11 aisle + 10 clerestory windows per side need about 3 voxels per bay; at grid 48 a bay is about 2.5 voxels. They came out as about 14–18 recesses per side instead of 35, often merging aisle and clerestory into one tall slot per bay (Haiku then passes one row and fails the other: A got the aisle row, B the clerestory row).
- **The sheet still had shadows.** shading_check flagged all 8 sheets as shaded (shadow share 0.32–0.41) despite the no-shadow rule. A1's top view also drew a cross or oval plan that is not in the photo. The long A prompt (about 27k chars) did not hurt fal, but the plan view is the weakest panel in both runs.
- **Retries did not converge.** Naming the missing ids changed which parts were missing more than how many:
  - A: 14 → 9 → 8 → 13
  - B: 19 → 13 → 14 → 18
  - Mesh variance dominates the effect of the prompt.

## Spend
- fal: **$1.912** (8 sheets × $0.039 + 8 meshes × $0.20), under the $2.00 cap, about $0.956 per run.
- Haiku: **$0.188** (16 checks).
- Total $2.10.

## Images
- `/workspace/fd-work/cathedral_exp/cathedral_A_vs_B.png`: best A vs best B, each with its sheet, three-quarter grey, and front and right grey + depth.
- `/workspace/fd-work/cathedral_exp/cathedral_all_attempts_3q.png`: all 8 attempts, three-quarter grey.
- Copies of both are in `results/cathedral_exp/`.

## Next, if continued
- Judge "open" parts at the mesh or sheet stage (or carve them as voxel templates after voxelizing), since the lowpoly mesh never keeps holes.
- Make Haiku count without the blueprint counts visible, or count on depth-map crops per face, to remove the count parroting.
- Use ≥3 meshes per prompt, scored by median, before concluding on prompt effects.
