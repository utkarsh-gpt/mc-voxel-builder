# What makes voxel art look good, how to measure it, and how to match an inspiration picture

Everything here lives in pipeline/. Minecraft block IDs are set aside: models are free-colour voxels
(hex palette). Mapping to blocks comes afterwards, using the existing voxel_ai.py.

## 1. Craft baselines (what good voxel art does)

| # | Principle | What it means in practice | Source |
|---|-----------|---------------------------|--------|
| 1 | **Silhouette first** | The outline against a plain background carries recognition. Block out big forms in 1-2 colours, fix proportions from front/side/top/3-4 views, *then* add detail. Separate parts slightly; don't merge everything into one mass. | MegaVoxels beginner + character guides |
| 2 | **Scale / resolution = budget** | Choose the grid so every feature you care about gets >=2-3 voxels. Small grid: exaggerate key features. Larger grid: needs longer colour ramps or it looks flat-banded. Curves are stepped (3-5-3 reads as round). | MegaVoxels; Adobe ramp guide (ramp length grows with canvas) |
| 3 | **Limited palette, value ramps** | Per material: base + shadow + highlight (3-5 steps), evenly spaced in value. Big value differences beat many near-identical shades. | Rick Chow workflow; MegaVoxels; Adobe |
| 4 | **Hue shifting** | Shadows shift cooler (blue/purple), highlights warmer (yellow), ~10-20 deg per step, saturation peaks in the midtones; never max saturation + max brightness on one swatch; every material shifts the same way (one light). | the-pixel.art, pixor.art, Adobe, OpenGameArt ch.5 |
| 5 | **Baked light + AO** | One consistent light direction: brighter up-facing edges, darker undersides, crevices and contact points. Voxel AO is per-vertex from the 3 neighbouring voxels (side1, side2, corner), which is what gives Minecraft "smooth lighting" its depth. | MegaVoxels; 0fps AO + voxel lighting |
| 6 | **Texture noise / dithering** | Organic materials get 2-4 close shades scattered per voxel (grass, bark, stone). Man-made surfaces stay flatter. Add the high-contrast micro-details the subject is known for (spots, pores, rivets). | briq guide; Voxify3D (palette-constrained colour) |
| 7 | **Edge detailing** | Avoid perfectly flat faces: 1-voxel lips, raised rims, insets for openings, roof overhangs, irregular outlines on organic forms. Use outlines/darker shades only where separation is needed. | MegaVoxels |
| 8 | **Depth and layering** | Overlapping planes and recesses create shadow shapes. Separate objects and volumes for editing. | MegaVoxels; briq |
| 9 | **Composition and focus** | One focal feature. Mostly muted palette with saturation saved for what matters. Symmetry, then deliberately break it. | Adobe; MegaVoxels |
| 10 | **Materials and lighting at render time** | Metal, emissive and glass materials and good render lighting make flat models rich without changing hue. | briq (MagicaVoxel materials) |
| 11 | **Readable from all angles** | Rotate constantly; check for holes, lopsided backs and shapes that vanish from above. | MegaVoxels |

## 2. Measurable rubric (scorer.py)

`python scorer.py REF.jpg MODEL.json --fit [--judge] --out out/name`
- Renders the model from the reference camera. The camera is the model's own `camera` field, refined with `--fit` by searching around it to maximise silhouette IoU + colour agreement.
- Writes `_compare.png` (reference | render | overlap), `_sheet.png` (6 views) and `_score.json`.

| Criterion | Auto metric (0-100 part score) | Weight |
|-----------|-------------------------------|--------|
| Silhouette | IoU of the reference mask vs the render mask. Both are bbox-cropped and letterboxed to 256 px. | .22 |
| Proportion | Aspect-ratio agreement, log-scaled | .08 |
| Big-shape structure | SSIM of blurred grayscale (light/dark layout) | .12 |
| Palette | Symmetric weighted nearest-ΔE between k-means Lab palettes (6 clusters) | .14 |
| Pixel colour | Mean ΔE76 over overlapping pixels | .10 |
| Shading layout | Correlation of L* between reference and render in the overlap | .10 |
| Integrity | Floating / disconnected voxels (26-connectivity) | .08 |
| Detail density | Surface colour variation (neighbour pairs that differ) × unique surface colours | .08 |
| All angles | Min/max silhouette area across 6 views (catches paper-thin models) | .08 |

The JSON also reports raw values: full SSIM, Lab histogram intersection, value range L*, bbox fill, component count and voxel counts.

**Vision-LLM judge** (`--judge`; prompt is `JUDGE_PROMPT` in scorer.py). Claude reads the reference, the compare strip and the 6-view sheet, then scores 1-10:
- likeness
- silhouette_proportion
- colour_fidelity
- shading_value
- surface_detail
- all_angles
- craft

It also gives an overall score and its 5 most impactful fixes, with coordinates.

Lessons from the demo:
- The auto score rewards the matched view. The judge is the only thing that sees the other angles.
- Absolute 1-10 judge scores are sticky (4/10 every round). Pairwise A-vs-B judging would rank iterations better; that's a next step.
- CLIP/DINO/DreamSim similarity is the missing "semantic likeness" metric. It needs torch, so it isn't installed yet.

## 3. Pipeline options for "inspiration image -> voxel art as close as possible"

| Option | Matched view | Other angles | Cost/infra | Verdict |
|--------|--------------|--------------|------------|---------|
| A. Image-to-3D (fal Trellis / Trellis 2 / Hunyuan3D v3.1 / TripoSR), then voxelize, then palette transfer from the reference | good geometry | **best**: a real learned 3D prior for the back | a few cents per model on fal; **fal balance is currently empty** | Best geometry source |
| B. LLM voxel JSON + vision-judge repair loop (demoed) | ok shape, weak colour/value | plausible but generic | Claude CLI only, ~1-2 min per call | Good for stylised/designed builds; plateaus on likeness |
| C. Differentiable voxel optimisation vs reference (DVGO-style density+RGB grid, Voxify3D palette Gumbel-softmax + CLIP) | best possible | needs multi-view targets or a 3D prior, else back/sides are free to be garbage | GPU + torch | Upgrade path once we have multi-view images |
| D. **Hybrid (recommended)**: geometry from A (or B as fallback), then deterministic fit-to-reference refine, then LLM craft pass for unseen sides, then rubric + judge loop | best | good | cheap | **Recommended** |

### Recommended pipeline (D)
1. **Geometry:** image-to-3D mesh (Trellis/Hunyuan3D) voxelized at the target resolution (`voxel_ai.py mesh`). If there's no fal balance, an LLM-primitive model instead (`loop.py` generation step).
2. **Camera fit** (`scorer.fit_camera`): search near the prior, using IoU plus colour agreement. Silhouette alone can't tell "seen from above" from "seen from below"; the first demo fit chose a top view of an underside photo.
3. **Fit-to-reference refine** (`refine.py`), with fixed grid framing:
   - silhouette carve/grow from the reference view;
   - project reference colours onto visible voxels (edge-eroded mask, grazing voxels ignored);
   - **render-and-compare colour correction**: nudge each voxel's Lab colour by (reference - lit render), 3 iterations, mean ΔE 20 → 7. This is a gradient-free analogue of differentiable rendering;
   - snap to a 16-colour palette taken from the reference.
4. **Craft pass** by the LLM for hidden sides: hue-shifted ramps, AO and contact shadows, rim lips, symmetry breaks. Feed in the judge fixes and the 6-view sheet.
5. **Score and loop:** auto rubric + judge each round, keep the best, stop when the combined score stalls.

## 4. Demo (reference: Wikimedia Commons "Mushroom on white background.jpg", public domain)
`python loop.py refs/mushroom.jpg --name mushroom --iters 2` (Sonnet generator + judge), then `python refine.py ...`

| Version | Auto | Judge | Silhouette IoU | Low-freq SSIM | Pixel ΔE | Palette ΔE | L* corr |
|---------|------|-------|----------------|---------------|----------|------------|---------|
| hand-made naive (ellipsoid + cylinder) | 72.3 | - | .927 | .73 | 22 | 13 | .42 |
| v0 Sonnet first try | 76.0 | 4 | .907 | .67 | 23.7 | 11.5 | .09 |
| v2 after 2 judge-repair rounds | 79.8 | 4 | .875 | .70 | 23.6 | 12.5 | .58 |
| v2 + refine.py | **88.5** | 4 | .925 | .84 | 14.0 | 8.6 | .84 |

The naive row's numbers come from `out/naive_score.json`.

- Before/after strip: `out/mushroom_before_after.png`
- Per version: `out/mushroom_{v0,v1,v2,refined}_{compare,sheet,render}.png` and `_score.json`

Takeaways:
- The LLM loop improves shading (L* correlation .09 → .58) but plateaus on likeness.
- The deterministic refine closes most of the gap in the matched view (pixel ΔE 24 → 14).
- **But** projection leaks some pale reference colours onto rim voxels that show from other angles; see the sheet. The judge still says 4/10 because:
  - the stem is too short and straight;
  - the cap is a symmetric dome where the photo shows a tilted, bun-shaped cap;
  - there's no pore texture.

  These are geometry problems that need option A's 3D prior or a stronger, LLM-guided geometry edit.
- A naive primitive already scores 72 automatically, so automatic scores only become meaningful above ~80. Weight the judge and all-angle checks more.

## 5. Going further
1. **Top up fal** (Trellis 2 / Hunyuan3D multi-view): biggest jump in geometry and hidden sides. Then pipeline D end to end.
2. **Projection guard:** only project onto faces whose normal faces the camera (dot > 0.5). Inpaint the hidden side from the LLM/hue-shifted ramp so pale rim leaks disappear.
3. **Pairwise judge** (A vs B, which is closer) instead of absolute scores. Add a DINOv2/CLIP/DreamSim similarity term (CPU torch install, ~1 GB).
4. **Multi-view targets:** generate 4-6 consistent views from the reference with a multi-view diffusion model, or render the image-to-3D mesh. Then do differentiable voxel optimisation (DVGO + Voxify3D palette quantisation) on a GPU.
5. **Style pass presets:** hue-shift ramp generator, AO bake, outline, 1-voxel rim lips, applied after fitting.
6. Then map the palette to Minecraft blocks (`voxel_ai.py` colour matching) and add guardrails.

Cost of this demo: about 7 Sonnet CLI calls (3 generate/revise + 4 judge) and roughly 10 min wall time. No fal spend; fal has no balance.

## Links
- MegaVoxels beginner tutorial: https://www.megavoxels.com/learn/magica-voxel-beginner-tutorial/
- MegaVoxels voxel characters: https://www.megavoxels.com/learn/how-to-create-voxel-characters/
- MagicaVoxel to Unity asset workflow (Rick Chow): https://rickchow.info/blog/magicavoxel-to-unity-workflow/
- briq beginner's guide: https://www.briq.market/articles/how-to-start-creating-voxel-art
- Hue shifting (the-pixel.art): https://the-pixel.art/articles/hue-shifting-pixel-art-shading/
- Hue shifting (pixor.art): https://pixor.art/learn/hue-shifting/
- Adobe pixel-art palette guide: https://www.adobe.com/uk/products/firefly/discover/pixel-art-colour-palette.html
- OpenGameArt colour palettes chapter: https://opengameart.org/content/chapter-5-color-palettes
- 0fps voxel AO: https://0fps.net/2013/07/03/ambient-occlusion-for-minecraft-like-worlds/
- 0fps voxel lighting: https://0fps.net/2018/02/21/voxel-lighting/
- Voxify3D (pixel art meets volumetric rendering): https://arxiv.org/abs/2512.07834
- DVGO (direct voxel grid optimisation): https://arxiv.org/abs/2111.11215
- ShaRF (single-view voxel scaffold + radiance field): https://proceedings.mlr.press/v139/rematas21a/rematas21a.pdf
- Pixel art to voxel reconstruction (TU Delft thesis): https://repository.tudelft.nl/file/File_d2a3ecff-c884-4ac5-8897-4563e770a8eb
- 2DtoVoxel (Claude writes a build script, scores against the image, iterates; closest existing project): https://github.com/NangManCatDev/2DtoVoxel
- fal Trellis: https://fal.ai/docs/model-api-reference/3d-api/trellis
- fal Hunyuan3D v3.1 Pro: https://fal.ai/docs/model-api-reference/3d-api/hunyuan-3d-v3.1-pro
- fal 3D overview: https://fal.ai/docs/model-api-reference/3d-api/overview
- Reference image (public domain): https://commons.wikimedia.org/wiki/File:Mushroom_on_white_background.jpg

## 6. Batch run: 6 subjects, no fal (run_subject.py)
Pipeline per subject, using 4 Sonnet calls:
1. Sonnet makes the v0 shape.
2. Sonnet judges v0.
3. Sonnet does a craft/repair pass, giving v1.
4. `refine.py` runs (no Sonnet call): camera fit, silhouette grow/carve, photo projection limited to voxels whose smoothed surface normal faces the camera (cos >= 0.5), render-compare colour correction, and a 16-colour palette.
5. Sonnet judges the refined model.

Subject masks come from rembg isnet-general-use (`refs/<name>_mask.png`).

| Subject | v0 auto / judge | refined auto / judge |
|---------|-----------------|----------------------|
| cottage | 82.4 / 4 | 83.9 / 4 |
| lighthouse house | 70.8 / 3 | 79.5 / 4 |
| windmill | 64.0 / 4 | 74.7 / 4 |
| teapot | 75.6 / 4 | 85.5 / 4 |
| bonsai | 64.8 / 4 | 72.4 / 5 |
| lantern | 37.2 / 2 | 82.3 / 5 |

- Files: `out/gallery.png`, `out/<name>_before_after.png`, `out/<name>_turntable.png`, `out/<name>_summary.json`.
- Models: `art/<name>_{v0,v1,refined}.json`.

## 7. fal Trellis shape stage (run_fal.py), replacing the Claude shape
Pipeline per subject:
1. Masked reference goes to fal Trellis ($0.02 per mesh), then voxelized at 40 on the longest side with fill. Colours are sampled from the Trellis texture, then Lab mean/std-matched to the reference.
2. Camera fit with `fit_cardinal`. Trellis's front lands on any one of the 4 cardinal directions, so the fit searches all four. An unconstrained 360 search picked wrong optima, such as the bonsai seen from the top.
3. Then `refine.py` (same texturing as before) and the Sonnet judge.

| Subject | OLD Claude-shape refined (auto / judge) | fal raw voxels (auto) | NEW fal + refine (auto / judge) | camera az,el |
|---|---|---|---|---|
| mushroom | 87.3 / 4 | 84.2 | 88.8 / 5 | 55,-19 |
| cottage | 83.9 / 4 | 80.4 | 86.2 / 4 | 105,1 |
| lighthouse | 79.5 / 4 | 74.0 | 78.9 / 3 | 80,-4 |
| windmill | 74.7 / 4 | 67.1 | 72.9 / 3 | 257,-23 |
| teapot | 85.5 / 4 | 82.6 | 85.3 / 3 | 0,-30 |
| bonsai | 72.4 / 5 | 58.8 | 69.4 / 3 | 338,-10 |
| lantern | 82.3 / 5 | 76.4 | 80.5 / 4 | 317,-14 |

Spend: 8 Trellis calls (7 + 1 bonsai retry) at about $0.16, plus 1 Hunyuan3D v3.1 Pro bonsai retry at $0.375. About $0.54 total.

Notes:
- **Thin parts and outlines are much better.** The windmill now has real X-shaped sails in 3D and a tower on legs. The cottage roof is now low, wide thatch instead of a stepped pyramid. The mushroom stem is now slender and curved.
- **Auto and judge scores barely moved, or dropped.** Trellis textures are dark and noisy, and photo projection only fixes the side facing the reference camera. The judge penalises the muddy hidden sides and the noisier surface.
- **Bonsai failed on fal.** Trellis, a Trellis retry on the raw photo, and Hunyuan3D all dropped the wispy canopy. The meshes contain only the trunk and pot, plus a floating blob in Hunyuan's case.
- Next step: colour hidden voxels from the reference palette with hue-shifted ramps instead of the Trellis texture, and add 2-4 more reference views (Hunyuan multi-view inputs) for back sides.

## 8. Shape-first: orthographic views -> voxels (windmill, cottage, bonsai)
Pipeline: `ortho_gen.py` (fal `nano-banana/edit`, one 2x2 ortho sheet front/right/back/top on white, split to `ortho/<n>_{front,right,back,top}.png`)
-> either `ortho_carve.py` (visual hull, flip search, front-priority silhouette completion, flat k=14 palette)
or `ortho_hunyuan.py` (fal `hunyuan-3d/v3.1/pro/image-to-3d` multi-view: front+back+right+top -> GLB -> 48 grid).
Gallery `out/ortho_gallery.png` (reference | sheet | front | side | back | 3/4), turntables `out/<model>_turntable.png` (6 azimuths + top + low),
reprojection IoU vs the ortho masks in `out/ortho_reproj_iou.json`.

| model | IoU F/B/side (mean) | verdict |
|---|---|---|
| windmill_hymv | .78/.75/.72 (.75) | **pick** - round tower, 4 legs/arches, 4 sails, cap; reads from every angle. Ground ring from the drawn top-view circle removed by a footprint filter. |
| windmill_ortho (carve) | .79/.81/.87 (.82) | boxy tower; AI top view is a disk so it can't carve; messy at 3/4 |
| cottage_ortho (carve) | .93/.97/.88 (.93) | **pick** - good from all sides (hipped thatch, chimney, door/windows); a bit block-like |
| bonsai_hymv | .88/.88/.79 (.85) | **pick** - dome canopy, curved trunk, pot; best 3/4 |
| bonsai_v2_ortho (carve) | .93/.93/.95 (.94) | matches the views but canopy is a cube at 3/4 (hull can't round off convex corners) |
Lessons: carving wins IoU by construction but over-fills the corners between views; Hunyuan MV gives rounder, more plausible solids.
AI top views are unreliable (X'd sails, circles). Main fidelity loss is now in the sheet step: nano-banana redraws a cleaner/simpler subject
(the windswept bonsai became a compact dome; the cottage became a tidy hip-roof cottage), so shape matches the sheet better than the photo.
Spend this phase: 5 x nano-banana (~$0.20) + 2 x Hunyuan MV ($0.75) = ~$0.95.

## 9. Rendered voxels from ortho drawings (all three on Hunyuan3D-MV shapes)
Cottage now also on `hunyuan-3d/v3.1/pro` multi-view (`art/cottage_hymv.json`, first try, no retry).
`ortho_paint.py NAME [TAG]`: solidify the Hunyuan shell (3D fill of 1-dilated copy + per-slice ring fill for open towers, drop floaters);
smoothed normals (gaussian 1.6); views front/right/back/top + **left = mirrored right drawing**; each drawing is rembg-masked, bbox-fitted
to the voxel projection (mirror chosen by IoU; view rejected if IoU < 0.6, e.g. windmill top disc), background filled with nearest eroded-mask
colour, box-downsampled to the grid; per surface voxel take the visible (first-hit) view with the best normal facing (>= 0.35), else Hunyuan's
texture (bottoms, deep crevices). Then k=12 Lab palette + a darker crevice step (lowest-12% openness) = 22-24 colours.
`tone_to_ref.py`: 60% Reinhard Lab transfer of the palette toward the photo (warmer stone, bluer sails, brighter greens) -> `art/<n>_rendered_toned.json` (final).
Renders use a top-front key light (-0.25, 0.8, 0.55) + renderer AO. `ortho_rendered.py` -> 8-angle turntables, scores, `out/ortho_rendered_gallery.png`.

Coverage from drawings: windmill 76%, cottage 73%, bonsai 58% of surface voxels (rest = Hunyuan texture). No muddy hidden sides any more.
| subject | auto (toned / untoned / Hunyuan tex) | judge toned / untoned | old Claude+refine | old Trellis+refine |
|---|---|---|---|---|
| windmill | 77.9 / 77.2 / 77.1 | 4 / 4 | 74.7, 4 | 72.9, 3 |
| cottage | 66.4 / 67.8 / 66.8 | 4 / 4 | 83.9, 4 | 86.2, 4 |
| bonsai | 69.8 / 69.1 / 69.2 | 4 / 5 | 72.4, 5 | 69.4, 3 |
Scores are vs the *photo*; the shape follows the nano-banana sheet, which redraws the subject (cottage -> compact steep hip roof instead of the
long low thatch; bonsai -> symmetric dome, brown pot instead of oxblood). Old versions were refined directly against the photo from that one
camera, so they win per-view auto (cottage) while looking bad from other angles. Judge feedback: sails are solid slabs (want lattice), colours
still a bit dull, cottage roof too tall/striped, bonsai pot colour/trunk. Next lever: make the sheet faithful to the photo (stronger prompt / reference
colours), then the mushroom-style render-and-compare colour refine on top of these shapes.
Spend this phase: 1 x Hunyuan MV = $0.375 (cumulative fal for sections 8-9 ~ $1.32); 6 Sonnet judge calls.

## 10. (A) Tuned ortho sheets - BLOCKED
fal returned "User is locked: Exhausted balance" on the first nano-banana call (no sheet produced, $0 spent this phase).
Prepared: `ortho_gen.py --with-photo` (passes the full photo as a 2nd reference image) and `ortho_tuned.sh` with photo-exact prompts
(windmill arcade/dome/white lattice sails, top view = disc + one bar; cottage long-low thatch 3:1, no props; bonsai umbrella canopy 2:1,
S-trunk Y-fork, oval oxblood pot). Needs ~$1.24 of fal after a top-up; `out/ortho_tuned_gallery.png` not produced yet.

## 11. (B) Mixed-resolution sub-blocks (half-size builds) - `subblock.py`, `subblock_gallery.py`, `subblock_score.py`
Fine grid = 4x target (96 for a 24-block build) voxelised from the existing Hunyuan GLBs, solidified, masked by the cleaned full-size model;
colours = nearest surface voxel of `art/<n>_rendered_toned.json`. Per 4x4x4 block: Hamming error vs 21 templates
(full | slab 1/2,1/4 bottom/top | vslab 1/2,1/4 along x or z flush to one side | stairs N/S/E/W bottom/top; one-axis cuts only, no quarter-cubes).
Partial shapes allowed only if 0.1<fill<0.9 and smoothed normal not axis-aligned (max |n| <= 0.92) and gain > lambda=10 fine voxels;
exception: thin plates (fill >= 0.12 that would round to empty, e.g. sails) may become slabs/vslabs. Flat areas stay full blocks.
JSON: voxel `s` = {"type":"slab","size":0.5,"align":"bottom"} / {"type":"vslab","size":0.25,"axis":"z","align":"south"} /
{"type":"stairs","facing":"north","half":"top"}; absent = full block. +x=east, +z=south (front). `*_half_sub_fine.json` = exact 4x expansion for render/score.

| subject | grid full -> half | sub-blocks % of blocks (% of surface) | sil. IoU vs full size: full-only / sub | auto full48 / half full / half sub | judge full48 / half full / half sub |
|---|---|---|---|---|---|
| windmill | 47x48x34 -> 24x24x17 | 42.0 (58.8) - mostly sail vslabs | 0.581 / 0.878 | 77.9 / 53.3 / 78.2 | 4 / 2 / 3 |
| cottage | 48x30x34 -> 24x15x17 | 12.1 (30.0) | 0.914 / 0.909 | 66.4 / 66.5 / 66.9 | 4 / 4 / 4 |
| bonsai | 48x48x46 -> 24x24x23 | 22.9 (39.2) | 0.900 / 0.929 | 69.8 / 70.0 / 69.5 | 4 / 4 / 4 |
(half-sub auto uses the colour-detail metric from the block grid; on the 4x expansion it is artificially 20/100 - raw 72.3/60.7/63.1.)
Verdict: big win where thin/curved parts would vanish (windmill sails kept, auto 53 -> 78, matches full size); bonsai dome, pot rim and trunk
visibly smoother; cottage roof gets half-steps/stairs on the hips but no measurable gain (Hunyuan's thatch is terraced). Windmill % is high only
because the sails are 1-2 fine voxels thick and are built from vslabs; cottage and bonsai use 12-23%.

## 12. Tuned pass (tuned sheets -> Hunyuan MV -> ortho colour + tone -> half-size sub-blocks)
Sheets (`ortho_gen.py --with-photo`, photo-exact prompts from `ortho_tuned.sh`): `ortho/windmill_t2_sheet.png` (retry; first `_t` had X-sails in
side/top), `ortho/cottage_t_sheet.png`, `ortho/bonsai_t_sheet.png`. New `ortho_clean.py` crops panel frames/labels (raw kept as `*_raw.png`);
`ortho_carve.mask_of` now unions rembg with a filled non-white mask (white walls on white page) and opens away thin ground lines.
Hunyuan MV: windmill front+back+top (side view still had X sails, so skipped for shape and colour), cottage/bonsai all 4 views.
`ortho_paint.py` now: tag-aware keys, `--skip=VIEW`, near-white "page bleed" samples replaced by Hunyuan colour unless Hunyuan is also white.
`subblock.py` now: block colour = majority of full-size surface colours in the block footprint (less speckle); cleanup drops dangling
sub-blocks (<= 1 neighbour, non-sail) and pieces < 1% of the model (the stray-vslab fix; 0/0/1 removed this pass).
Gallery `out/tuned_pass_gallery.png`, scores `out/tuned_pass_scores.json`.

| subject | half grid | sub-blocks | auto | judge | notes |
|---|---|---|---|---|---|
| windmill | 23x24x12 | 39.5% (mostly sail vslabs) | 68.2 | 3 | sheet now photo-like (stone, blue/white lattice sails, dome); voxel: 4 sails + dome + legs, but tower colours mottled dark/blue and the arches don't read at half size |
| cottage | 24x14x13 | 13.3% | 65.3 | 4 | no props now, white walls, red door/window under eyebrows, green-grey thatch with stair/slab hips; still too short/tall vs the long-low photo (sheet came out ~1.3:1, not 3:1) |
| bonsai | 23x24x24 | 24.2% | 75.9 | 4 | biggest gain: oxblood oval-ish pot, visible orange trunk, umbrella canopy with slab-smoothed dome; foliage a bit olive, a few pale specks remain |
Spend this pass: 4 x nano-banana ($0.16) + 3 x Hunyuan MV ($1.125) = ~$1.28.

## 13. Verification layer + Hyper3D low-poly (only this pass shown: `out/verified_lowpoly_gallery.png`)
**Cost correction:** Hunyuan v3.1 Pro charges +$0.15 for multi-view input, so every Hunyuan MV call so far was **$0.525**, not $0.375
(fal model page llms.txt). Corrected: sections 8-9 = ~$1.77 (not ~$1.32); section 12 tuned pass = ~$1.73 (not ~$1.28, i.e. over its $1.50 cap).

**(1) `ortho_verify.py`** - per sheet attempt: (a) geometric checks on cleaned masks (heights front/side/back within 12%, widths front/back/top
within 12-15%, side depth vs top depth within 15%, front vs mirrored-back silhouette IoU >= 0.75); (b) haiku vision check via claude CLI
(sheet + photo -> JSON pass/bad_views/issues). Fail -> regenerate with the issues appended (max 3 sheets, $0.039 each), keep the best attempt,
drop bad views. (Superseded in section 16: the Sonnet second opinion `ortho_verify_confirm.py` is retired; step 3 is Haiku-only.)
`ortho_clean.py` frame detection fixed (frames touching the object were missed, which also inflated some geometric sizes).
Results: windmill - all 3 attempts caught the side-view sail error (X / bars at both edges / bar in the middle) and the bad top view;
chosen v2, used front+back. Cottage - v1/v2 props + height/depth mismatches; v3 geometry passed, sonnet confirmed the side view is inconsistent
(pointed apex vs long ridge) -> front/back/top. Bonsai - v1/v2 oblique top view (pot visible), v3 side canopy tilted; chosen v2 front/right/back.
No sheet fully passed in 3 tries (haiku is strict), so the "drop bad views" fallback was used for all three.

**(2) `ortho_lowpoly.py`** - fal `hyper3d/lowpoly/image-to-3d` ($0.20/gen; 1-5 images with view labels F/R/B/U; face_count 4000; Shaded
material = colour in the emissive texture, now read by `fal_shape.voxelize`). `subblock.py --close` closes gaps in thin low-poly shells (bonsai: 4).
| subject | auto / judge (low-poly) | auto / judge (Hunyuan Pro, sec 12) | pipeline cost per subject low-poly vs Hunyuan Pro | sub-blocks |
|---|---|---|---|---|
| windmill | 67.4 / 4 | 68.2 / 3 | $0.32 (3 sheets + $0.20) vs ~$0.60 | 31.8% |
| cottage | 66.8 / 4 | 65.3 / 4 | $0.32 (+$0.40 spent on 2 A/B runs) vs ~$0.56 | 14.5% |
| bonsai | 69.4 / 4 | 75.9 / 4 | $0.32 vs ~$0.56 | 32.3% |
Verdict: windmill better (sails on the front face and edge-on in the side view, judge 3 -> 4); cottage about equal (walls + hipped thatch, a bit boxier;
with only front+back the low-poly model left the sides open - the drop policy needs at least a side or top view); bonsai worse (low-poly canopy is a thin
terraced shell, dark gaps remain even after closing). Spend this pass: 9 sheets $0.35 + 5 low-poly runs $1.00 = ~$1.35.
Final viewer files: `art/final/{windmill,cottage,bonsai}_voxels_subblocks.json` (+ `_fine.json`), format in `art/final/FORMAT.md`.

## 14. Texturing + colour pass (base colours -> brightness ramps -> gradient blends) - `palette_texture.py`
Only this pass is shown: `out/textured_pass_gallery.png` (reference | front | side | back | 3/4). Scores: `out/textured_pass_scores.json`.
Rules: `TEXTURE_RULES.md` (designed by an Opus worker; implemented here). Shapes and sub-block `s` fields are unchanged; only colours change.

Research used (how Minecraft builders use colour; output stays plain voxel colours, no block mapping):
- https://voxyl.xyz/guides/gradients-and-wear.md - ramps of 3-5 shades ordered light->dark, value first; place variation by cause (damp, soot, overhang); clusters, never "smallpox" speckle or sandwich bands.
- https://palettinator.com/articles/minecraft-block-gradient-guide - main/darker/lighter trio; clustered beats scattered or banded; soften edges with the middle shade; leave quiet areas.
- https://www.ardacraft.me/resources/gradient-guide - value > colour > texture; never skip a gradient step; blob-shaped weathering.
- https://www.minecraftmaps.com/tools/wall-pattern-generator - stay in one colour family; keep odd blocks under ~15%.
- https://minecraft.wiki/w/Tutorial:Color_palette - pick primary materials first; contrast for frames/trim; gradients of 3-4 shades of one colour.

Colour rules chosen:
1. Zones by geometry first (colour only breaks ties): windmill stone / slate cap / white sails / dark hub+windows; cottage white wall / thatch / moss / red door+frames / brick chimney; bonsai foliage / trunk / oxblood pot / soil / moss.
2. One base colour per material (photo-based, de-baked: e.g. windmill cap navy #102c45 -> slate #4f555c, cottage wall #8e8c8c -> #e6e3dc).
3. Ramps: 3-5 shades, ~5-8 dE apart; lights shift warm (toward yellow), shadows shift cool (toward blue); whites only get +1, darks only -1.
4. Placement score = openness/AO + up-facing + height + sun direction + low-frequency 3D cluster noise + cause terms (damp foot, soot round the chimney, under-eave/overhang shadow, sun-bleached ridge, drip shadow under ledges, lit pot rim, dark canopy underside). Quantiles keep ~75-82% of each material on its base shade.
5. Cleanup: no isolated accent voxels, accent clusters >= 3, neighbours never jump more than one shade (anti-splatter).
6. Gradient blends between BLEND pairs (stone<-cap, wall<-thatch, thatch<-chimney, thatch<-moss, trunk<-soil, trunk<-foliage, soil<-moss): Lab-interpolated chain whose length comes from the colour gap (dE/11 - 1, max 3), noisy distance so the edge is ragged, step-checked so no chain step is skipped. No fixed depth (per t128u); a blend may not swallow more than 1/3 of a short part (the cottage wall is 3 voxels tall). CRISP pairs (sails, door/glass, pot/soil) stay hard-edged.
7. Palette merge at dE2000 < 2. Final palettes: windmill 12, cottage 18, bonsai 21 colours.
8. Optional photo mean shift (`photo_match.py`, 50%, mean only so ramp contrast survives) applied to cottage and bonsai; skipped for the windmill because its photo mask includes sky seen through the sails (it pulled the stone blue).

Scores (auto /100, Sonnet judge /10; same scorer, block-grid colour-detail correction):
| subject | before (current final) | textured pass | note |
|---|---|---|---|
| windmill | 67.4 / 4 (low-poly) | 62.6 / 3 | lab-histogram match fell (0.47 -> ~0.21): the old palette was 60% Reinhard-toned to a photo full of sky blue; judge complaints are mainly shape (solid sails, fused arches) |
| cottage | 66.8 / 4 (low-poly fbt) | 68.1 / 4 | pixel dE 24.0 -> ~17; judge colour 5-6, asks for taller walls / flatter roof (shape) |
| bonsai | 69.4 / 4 (low-poly); 75.9 / 4 (same Hunyuan shape, tuned pass) | 71.6 / 5 | judge up 4 -> 5 (likeness 6); auto below the tuned-pass colouring of the same shape (histogram 0.56 -> ~0.43) |
Takeaway: the ramp/gradient stage reads as more "built" to the judge (cleaner materials, real red door, moss, chimney soot, lit pot rim) but the auto metric rewards photo-histogram matching, which the old toning maximised. Shape is now the main limit for all three.
Review gate (Opus) found 10 issues (wrap-around in cleanup, tie case in anti-splatter, moss removal, arch->window misclass, min-size not enforced, bonsai edge cases, missing blend step check, dE76 vs dE2000, sub-block weight default); all fixed before the final run.
Not implemented: anti-sandwich layer re-quantise (no bands observed in renders); cottage glass panes (no dark clusters matched the rule).
fal spend this phase: $0. Final files: `art/final/{windmill,cottage,bonsai}_voxels_textured.json` (+ `_fine.json`); the bonsai uses the Hunyuan shape `art/bonsai_t_half_sub.json` (organic rule).
Viewer: dropdown grouped by subject (Windmill, Cottage, Bonsai, then alphabetical), textured finals featured; deployed to https://voxel-viewer-ten.vercel.app.

## 15. Minecraft block pass (image noisiness + art-technique classes) - `mc_map.py`
Only this pass is shown: `out/mc_blocks_gallery.png` (reference | previous textured colours | MC blocks front/side/back/3/4 with real 26.3 textures).
Rules: `MC_BLOCK_RULES.md`. Scores: `out/mc_blocks_scores.json`. Outputs: `art/final/{n}_mc_blocks.json`, schematics in `art/final/schematics/`.
- Dataset additions (`mc-blocks/add_pattern_metrics.py` -> `blocks.json` `pattern.*`, `blocks.csv` `pattern_*`/`tech_*`): orientation
  coherence, line orientation/period, grain wavelength, hf energy, and six technique scores (hatching, cross_hatching, stippling, scumbling, glazing, outline).
- Image noisiness (`noise_measure.py` -> `art/final/meta/{n}_noise.json`): per (material, height band) local L* std in a 1-voxel window,
  hf ratio and pattern wavelength on the photo (fitted camera) and the front ortho view; 0.7/0.3 mix; target block spread = 0.5 x image value.
- Mapping: cost = dE2000 + 1.2 noise mismatch + 4 (1 - technique score) + family prior; technique may not cost more than +8 dE; ramps grown from
  the base along the dataset's gradient chains / nearest graph, monotonic, <= 15 dE per step, <= 5 blocks per material.
- Shapes: slabs keep their type; 0.25 plates -> trapdoors where the family has one and it matches colour; half-width vertical pieces and stairs -> full blocks.
- Review gate (Opus) found 9 issues (crash on empty pools, trapdoor colour check, half-width vslab volume loss, ramp monotonicity per step,
  blend slot keys, slab fallback scope, noise window used grid height); all fixed before the final run. fal spend $0.
- Caveats: technique classes come from automatic texture analysis (cobblestone reads as stippling rather than scumbling, bricks as hatching);
  few outline-type blocks exist in the material families, so trim mostly falls back to colour. Schematics are written with DataVersion 4325
  (1.21.5); 26.3-only blocks (poplar, sulfur, cinnabar...) need a 26.3 world.
Scores (auto /100, Sonnet judge /10), previous textured pass -> MC blocks: windmill 62.6/3 -> 67.2/3; cottage 68.1/4 -> 67.6/4; bonsai 71.6/5 -> 69.3/4.

## 16. Cost cut + stairs pass (2026-11-22)
- **Step 3 verification is Haiku-only.** `ortho_verify.py` pins `VERIFY_MODEL = "claude-haiku-5-5"` (the newest Haiku Claude Code accepts; `haiku` alias resolves to it). The Sonnet confirm pass (`CONFIRM_PROMPT`/`confirm_view`, `ortho_verify_confirm.py`) is removed; the script was moved to `attic/`. Geometry checks + drop-bad-views fallback unchanged. Sanity run on the existing windmill sheet `ortho/windmill_v2_sheet.png` (no regeneration): Haiku alone returns `bad_views: [right, top]` and names the side-view sails ("two outward-tilted bars ... must be edge-on"), cost $0.0071 (`out/windmill_haiku_only_sanity.json`).
- **Stairs in the dataset.** `mc-blocks/add_stairs.py` adds all 97 vanilla stairs (blocks.json/CSV now 591 entries); stats copied from the same-texture block, plus `stairs.props` (facing/half/shape) and `stairs.source_block`.
- **Stair detection** (`subblock.stairify`, called by `mc_features`): a top-open voxel becomes a bottom stair facing d when the neighbour toward d and the cell above it are solid and the -d side is open (mirrored for upside-down stairs under eaves); shape from Minecraft's own neighbour rule (straight/inner/outer). Sails, glass, doors and dark details are skipped.
- **mc_map**: stairs use the same-texture stair of the voxel's block, else the closest ramp/family block with stairs (<= 8 dE). `mc_render.boxes` emits real stair geometry; bake, preview and viewer use it (the viewer already draws palette boxes and shows the blockstate on hover, so no UI change was needed).
- **Windmill warm stone.** No vanilla stone sits at the photo's warm-limestone tone (~#A89F8C), so 20% of the plain/rough full stone blocks are dithered to `packed_mud` (low-contrast warm accent); the wall's mean moves from 9.4 to 7.1 dE of the warm target.
- Stairs placed: windmill 51, cottage 144, bonsai 64 (182 more bonsai foliage candidates have no stair-capable block within 8 dE, so they stay full).
- Scores (auto / Sonnet judge, one pass): windmill 67.2/3 -> 69.0/3, cottage 67.6/4 -> 68.1/4, bonsai 69.3/4 -> 69.9/4. Judge cost $0.224 (claude-sonnet-5-5).

## 17. New reference set: cathedral, landscape, turtle (2026-11-23). Only this pass is shown: `out/new_set_mc_blocks_gallery.png`

**Subjects:** new nano-banana refs written by `gen_refs.py`.
- Gothic twin-spire cathedral in warm limestone.
- Coastal headland terrain diorama: the landscape, built at a larger scale.
- Coral-encrusted sea turtle: the organic subject.

| subject | 3D route | blocks W×H×D | blocks | block ids | stairs | slabs | trapdoors | auto | judge (Sonnet) |
|---|---|---|---|---|---|---|---|---|---|
| cathedral | Hyper3D low-poly (front+right verified views, GLB rotated 180°) | 13×26×32 | 3,916 | 14 | 120 | 36 | 0 | 68.7 | 3 |
| landscape | Hyper3D low-poly (front+top) | 56×18×51 | 43,640 | 38 | 248 | 633 | 2 | 70.3 | 3 |
| turtle | Hunyuan v3.1 Pro multi-view (front+top) | 27×11×30 | 2,073 | 29 | 165 | 31 | 28 | 73.8 | 3 |

- **Landscape scale:** its footprint is about 2,856 columns. That is about 6.9× the cathedral's and 3.5× the turtle's, and it has 11× the cathedral's block count. It is shorter than the cathedral (18 vs 26 tall), because terrain is wide and the cathedral is tall.
- **Old set, for reference:** windmill 69.0/3, cottage 68.1/4, bonsai 69.9/4.
- **Raw scores:** `out/new_set_scores.json`.

**Shape changes**
- `ortho_clean.normalize_bg()` removes black padding bars and a grey page background, and `ortho_carve.mask_of` drops frame lines of 8 px or thinner. Cathedral front mask IoU went from 0.24 to 0.69.
- `ortho_verify`: added `--start` to continue a run. If fewer than 2 views would remain, it re-admits views that only Haiku flagged but that pass the geometry checks.
- `subblock --keep-thin`: a cell crossed by thin material is kept as a partial or full block instead of being dropped. thin_kept: cathedral 278, landscape 290, turtle 121. This applies to spires, branches and flippers.
- The sub-block colour grid now follows the model size (it was a fixed 48), so the large landscape keeps its detail.

**Colour changes**
- `palette_generic.py`: base colours are measured from the photo per material, with a hue/chroma guard against polluted bases. Context rules handle windows, foam near water, and coral/algae accents.
- `mc_map`:
  - STRICT material families, so wood is never used for stone.
  - SAT_CAP: a block may not be more saturated than 1.6·C+8. This stopped garish yellow terracotta.
  - The low-contrast accent dither (the windmill "mud" decision) is extended to every material. An accent needs |ΔL| ≤ 12, dE ≤ 20 and a hue check, so it never greys out the material.
  - `grass_block` is placed wherever the grass layer is open to the sky (1,682 blocks).
  - `place()` is memoized, cutting landscape mapping from about 770 s to about 5 s.
- Results:
  - cathedral: white_terracotta + 20% chiseled_sandstone, slate roof, blackstone accents in the windows
  - landscape: smooth_stone/cobblestone, chiseled_sandstone bands, grass_block tops over lime_concrete/wool
  - turtle: acacia_log + jungle_log shell, smooth_stone + white_terracotta skin

**What the judge said is still weak (next targets)**
- **cathedral:** reads pinkish-beige rather than honey sandstone; spires are stepped lumps; the windows read as holes.
- **landscape:** the turquoise cove and the waterfall are almost missing; strata are not continuous bands.
- **turtle:** flippers are stubs; the head is unreadable; there are too few coral and fan sprigs.
- Shape is now the limit, more than colour. The fix is higher resolution on thin features plus explicit window and rose-window carving, which ties into the glass plan in `TRANSPARENT_BLOCKS_PLAN.md`.

**Viewer**
- Deployed with `sync.sh` (https://voxel-viewer-ten.vercel.app); all 3 appear as Featured tiles.
- `sync.sh` now skips files over 95 MB. Vercel has a 100 MB limit, and the landscape's two 1/8-block `_fine` passes are about 110 MB each.

**Spend**
- fal $1.393, broken down below. This is from the price list (fal billing was not checked):

  | item | count | unit price | total |
  |---|---|---|---|
  | nano-banana refs | 3 | $0.039 | $0.117 |
  | ortho sheets | 9 | $0.039 | $0.351 |
  | Hyper3D low-poly | 2 | $0.20 | $0.40 |
  | Hunyuan Pro multi-view | 1 | $0.525 | $0.525 |

- Haiku: 9 verification calls, about $0.06 (estimated, not metered).
- Sonnet judge: $0.165, metered.
- claude-ui: not used.
