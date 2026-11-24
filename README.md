# mc-voxel-builder

Research tools that turn a single reference photo into a Minecraft build: orthogonal views, a low-poly mesh, coloured voxels, sub-blocks (slabs, trapdoors, stairs) and a final mapping onto vanilla 26.3 blocks, exported as `.schem` and `.litematic`.

**Live viewer:** [https://voxel-viewer-ten.vercel.app](https://voxel-viewer-ten.vercel.app)

This repository is a public snapshot of the builder scripts, block-colour dataset, research notes, generated references, schematics and the static viewer. The original working trees (`voxel-ai`, `mc-blocks`, `voxel-viewer`) are unchanged.

## Photo-to-Minecraft pipeline

```
photo ─► cut-out ─► drawing sheets ─► 3D mesh ─► painted colours ─► shape fit ─► materials ─► photo noise ─► Minecraft blocks ─► viewer
```

1. **Reference photo.** One picture of the subject in `pipeline/refs/NAME.jpg`, with a `NAME_SOURCE.txt` credit file. `gen_refs.prep` removes the background (rembg) and writes the cut-out `NAME_fal_in.png`. `gen_refs.py` can also generate a reference with fal.ai.
2. **Drawing sheets.** fal.ai (nano-banana) redraws the subject as flat front, side, back and top views on one sheet (`ortho_gen.py`). `ortho_verify.py` makes up to 3 sheets and checks each with geometry tests plus a Haiku review. It records the pick in `out/NAME_verify.json`; you can override the pick by hand there.
3. **3D model.** Hyper3D builds a low-poly mesh (about 3–4K faces) from the chosen views (`ortho_lowpoly.py`). Organic or leafy subjects go to Hunyuan (`ortho_hunyuan.py`).
4. **Painted colours.** The mesh is coloured from the drawings and toned to the photo (`ortho_paint.py`, `tone_to_ref.py`).
5. **Shape fit** (`shape_fit.py`; replaces `subblock.py` for new subjects).
   - The mesh is scaled to real-world size: 1 block = 1 m by default, from `art/final/meta/NAME_scale.json`. `--bpm` scales it up or down.
   - Planes, vertical cylinders and spheres are fitted to the surface.
   - The fitted shapes are snapped the way a builder would:
     - walls onto block edges
     - diagonals onto 45°, 1:2 and 1:3 step lines
     - heights onto half blocks
     - roof pitches onto 1:8 to 4:1
   - The solid is rebuilt at 1/8 block, with sharp corners where two shapes meet.
   - Each block gets one of 87 shapes with real vanilla dimensions:
     - full block
     - slab and quarter slab (a trapdoor, 3/16 thick)
     - vertical half and quarter pieces
     - stairs, including inner and outer corners
     - walls and fences, which connect the way the game does
   - Roofs and domes are laid as heightmaps (half-block steps, with a stair where the height drops a full block), and symmetric models are mirrored.
6. **Materials.** Voxels are split into materials. Each material gets a base colour from the photo and a ramp of 3–5 shades placed by crevices, height and wear (`palette_generic.py`, `TEXTURE_RULES.md`). Neighbouring materials blend where they meet.
7. **Photo noise.** How busy the photo's texture is in each region (`noise_measure.py`).
8. **Minecraft blocks** (`mc_map.py`, `mc_render.py`, `MC_BLOCK_RULES.md`).
   - Every voxel is scored against the block dataset on colour, photo noise and the shading technique its texture imitates (for example planks as hatching).
   - Each material keeps to block families that have stairs, slabs and walls, so shapes survive.
   - Dark window clusters become a glass pane with a stair hood above and a slab sill below.
   - Output is `.schem` / `.litematic` plus the viewer JSON.

Steps 4–8 are plain Python. fal.ai is used in steps 2 and 3 (about $0.32–0.36 per building). The Haiku checks in step 2 call the `claude` CLI (about $0.015 per building). Review tools: `shape_view.py` renders shapes, `shape_compare.py` compares the outline with the drawing, and `detail_metrics.py` / `detail_gallery.py` score detail against a hand-built benchmark. `pipeline/DETAIL_DISCOVERY.md` explains why builds came out flat and how each step was measured.

## Repository layout

```
pipeline/          Builder, scoring and export scripts, plus research notes
  refs/            Generated reference photos and masks
  ortho/           Orthographic view sheets used by the mesh stage
  art/final/       Final voxel / block-map JSON (under 25 MB) and meta
  art/final/schematics/   WorldEdit .schem and Litematica .litematic files
  out/             Runtime galleries and score JSON (not checked in)
  examples/        Early hand-sized voxel JSON examples
  samples/Duck.glb Khronos sample mesh for the voxelize-from-GLB path
  shape_fit.py     Shape-fitting voxelizer (real-world scale, snapped primitives, vanilla shapes)
  shape_view.py, shape_compare.py, detail_metrics.py, detail_gallery.py   Review tools
  *RULES.md, QUALITY.md, PROMPTS.md, TRANSPARENT_BLOCKS_PLAN.md, DETAIL_DISCOVERY.md
mc-blocks/         Minecraft 26.3 colour / pattern / stairs dataset
  blocks.json, blocks.csv, excluded.json
  gradients.png, swatches_colors.png
  block_colors.py, add_pattern_metrics.py, add_stairs.py
viewer/            Static web viewer (source, manifest, models under 25 MB)
```

## Running the scripts

```bash
git clone https://github.com/utkarsh-gpt/mc-voxel-builder.git
cd mc-voxel-builder
python3 -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt

# Optional: fal.ai key for reference / ortho / mesh generation
cp .env.example .env   # then edit; never commit .env
export FAL_KEY=...     # fal_client reads this from the environment

cd pipeline
python voxel_ai.py build examples/cottage.json --out out/cottage
python voxel_ai.py mesh samples/Duck.glb --size 28 --out out/duck_mesh
python mc_map.py cathedral landscape turtle hagia house
```

Call the scripts from `pipeline/` so local imports resolve. `mc_map.py` and `mc_render.py` look for the dataset in `../mc-blocks` (override with `MC_BLOCKS`). The drawing check (`ortho_verify.py`) and the optional judge need the `claude` CLI installed and signed in.

### A new building from a photo

To add a subject, first create:
- `refs/NAME.jpg` and `refs/NAME_SOURCE.txt`
- a drawing description in `SPEC` in `ortho_verify.py`
- a material list in `CFG` in `palette_generic.py`, with `src` set to `art/NAME_shapefit.json`
- block families in `FAMILIES` / `STRICT` in `mc_map.py`
- the real size in `art/final/meta/NAME_scale.json` (`{"length_m": ...}`)

Then run:

```bash
cd pipeline
python -c "import gen_refs; gen_refs.prep('NAME')"     # cut-out, free
python ortho_verify.py NAME                             # drawing sheets: fal $0.039 each + Haiku checks
python ortho_lowpoly.py NAME                            # 3D mesh: fal $0.20
python ortho_paint.py NAME _v1 --model=NAME_lowpoly     # use the sheet tag chosen in out/NAME_verify.json
python tone_to_ref.py NAME_lowpoly
python shape_fit.py NAME                                # add --bpm 2 for small buildings
python palette_generic.py NAME
python noise_measure.py NAME
python mc_map.py NAME                                   # -> art/final/NAME_mc_blocks.json + schematics/
python shape_view.py out/NAME_views.png "NAME" art/NAME_shapefit.json   # quick look at the shapes
```

Small buildings (a house is about 10 m across) come out much cleaner at `--bpm 2`, which still means 2-block doors and floors about 6 blocks tall.

In-game: load a `.schem` with WorldEdit/FAWE (`//schem load` then `//paste`) or a `.litematic` with Litematica. Exports are tagged data version 4325 (1.21.5); those tools upgrade them on newer versions.

### Viewer

Do **not** run `viewer/sync.sh` in this repo. It empties `viewer/models/` and recopies from `pipeline/art/`, and this snapshot's `pipeline/art/` does not hold every pass the viewer ships. Add models by hand instead:

```bash
cp pipeline/art/final/NAME_mc_blocks.json viewer/models/
cp pipeline/refs/NAME.jpg viewer/refs/
# optional credit line under the photo: viewer/refs/NAME_credit.json  {"text": ..., "url": ..., "license_url": ...}
python viewer/scripts/generate_manifest.py
vercel deploy viewer --prod      # publishes the live site
```

## What is not in this repo

- **Secrets.** No `.env` files, API keys, tokens or credentials. Set `FAL_KEY` locally if you run fal.ai stages. Vercel project link metadata (`.vercel/`) is also omitted.
- **Official Minecraft assets.** The 26.3 client JAR (`mc-blocks/raw/client-26.3.jar`), extracted vanilla PNGs, models and blockstates (`mc-blocks/assets/`, `/assets/`), and the vanilla asset zip are © Mojang Studios / Microsoft and are **not** redistributed. `shape_fit.py` uses only block dimensions read from the models (for example the wall post is 8/16 wide and the fence post 4/16). To regenerate the colour dataset or render previews with real 16×16 textures, download the client yourself and pass `--jar` to `block_colors.py`.
- **`swatches.png`** from the original dataset work, because it contained official texture thumbnails. The published `mc-blocks/swatches_colors.png` is average-colour chips only. `blocks.json` / `blocks.csv` store derived colour and pattern metrics (and texture *path names*, not pixels).
- **Oversized generated binaries** (cap: 25 MB per file; GitHub rejects files over 100 MB):
  - `landscape_voxels_textured_fine.json` (~105 MB) and `landscape_mc_baked_fine.json` (~110 MB)
  - other `*_mc_baked_fine.json` 4× colour-grid caches (2–10 MB), omitted for consistency
  - the Hagia 4× fine passes (`*hagia*_fine.json`, ~76 MB each)
- **The Little Hagia Sophia benchmark schematic** (by Skyman0, via Planet Minecraft / BawkBlock), which was used only for comparison.
  - intermediate `art/*.json` experiment passes (the viewer already ships the same models under `viewer/models/`)
- **Gallery PNGs / score JSON** under `pipeline/out/`. They were not present in the workspace copy, and the Minecraft-block galleries composite official vanilla textures, so they are not checked in. The scripts will rewrite them locally.
- Python virtualenvs, `__pycache__`, `node_modules` and `.DS_Store`.

## License and attribution

Minecraft is a trademark of Mojang Studios / Microsoft. This project is not affiliated with or endorsed by them. Do not copy official textures or the client JAR into forks of this repository.

The builder scripts, research notes, derived colour tables and generated reference images in this repo are published for research and personal use. The example mesh `pipeline/samples/Duck.glb` is the well-known Khronos glTF sample duck.

Two reference photos are from Wikimedia Commons under their own licences; credits are in `pipeline/refs/*_SOURCE.txt` and appear under the photo in the viewer:
- `refs/hagia.jpg`: Dosseman, CC BY-SA 4.0
- `refs/house.jpg`: Corey Coyle, CC BY 3.0
