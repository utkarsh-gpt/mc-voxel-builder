# Minecraft 26.3 block colour dataset

A colour dataset of Java Edition building, coloured and natural blocks, measured from the official 26.3 client textures. It is meant for later voxel-to-block mapping: pick a small set of base colours, add lighter/darker shades of each for texture, and blend neighbouring colours along short gradients.

This is a separate workstream from the voxel art pipeline. No fal usage.

**Not included:** the official Minecraft client JAR and the extracted vanilla textures / models / blockstates (`raw/`, `assets/`). Those are © Mojang Studios / Microsoft and cannot be redistributed. `blocks.json`, `blocks.csv`, `gradients.png` and `swatches_colors.png` are derived colour and metric tables (plus 4×4 colour samples in the mapper), which are fine to share.

## Output files

| Path | What it is |
| --- | --- |
| [`blocks.json`](blocks.json) | Full dataset: metadata, per-block records, suggested gradient chains, and the MCBI cross-check. |
| [`blocks.csv`](blocks.csv) | Flattened table (one row per block) for spreadsheets. |
| [`excluded.json`](excluded.json) | Every scanned blockstate that was left out, with a reason. |
| [`swatches_colors.png`](swatches_colors.png) | Average-colour chips for every included block, sorted grey → hue → lightness. (The original sheet with official texture thumbnails is not in this repo.) |
| [`gradients.png`](gradients.png) | Sample ramps (greyscale, wood, terracotta, concrete, wool, copper oxidation, stone, hue bands, dye wheels). |
| [`block_colors.py`](block_colors.py) | Reproducible builder. |

Regenerate (the official client JAR and extracted `assets/` are **not** in this repository and must not be redistributed):

```bash
python3 block_colors.py --jar /path/to/client-26.3.jar
```

Requires Python 3 with `numpy` and `Pillow`. The official jar can be fetched for personal use from Mojang's [piston-meta version manifest](https://piston-meta.mojang.com/mc/game/version_manifest_v2.json) → version JSON → `downloads.client` (26.3 client SHA-1 `e877b6a07acd633fb3bb475002175cec036e7b87`).

## Scope (Minecraft 26.3)

1,288 blockstates were scanned.

**Included: 494**

- 358 full cube blocks
- 101 slabs (including the 26.3 wool and concrete slabs)
- 22 trapdoors (wood, iron, copper and waxed/oxidized copper)
- 13 wooden shelves (the 1.21.11+ shelf family, including poplar)

Examples: `oak_planks`, `oak_log`, `oak_slab`, `oak_trapdoor`, `oak_shelf`, `white_wool`, `white_concrete`, `white_concrete_slab`, `grass_block`, `glowstone`, `sea_lantern`, `shroomlight`, `ochre_froglight`, `poplar_planks`, `sulfur`, `cinnabar`, `resin_bricks`.

**Excluded: 794**, by reason (examples in `excluded.json`):

| Reason | Count | Examples |
| --- | ---: | --- |
| plants / crops / flowers | 110 | `allium`, `cactus`, `red_shrub`, `shelf_mushroom`, `golden_dandelion` |
| stairs | 0 (all 97 now included, see Stairs below) | `oak_stairs`, `white_wool_stairs` |
| signs | 52 | `oak_sign`, hanging and wall signs |
| other non-full shapes | 49 | `anvil`, `dirt_path`, `farmland`, `lectern`, `campfire` |
| glass (any, including stained/tinted/panes) | 35 | `glass`, `tinted_glass`, `blue_stained_glass_pane` |
| candles / cake candles | 34 | `candle`, `black_candle` |
| walls | 32 | `cobblestone_wall` |
| banners | 32 | `white_banner` |
| technical | 30 | `barrier`, `command_block`, `spawner`, `structure_block`, `jigsaw` |
| redstone components | 30 | `redstone_block`, `redstone_lamp`, `observer`, `piston`, `copper_bulb` |
| potted plants | 28 | `potted_oak_sapling` |
| doors, saplings, special utilities, carpets, pressure plates, beds, shulker boxes, buttons, fences, leaves, fence gates, coral fans, lanterns (not sea/jack o'), heads, bars, chains, grates, torches, statues, infested, skulls | the rest | |

Light-emitting **full** blocks that are included, with wiki light levels: glowstone 15, sea lantern 15, shroomlight 15, the three froglights 15, jack o'lantern 15, crying obsidian 10, sculk catalyst 6, magma block 3. Furnaces, blast furnaces and smokers are stored unlit (`light_level` 0) with `light_level_lit` 13.

## How colour is measured

- Blockstate and model JSON resolve each block to the textures on its faces (top, bottom and the four sides). Parent models and `#texture` references are flattened. Default states prefer things like `axis=y`, `lit=false`, `snowy=false`, `creaking_heart_state=dormant`. Multipart cubes such as mushroom blocks use the inventory (all-cap) model.
- Tinted faces (`tintindex` in the model, e.g. grass-block top and the grass side overlay) are multiplied by the default **plains** colours: grass `#91BD59`, foliage `#77AB2F`. Birch/spruce leaf constants and a plains dry-foliage sample are also defined in the script, though leaf blocks themselves are out of scope.
- Grass-block sides composite the dirt-like `grass_block_side` with the tinted `grass_block_side_overlay`.
- Animated textures (sea lantern, magma, prismarine, …) are time-averaged in linear RGB across frames, using `.mcmeta` frame durations when present.
- Pixels with alpha 0 are ignored. A block is flagged `has_cutout` if any pixel is fully transparent, and `has_translucency` if any kept pixel is partly transparent (ice, slime, honey, trapdoors with holes, …).
- The **canonical average** is the **OKLab mean** of visible pixels, converted back to sRGB, CIELAB and OKLCh. Averaging in sRGB makes mixed textures too dark; averaging in OKLab matches what builders' tools such as MCBI and MCTools do, and is the right space for interpolating gradients.
- A block's **overall** colour is the OKLab mean of top + bottom + four sides, weighted 1+1+4 (the look of a placed cube). Per-face colours are also stored. When the four sides differ (furnace, crafting table, jack o'lantern), `side` is their mean and `sides_differ` is set.
- Distance for neighbours and ramps is **CIEDE2000** in CIELAB (D65, 2°) of those canonical colours.

## Fields (and why they help matching and gradients)

### Identity and shape

| Field | Why it is here |
| --- | --- |
| `id`, `display_name` | Block id and English name. |
| `shape` | `full_block`, `slab`, `trapdoor` or `shelf`. Mapping can restrict to full cubes, or allow slabs/trapdoors/shelves as half and quarter pieces. |
| `family`, `subfamily` | Wood, stone, terracotta, concrete, wool, copper, … Group shades and build per-family ramps. |
| `dye_color`, `wood_type` | Dye name or wood type when it applies. |
| `emits_light`, `light_level`, `light_level_lit` | So glowing blocks can be preferred or avoided. |
| `gravity` | Sand, gravel, concrete powder: bad for ceilings and floating maps. |
| `biome_tinted`, `tint_type` | Grass (and any future tinted includes) used the plains tint; other biomes would shift them. |
| `faces_differ`, `sides_differ`, `face_delta_e00`, `side_delta_e00` | Logs, sandstone, grass, workstations: top/side/bottom (or the four sides) are not the same colour. Use the face that will actually show. |
| `animated` | Colour is a time average; the live block will flicker slightly around it. |
| `partially_transparent`, `has_cutout`, `has_translucency` | Ice, slime, honey, trapdoors. Useful filters if the build needs opaque cubes. |
| `model`, `state`, `textures` | Which model and texture files were measured, for debugging. |

### Colour (on `overall`, and again under `faces.top` / `faces.side` / `faces.bottom`)

| Field | Why it is here |
| --- | --- |
| `srgb`, `hex` | Canonical display colour (from the OKLab mean). This is the value to match against. |
| `lab` | CIELAB L\*a\*b\*. Perceptual base for ΔE2000. `brightness_L` is L\*. |
| `oklab`, `oklch` | OKLab / OKLCh. Best space for interpolating a gradient: walk a straight line in OKLab, then pick the nearest block at each step. `oklch.h` / `hue_deg` and `chroma` (C) are for grouping by hue family and for telling greys from colours. |
| `hex_naive`, `srgb_naive` | Plain average of sRGB bytes (faces only). Kept so you can see the dark bias on noisy textures; do not use this for matching. |
| `hex_linear_mean` | Mean in linear RGB, converted back to sRGB. Physically reasonable, but OKLab is preferred. |
| `lightness_rank`, `lightness_percentile` | 1 = darkest included block. Easy shade stacks (dark crevice → mid → sun-bleached top) without comparing raw L\* by hand. |
| `l_stddev`, `spatial_contrast`, `busyness` | How noisy the texture is. `flat` (concrete) vs `smooth` vs `textured` vs `noisy` (ore, cobble, foliage-like). Flat blocks read as a clean colour; noisy ones blend better at a distance and in gradients. `spatial_contrast` is the mean |ΔL\*| between neighbouring pixels. |
| `unique_opaque_colours` | Another “how busy is this” signal. |
| `dominant_colours` | 2–3 k-means colours in OKLab, with fractions, merged if ΔE2000 < 6. Helps describe a block that is not a single flat colour (e.g. a dark grid on a light field). |
| `nearest` | The five closest included blocks by ΔE2000. A ready graph for “what else can I use in this shade”. Slab/full pairs with the same texture correctly show up at ΔE 0. |
| `gradient_chains` | Which suggested ramps this block sits on, plus the previous and next block in each. |

`blocks.json` also has a top-level `gradient_chains` list: family ramps sorted by L\*, thinned “smooth” subsets that skip near-duplicates, copper oxidation order, a greyscale ramp, hue-band ramps, and dye-family hue wheels (wool, concrete, terracotta, …).

## Online sources (cited, not copied)

Measured independently from the 26.3 client. These projects shaped the field list and were used to cross-check a sample of averages:

- **[MCBI](https://mcbi.ai/about/colors)** — 26.3, OKLab mean of visible pixels, plains tint, first frame of animations. 1,205 blocks in their broader catalogue. Our averages for `white_concrete`, `black_concrete`, `oak_planks`, `white_wool`, `stone`, `cobblestone`, `glowstone` and `terracotta` match their published hex values **exactly** (ΔE2000 = 0).
- **[MCTools gradient generator](https://mc-toolbox.com/minecraft-gradient-generator/)** — 26.3, OKLab, 285 full blocks, stores texture variance, interpolates gradients in OKLab. Method agrees with ours; no bulk table was copied.
- **[HueBlocks](https://github.com/1280px/hueblocks)** — open-source jar-to-blockset pipeline, OkLAB default, optional facing filter. Intentionally drops biome-tinted and cutout blocks, so its set is narrower.
- **[Palettinator](https://palettinator.com/)** and **[Block Colors](https://blockcolors.app/about)** — palette browsers for builders; no redistributable colour table used.
- **[Minecraft Wiki: Block colors](https://minecraft.wiki/w/Block_colors)** — biome tints (plains grass `#91BD59`, foliage `#77AB2F`, birch/spruce leaf constants).
- **[Minecraft Wiki: Map item format](https://minecraft.wiki/w/Map_item_format)** — coarse official map-colour categories (one RGB per material, four brightness shades). Too coarse for texture-accurate matching; cited only as the game's own colour system.
- **[Minecraft Wiki: Light](https://minecraft.wiki/w/Light)** — light levels for included emitters.
- Older datasets ([MCBlockColors](https://github.com/hhhzzzsss/MCBlockColors), [mc-gradient-wheel](https://github.com/rj-price/mc-gradient-wheel), [mc_block_color_mapper](https://github.com/RandomGamingDev/mc_block_color_mapper), a [Kaggle 1.21.8 texture pack](https://www.kaggle.com/datasets/urvishahir/minecraft-block-textures-dataset)) informed the idea of storing Lab/ΔE and per-face variants. They target older versions and were not copied.

## Ambiguous scope choices

- **Leaves** are cube-shaped and common in builds, but were excluded as plants. The tint pipeline is still in the script if they are added later.
- **Redstone ore** (and deepslate redstone ore) is a natural ore, but was excluded with other redstone components, as requested (“no redstone blocks”).
- **Copper bulbs** and **redstone lamps** are full light blocks but redstone-controlled, so excluded. Jack o'lanterns, glowstone, sea lanterns, shroomlights, froglights, magma, crying obsidian and sculk catalysts are included.
- **Chests, shulker boxes, beds, signs, vaults, spawners, beacons, respawn anchors, decorated pots** were excluded as entity or special-utility blocks, even when the collision box is a cube.
- **Infested** stone variants were excluded as technical/mob blocks (they share textures with the normal stone family).
- **Slime and honey** are slightly inset / translucent full-ish cubes; included and flagged transparent.
- **Ice** (plus packed and blue ice) is included as a natural full block, not treated as glass.
- **Waxed copper** is included alongside the unwaxed block of the same oxidation. The colours match (ΔE 0); a mapper can prefer the unwaxed id.
- **Cushions** from the 26.3 drop do not appear as their own blockstates in this client; `straw_bed` was excluded as a bed. **Shelf mushrooms** are a wall fungus, not the wooden shelf family, and were excluded as plants.
- Workstations (furnace, crafting table, loom, …) are included as full building blocks under family `utility`.
- `potted_torchflower` is tagged `torch` rather than `potted_plant` because the id contains “torch”; it is still excluded.

## Self-tests

`block_colors.py` checks CIELAB white, an official CIEDE2000 test pair (Sharma et al., expected 2.0425), OKLab white (L ≈ 1), and sRGB round-trips before it builds the dataset.

## Stairs (added 2026-11-22)
`add_stairs.py` adds the 97 vanilla stairs blocks (`shape: "stairs"`). Colour, texture and pattern stats are copied from the block with the same textures (`stairs.source_block`, e.g. `stone_brick_stairs` <- `stone_bricks`). `state` is the default `facing=north,half=bottom,shape=straight`. `stairs.props` lists the blockstate values: `facing` is the tall side, `half=top` is upside down, and `shape` is straight/inner_left/inner_right/outer_left/outer_right. The CSV gains `stairs_source_block` and `stairs_volume_fraction` (0.75). Stairs are no longer listed in `excluded.json`.
