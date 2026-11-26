# Detailed parts

This spec has one plan.
The LLM reads the pictures of the object and writes down every part of it.
Each part gets a place (`where`) and detailed notes on its facade and architecture, in plain words.
The parts are then generated into the structure, and the build is checked until every part is really there as structure.
The notes do not need colours or dimensions.
They exist so the generated image carries as much of the architecture as the pictures show.

Every part must be generated as structure.
A window is an opening set back into the wall.
A door is a recess with a leaf at the back of it.
The rose is a round opening with solid tracery standing in it.
A part that is only a colour, a dark patch, or a drawing on a flat wall is not generated, and the build fails.
Nothing in this spec decides that a part exists from its colour.

This is a rule for each part on its own.
Every part on the list is generated explicitly, as its own structure.
The build is judged part by part.
A building that looks right as a whole, but has one part that is only a colour or is missing, fails.
No part is allowed to appear by chance, and no part passes because its neighbours are present.

It joins three earlier specs: the blueprint (`blueprint.md`), the part notes and stamp (`part-detail.md`), and the detail shapes (`detail-shapes.md`).
The pass is for structures.
Organic subjects stay on the current pipeline.
The first subjects are the cathedral (list, detailed notes, build check) and the windmill (part notes and stamps).

## Order of work

1. **Look and list.** The LLM CLI reads the pictures of the object and lists every part, each with a count, where it is, and detailed notes on its facade and architecture.
2. **Check the list.** A second read of the pictures rejects a part that is missing from the list or a count that disagrees with the pictures.
3. **Mesh.** One orthographic sheet carries the whole list, lines per part with where it is and its notes. One mesh is built from that sheet and voxelized.
4. **Check the build.** Every part on the list must exist in the voxels as its own shape, at its count. A part that is missing sends the build back to step 3, naming that part.
5. **Stamp.** Relief that no prompt can put into a mesh is added to the parts the build contains, as slabs and trapdoors. Never as full cubes.
6. **Map.** `mc_map.py` treats each part as its own job and turns each shape into a Minecraft block.

### Why there is one mesh

The whole list goes into one sheet, and one mesh is built from it.
No mass-only mesh is built first.
A mass-only mesh that is kept as "the body" and then followed by a second mesh with the features does nothing: the second mesh is drawn and voxelized on its own, so the first one costs a sheet and a mesh (about $0.20) for no change.
`mass` and `feature` stay as labels on a part, not as two meshes.
A mass part (tower, nave, roof) is the body, and a build that loses one fails.
A feature (door, window, buttress) is a part the body carries, and a build that loses one fails too, and is redone with that part named.

### Structure, not colour

A part counts as generated when the voxels contain it as geometry, as its own shape.
There are only four kinds of geometry that make a part, and every part on the list is one of them:

- **Set back.** The part is a recess in a wall: a window, a door, a portal, a niche, a panel. The wall face is in front of it, and its floor is deeper than the wall.
- **Open.** The part is a hole or a gap you can see through, or past: the openings of a belfry, the spaces between the posts of a balustrade, the air under a flying buttress, the gaps between the teeth of a battlement.
- **Proud.** The part is a solid that stands out of the surface: a buttress, a pinnacle, a gable, a string course, a moulding, a sill, a pier.
- **Outline.** The part changes the silhouette: a tower, a spire, a roof, a gable, an apse.

Every part on the list names which of these it is, in its `built_as` field, and the mesh, the voxels, and the check must give it that geometry.
A part that is none of these is not a part.
A colour on a solid block is not a window.
A dark stripe on a flat wall is not a door.
A drawing of the part on the sheet is not the part.
Three doors that merge into one dark stripe are one door.

The test is made with the colour removed.
The voxels are drawn in one flat grey, lit from the side, so only depth and outline show.
Every required part must still be seen, as its own shape, at its count.
A part that shows only when it is coloured fails.

Colour is applied after the structure is fixed.
It paints the blocks of a part that already exists.
It never creates a part, and it never decides that a part is there.
A drawing that shows a dark window is evidence for the notes, not for the build.
The check in "Visible" below is the test.

### Why the notes say how a part is formed

A sheet prompt that names a window gets a window-shaped dark patch on a flat wall.
A sheet prompt that says the window is a pointed opening set back into the wall, with a ledge under it and a solid mullion down the middle, gets a window that has depth.
So each note says how its part is formed in depth: what is set back, what is proud, what is open, and what makes the outline.

## Problems

**Parts lost in the voxels.**
The cathedral photo shows three separate doors, a rose window, a pointed window on each side of the rose, and one tall pointed window in each nave bay.
The voxel build shows a dark patch and a dark stripe.
A placed description gets those openings onto the orthographic sheet.
`ortho/cathedral_bp3_front.png` and `ortho/cathedral_bp3_right.png` are that sheet.
The 27-block-wide voxels made from it close the openings again.
A part that is only in the sheet is still missing.

**Relief with no owner.**
Material, shade, and role describe a surface, not a part of the building.
On the windmill the drum, the piers, the arches, and the cap are all stone.
A script cannot be told "put a ring on the piers" because nothing marks which voxels are piers.
The stone ring at about two thirds of the pier height, the plinth at each foot, and the lip under the cap are one block of relief.
They are missing from the current build, and a longer prompt will not add them to the mesh.

**Stamps that are too big.**
The first stamp wrote every new cell as a full block.
On the windmill a pier is about three blocks wide, so one block of proud is as big as the pier itself.
The legs bulge, the arches crowd, and the cap lip juts.
The same notes at half a block of thickness are the detail the photo actually has.

## Goals

- Write down every part of the object from its pictures, before any mesh is requested.
- For every part, say where it is and describe its facade and architecture in detail, so the sheet shows as much of it as the picture has.
- Generate the parts into the structure, and fail the check while any listed part is missing from the voxels.
- Break the finished voxel structure into named parts, and record relief once on each part.
- Stamp missing relief onto the voxel model as a slab or a trapdoor.
- Let the block mapper treat each part as its own job.

## Blueprint

### What a blueprint is

A blueprint is a file, one part id per component.
Repeated pieces share one id and a count.
The three doors are `door` with count `3`.
The rose is `rose` with count `1`.
The two towers are `tower` with count `2`.

Each part stores `kind`, `count`, `where`, `notes`, and `built_as`.
`kind` is `mass` or `feature`.
A feature also stores `parent`, the mass part it sits on, and `face` (`front`, `right`, `back`, `left`, or `top`).
`count` is a field and not a sentence, because the check needs it.

`built_as` says how the part is generated as structure.
It is a list of one or more of `set_back`, `open`, `proud`, and `outline`, defined under "Structure, not colour".
It is required on every part.
A part with no `built_as` is not generated explicitly, so the list is rejected.

`where` says where the part is.
It names the face or side, the height on that face, and the neighbours: above, below, beside, between.
One or two sentences.

`notes` describe the part in detail.
This is the facade and the architecture of the part, as the pictures show it:

- its form and outline
- how it is divided into tiers, bands, or bays, and what each one holds
- the shape of its arches, heads, and tops
- its mouldings, string courses, tracery, mullions, spokes, hoods, and trim
- what stands proud of the wall, what is set back into it, and what is open or cut through
- how deep a recess is (a shallow panel, a deep portal) and how far a solid stands out
- how the part repeats, and where the rhythm changes
- what is plain and what is ornate
- how it meets the parts around it

The notes are as long as the part needs.
They are plain words taken from the pictures.
They do not need colours, materials, sizes, or coordinates.
They must not rely on colour to say what a part is: "a dark window" is not a note, "a pointed opening set back into the wall with a ledge under it" is.
They must not invent anything the pictures do not show.

The notes exist so the sheet carries the detail.
A sheet prompt that says only "a rose window" gets a plain circle.
A sheet prompt that says the rose is a round opening set back into the wall, with a raised stone rim, a hub, and solid spokes standing in the opening, gets that.

`material` and `colour` are optional.
The pictures already carry the colour, and the colour pass reads it from them, after the structure exists.
A colour is never evidence that a part is present.

One summary paragraph sits beside the parts.
It says what the finished building must still read as.
The generator does not execute the paragraph.
The check reads it.

### Mass and feature

Mass is the outline.
For the cathedral that is the plinth, the nave, the roof, the two towers, and the two spires.

A feature is a part the photo can lose without the mass collapsing.
For the cathedral that includes the three doors, the rose, the pointed window on each side of the rose, the nave windows, the buttresses, and the pinnacles.
Each feature names the mass part it belongs to and the face it sits on.

### Data

The list is written to `art/final/meta/{name}_blueprint.json` before `ortho_gen.py` runs.

```json
{
  "subject": "cathedral",
  "summary": "A Gothic cathedral. Two towers with slender spires stand on the west front. Three pointed portals sit at the bottom of that front, a rose window above them between the towers. The nave runs back, each bay with its own tall pointed window between buttresses, under a steep slate roof.",
  "parts": {
    "tower": {"kind": "mass", "count": 2, "where": "one at each end of the west front, flanking the centre section; the tallest parts apart from their spires",
              "notes": "Each tower is a tall, square, slender shaft with a tall lower stage and a shorter belfry stage topped by a battlement. All four faces are built the same way. Corner buttresses climb each outer corner and end in sloped shoulders under the belfry.",
              "built_as": ["outline", "proud"]},
    "rose": {"kind": "feature", "count": 1, "parent": "west_front", "face": "front", "where": "in the middle of the west front, on the centre line, above the arcade and below the gable",
             "notes": "A large round window in a thick moulded ring of stone, with a pointed arch moulding above it. A small hub in the centre, twelve slim spokes radiating to the rim, each ending in a petal-shaped lobe. Small round medallions fill the corners around the circle.",
             "built_as": ["set_back", "open", "proud"]},
    "door": {"kind": "feature", "count": 3, "parent": "west_front", "face": "front", "where": "the bottom band of the west front, one wide in the centre and one narrower at the foot of each tower",
             "notes": "Each is a pointed arch set back into the wall under its own steep triangular gable. The centre one is the largest, with stepped rings in the arch and two doors split by a post. The two side ones are about half as wide with one door each.",
             "built_as": ["set_back", "proud"]}
  }
}
```

The full part notes for the cathedral are in [detailed-parts-cathedral.md](detailed-parts-cathedral.md).

`parent` on a mass part is optional.
`face` is required on a feature.
A part on the right side of the nave has a twin on `face` `left` with the same count and the same notes.

The file is not pasted into fal as a paragraph.
Each part becomes lines of the sheet prompt: the count, where it is, and its notes.

### Visible

Every part in the blueprint is required.
The build is unfinished while any required part is missing from a render of the voxels.
A sheet that draws the part does not satisfy the check.
A repeated part must show its count as separate shapes.
For a window, stone between one opening and the next is part of the requirement.
A dark stripe that joins a row of windows fails the same way a missing door fails.
A part that is present only as a colour fails the same way a missing part fails.
`check: failed` records the missing ids.
It does not accept the build.

On the cathedral, `door` count 3, `rose` count 1, the pointed window on each side of the rose, and one tall window in each nave bay are required.
There is no separate clock in the photo, so the list does not add one.

A part is a physical component.
A window is an opening set back into the wall, with a frame or a thin pane set in that opening.
A dark colour on a solid block is not the window.
Structure is fixed first.
Colour is applied after, and a coarser grid may change the colour while the component stays.

The check is made on structure only.
The renders the checker sees are drawn in flat grey, with depth and outline showing and no colour.
The script that counts openings per face counts recessed and open patches by depth alone.
It does not count a patch because it is dark.

The checker also reads each part's notes and records which of the described elements show in the renders.
A part whose notes are only partly visible (the rose has no spokes, the doors have no pointed heads) is present, and its build does not fail for that.
The missing elements are written to `detail_missing` and named in the next sheet prompt.

### Steps

The LLM is a command-line agent such as `claude` or `codex`.
The list may also be written by hand.
Then the list steps are skipped and the check uses the geometric count only.

1. **List.** Model tier `sonnet`, the same call shape as `ortho_verify.py`. It sees the photo (`refs/{name}.jpg`), and the orthographic views when they exist. It returns one JSON object: the summary and the parts, each with `where`, detailed `notes`, and `built_as`. It does not emit voxels, coordinates, dimensions, or colours.
2. **Check the list.** Model tier `haiku` sees the pictures and the blueprint. It rejects a list that drops a separate object in the pictures, a count that disagrees with them, or a part with no `where`, no `built_as`, or with thin `notes` (notes that do not say more than the part's name, or that describe the part only by its colour and not by how it is formed in depth). For the cathedral, a `door` count other than `3`, a missing `rose`, or a `window` count that is not one per nave bay, is a failure. The list step may run at most 3 times, the same cap as `ortho_verify.py`. On a retry it may add a part or correct a count, a parent, a face, or a part's `where` or `notes`. It may not remove a part the previous check said was present.
3. **Mesh.** Draw one orthographic sheet with every part on the list, each as its own separate shape at its count and built the way its `built_as` and notes describe, so it has depth and not only a colour. Each part is its own line in the prompt, and none is left to appear by chance. Build one mesh from that sheet through the current path (`ortho_lowpoly.py` or `ortho_hunyuan.py`, then the local voxelize). fal is not asked to edit a `.glb`.
4. **Check the build.** The checker sees the pictures, the blueprint, and flat grey renders of the voxels (depth and outline, no colour) from the front, both sides, the back, and a three-quarter view. Every part must be visible as its own shape, at its count, with the geometry its `built_as` names. The verdict is given for each part, and a part is never passed because the building looks right overall. A script also counts recessed and open patches per face, by depth alone, against the openings the list requires. When a part is lost at the voxel grid, the same mesh is voxelized again on a finer grid before it counts as lost. This costs no fal call.
5. **Retry.** On a failure, redo the mesh, at most 3 times, and name the missing part ids in the sheet prompt. A part the sheet already drew and the voxels swallowed is still missing. After the last failure, keep the blueprint, set `check: failed`, and record the missing ids. The build stays unfinished.

## Part notes and stamps

The windmill pass is a new script, `pipeline/part_detail.py`.
It reads the textured build, writes `art/final/meta/windmill_parts.json`, and updates the three files `mc_map.py` reads.

The mesh stays as it is.
Detail is added after the voxels exist.
An LLM writes one note per part.
A script places the blocks.
The text is not sent back to fal.ai, and fal.ai is not asked to edit the `.glb`.

### What a part is

A part is a set of voxels that act together: the piers, the ring on those piers, the drum, the cap, the window, the sails.
Every voxel stores only the part id.
The note lives on the part, once.

Repeated pieces share one part id.
The four columns are all `pier`, so one shell op hits every column.
The script still remembers which connected column each voxel belongs to, and a stamp on one column must not touch another column.
Separate ids (`pier_0` to `pier_3`) are used only when a later note treats one pier differently from the others.

A note says where the part sits, how far it sticks out, and which material it uses.
Example: "a vertical plate, two thirds of the way up each pier, flush to the pier."
The numbers that place the blocks live in `op`, not in the sentence.
The script adds `shape`.
The naming step does not.

### Whole note

One paragraph sits beside the parts table.
It says why the details exist together, and what the finished building must still read as.
Example: "Dressed stone piers carry an open arcade. A ring below each capital marks the springing of the arches. A lip separates the dome from the drum. One dark window sits in the drum. The sails stay thin plates on the front of the cap."

The stamp script does not execute this paragraph.
The naming step writes it, and the whole-building check reads it.
A ring at two thirds of the pier can satisfy its own note and still sit below the arches.
The whole note is what makes that a failure.

### How the windmill groups are found

The group step uses the zones `palette_texture.py` `zones_windmill` already computes (`ycap`, `core_top`, `zf`).
It does not ask the LLM to draw the groups.
The LLM names them and writes notes.

- `sail`: voxels `zones_windmill` marks `sail_white`, including the hub voxels it marks `dark_detail` on the sail.
- `cap`: voxels marked `cap_slate`.
- `drum`: stone at or above the arcade springing. The springing is the top of the pier columns, below `ycap`.
- `pier`: each connected column of stone below that line. All of those columns are stored as the one part id `pier`, with a column index kept beside the voxels.
- `window`: the `dark_detail` cluster `zones_windmill` already keeps on the drum (2 to 6 voxels, not an arch). This is an existing part. The opening op names it by id.
- `arch`: the empty cells enclosed by the pier columns and the underside of the drum. An arch has no voxels in the build. The group step stores those empty cells on the part as `kind: void`. The check uses them. No stamp targets them.

### Data

The pass reads and updates the textured build the mapper already uses:

- `art/final/{name}_voxels_textured.json`
- `art/final/meta/{name}_texture_labels.json`
- `art/final/meta/{name}_noise.json`

For the windmill, that textured file is produced from `art/final/windmill_voxels_subblocks.json`.
The stamp does not edit the sub-block file.
A later texture pass would drop voxels that exist only there.

Notes live in a new file `art/final/meta/{name}_parts.json`:

```json
{
  "subject": "windmill",
  "summary": "Dressed stone piers carry an open arcade. A ring below each capital marks the springing of the arches. A lip separates the dome from the drum. One dark window sits in the drum. The sails stay thin plates on the front of the cap.",
  "parts": {
    "pier": {
      "kind": "existing",
      "material": "stone",
      "note": "square stone columns under the arcade"
    },
    "pier_ring": {
      "kind": "stamp",
      "parent": "pier",
      "material": "stone",
      "note": "a vertical plate, two thirds of the way up each pier, flush to the pier",
      "op": {"type": "shell", "target": "pier", "height": 0.66, "proud": 1, "shape": {"type": "vslab", "size": 0.25}}
    },
    "window": {
      "kind": "existing",
      "material": "stone",
      "note": "the dark opening in the drum",
      "op": {"type": "opening", "target": "window", "depth": 1}
    },
    "arch": {
      "kind": "void",
      "note": "empty cells inside the arcade, used by the check"
    }
  }
}
```

`kind` is `existing` for voxels already in the build, `stamp` for voxels this pass adds, or `void` for empty cells the check must protect.
`op` is present only when the part changes the grid.
`height` is a fraction of the target part's own vertical extent, from its lowest voxel to its highest, not of the whole model.

Each voxel in the textured model gains `"p": "pier"`.
Existing colour, shade, and sub-block shape stay as they are.
A stamped cell carries a partial shape `s`, specified under "Detail shapes" below.
It copies the parent's palette colour and is written into all three files:

- the textured model gains the voxel and its palette colour
- `texture_labels` gains a row with the part's material, shade `0`, and `surf` true when the cell faces air
- `noise` for that cell is the median noise of the parent part's surface voxels

The slot key in `mc_map.py` gains the part id.
A job is `(part, shade, role)` instead of `(material, shade, role)`.
`pier_ring` and `pier` are different jobs even when both use stone.
The part's `material` still picks the block family.

### Ops

The first ops are numbers only.
The note explains why.
The op does the edit.

| op | fields | effect |
|---|---|---|
| `shell` | `target`, `height`, `proud`, `shape` | at `height` along each column of `target`, add `proud` face neighbours of each occupied cell of that column, then drop arch cells |
| `plinth` | `target`, `proud`, `shape` | add `proud` face neighbours around the bottom layer of each column of `target`, then drop arch cells |
| `lip` | `target`, `proud`, `shape` | add `proud` face neighbours around the lower edge of `target`, then drop arch cells |
| `opening` | `target`, `depth` | clear the voxels of the named component `target`, and `depth` blocks inward from their exposed face |

A shell, plinth, or lip keeps only the four face neighbours that sit farther from the tower centre.
Diagonal corners stay empty.
Any of those cells that land in an arch void are dropped.
A shell or plinth is applied per column.
Added cells from one column that would touch another column are not written.
The grid check rejects that op.

### Steps

1. **Group.** A script reads `art/final/{name}_voxels_textured.json` and the windmill rules above. It writes a draft `parts` table with `kind: existing` or `kind: void` and no notes. It does not call an LLM.
2. **Name.** The LLM CLI, model tier `sonnet`, the same call shape as `ortho_verify.py`. It sees the photo (`refs/{name}.jpg`), the orthographic sheet, a render of the current voxels, and the draft groups. It returns one JSON object: the whole note, one note per part, and the stamps. It does not emit coordinates, regroup voxels, rewrite the tower, or set `shape`.
3. **Check.** Before stamping, apply every op on a copy of the grid. Reject a stamp that leaves its parent, two stamps that claim one cell, a shell or plinth whose new cells join two columns, a shell that occupies an `arch` void, and an opening that deletes a part another note still uses. Then the LLM CLI, model tier `haiku`, sees the photo, the whole note, the parts table, and a render of that copy, and returns whether the parts still add up to this building. That render is the fine grid described under "Render" below, so a slab is drawn at half height.
4. **Stamp.** When the check passes, the script applies the ops and updates the three textured files in place. Re-running the group step ignores voxels whose part is a `stamp` and rebuilds from the `existing` parts, so a second run does not stamp on top of a stamp.
5. **Map.** `mc_map.py` runs on the updated textured model. Voxels that share a part, a shade, and a role are one job. The ring carries its slab or trapdoor shape, and the pier shaft stays a full block.

### When the check fails

The naming step may run at most 3 times, the same cap as `ortho_verify.py`.
On a retry the LLM may rewrite the summary, the per-part notes, and the numbers `height`, `proud`, and `depth` inside an existing op.
It may not regroup voxels, add a part id, or add an op type.
The script sets `shape` from the material.
A reply that adds or changes `shape` is ignored.
After the third failure, keep the last result that passed the grid check, write it, and set `check: failed` on the parts file.
The whole-building failure is recorded.
It does not block the stamp of a grid-valid result.

## Detail shapes

The part pass adds the ring, the plinth, and the cap lip.
It changes only the shape of the cells it adds.
Each added cell is a slab or a trapdoor.
A full cube is not a detail.

### Shapes the mapper already keeps small

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

### Which shape a stamp uses

The script writes `shape` on the op.
It does not take the shape from the naming reply.
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

### Windmill ops

The notes are the ones in the parts example above.
The ops carry a shape.

- `pier_ring`: shell, height `0.66` of each pier, proud `1`, vertical slab size `0.25`, flush to the pier.
- `pier_plinth`: plinth, proud `1`, vertical slab size `0.25`, flush to the pier.
- `cap_lip`: lip, proud `1`, vertical slab size `0.25`, flush to the cap.
- `window`: opening of depth `1`, no shape.
- `sail`: unchanged.

The arch check still counts the whole cell, then drops any cell inside the arcade.
The plate that remains is a quarter of a block thick and the full height of that cell.
On a pier about three blocks wide that plate is a small share of the pier.

### Data

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
Labels, noise, and the part id are as specified under "Part notes and stamps".
The part id remains the mapper slot, so the ring and the pier shaft are different jobs.

### Shape check

The grid check also rejects an op when:

- an added cell has no `s`
- `shape.type` is not `slab` or `vslab`
- a slab is not size `0.5` with `align` `bottom` or `top`
- a vertical slab is not size `0.25`
- the material has no slab for a slab stamp, or no trapdoor family for a vertical slab
- `proud` is not `1`

The arch test uses the cell footprint.
The cells that can reach an arch are the face neighbours farther from the tower centre, as the shell, plinth, and lip ops specify.
Corners stay empty.
A slab that lands in an arch void is rejected, the same as a full cube.

### Render

The check render and the compare image must show the slab, not a full cube.
`vox.render` fills every occupied cell as a cube, and it does not read `s`.
Before either picture is drawn, expand each cell with the 4x templates in `subblock.shapes`, then call `vox.render` on that fine grid.
`subblock.expand` is the path the galleries already use.
A stamp shape must be one of those templates.
A slab of size `0.5` aligned bottom or top already has a box there.

### Map

`mc_map.py` reads `s` from the textured model.
A slab stamp resolves to the material's slab.
A vertical slab on wood, copper, or iron resolves to an open trapdoor.
A vertical slab on stone or cap slate resolves to a wooden shelf.
The summary must not list a detail part under "full".
If it would, the stamp should have been rejected above.

## Subjects

### Cathedral

The cathedral is the first subject for the list, the detailed notes, and the build check.
Its notes are written out part by part in [detailed-parts-cathedral.md](detailed-parts-cathedral.md), read off the drawings and the photo.
They are the input of the experiment below.

### Windmill, first check

The notes for this subject include:

- `pier`, one part id for every column under the arcade
- `pier_ring`, shell, height 0.66 of each pier column, proud 1, vertical slab size 0.25 flush to the pier, stone
- `pier_plinth`, plinth at the foot of each pier column, proud 1, vertical slab size 0.25 flush to the pier
- `cap_lip`, lip under the dome, proud 1, vertical slab size 0.25 flush to the cap
- `window`, the `dark_detail` cluster on the drum, opening of depth 1
- `arch`, a void, so the check can reject a stamp that fills the arcade
- `sail`, left as the plates already in the build

Done means the ring reads as a band that steps out from each pier, the pier shaft is unchanged, the arches stay open, and the sails are the ones from the current mesh.

## Experiment: the cathedral

The experiment tests one claim: detailed notes that say how each part is formed in depth make a mesh that contains the parts as geometry, where a plain list of part names does not.

**Input.**
The photo `pipeline/refs/cathedral.jpg`.
The drawings `pipeline/ortho/cathedral_v3_front.png`, `cathedral_v3_right.png`, `cathedral_v3_back.png`, `cathedral_v3_top.png`, and the sheet `cathedral_v3_sheet.png`.
The part list and notes in [detailed-parts-cathedral.md](detailed-parts-cathedral.md).
The list is written by hand, so the list and list-check steps are skipped.

**Two runs, the same photo.**

- **A, the detailed notes.** The sheet prompt has one block per part from the notes file: the count, `where`, `notes`, and `built_as`.
- **B, the control.** The sheet prompt has only the part id and the count for each part, for example "3 x door, 1 x rose, 11 x aisle window". No `where`, no notes.

**Steps for each run.**

1. Build the sheet prompt from the parts.
2. Draw one orthographic sheet from the photo and that prompt.
3. Build one mesh from the sheet and voxelize it. If a part is lost at the first grid, voxelize the same mesh again on a finer grid, and again finer, with no new mesh.
4. Draw flat grey renders of the voxels (depth and outline, no colour): front, both sides, back, and a three-quarter view.
5. For each part, record present or missing, at its count, as its own shape with the geometry its `built_as` names.
6. If a part is missing, redo the mesh with that part named, at most 3 times.

**What is recorded.**
For each run: the parts present and missing, the count seen for each repeated part, the `detail_missing` elements, the number of retries, and the cost (one sheet and one mesh, about $0.20 for the mesh, per attempt).

**Pass.**
Run A passes when every part in the notes file is present at its count in the flat grey renders.
These are the parts that decide it:

- three separate recessed portals, the middle one wider
- the rose, readable as a circle by its outline and depth, with its hub and spokes as solid bars
- four front windows, two stacked on each tower face
- the five-opening arcade under the rose
- eleven aisle windows and ten clerestory windows on each long side, each a separate opening
- ten piers with a pinnacle each on each long side, and a flying buttress with air under it from each
- sixteen belfry openings and two battlements
- the faceted apse with three windows and its fan of arms

The claim holds if A has more of these parts present than B, or the same parts with more of the detail from their notes.

**Where it is expected to fail.**
At a grid of 48 or 72 a part narrower than one block is lost whatever the sheet drew.
The arcade, the rose spokes, the belfry slats, and the pinnacles are the likely losses.
A loss of that kind is the finding, and it says which parts need a finer grid or a stamp.

## Work to do

Nothing in this spec is built yet.
The pieces to build are:

- `pipeline/blueprint.py`, new: the list and list-check steps, the sheet prompt from the parts, one mesh, the build check, and the retry.
- A flat grey depth render, new, used by the checker and by the script that counts openings.
- An opening count by depth alone, with no use of darkness.
- A feature pass that builds an opening as geometry (a recess with a pane or a leaf set back in it) and paints it afterwards.
- `pipeline/part_detail.py`, new: group, name, check, and stamp for the windmill, then other subjects.
- `mc_map.py`: slots keyed by part, and shapes resolved to slabs, trapdoors, and shelves.
- The experiment above, run on the cathedral.

## Out of scope

- A markup or HTML pipeline.
- Sending the blueprint to fal as one long paragraph, or asking fal to edit an existing `.glb`.
- Sending the part notes or the shapes to fal.ai.
- Regenerating the orthographic sheet or the `.glb` in the part pass.
- Placing Minecraft blocks in the blueprint step. That stays with `mc_map.py` after the parts exist.
- A separate mass-only mesh.
- Colours, dimensions, or positions in numbers as required fields of a part.
- Slab and shelf stamps on a part the voxels do not already contain.
- Inventing a part the photo does not show.
- A prose note on every voxel.
- A separate id per pier column.
- Lattice holes inside the sails.
- Full-cube stamps.
- Stairs, walls, and any block the set currently excludes.
- Changing the sails or any other voxel that was already in the build.
- Borrowing a wooden trapdoor for a stone part. A wooden shelf is the vertical plate for that part.
- Choosing a larger grid so the same full cube would look smaller.
- Turtle, bonsai, and the other organic subjects.
