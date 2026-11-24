# Detail shapes

The part pass in `specs/part-detail.md` adds the ring, the plinth, and the cap lip.
This spec keeps that pass, those parts, and those three files.
It changes only the shape of the cells the pass adds.
Each added cell is a slab or a trapdoor.
A full cube is not a detail.

## Problem

The first stamp wrote every new cell as a full block.
On the windmill a pier is about three blocks wide, so one block of proud is as big as the pier itself.
The legs bulge, the arches crowd, and the cap lip juts.
The same notes at half a block of thickness are the detail the photo actually has.

## Shapes the mapper already keeps small

`pipeline/MC_BLOCK_RULES.md` places two partial shapes and turns the rest into full cubes.
This pass uses only the two that stay small.

A slab of size `0.5` becomes the material's own slab.
It fills the cell's footprint and half its height.
Stone, deepslate, and wood have slabs, so the pier and the cap can use one.

A vertical slab of size `0.25` becomes an open trapdoor, flush to one face of the cell.
The plate is about a quarter of a block thick.
Only wood, copper, and iron have trapdoors.
A vertical slab of size `0.5` is placed as a full block, so this pass does not use that size.

Stairs and walls are excluded from the block set.
A stair written here would be saved as a full cube.
They are not a detail shape.

## Which shape a stamp uses

The script writes `shape` on the op.
It does not take the shape from the naming reply.
A reply that adds or changes `shape` is ignored.
The script fills facing fields that depend on the parent face, per cell, and those fields are not stored on the op.

A part whose families include wood, copper, or iron may get a vertical slab of size `0.25`, placed as a trapdoor.
Stone and cap slate get the same vertical slab, placed as the nearest wooden shelf.
A material has a slab when some block in its `FAMILIES` entry has a slab in the dataset, the same test `slab_of` uses.
A material has a trapdoor family when that entry includes `wood`, `copper`, or `iron`.

A course, a foot, or a lip that can be short uses a slab of size `0.5`.
The windmill ring, plinth, and cap lip do not.
They have to stay thin in plan, or they close the arcade.
They are vertical slabs of size `0.25`, flush to the parent.

A moulding that must stay thin in plan uses a vertical slab of size `0.25`.
The script sets `axis` and `align` so the plate sits against the parent.
Wood, copper, and iron place that plate as an open trapdoor.
Stone and cap slate have no trapdoor and no shelf of their own.
A shelf is the vertical plate this block set does have, and it is wood, about five pixels deep.
Those parts place the nearest wooden shelf, and they do not fall back to a full cube.

If the material cannot place the named shape, the op is not written.
The check records the reason.
The cell is not saved as a full block.
A trapdoor is not borrowed from another material.
A shelf is the one borrowed plate, and only for a vertical slab whose material has no shelf.

`proud` is `1`.
The shape is the thickness.
A second layer of cells is a second footprint, and the check rejects it.

An opening removes cells and has no shape.
Voxels already in the build keep the shape they have.
The sails stay the plates from the mesh.

## Windmill

The notes are the ones in `specs/part-detail.md`.
The ops gain a shape.

- `pier_ring`: shell, height `0.66` of each pier, proud `1`, vertical slab size `0.25`, flush to the pier.
- `pier_plinth`: plinth, proud `1`, vertical slab size `0.25`, flush to the pier.
- `cap_lip`: lip, proud `1`, vertical slab size `0.25`, flush to the cap.
- `window`: opening of depth `1`, no shape.
- `sail`: unchanged.

The arch check still counts the whole cell, then drops any cell inside the arcade.
The plate that remains is a quarter of a block thick and the full height of that cell.
On a pier about three blocks wide that plate is a small share of the pier.
This spec stamps it.

## Data

`op.shape` is the shape every cell of that stamp receives.
Facing fields that depend on the parent face are filled per cell and are not stored on the op.

```json
"pier_ring": {
  "kind": "stamp",
  "parent": "pier",
  "material": "stone",
  "note": "a vertical plate, two thirds of the way up each pier, flush to the pier",
  "op": {
    "type": "shell",
    "target": "pier",
    "height": 0.66,
    "proud": 1,
    "shape": {"type": "vslab", "size": 0.25}
  }
}
```

Each added voxel in `art/final/{name}_voxels_textured.json` stores that object as `s`.
`s` absent still means a full block, and a stamp must not omit it.
Labels, noise, and the part id are unchanged from `specs/part-detail.md`.
The part id remains the mapper slot, so the ring and the pier shaft are different jobs.

## Check

The grid check in `specs/part-detail.md` also rejects an op when:

- an added cell has no `s`
- `shape.type` is not `slab` or `vslab`
- a slab is not size `0.5` with `align` `bottom` or `top`
- a vertical slab is not size `0.25`
- the material has no slab for a slab stamp, or no trapdoor family for a vertical slab
- `proud` is not `1`

The arch test uses the cell footprint.
The cells that can reach an arch are the face neighbours farther from the tower centre, as the shell, plinth, and lip effects in `specs/part-detail.md` specify.
Corners stay empty.
A slab that lands in an arch void is rejected, the same as a full cube.

## Render

The check render and the compare image must show the slab, not a full cube.
`vox.render` fills every occupied cell as a cube, and it does not read `s`.
Before either picture is drawn, expand each cell with the 4x templates in `subblock.shapes`, then call `vox.render` on that fine grid.
`subblock.expand` is the path the galleries already use.
A stamp shape must be one of those templates.
A slab of size `0.5` aligned bottom or top already has a box there.

## Map

`mc_map.py` already reads `s` from the textured model.
A slab stamp resolves to the material's slab.
A vertical slab on wood, copper, or iron resolves to an open trapdoor.
A vertical slab on stone or cap slate resolves to a wooden shelf.
The summary must not list a detail part under "full".
If it would, the stamp should have been rejected above.

## Out of scope

- Stairs, walls, and any block the set currently excludes.
- Changing the sails or any other voxel that was already in the build.
- Sending shapes to fal.ai, or editing the mesh.
- Borrowing a wooden trapdoor for a stone part. A wooden shelf is the vertical plate for that part.
- Choosing a larger grid so the same full cube would look smaller.
- Turtle, bonsai, and the other organic subjects.
