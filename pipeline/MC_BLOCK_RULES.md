# MC_BLOCK_RULES — voxel colours -> Minecraft 26.3 blocks (`mc_map.py`)

Inputs per voxel (`mc_features.py`): material m, shade sh (-2..+2), blend (donor, k, n), target colour (textured pass, Lab),
region noise (`noise_measure.py`), openness/AO, up/sun facing, edge/corner, material-boundary partners, top/under exposure, sub-block shape.
Dataset: `mc-blocks/blocks.json` (494 blocks) + `pattern.*` fields added by `add_pattern_metrics.py`.
(The Opus design worker for this phase hit the Claude 5-hour usage limit mid-run, so these rules were written by the coder; Opus reviews them in the gate.)

## 1. Noisiness from the image
- Region = (material, vertical band of ~3 layers). The block-grid model is rendered as an id buffer with the photo's fitted camera
  (and at az 0/el 0 for the front ortho view) and stretched onto the photo's subject box, then on the covered pixels:
  `l_std` = median local L* std in a 1-voxel window (same unit as the dataset's `l_stddev`, i.e. L* spread inside one block),
  `hf` = fine/coarse residual variance ratio, `scale_vox` = power-weighted wavelength in voxels. noise = 0.7·photo + 0.3·ortho.
- Normalisation: photo windows also contain lighting edges, so they read ~2x a block texture's own spread (smooth white wall 5.4 vs
  wool 4.4 / concrete 0.3; noisy foliage ~13 vs moss 6.4). Target block spread `lstd_t = 0.5 · noise`.
- Cost term: `W_N · min(3, |lstd_t − l_stddev(block)| / 3)`, W_N = 1.2.
- Roles from noise: `lstd_t ≥ 6` -> rough (stippling/scumbling wanted); `lstd_t ≤ 3.5` -> smooth (glazing wanted).

## 2. Art-technique classes (dataset `pattern.techniques`, 0..1 from the side texture)
| technique | measured from | typical blocks |
|---|---|---|
| hatching | orientation coherence × contrast × line regularity × line length | planks, bamboo, hay, polished basalt, stone/mud bricks |
| cross_hatching | strong edges split between horizontal and vertical lines, long runs | tuff/polished bricks, chiseled stone bricks, polished andesite |
| stippling | area share of ≤3 px specks vs a 5x5 median, low coherence | granite, gravel, coarse dirt, moss block, andesite, wool |
| scumbling | 5–120 px off-tone blotches, irregular | mud bricks, calcite, smooth stone, pale oak |
| glazing | 1 − L* spread/7 | concrete, terracotta, quartz, snow |
| outline | border ring vs interior contrast, consistent on all four sides | smooth stone, chiseled/framed blocks |
Image role per voxel (priority order): **trim** (boundary with a CRISP partner: door/window frame, cap lip, eave lip, pot rim) -> outline;
**shadow** (sh < 0, crevice open < −0.35, or blended from a darker donor: under-eave, cap cornice, root flare) -> hatching / cross-hatching;
**rough** -> stippling / scumbling; **smooth** -> glazing; else plain (colour + noise only).
Cost term `W_T · (1 − best technique score)`, W_T = 4. Guard: among candidates, only those within **+8 dE2000** of the slot's best colour
match may win, so a technique never buys a bad colour. Labels in the output say "colour only (wanted …)" when no candidate scored ≥ 0.25.

## 3. Candidates and families
Allowed: full cubes; no light emitters, gravity, transparency, animation, biome tint, ores, utility/workstations, glazed terracotta,
coral, sculk, gourds, concrete powder, precious-metal blocks, nylium/mycelium/podzol (top ≠ side), waxed duplicates. No leaves (not in the dataset).
Material families (out-of-family pays +10): stone -> stone/andesite/tuff/diorite/calcite/deepslate/dripstone/sandstone/mud/basalt/granite;
cap -> deepslate/blackstone/basalt/tuff/stone/concrete/terracotta/wool; sails -> wood/quartz/calcite/wool/concrete/snow; walls -> concrete/wool/quartz/calcite/snow/terracotta;
thatch -> wood/mud/tuff/stone/terracotta/wool/organic/sandstone/moss; door -> wood/terracotta/concrete/wool/brick; chimney -> brick/mud/terracotta/granite/wood;
foliage -> moss/wool/concrete/terracotta/organic; trunk -> wood/mud/terracotta/soil; pot -> terracotta/brick/nether brick/wool/concrete/wood; soil -> soil/mud/wood/terracotta/wool.
Hue guard: near-neutral targets (C* < 12) take greys or low-chroma blocks within 50° hue; coloured targets need C* ≥ 0.35·C*target and hue within 40°.
Block colour = mix of top and side face Lab by the slot's share of top-exposed voxels.

## 4. Ramps and gradients
Slots = (material, shade, role); blends are their own slots. Per material: pick the base for the largest sh = 0 slot from all candidates,
then grow outward (|sh| ascending): pool = base's family ∪ blocks sharing a dataset gradient chain ∪ 2-hop nearest-neighbour graph
(+ hatch pool for shadow slots, + any block < 12 dE for trim/rough/smooth). Constraints: monotonic L (darker shades may not be lighter than
the base and vice versa, +10 penalty), each new block within **15 dE2000** of a block already in the ramp, reuse bonus −2, at most **5 blocks per material**
(least-used block dropped and its slots re-solved). Blends pick from both materials' blocks ∪ blocks on gradient chains containing both bases ∪ any block < 6 dE.

## 5. Shapes
full -> block. slab 0.5 top/bottom -> the block's own slab (same textures) with `type`; if none, the closest block with a slab within 6 dE, else full.
0.25 plates -> trapdoor of the block's family (wood types, copper oxidation, iron) closed with `half`; else slab, else full.
vslab -> open trapdoor (`facing` = opposite of the plate's side) if the block's family has one, or a trapdoor of a family listed for the
material within 10 dE (e.g. pale oak for white sails); else full block. stairs -> full block (stairs were excluded from the dataset);
the summary records whether `<stem>_stairs` exists in vanilla for each chosen block.

## 6. Output
`art/final/{n}_mc_blocks.json`: palette of blockstates (id, props, state string, material, count, roles, technique served) + voxels `{x,y,z,b}`,
summary (ramps dark->light with adjacent dE, roles/techniques per block, slab/trapdoor/stairs availability, shape fallbacks, blends),
plus 4x4 texture bakes for the viewer. Schematics: `art/final/schematics/{n}_mc_blocks.schem` (Sponge v2) and `.litematic`.
