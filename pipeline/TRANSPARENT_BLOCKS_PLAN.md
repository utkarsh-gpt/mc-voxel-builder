# Transparent blocks (leaves, glass): plan only, nothing implemented yet (2026-11-23)

## Current state
- `mc-blocks/excluded.json` currently excludes 14 `leaves` and 35 `glass` ids (glass, tinted_glass, 16 stained glass, plus the panes).
- Leaves: `biome_tinted` blocks are rejected by `mc_map.allowed()`. `grass_block` is the only exception (`NATURAL_OK`).
- Viewer (`js/scene.js` buildMcMesh): it already builds an RGBA atlas with `alphaTest: 0.5`, so cutout textures need only small changes. It has no blended (translucent) pass.
- `mc_render.tex()` already composites RGBA tiles, including the grass overlay tint.

## 1. Dataset (`mc-blocks/`)
- Re-admit leaves (oak, spruce, birch, jungle, acacia, dark_oak, mangrove, cherry, azalea, flowering_azalea, pale_oak) and glass (glass, tinted, 16 stained, and panes) to `blocks.json` with new fields:
  - `render: "cutout" | "translucent" | "opaque"`
  - `alpha_coverage` (fraction of opaque texels)
  - `mean_alpha` (stained glass ≈ 0.6)
- Colour stats are computed on the visible colour, not the raw grey texture:
  - **Leaves:** texture × foliage tint. The fixed tints are spruce #619961 and birch #80a755. Oak, jungle, acacia, dark oak and mangrove use the plains foliage tint #77ab2f, and each block also gets a `tint_by_biome` table. Azalea and cherry are untinted. Store the colour as `alpha_coverage`×colour + (1−coverage)×`backdrop`. The backdrop is a canopy-interior dark green (≈ #2b3a1c), because leaves are seen against other leaves.
  - **Glass:** colour composited over a dark interior (≈ #1a1a1a) plus a sky term, so it matches how a window reads in a build.
- Add a `pane_of` map (glass to glass_pane, stained to stained_pane), like the existing slab/stairs maps. Panes are the thin, 1/8-wide variant for a 1-block-thick wall.

## 2. Detection (where these blocks go)
- **Glass:**
  - Use the window clusters `palette_generic` already finds (`window_dark`: L < 24 on vertical faces, 2–12 voxel clusters).
  - Add specular/sky-reflection clusters: high L, low C and a blue cast inside a darker frame. Use the ortho views and the photo, back-projected the same way `ortho_paint` does.
  - Add circle detection (Hough transform on the front ortho) for rose windows. Map the ring to stone and the inside to stained glass, choosing the hue from the photo.
  - Only consider surface voxels on vertical faces, at least 1 block from a corner.
  - Have Haiku (already used for verification, about $0.007 per call) confirm "these are windows" on one crop per subject.
- **Leaves:**
  - Look for high-chroma green (h 90–150°, C > 20) with rough noise (`noise_measure` lstd ≥ 6) and a lumpy silhouette, in the top portion of organic subjects (Hunyuan route) or the landscape "grass" layer above ground level (trees/bushes).
  - Do not use leaves for flat grass, which stays `grass_block`.
  - Choose the species by dE against the tinted leaf colours. Spruce suits dark blue-greens, birch light yellow-greens, and azalea/flowering_azalea suits pink accents.

## 3. Solid-fill interaction
- Solid-fill currently makes the interior full, so glass would show stone behind it.
- **Glass:**
  - Carve a cavity 1 block deep behind each glass voxel and line it with a dark block (`black_concrete` or `polished_blackstone`), or leave it as air when the interior is big enough to be a room.
  - Thin walls (thickness ≤ 1): use a pane and recess it half a block, which gives a real depth shadow.
  - Rose window: stained glass with a dark backing 2 blocks deep, so the colour reads.
- **Leaves:**
  - Hollow the canopy: keep a 1–2 block leaf shell and replace the interior with a log/wood core plus air, so the cutout gaps show dark depth, not stone.
  - Branch/trunk voxels (`--keep-thin`) become logs with `axis` set from their direction.
  - Leaves must be exported with `persistent=true` so they never decay, and with `distance` set to the BFS distance to the nearest log, capped at 7, so the blockstate is valid. Add this in `mc_render.export`.
  - Leaves have no slab or stair forms, so `subblock` sends them only to full shapes (and `mc_features.STAIR_SKIP` already includes `foliage`).

## 4. Mapping (`mc_map.py`)
- New materials and families:
  - `glass` {glass, stained_glass, tinted_glass, panes}
  - `foliage_leaves` {leaves}
  Both are STRICT, so stone can never become glass and glass can never land on stone.
- Allow the `biome_tinted` exception for leaves, as `NATURAL_OK` does for grass_block.
- Dither between 2 leaf species (for example oak with 25% azalea) using the existing accent dither, which already passes the |ΔL| and hue checks.

## 5. Viewer and renders
- `scene.js`:
  - Split the mc mesh into an opaque/cutout mesh (current `alphaTest 0.5`, with real leaf alpha baked into the atlas) and a translucent mesh. The translucent mesh uses `transparent: true`, `depthWrite: false`, `side: DoubleSide`, and is sorted back to front per frame (it is small, so sort the quads by camera distance).
  - Face culling: do not cull a face against a transparent neighbour. Do cull glass against glass of the same id, as Minecraft does.
  - Leaves render all faces, which is like the "fancy" graphics setting.
  - Add pane geometry (2/16-thick centre post) next to the existing slab/stair geometry.
- `mc_render.bake_fine`: composite in depth order. A cutout texel with alpha < 0.5 shows whatever is behind it, and translucent texels use alpha-over. This keeps the scorer and gallery honest.
- `.litematic` and `.schem` export: add states like `minecraft:oak_leaves[persistent=true,distance=1,waterlogged=false]` and `minecraft:glass_pane[east=true,west=true,...]`. Compute pane connections from the neighbours.

## 6. Order of work and cost
1. Dataset fields and tinted stats
2. Export blockstates
3. Viewer passes
4. Glass detection on the cathedral
5. Leaves on a new tree/organic subject

All of this is local code with $0 fal spend. The only paid parts are about 1 Haiku window check per subject (≈ $0.007) and one optional Sonnet judge pass.
