# Research questions

## How do we make generated structures look more detailed and better?

Material, shade, and role are coarse buckets, so the block mapper has little freedom inside a region.
Every voxel that shares one material, one shade, and one role is one job, and that job receives a single Minecraft block.
A stone wall at mid shade with a plain role becomes the same block repeated across the wall.
Shade only runs from -2 to +2, each material is capped at 5 blocks, and role may only swap in a texture technique that stays within 8 colour units of the best colour match.
That keeps a wall coherent.
It also keeps the surface flat once the voxels exist.

These labels run after the shape is already built.
The mesh, the voxel grid, and the slab, trapdoor, and stair pass decide where walls, roofs, windows, and thin parts are.
The labels only choose which vanilla block paints each of those cells.
A window, a brick course, or a carving appears only when an earlier stage already separated it as its own material or its own shape.
The scorer will not invent that detail inside a uniform wall.

## Ideas

- Create a plan first (I think this is a must) before we generate the structure. How is the mesh used? I think we should probably use it.
- Considering a separate pipeline for structures.

## Bettering the mesh

A better mesh does not come from clicking around on the fal.ai website.
The scripts already call fal's API with `FAL_KEY`.
The mesh comes out only as good as the pictures uploaded, and those pictures can be fixed or replaced before the 3D call.

For the windmill, the `.glb` is built from the orthographic sheet, not from the photo directly.
`ortho_gen.py` asks fal (nano-banana) to redraw the photo as front, side, back, and top.
`ortho_lowpoly.py` or `ortho_hunyuan.py` then turns those panels into the mesh.
On this windmill the side panel drew the sails as an X, so that view was thrown out, and the sheet simplified the tower.
Hyper3D then built a solid sail and a thick base from what was left.
The arches and the window were already weak in the input.

Three levers, in the order they matter:

1. **Better views, same API.**
   The sheet has to show a short drum on tall open arches, a dark window, and sails as a lattice rather than a solid bar.
   The pipeline already retries a sheet up to three times and drops a panel that fails the geometry check or the Haiku review (`ortho_verify.py`).
   The real photo can be passed in with `--with-photo`, and the panels can be drawn by hand to skip nano-banana.
   The 3D model will follow a drawing that already has the holes.
2. **A different model or a higher face budget, still the API.**
   Hyper3D low-poly is the default at 4,000 faces (`--faces` on `ortho_lowpoly.py`).
   Hunyuan v3.1 Pro takes the same views and did better on organic shapes.
   On this windmill it kept legs and a dome, and the arches still failed once the build was cut to about 24 blocks.
   Raising the face count keeps more of the opening in the `.glb`.
   It does not invent an arch the drawings never showed.
3. **Edit the `.glb` locally, no fal.**
   After the file is downloaded, a mesh tool can cut the arcade through, punch the window, and thin the sails.
   Voxelizing then runs on that repaired file.
   That is the reliable way to force the three errors in the windmill screenshot, because image-to-3D keeps filling small holes and thickening stone.

Swapping websites or models without fixing the sheet will keep producing a tall solid tower with bar sails.

Ideas:

- Make specific detail annotation blocks and only allow special decoration blocks to be placed there
- Experiment with having annotations for all blocks
- Make a blueprint of the structure first before the mesh, list down all components etc
- From there, components / parts can be described in detail 
- Maybe first we generate a outline of the mesh of the general structure and then fill it in with the parts that were described up above.
- This way, we don't miss anything from the picture structure wise and we have the detail down.
- Could experiment with different pipelines (e.x with HTML, etc but probably wouldn't work).
- 