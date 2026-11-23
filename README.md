# mc-voxel-builder

Research tools that turn a single reference photo into a Minecraft build: orthogonal views, a low-poly mesh, coloured voxels, sub-blocks (slabs, trapdoors, stairs) and a final mapping onto vanilla 26.3 blocks, exported as `.schem` and `.litematic`.

**Live viewer:** [https://voxel-viewer-ten.vercel.app](https://voxel-viewer-ten.vercel.app)

This repository is a public snapshot of the builder scripts, block-colour dataset, research notes, generated references, schematics and the static viewer. The original working trees (`voxel-ai`, `mc-blocks`, `voxel-viewer`) are unchanged.

## Photo-to-Minecraft pipeline

1. **Reference photo.** Start with one picture of the subject (`pipeline/refs/`).
2. **Ortho sheet.** fal.ai (nano-banana) redraws the subject as flat front, side, back and top views on one sheet (`pipeline/ortho/`, `ortho_gen.py`).
3. **Verification.** Geometry checks plus a Haiku review (`ortho_verify.py`) catch views that do not agree. Bad views are dropped rather than regenerated forever.
4. **3D model.** Hyper3D (Trellis) builds a low-poly mesh by default (`ortho_lowpoly.py`). Organic or leafy subjects go to Hunyuan (`ortho_hunyuan.py`).
5. **Voxelize and fill.** The mesh is cut into voxels and the interior is filled solid (`fal_shape.py`, `vox.py`).
6. **Colour and texture.** Each material gets a base colour and a ramp of 3–5 shades placed by crevices, height and wear (`palette_texture.py`, `TEXTURE_RULES.md`). Neighbouring materials blend where they meet.
7. **Sub-blocks.** Thin or half-height spots become slabs or trapdoors; stair-shaped volumes become stairs with facing and corner shapes (`subblock.py`).
8. **Minecraft blocks.** Every voxel is scored against the block dataset on colour, local noisiness in the photo, and which shading technique its texture imitates (for example planks as hatching). Output is `.schem` / `.litematic` plus the viewer (`mc_map.py`, `mc_render.py`, `MC_BLOCK_RULES.md`).

Steps 5–8 and a rerun of step 8 are plain Python. fal.ai is used in steps 2 and 4 (and for generating references). Step 3 and the optional quality judge call the `claude` CLI (Haiku for view checks, Sonnet only if you turn the judge on).

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
  *RULES.md, QUALITY.md, PROMPTS.md, TRANSPARENT_BLOCKS_PLAN.md
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
python mc_map.py cathedral landscape turtle
```

Call the scripts from `pipeline/` so local imports resolve. `mc_map.py` and `mc_render.py` look for the dataset in `../mc-blocks` (override with `MC_BLOCKS`). The optional judge and the older revision loop need the `claude` CLI installed and signed in.

In-game: load a `.schem` with WorldEdit/FAWE (`//schem load` then `//paste`) or a `.litematic` with Litematica. Exports are tagged data version 4325 (1.21.5); those tools upgrade them on newer versions.

To refresh the local viewer from new `pipeline/art` models without deploying:

```bash
SYNC_NO_DEPLOY=1 viewer/sync.sh
```

## What is not in this repo

- **Secrets.** No `.env` files, API keys, tokens or credentials. Set `FAL_KEY` locally if you run fal.ai stages. Vercel project link metadata (`.vercel/`) is also omitted.
- **Official Minecraft assets.** The 26.3 client JAR (`mc-blocks/raw/client-26.3.jar`) and extracted vanilla PNGs, models and blockstates (`mc-blocks/assets/`) are © Mojang Studios / Microsoft and are **not** redistributed. To regenerate the colour dataset or render previews with real 16×16 textures, download the client yourself and pass `--jar` to `block_colors.py`.
- **`swatches.png`** from the original dataset work, because it contained official texture thumbnails. The published `mc-blocks/swatches_colors.png` is average-colour chips only. `blocks.json` / `blocks.csv` store derived colour and pattern metrics (and texture *path names*, not pixels).
- **Oversized generated binaries** (cap: 25 MB per file; GitHub rejects files over 100 MB):
  - `landscape_voxels_textured_fine.json` (~105 MB) and `landscape_mc_baked_fine.json` (~110 MB)
  - other `*_mc_baked_fine.json` 4× colour-grid caches (2–10 MB), omitted for consistency
  - intermediate `art/*.json` experiment passes (the viewer already ships the same models under `viewer/models/`)
- **Gallery PNGs / score JSON** under `pipeline/out/`. They were not present in the workspace copy, and the Minecraft-block galleries composite official vanilla textures, so they are not checked in. The scripts will rewrite them locally.
- Python virtualenvs, `__pycache__`, `node_modules` and `.DS_Store`.

## License and attribution

Minecraft is a trademark of Mojang Studios / Microsoft. This project is not affiliated with or endorsed by them. Do not copy official textures or the client JAR into forks of this repository.

The builder scripts, research notes, derived colour tables and generated reference images in this repo are published for research and personal use. The example mesh `pipeline/samples/Duck.glb` is the well-known Khronos glTF sample duck.
