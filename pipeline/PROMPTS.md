# AI voxel / Minecraft structure prompts (starting line)

Three viable approaches, in order of recommendation:

| # | Approach | Truly 3D? | Block-accurate? | Cost | Best for |
|---|----------|-----------|-----------------|------|----------|
| A | LLM writes voxel JSON (boxes + layers + blocks) | yes | yes, real block IDs and states (stairs, doors) | cheap (Haiku/Sonnet text) | buildings, trees, props, anything architectural |
| B | LLM writes *code* that emits blocks (MC-Bench / APT style) | yes | yes | cheap | big or repetitive builds (towers, walls, spirals) where JSON gets too long |
| C | text -> image -> image-to-3D mesh (fal Trellis / Hunyuan3D / TripoSR) -> voxelize -> colour-match blocks | yes | approximate (colour-matched solid blocks only) | ~cents per model | statues, creatures, organic shapes LLMs can't sculpt |

---

## A. LLM -> voxel JSON (recommended default)

### A0. Master template (system prompt) - paste, then fill `{REQUEST}`, `{W} {H} {D}`

```
You are a Minecraft Java Edition voxel architect. You output ONE JSON object and nothing else
(no markdown fences, no commentary).

COORDINATES
- Grid size is W={W} (x, east), H={H} (y, up), D={D} (z, south). All coords are 0-based and
  inside the grid. y=0 is the ground layer the structure sits on.
- Front of the build faces north (z=0 side) unless told otherwise.

SCHEMA
{
  "name": "<snake_case>",
  "size": [W, H, D],
  "palette": { "<single char>": "minecraft:<block_id>[state=value,...]", ... },
  "boxes":  [ {"from":[x,y,z], "to":[x,y,z], "block":"<char>", "hollow":false}, ... ],
  "layers": [ ...optional, H layers bottom-up; each layer is D strings of exactly W chars;
              '.' = air... ],
  "blocks": [ {"x":..,"y":..,"z":..,"block":"<char>"}, ... ]
}
Sections are applied in order boxes -> layers -> blocks; later ones overwrite earlier ones.
Use "boxes" for big volumes (foundation, walls, floors, roof slabs), "hollow":true for
shells. Use "blocks" for details (doors, windows, torches, stairs, leaves clusters).
Carve air by placing the "." palette key.

PALETTE RULES
- Use at most {N_BLOCKS} palette entries. Only real vanilla block IDs for Java 1.21+.
- Directional blocks MUST include state: stairs [facing=north|south|east|west,half=bottom|top],
  doors need two entries (lower/upper) [facing=..,half=lower|upper], logs [axis=x|y|z],
  wall torches [facing=..]. Glass panes and fences connect automatically - no state needed.

QUALITY RULES (think silently before writing)
1. Plan the massing first: footprint, wall height, roof shape, then details.
2. It must read well from ALL sides and from above: no flat unfinished backs, no floating
   blocks, every block supported or attached.
3. Add depth: overhangs, window recesses, log pillars at corners, trim lines, a varied roofline.
4. Keep symmetry where the object is naturally symmetric; break it deliberately with 1-2
   details (chimney, flower pot, side door).
5. Interior must be hollow and walkable (2-block clear headroom) for buildings.
6. Stay strictly inside the grid.

REQUEST: {REQUEST}
```

### A1-A8. Ready-to-use REQUEST lines (drop into `{REQUEST}`)

1. **Cottage (16x16x16):** "A cosy medieval cottage: cobblestone foundation, oak log corner pillars, white-plaster (white_terracotta / calcite) walls, spruce stair gable roof with 1-block overhang, brick chimney on the east side, two glass-pane windows per side, oak door on the north face with a lantern above."
2. **Oak tree (16x20x16):** "A large natural oak tree: 2x2 trunk of oak_log[axis=y] rising 9 blocks, two diagonal branches with oak_log[axis=x/z], a lumpy irregular canopy of oak_leaves 11 wide (never a perfect sphere - vary radius per layer, leave gaps), a few moss_carpet and short_grass around the roots."
3. **Wizard tower (11x32x11):** "A round wizard tower 9 blocks across: stone_bricks with mossy_stone_bricks scattered at random (~20%), spiral of window slits, purple_stained_glass at the top room, conical dark_oak stair roof reaching a point, a small balcony on the south face."
4. **Market stall (8x7x6):** "A market stall: 4 spruce fence posts, striped red_wool/white_wool canopy that slopes forward, oak_slab counter with barrels and a few pumpkins and melons on top."
5. **Viking longship (24x12x9):** "A viking longship: hull curved from bow to stern using spruce_planks and spruce_stairs, dark_oak trim, a mast at the center with a red_wool/white_wool striped square sail, shields (alternating blue/yellow banners or wool) along both sides, a curled prow."
6. **Statue / mascot (12x24x8):** "A blocky statue of a knight standing on a 2-block plinth: polished_andesite plinth, iron_block armor, gold_block trim, sword held vertically in front, cape behind made of red_concrete. Must look correct from the back and sides."
7. **Well (7x7x7):** "A village well: circular-ish cobblestone ring 5x5 with water in the middle, two oak_log posts, an oak stair roof, a chain hanging down holding a lantern."
8. **Bridge (24x10x7):** "A stone-arch footbridge: stone_bricks deck with stone_brick_wall railings, one semicircular arch underneath, lanterns on posts at both ends, moss and vines hanging from the arch."

### A9. Layer-by-layer variant (better spatial accuracy for small, detailed builds)

```
Return the build as "layers" only. Before each layer, think about which blocks of the layer
below support it. Each layer: exactly {D} strings of exactly {W} characters. Row index = z
(north first), character index = x (west first). Layer index = y (ground first).
Repeat the legend in your head for every row; never change string length.
```

### A10. Repair / critique pass (feed the previous JSON + the 6-view preview PNG back)

```
Here is your voxel JSON and a 6-angle render of it. List concrete defects (floating blocks,
holes, flat back side, wrong stair facing, out-of-proportion parts), then output a corrected
full JSON with the same schema. Output JSON only.
```

---

## B. LLM -> code that emits blocks (MC-Bench / APT style)

### B0. Template

```
Write a Python function build() that returns a list of (x, y, z, "minecraft:block_id[states]")
tuples for the structure below. Use loops, math (sin/cos for circles, spirals), and helper
functions box(x0,y0,z0,x1,y1,z1,block,hollow=False). No imports except math and random
(random.seed(42) first). Coordinates: x east, y up, z south, all >= 0 and inside
{W}x{H}x{D}. Output only the code.
STRUCTURE: {REQUEST}
```
(Run the returned code in a sandbox, then dump it to the A-schema "blocks" list and feed it to voxel_ai.py.
Guardrails later: never exec untrusted code on the server host.)

### B1-B5 REQUESTS
1. "A 40-block spiral staircase tower of deepslate_bricks with a lantern every 8 steps."
2. "A circular colosseum, radius 20, 3 tiers of arches, sandstone with smooth_sandstone trim."
3. "A Japanese pagoda, 5 tiers, each tier 2 smaller, dark_oak frame, red_terracotta walls, deepslate_tile_stairs roofs with upturned corners."
4. "A city wall segment 48 long with crenellations, two square towers and a gatehouse."
5. "A giant mushroom forest patch 32x32 with 6 huge mushrooms of different heights (red_mushroom_block caps, mushroom_stem stalks)."

---

## C. Text -> image -> 3D mesh -> voxels (fal)

Image-to-3D models want: ONE object, centered, full body in frame, plain/white background,
3/4 view, even lighting, no text. These image prompts work well (feed result to Trellis / Hunyuan3D):

1. "A single cute stylized fox statue, full body, 3/4 view, isometric, centered, plain white background, soft even studio lighting, game asset, clean simple shapes, no shadows on background"
2. "A small fantasy cottage with a thatched roof and stone chimney, isolated game asset, 3/4 isometric view, plain white background, soft lighting, low-poly stylized, no ground plane"
3. "A large oak tree with a round canopy, isolated 3D game asset, full tree visible, centered, plain white background, stylized"
4. "A medieval knight statue standing on a square pedestal, full body, 3/4 view, white background, game-ready 3D asset render"
5. "A red and white lighthouse on a small rock, isolated, centered, plain white background, stylized 3D render"
6. "A dragon head trophy, symmetrical, front 3/4 view, plain white background, stylized game asset, bold colours"
7. "A hot air balloon with a wicker basket, isolated, centered, plain white background, bright saturated colours, stylized 3D"

Then: `python voxel_ai.py mesh model.glb --size 32 --out out/name` (voxelize + nearest-colour block match).
Tip: keep `--size` 24-64; bright, flat colours voxelize best; organic shapes > buildings for this route.

---

## Sources
- T2BM, "3D Building Generation in Minecraft via LLMs" (JSON interlayer + repair): https://arxiv.org/html/2406.08751
- APT, "Architectural Planning and Text-to-Blueprint Construction Using LLMs" (layout synopsis -> code): https://arxiv.org/pdf/2411.17255v2.pdf
- BuildingBlock: hybrid LLM + rule-based layouts: https://arxiv.org/abs/2505.04051
- LLMs as Minecraft Agents (JSON builder prompt, coordinate conventions): https://arxiv.org/abs/2402.08392
- MC-Bench (LLM writes JS build scripts) https://mcbench.ai/ , template repo: https://github.com/mc-bench/simple-minecraft-server-builder
- BuilderGPT (LLM -> .schem/.mcfunction): https://github.com/cyniaai/buildergpt
- voxel-architect (agentic LLM with fill/place tools): https://github.com/adityonugrohoid/voxel-architect
- Voxel-to-Text experiment (part-wise decomposition): https://kokecacao.me/html/voxel-to-text-experiment/
- Mine-Builder (text -> Hunyuan3D mesh -> voxel -> schematic): https://github.com/heartrue/Mine-Builder
- Text-to-Schematics (Shap-E -> schematic, Paper plugin): https://github.com/xam74er1/Text-to-Schematics
- model2mc (GLB -> .schem with CIEDE2000 colour match): https://github.com/Stink-O/model2mc
- Scan2Craft (mesh -> .litematic): https://github.com/y3jian/MinecraftModel
- Hunyuan2Minecraft voxel utils: https://github.com/0xrushi/Hunyuan2Minecraft
- fal Trellis: https://fal.ai/docs/model-api-reference/3d-api/trellis
- fal Hunyuan3D v3.1 Pro: https://fal.ai/docs/model-api-reference/3d-api/hunyuan-3d-v3.1-pro
- fal 3D API overview (Trellis 2, etc.): https://fal.ai/docs/model-api-reference/3d-api/overview
- GDMC (Generative Design in Minecraft competition): https://github.com/mcgreentn/GDMC
