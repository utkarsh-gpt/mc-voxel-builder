# DETAIL_DISCOVERY: why our builds come out flat, and how to fix it (2026-11-24)

**Problem.** Builds lose their intricacy as they go through the pipeline. Walls are flat planes, windows read as dark speckle, spires are stepped lumps, and the final schematic is mostly full cubes.

**Method.**
1. Traced the cathedral through every stage: ortho sheet, then low-poly mesh, 48-grid voxels, half-size sub-blocks and `mc_map`.
2. Parsed the hand-built *Little Hagia Sophia* benchmark (Skyman0, 39×24×34, 8,152 blocks) layer by layer.
3. Compared it with our own `.schem` outputs using the same metrics.
4. Collected what community cathedral and detailing guides say about using small blocks.

Analysis scripts are throwaway and not checked in: a pure-Python Sponge `.schem` reader, ASCII slicer and detail metrics.

---

## 1. TL;DR

| # | Root cause | Where | Share of the loss |
|---|---|---|---|
| 1 | **The block mapper erases 83% of the sub-block geometry.** It picks the base block by colour only (limestone → `white_terracotta`). Terracotta has no stairs, slabs or trapdoors, so every shaped cell falls back to a full cube. | `mc_map.py` `choose()` / `_place()` | 754 of 910 shaped cells on the cathedral |
| 2 | **The detail vocabulary is not in the dataset.** Walls, fences, panes, iron bars, buttons, doors, chains, lanterns, end/lightning rods and carpets are all in `excluded.json`. The mapper physically cannot place the blocks builders use for detail. | `mc-blocks/excluded.json`, `mc_map.allowed()` | all of the "small-block" detail |
| 3 | **There is no detailing stage at all.** The pipeline goes from mesh to voxels to colour to block. Nothing adds cornices, window kits, hood moulds, sills, pilasters, plinths or eaves, and that is what a builder spends most of their effort on. | missing stage | the main difference from the benchmark |
| 4 | **Geometry is low-pass filtered four times before blocks exist.** 1. Hyper3D *low-poly* mesh at 4,000 faces. 2. 48-voxel grid. 3. Downscaled to a *half-size* grid (cathedral 13×26×32). 4. Sub-block shapes are banned on axis-aligned faces, and `solidify` closes gaps under half a block. Windows, rose window, tracery and crenellations exist only as *colour* after step 1. | `ortho_lowpoly.py`, `fal_shape.voxelize`, `subblock.py` | relief, openings, thin parts |
| 5 | **Solid fill.** Only 43% of our cathedral's blocks are surface (Hagia: 88%). A solid mass has nowhere to put a recess, so windows can only be painted on. | `voxelize(...).fill()`, `solidify`, `ortho_paint` ring fill | recessed windows and doors |
| 6 | **Nothing measures geometric detail.** "Detail density" in `scorer.py` is surface *colour* variation. Neither the rubric nor the judge loop ever rewards a stair cornice over a flat wall. | `scorer.py` | why the loop never pushed toward detail |

The ortho sheet stage is **not** the bottleneck. `ortho/cathedral_v3_sheet.png` clearly has the rose window, about 12 bays of lancet windows, buttresses, pinnacles, crenellated tower tops and gabled portals. The detail is in the drawings, and we throw it away later.

---

## 2. Stage-by-stage trace (cathedral)

| Stage | Output | What survives |
|---|---|---|
| Reference photo, then nano-banana ortho sheet | 1024² sheet | Everything: rose window, lancets, buttresses + pinnacles, crenellations, portals, roof |
| Hyper3D `lowpoly/image-to-3d`, `face_count=4000` | GLB | Big masses only. Windows and the rose window are baked into the **texture**, not the geometry. |
| `fal_shape.voxelize(glb, 48)` | 19×39×48, 12,075 voxels, solid | Side buttress rhythm (period 3 voxels, depth 1). Towers stand proud of the front by 1, with a recessed centre bay. No openings. |
| `ortho_paint` + `palette_generic` | colours | Windows become a `window_dark` **colour** cluster flush with the wall |
| `subblock.py --n 32` (half size, 4× fine grid) | 13×26×32, 3,916 cells, **887 shaped** | Buttress rhythm aliased (period 3 → 2). The front facade is 13 blocks wide, so the rose window would be about 3 blocks. |
| `mc_map.py` | `.schem`, 22 states, 14 ids | **156 shaped** (120 stairs, 36 slabs). Breakdown of what was flattened: |

The `mc_map` flattening in detail (`summary.shapes` in `art/final/cathedral_mc_blocks.json`):

```
full (no vertical piece)          405   vslab 1/4 -> only wood/copper have trapdoors; stone never gets a thin vertical piece
full (half-width vertical piece)  162   vslab 1/2 -> full by rule
full (no stairs for material)      96   white_terracotta / chiseled_sandstone have no stairs
full (no slab)                     91   ... and no slabs
stairs 120, slab 36                     survived
```

What our final cathedral side wall looks like (`-x` elevation, first-hit block; `t` = terracotta, `d` = dark accent, `s` = stair, `_` = slab):

```
14     dddddddddd______ddd__ttttt
13     ts___________________ttttt
12     sssssssssssssssssssssttttt      <- the roof is the only place shapes survive
11   ddsttttttttssssssssssssttttt
10   ddddddttdtttdttdddddddddtddt      <- "windows" = random dark blocks in the wall plane
 9  tdttddtttdtdtdtdtdddddddttdtt
 8  tttdtdtttttttttttttddtdtttttt
 5  ttttttttttttttttttttttttttttt      <- flat wall: no plinth, no band, no cornice
 0 tttttttttttttttttttttttttttttttt
```

---

## 3. What the Little Hagia Sophia benchmark does

### 3.1 Numbers, compared with ours (same metric code on every `.schem`)

| metric | **Hagia (hand-built)** | our cathedral | our windmill | our cottage |
|---|---|---|---|---|
| grid | 39×24×34 | 13×26×32 | 21×23×12 | 24×15×14 |
| blocks | 8,010 (excl. plants) | 3,916 | 996 | 2,627 |
| surface share ("hollowness") | **88%** | 43% | 55% | 37% |
| non-full blocks among surface blocks | **26.6%** | 7.8% | 19.8% | 20.2% |
| distinct blockstates | **109** | 22 | 34 | 35 |
| shape families | full, slab, stairs, **pane, fence, door, torch** | full, slab, stairs | + trapdoor | + trapdoor |
| upside-down stairs (share of surface) | **598 (8.5%)** | 3 (0.2%) | 20 (3.7%) | 15 (1.6%) |
| overhang cells (block with air below, y>1) | **19.4% of surface** | 1.6% | 20.0% (sails) | 11.5% |

The overall grid is **not** drastically different: 39 vs 32 on the longest side. The difference is how the blocks are spent. Hagia has 1-block walls and every block is a surface decision. About 1 in 4 surface blocks is a partial block, and upside-down stairs alone make up 8.5% of the surface.

### 3.2 Techniques, read from the slices

Legend: `o` cut sandstone wall, `Q` quartz trim, `B` stone bricks, `S`/`s` upside-down/normal stair, `=`/`_` top/bottom slab, `#` glass pane, `|` fence.

**(a) Cornice / string course.** A continuous ring of upside-down stairs one block proud of the wall, at every eave line. A layer of slabs above it forms the roof edge. This is the single biggest "not flat" signal.

```
y=14   ____________________________________   slab roof edge
y=13  SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS  upside-down stair cornice, 1 block proud (depth 3 vs wall 4)
y=12   oooooooooooooooooooooooooooooooooooo   wall
```

**(b) Window kit, repeated on a fixed bay rhythm (every 4–5 blocks).** The window is 2 tall and 1 wide, made of a glass pane set in the wall plane. A pane is only 2/16 thick, so it reads as a deep reveal. Above each window is an upside-down stair acting as a hood or lintel. The ground and gallery floors repeat the same kit.

```
y=11   oooSoooooSooooSooooSooooSooooo     hood stair above every window
y=10   ooo#ooooo#oooo#oooo#oooo#ooooo
y= 9   ooo#ooooo#oooo#oooo#oooo#ooooo     2-high pane windows, bay spacing 5/4/5/5
```

**(c) Drum and dome.**
- *Drum:* buttress piers alternate with slabs (`_o_o_o_`), and a ring of pane windows sits between them.
- *Dome:* a 1-block shell of concentric rings. Each ring steps in by one and is edged with bottom slabs, which halves the visible step, and corner stairs round off the ring corners.
- *Lantern / finial:* a fence post on top.

```
y=19   _o_o_o_oooSooo_o_o_o_      drum: pier / slab rhythm
y=18   sso#ssosoo#oososs#oss      windows between piers, stairs as pier caps
y=20 (plan)   __sBQQQ  QQQBs__    ring: slab edge + corner stairs + quartz infill
```

**(d) Material roles, not just colours.**

| role | blocks |
|---|---|
| walls | `cut_sandstone` (2,989) |
| trim at corners, drum and columns | `quartz_block` / `chiseled_quartz` / `quartz_pillar` |
| roof | `stone_bricks` + `stone_brick_slab` / `_stairs` |
| plinth and paving | `smooth_stone`, `polished_andesite` |
| ground | `grass_block` + `short_grass` |

Every one of these blocks has a full stair/slab family, so the builder never runs out of shapes.

**(e) Small features from small blocks.**
- *Door canopy:* fence posts carrying a top-slab roof. This matches the door awning in the photo.
- *Railings and finial:* fences.
- *Lighting:* torches and wall torches.
- *Interior:* hidden glowstone.

**(f) Symmetry and regularity.** The plan is exactly mirror-symmetric, and the windows sit on a bay grid. Noise-free regularity is part of what makes it read as architecture.

**(g) Hollow shell with interior floors.** Galleries at y=7 have slab/upside-down-stair edges, and quartz columns stand inside. This is not visible from outside, but the 1-block walls are what make the reveals possible.

---

## 4. What cathedral builders say (community guides)

These are mostly blog-grade sources, so treat the numbers as rules of thumb. They agree with the benchmark.

- **Arches:** made from stairs and slabs, with upside-down stairs, walls and slabs for pointed arches over doors and windows. Squared-off openings "feel wrong" on a cathedral. [minecraft.how](https://minecraft.how/blog/post/build-cathedral-minecraft), [Cal Poly guide](https://grandavehousing.calpoly.edu/blog/minecraft-european-architecture-guide-1764801144)
- **Buttresses:** spaced every 8–12 blocks and projecting 2–3 blocks on large builds, tapering as they rise. Flying buttresses can be decorative. [minecraft.how](https://minecraft.how/blog/post/build-cathedral-minecraft)
  - At our scale this becomes "one buttress per bay, 1 block proud, stair/slab set-offs".
- **Tracery and mullions:**
  - Blocks can't reproduce stone tracery, so builders approximate it with fences, walls or trapdoors. [Washingtonian](https://views.washingtonian.com/vie/build-a-stunning-medieval-church-in-minecraft-a-complete-guide-to-spiritual-architecture-in-block-form), [Cal Poly guide](https://grandavehousing.calpoly.edu/blog/minecraft-european-architecture-guide-1764801144)
  - Fence posts serve as mullions in tall Gothic windows. Iron bars and chains add fine detail. [minecraft.how](https://minecraft.how/blog/post/build-cathedral-minecraft)
- **Rose window:** upside-down stairs around glass. One example uses 21 glass blocks in a 5×5 without corners. [Zach's Art of Architecture](https://zachsartofarchitecture.blogspot.com/2015/03/minecraft-architecture-final-tour-of.html)
- **Depth:**
  - Recess windows and frame them with trapdoors, stairs or fences. Pull pillars 1 block off the wall plane. [Sportskeeda](https://sportskeeda.com/minecraft/4-best-ways-add-depth-minecraft-build), [craftdex](https://craftdex.net/fr/articles/the-architecture-of-builds)
  - Stairs and slabs give half-block relief; trapdoors, walls and panes give thinner layers.
- **Depth must be structural:** overhangs, buttresses, window reveals and sill projections, not random bumps. A roof without an eave "looks unfinished". [WesterosCraft exteriors](https://westeroscraft.com/docs/building/fundamentals/exteriors)
- **Spires:** steps in one block at a time as they rise. [Zach's Art of Architecture](https://zachsartofarchitecture.blogspot.com/2015/03/minecraft-architecture-final-tour-of.html)
- **Spire and roof trim:** crenellations along the roofline. [minecraft.how](https://minecraft.how/blog/post/build-cathedral-minecraft)
- **Palette roles:** about 60–70% dominant, 20–30% trim, 5–10% accent. [craftdex](https://craftdex.net/fr/articles/the-architecture-of-builds) (single source)

### The idiom catalogue (what a "detailer" should know)

| feature | block idiom | trigger in our data |
|---|---|---|
| cornice / string course | ring of upside-down stairs 1 proud + slab cap | top edge of a wall under a roof; floor bands |
| eave | upside-down stairs under the roof's lowest course, 1 overhang | roof-to-wall junction |
| window | 1-deep recess, pane or stained-glass pane, upside-down stair hood, slab or stair sill; fence or wall mullion if ≥2 wide; trapdoor shutters for domestic | `window_dark` cluster (2–12 voxels) on a vertical face |
| pointed arch | two stairs meeting at the apex over the opening | window/door taller than 2× its width (Gothic style tag) |
| rose window | ring of upside-down/normal stairs around stained glass, mullions from walls/bars | circle in the front ortho (Hough) |
| pilaster / buttress | 1-proud column per bay, stair/slab set-offs every few blocks, wall/rod pinnacle | periodic vertical relief, or bay rhythm detected in the ortho |
| plinth / base course | 1-wide flare of stairs or a darker full block, 1–2 high | bottom 1–2 rows of every wall |
| quoins / corner trim | trim material on vertical edges | `edge` flag in `mc_features` |
| crenellation | alternating wall/slab (or block/air) on parapet tops | flat tower tops |
| spire / pinnacle | stairs per course, wall + end rod / lightning rod / fence tip | thin tall parts (`--keep-thin` cells) |
| roof surface | stairs + slabs for half-steps, a contrasting ridge course | sloped roof cells (already `stairify`) |
| dome | rings stepping in by 1, slab edges, corner stairs, finial | round roof cells |
| door / porch | door block in a 1-deep reveal, fence posts + slab canopy | `door_red`-type cluster at ground level |

---

## 5. Proposed fixes, by impact per effort

### P0: stop destroying what we already have (mapping only, $0)

1. **Shape-aware base selection in `mc_map`.**
   - Add a term to `slot_cost`: `W_SHAPE × (share of this material's surface voxels whose shape the block cannot realise)`.
   - Prefer blocks whose texture family has stairs + slab (+ wall).
   - For limestone this pushes `white_terracotta` toward `sandstone` / `cut_sandstone` / `smooth_sandstone`, the same family Hagia uses. The accent dither can still warm it.
   - Expected effect: most of the 96 + 91 "no stairs/no slab" cells come back immediately.
2. **Real thin vertical pieces for stone.**
   - Re-admit `*_wall` (and fences, iron bars, panes) to the dataset with shape metadata.
   - vslab ¼ on stone → wall when it is a free-standing thin part (mullion, pinnacle, spire edge). Otherwise snap it to the wall plane (full block, or air if it is <¼ of an inset).
   - Stop turning vslab ½ into "full by rule". Choose between full and a one-block recess from the neighbours, so relief is kept rather than filled.
3. **Windows as windows.**
   - Implement `TRANSPARENT_BLOCKS_PLAN.md` steps 1–4 for glass.
   - Each `window_dark` cluster gets a 1-block recess, a pane, an upside-down-stair hood above it and a slab sill below it.
   - Even without the rest of the detailer, this turns "random dark blocks" into Hagia-style windows.

### P1: keep more geometry (cheap code changes, small fal delta)

4. **Pick resolution from feature size, not a fixed `--n`.**
   - Measure the smallest feature on the ortho drawing that must survive (window width, bay spacing) and set the block scale so it is ≥2 blocks (QUALITY.md principle 2).
   - For the cathedral: about 12 bays along the side × ≥4 blocks per bay gives ≥48–64 blocks long, versus 32 now.
   - Skip the "half-size" downscale for architecture subjects, and voxelize the GLB directly at block × 4 fine.
5. **Don't use the low-poly mesh for architecture detail.**
   - Either raise `face_count` (check Hyper3D's max) or use Hunyuan Pro / Trellis 2 for the mass.
   - Better: accept that the mesh supplies the **mass**, and let the drawings supply the **detail** (P2). Then low-poly is fine.
6. **`subblock.py` for architecture.**
   - Allow partial shapes on axis-aligned faces when the fine grid shows a coherent 1–2 fine-voxel inset or outset along a run (≥3 blocks). That is a cornice or reveal, not noise.
   - Use `--close 0/1` and a smaller gaussian for buildings.
   - Turn off the per-slice ring fill (it fills arcades and recesses) when the subject is tagged as a building.
7. **Hollow shell.**
   - After mapping, keep a 1–2 block shell for building subjects, and line the space behind windows with dark blocks or air.
   - This also cuts block counts by half or more and makes recesses possible.

### P2: add a detailing stage (the real fix)

8. **`detailer.py` between `subblock`/`palette_texture` and `mc_map`.**
   - It works on the block grid with material labels, and applies the idiom catalogue in §4.
   - **Facade analysis:**
     - Find large axis-aligned wall planes, wall-top edges under roofs, vertical edges and ground rows.
     - Find opening clusters (`window_dark`, `door_*`).
   - **Rhythm:**
     - Get the bay period from the autocorrelation of the side ortho drawing, or of the existing buttress relief.
     - Snap openings and pilasters to the bay grid, and enforce mirror symmetry when the drawings are symmetric (front/back IoU is already computed in `ortho_verify`).
   - **Apply idioms** in a fixed order:
     1. Plinth
     2. Pilasters/buttresses
     3. Window kits / arches
     4. String course
     5. Cornice + eave
     6. Crenellation
     7. Pinnacles/spires
     8. Roof ridge
     9. Corner trim
   - **Output:** per-voxel `s` plus a `detail` role (`cornice`, `hood`, `sill`, `mullion`, `trim`, …). `mc_map` then maps the role to a shape family: stair, slab, wall, pane, fence.
   - `mc_map` also gets a trim material per subject, a second shape-capable family for the 20–30% trim share, like Hagia's quartz.
9. **Feature extraction from the drawings.** The drawings are where the detail lives.
   - *Cheap and robust:* one vision call (Haiku, about $0.01) on the verified ortho sheet returns a facade spec JSON, for example `{bays_side: 12, window_rows: [{y0, h, w, arch:"pointed"}], rose: {cx, cy, r}, cornice_heights: [...], buttresses: true, crenellated_towers: true, spire_courses: n}`.
   - *Deterministic cross-check:* Hough circles for the rose window, dark-rectangle detection for windows, and column autocorrelation for bays on the cleaned ortho views. Back-project them with the `ortho_paint` mapping.
   - The detailer consumes the spec. The LLM never writes voxels, so this avoids the plateau seen with LLM voxel JSON in QUALITY §4.

### P3: measure it, so the loop optimises for it

10. **Geometric-detail metrics in `scorer.py`.** Port the metrics used here:
    - non-full share of surface
    - shape-family count
    - upside-down stairs + overhang share
    - distinct blockstates
    - hollowness

    Report them alongside the rubric, and use the Hagia numbers as a target band (≈25% non-full, ≈8% upside-down stairs, ≈19% overhang on building subjects).
11. **Make Little Hagia Sophia a regression subject.** It is the only subject with a **ground-truth schematic**.
    - Run the full pipeline on `photo_little_hagia_sophia.jpg`.
    - Score occupancy IoU after alignment, plus the detail metrics above, against the hand build.
    - Every change in P0–P2 then has a number.
    - The photo is CC BY-SA 4.0 and the schematic is third-party (Skyman0 via BawkBlock). Keep both out of the public repo, or check redistribution terms first.

### Suggested order

P0.1 → P0.3 → P3.10/11 (so we can measure) → P1.4 + P1.7 → P2.8 with a hand-written facade spec → P2.9 automatic spec → P1.5/6.

P0 is a day of work and should visibly fix "flat" on the existing cathedral without re-running fal.

---

## 6. Reproduction notes

- The local Python has no numpy, so the analysis used a pure-Python NBT reader:
  - Sponge v2: palette + varint `BlockData`, index = `x + z·W + y·W·L`.
  - Run with `python -I` on the extracted benchmark.
- Metrics:
  - Surface = a block with at least one air 6-neighbour (plants ignored).
  - Overhang = surface block above y=1 with air directly below.
  - Non-full = anything that is not a full cube (stairs, slabs, panes, fences, doors, torches).
- The cathedral numbers come from `art/final/cathedral_voxels_textured.json` (887 shaped cells), `art/final/cathedral_mc_blocks.json` → `summary.shapes`, and `art/final/schematics/cathedral_mc_blocks.schem`.
- The 48-grid trace uses `viewer/models/cathedral_lowpoly.json` (19×39×48, 12,075 voxels, 4,164 surface).
- The untracked `assets/minecraft/` folder (1,288 blockstates, including 32 `*_wall`) has the models we need to render walls, panes and fences once they are re-admitted.

---

## 7. Results: P0 + P3 implemented (2026-11-24)

### What was built
- **P3 metrics:** `detail_metrics.py` works on any `*_mc_blocks.json` or `.schem`.
  - It reports the §3.1 metrics, a 0–100 `detail_score` (closeness to the Hagia band) and `compare()`: 3D IoU + front/side/top silhouette IoU against a reference schematic, over 4 rotations × mirror.
  - `mc_map` stores the metrics in `summary.detail_metrics`, and `scorer.score()` reports them as `geometric_detail`.
  - `detail_gallery.py` renders labelled before/after strips.
- **P0.1:** shape-aware block choice in `mc_map`. `W_SHAPE`=30 per unit share of shapes a block can't make. The base block is judged on the whole material's needs.
- **P0.2, dataset:** `mc-blocks/add_detail_blocks.py` re-admits 32 walls, 17 panes and 13 fences.
- **P0.2, mapper:**
  - Free thin vertical pieces become walls.
  - ¼ "skin" layers on walls are dropped; they used to be inflated to full cubes.
  - ½ skins stay full.
  - `connect()` sets wall, pane and fence props from neighbours.
- **P0.2, render:** `mc_render` draws wall, pane and fence geometry.
- **P0.3, window kit:** dark clusters ≥2 tall become a pane, a `polished_blackstone` backing, an upside-down stair hood and a top-slab sill. One-voxel specks revert to wall.
- **Side fix, accent dither:** limited to ≤10 dE from the base, so it stays low-contrast. At 16 dE, `white_terracotta` on sandstone showed as pink patches.
- **A/B switch:** `MC_LEGACY=1` reproduces the old mapper exactly (cathedral: identical shape counts and metrics).
- **Fresh-checkout fixes:**
  - `ortho_verify` runs `ortho_gen` with `sys.executable`.
  - `noise_measure` no longer needs the uncommitted `out/textured_pass_scores.json`.
  - `palette_generic` restores the hint's chroma when flat light greys a coloured material (Hagia brick measured at C 6 vs hint 14).
  - fal downloads need `SSL_CERT_FILE` set to certifi's bundle on this machine.

### Numbers (same metric code; benchmark = hand-built Little Hagia Sophia)

| model | blocks | partial % of surface | upside-down stairs % | overhang % | states | vocabulary | detail score |
|---|---|---|---|---|---|---|---|
| cathedral, old mapper | 3,916 | 7.8 | 0.2 | 1.6 | 22 | – | 8.3 |
| cathedral, P0 | 3,581 | **27.2** | 1.3 | 3.6 | 63 | pane, wall | **30.5** |
| Hagia from photo, old mapper | 30,653 | 8.1 | 1.3 | 3.9 | 29 | – | 21.1 |
| Hagia from photo, P0 | 30,204 | **17.9** | 1.8 | 4.5 | 52 | pane, wall | **32.1** |
| Hagia benchmark (hand build) | 8,010 | 26.6 | 8.5 | 19.4 | 109 | pane, fence, door, torch | 100 |

Hagia vs the benchmark (`compare()`):
- Silhouette IoU: front 0.87, side 0.89, top 0.95.
- 3D IoU: 0.33. Ours is solid; the hand build is a 1-block shell.

Renders: `out/cathedral_p0_before_after.png`, `out/hagia_p0_before_after.png`.

### What this tells us
- **P0 fixed what it could.** Shapes are no longer thrown away: 83% of shaped cells were lost on the cathedral; now about 1% are. Materials are one shape-capable family (cathedral sandstone; Hagia mud bricks + a stone-brick roof, the same roof family as the hand build). Windows are real panes with hoods.
- **The partial-block share is close to the hand build** (cathedral 27% vs 27%).
- **The two numbers that define "not flat" barely moved.** Upside-down stairs are 1–2% vs 8.5%, and overhangs are 4% vs 19%.
- **That gap is geometry, and it is already gone before the mapper runs:**
  - The Hagia sheet `ortho/hagia_v2_sheet.png` has drum piers, arched windows, stepped cornices, a half-dome and two window rows.
  - The Hyper3D low-poly mesh keeps the envelope (silhouette IoU about 0.9) but turns the piers into stubs and the windows into texture.
  - So the pipeline gets the right **mass** and the wrong **surface**.
- **Hagia run notes:**
  - The verify step's automatic pick kept only the front view, because every sheet failed the strict checks. I overrode it to `_v2` front/right/top (recorded in `out/hagia_verify.json`).
  - Cost was 4 sheets (one lost to the SSL download failure) + 1 Hyper3D run ≈ $0.36.
  - `noise_measure` took 28 minutes: its camera fit renders the 4× fine model face by face in Python. It should fit on the block grid instead.

## 8. Next step if this is not enough: put the drawing's detail back (P2 first, P1 alongside)

P0 can only keep detail that reaches the mapper, and almost none does. The next work has to add surface detail **after** the mesh, taking it from the drawings:

1. **`detailer.py`: facade spec → idioms. Do this first.**
   - One Haiku vision call on the chosen ortho sheet returns a facade spec JSON: roof/cornice heights, window rows (y, height, width, spacing, arch type), bay count per side, drum pier count, crenellation and pinnacle flags.
   - Facade planes and edges are found on the block grid, and the §4 idioms are stamped onto them:
     - an upside-down stair cornice ring at every roof line
     - the window kit at spec positions, snapped to the bay rhythm and mirror symmetry
     - 1-proud piers/buttresses on the bay grid
     - a plinth course, corner trim and roof eaves
   - Every metric that is still far off (upside-down stairs, overhang) is produced by exactly these idioms. On the Hagia, cornices at the eave, gallery and drum lines plus drum piers would add roughly what the benchmark has.
   - Cost: about $0.01 per subject.
2. **Hollow shell (P1.7).** Keep 1–2 blocks of wall. This makes room for real recesses and cuts the Hagia from 30k to about 8k blocks, which is where the benchmark is. The 3D IoU vs the benchmark should rise well above 0.33.
3. **Relief from the drawings (P1, new idea).**
   - Run a depth/normal estimator (e.g. a fal depth model, about $0.01 per view) on each ortho view to get a facade relief map.
   - Carve recesses and add outsets of 1 block where the map shows them. This turns the drawing's piers, reveals and cornices into geometry directly, without the 4,000-face mesh in the way.
4. **Resolution from feature size (P1.4).** Choose the grid so the smallest wanted feature (window width or bay) is ≥2 blocks. The Hagia's 40 was enough; the cathedral's 13-block-wide facade is not, and needs about 2× that.
5. **Higher face count / Hunyuan for the mass (P1.5).** Lowest priority once 1–3 exist, because the drawings then supply the detail.

Measure every step with `detail_metrics.py --ref` against the benchmark (the Hagia is the regression subject). Targets:
- upside-down stairs ≥ 6%
- overhang ≥ 15%
- 3D IoU ≥ 0.5 after hollowing
- silhouette IoU stays ≥ 0.85

## 9. Shape-fitting voxelizer: `shape_fit.py` (2026-11-24)

Aim: get the **shape** right on the voxel grid first, at player scale, with slopes and curves laid the way builders lay them. Block mapping was deliberately left out of this run; the output is voxels with shapes.

### Scale: 1 block = 1 m
- A player is 1.8 blocks tall, so real metres = blocks gives a building you can walk through and that isn't oversized.
- The real size comes from `art/final/meta/NAME_scale.json` (`length_m` = longest horizontal side). For the Hagia that's 38 m (Wikipedia: narthex to apse "a little over 38 m"; dome 15–17 m).
- The benchmark hand build is 39×24×34 blocks, so the human builder also worked at about 1 block per metre.
- `--bpm` scales it up or down.

### Shape vocabulary (measured from `assets/.../models/block`)
| piece | geometry (1/16 block) |
|---|---|
| slab | 8 thick; the quarter slab is a trapdoor, 3 thick (`template_trapdoor_bottom` 0..3) |
| vertical half / quarter | 8 / 3 thick (no vertical slab in vanilla; the quarter is an open trapdoor) |
| stairs | 8 base + 8×8 step; inner and outer corners from `inner_stairs` / `outer_stairs` |
| wall | post 4..12 (8 wide, 16 tall); arms 5..11 (6 wide) × 14 tall, 16 when something sits on top |
| fence | post 6..10 (**4 wide, half a wall**); bars 7..9 (2 wide) at y 6..9 and 12..15 |
| pane | 7..9 (2 wide), not used here |

Walls and fences connect the way Minecraft does, after shapes are chosen:
- Walls connect to walls, fences to fences, and both to full faces.
- A straight wall run with nothing on top loses its post.
- An arm is tall when something sits above it.

A wall or fence stuck to a solid neighbour with no horizontal run is a mesh sliver and is dropped.

### Pipeline
1. **Fit primitives.** RANSAC on 16 surface samples per m², with mesh normals.
   - Candidates are planes, vertical cylinders and spheres, built from 1–2 points plus their normals.
   - Each accepted primitive is the largest connected patch of its inliers, refitted by least squares.
   - Hagia: 126 primitives explain 95% of the surface.
2. **Snap them like a builder.**
   - Walls go on block boundaries; big walls (≥300 samples) always land on whole blocks, small ones may land on halves.
   - Plan directions are limited to 0°, 45°, 1:2, 1:3 and 2:3 step lines; a diagonal sits on a lattice line `a·x + b·z = k`.
   - Floors and ledges go on half blocks.
   - Roof pitch is limited to 1:8 … 4:1 rise:run.
   - Sphere and cylinder centres and radii go on half blocks.
   - One global x/z offset puts the walls on block edges.
   - A snap is kept only if it still fits its own inliers. 121 of 126 snapped.
3. **Rebuild occupancy at 1/8 block.**
   - Inside each primitive's ±0.6-block band the analytic surface replaces the soft mesh: bulges are carved and dents filled.
   - Where two primitives meet, the corner becomes their intersection or union, whichever agrees better with the mesh. That gives sharp edges in place of the mesh's rounded ones.
4. **Choose a shape per block.** Each block is matched against 87 templates by volume error plus a small complexity cost.
   - Stairs are allowed only where both height and plan change.
   - Horizontal slabs only where height changes; vertical slabs only where plan changes.
   - This stops diagonal walls being drawn as stacked corner stairs.
5. **Heightfield pass for upward slopes and curves (roofs, domes).**
   - Each block column gets one top at the snapped primitive's height, rounded to half a block (.5 → bottom slab).
   - Where the column drops a full block downhill, it gets a stair facing uphill. Minecraft's neighbour rule (`subblock.stair_shape`) gives the corners.
   - This produces the standard patterns: 1:1 stair runs, 1:2 slab/full alternation, clean dome rings.
   - A column is touched only where the field's own surface agrees with the analytic height to within 0.75 block.
6. **Mirror symmetry.** If the block occupancy is mirror-symmetric (IoU > 0.9), the half that agrees better with the field is mirrored onto the other.
   - Shapes are mirrored too: stair facings swap, and left and right corners swap.
   - Hagia: an x mirror at 0.91 was applied; z scored 0.84 and was not.

Run: `python shape_fit.py NAME [--bpm 1] [--no-fit] [--no-height] [--no-sym] [--sheet _v2]`. Output is `art/NAME_shapefit.json` plus a report. View with `shape_view.py`, and compare with the drawing using `shape_compare.py NAME _v2 label=model ...`, which gives silhouette IoU and an elevation sheet.

### Hagia results
Renders:
- `out/hagia_elevations.png`: drawing vs old vs new, in front, right and top views
- `out/hagia_shapefit_views.png`
- `out/hagia_shapefit_close.png`

| | silhouette IoU vs drawing (front / right / top) | plan aspect error | blocks | look |
|---|---|---|---|---|
| old subblock (40 grid) | 0.884 / 0.821 / 0.953 | 26% | 30,653 | half-slab patchwork on every wall; dome rings broken |
| new, no fitting (1 m scale) | 0.898 / 0.840 / 0.955 | 25% | 25,883 | same patchwork: walls fall between blocks |
| new, fitted + snapped | 0.901 / 0.841 / 0.952 | 29% | 24,789 | walls on block edges; roofs and dome still per-block noise |
| **new, full** | 0.880 / 0.811 / 0.940 | 29% | 23,937 | walls on block edges, concentric dome rings, symmetric front and polygonal apse |
| hand build (benchmark) | 0.881 / 0.823 / 0.939 | 61% | 8,010 (hollow) | — |

What this shows:
- **The voxel stage now encodes the mesh cleanly, but outline agreement with the drawing doesn't move (0.88–0.90 for every version).** The remaining outline errors are already in the Hyper3D mesh:
  - The plan is 25% too square: the mesh is 34×38, while the drawing's top view and the real building are about 1:1.3.
  - The front half-dome, the stepped drum piers and the windows are smeared or missing in the 3,400-face mesh, though the drawing shows all of them clearly.
- **Stretching the whole mesh to the drawing's proportions (`--sheet`) is the wrong fix.** It corrects the plan (aspect error 25% → 0.4%) but turns the round dome into an ellipse. The sphere fit then fails and the dome top is flattened. The mesh is wrong part by part (the body is too short, the dome about right), not by one global scale.
- **The drawing views disagree with each other.** In the right view the depth:height ratio implies a plan about 1:1.08, while the top view gives 1:1.31. That's also why `ortho_verify` failed every sheet.
- **Thin parts are absent from the mesh**, so walls and fences correctly come out at zero on this subject. They will appear where the geometry has them (spires, finials, railings, tracery), and the vocabulary and connection rules are in place.

### Next
The voxel stage is no longer what loses the shape; the mesh is. To get the drawing's shape:
1. **Fit primitives to the drawings, not only the mesh** (the outline idea, using the drawings as the source):
   - Extract the plan outline from the top view (rectangle, apse arcs, the octagon with piers) and the elevation profiles from front and right (wall heights, roof lines, drum steps, dome profile).
   - Use them to place or correct the snapped primitives: a revolve for the dome and half-dome, polygon prisms for the drum and piers, extrusions for the apse.
   - Where the mesh and drawing disagree, the drawing wins for outline and the mesh only supplies depth.
2. **Surfaces of revolution with a fitted profile**, not only spheres, so domes, half-domes and drums are each one primitive with a profile curve read from the elevation.
3. **Pick the sheet by cross-view consistency** (front width = top width, right width = top depth) before the mesh step, so inconsistent sheets don't reach Hyper3D.
4. Then go back to block mapping, with `mc_map` reading the `s` shapes directly.

### Build (same day)
The Hagia now runs through the normal stages from the shape-fitted voxels: `palette_generic` (src `art/hagia_shapefit.json`), then `noise_measure`, then `mc_map`.
- Colours come from the painted model (`art/hagia_lowpoly_rendered_toned.json`), mapped back through the shape_fit transform, not from the raw mesh texture. The texture put roof grey down the walls.
- The previous build is kept as `hagia_p0_*` (JSON and schematics).
- Result: 23,624 blocks; partial blocks on the surface 26.9% (benchmark 26.6%); upside-down stairs 2.8%; overhang 6.7%; 90 block states; detail score 48.5 (was 32.1). Render: `out/hagia_shapefit_build.png`.
- `noise_measure` now fits the photo camera on the block grid (1.5 min instead of 28).
- `subblock.expand` rasterises any shape it doesn't know (stair corners, 3/16 pieces, walls, fences) from the real geometry.
- `mc_map` places shape_fit walls and fences.
- The viewer's `shapeToBoxes` now draws 3/16 pieces, corner stairs, and walls and fences with arms. It was checked against `shape_fit.boxes01` on all 87 shapes.
