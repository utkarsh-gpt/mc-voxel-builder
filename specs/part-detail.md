# Part notes and detail stamp

The windmill pass is `pipeline/part_detail.py`. It reads the textured build, writes `art/final/meta/windmill_parts.json`, and updates the three files `mc_map.py` already reads.

The mesh stays as it is. Detail is added after the voxels exist. An LLM writes one note per part. A script places the blocks. The text is not sent back to fal.ai, and fal.ai is not asked to edit the `.glb`.

## Problem

Material, shade, and role describe a surface, not a part of the building. On the windmill the drum, the piers, the arches, and the cap are all stone. A script cannot be told "put a ring on the piers" because nothing marks which voxels are piers. The stone ring at about two thirds of the pier height, the plinth at each foot, and the lip under the cap are one block of relief. They are missing from the current build, and a longer prompt will not add them to the mesh.

## Goal

Break one finished voxel structure into named parts. Record the detail once on each part. Stamp any missing relief onto the voxel model. Then let the block mapper treat each part as its own job.

The first subject is the windmill. The pass is for structures. Organic subjects stay on the current pipeline.

## What a part is

A part is a set of voxels that act together: the piers, the ring on those piers, the drum, the cap, the window, the sails. Every voxel stores only the part id. The note lives on the part, once.

Repeated pieces share one part id. The four columns are all `pier`, so one shell op hits every column. The script still remembers which connected column each voxel belongs to, and a stamp on one column must not touch another column. Separate ids (`pier_0` … `pier_3`) are used only when a later note treats one pier differently from the others.

A note says where the part sits, how far it sticks out, and which material it uses. Example: "a vertical plate, two thirds of the way up each pier, flush to the pier." The numbers that place the blocks live in `op`, not in the sentence. The script adds `shape`. The naming step does not.

## Whole note

One paragraph sits beside the parts table. It says why the details exist together, and what the finished building must still read as. Example: "Dressed stone piers carry an open arcade. A ring below each capital marks the springing of the arches. A lip separates the dome from the drum. One dark window sits in the drum. The sails stay thin plates on the front of the cap."

The stamp script does not execute this paragraph. The naming step writes it, and the whole-building check reads it. A ring at two thirds of the pier can satisfy its own note and still sit below the arches. The whole note is what makes that a failure.

## How the windmill groups are found

The group step uses the zones `palette_texture.py` `zones_windmill` already computes (`ycap`, `core_top`, `zf`). It does not ask the LLM to draw the groups. The LLM names them and writes notes.

- `sail`: voxels `zones_windmill` marks `sail_white`, including the hub voxels it marks `dark_detail` on the sail.
- `cap`: voxels marked `cap_slate`.
- `drum`: stone at or above the arcade springing. The springing is the top of the pier columns, below `ycap`.
- `pier`: each connected column of stone below that line. All of those columns are stored as the one part id `pier`, with a column index kept beside the voxels.
- `window`: the `dark_detail` cluster `zones_windmill` already keeps on the drum (2 to 6 voxels, not an arch). This is an existing part. The opening op names it by id.
- `arch`: the empty cells enclosed by the pier columns and the underside of the drum. An arch has no voxels in the build. The group step stores those empty cells on the part as `kind: void`. The check uses them. No stamp targets them.

## Data

The pass reads and updates the textured build the mapper already uses:

- `art/final/{name}_voxels_textured.json`
- `art/final/meta/{name}_texture_labels.json`
- `art/final/meta/{name}_noise.json`

For the windmill, that textured file is produced from `art/final/windmill_voxels_subblocks.json`. The stamp does not edit the sub-block file. A later texture pass would drop voxels that exist only there.

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

`kind` is `existing` for voxels already in the build, `stamp` for voxels this pass adds, or `void` for empty cells the check must protect. `op` is present only when the part changes the grid. `height` is a fraction of the target part's own vertical extent, from its lowest voxel to its highest, not of the whole model.

Each voxel in the textured model gains `"p": "pier"`. Existing colour, shade, and sub-block shape stay as they are. A stamped cell carries a partial shape `s`, specified in `specs/detail-shapes.md`. It copies the parent's palette colour and is written into all three files:

- the textured model gains the voxel and its palette colour
- `texture_labels` gains a row with the part's material, shade `0`, and `surf` true when the cell faces air
- `noise` for that cell is the median noise of the parent part's surface voxels

The slot key in `mc_map.py` gains the part id. A job is `(part, shade, role)` instead of `(material, shade, role)`. `pier_ring` and `pier` are different jobs even when both use stone. The part's `material` still picks the block family.

The first ops are numbers only. The note explains why. The op does the edit.

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

## Steps

1. **Group.** A script reads `art/final/{name}_voxels_textured.json` and the windmill rules above. It writes a draft `parts` table with `kind: existing` or `kind: void` and no notes. It does not call an LLM.
2. **Name.** `claude` CLI, model `sonnet`, the same call shape as `ortho_verify.py`. It sees the photo (`refs/{name}.jpg`), the orthographic sheet, a render of the current voxels, and the draft groups. It returns one JSON object: the whole note, one note per part, and the stamps. It does not emit coordinates, regroup voxels, rewrite the tower, or set `shape`.
3. **Check.** Before stamping, apply every op on a copy of the grid. Reject a stamp that leaves its parent, two stamps that claim one cell, a shell or plinth whose new cells join two columns, a shell that occupies an `arch` void, and an opening that deletes a part another note still uses. Then `claude` CLI, model `haiku`, sees the photo, the whole note, the parts table, and a render of that copy, and returns whether the parts still add up to this building. That render is the fine grid in `specs/detail-shapes.md`, so a slab is drawn at half height.
4. **Stamp.** When the check passes, the script applies the ops and updates the three textured files in place. Re-running the group step ignores voxels whose part is a `stamp` and rebuilds from the `existing` parts, so a second run does not stamp on top of a stamp.
5. **Map.** `mc_map.py` runs on the updated textured model. Voxels that share a part, a shade, and a role are one job. The ring already carries its slab or trapdoor shape from `specs/detail-shapes.md`, and the pier shaft stays a full block.

## When the check fails

The naming step may run at most 3 times, the same cap as `ortho_verify.py`. On a retry the LLM may rewrite the summary, the per-part notes, and the numbers `height`, `proud`, and `depth` inside an existing op. It may not regroup voxels, add a part id, or add an op type. The script sets `shape` from the material, as `specs/detail-shapes.md` specifies. A reply that adds or changes `shape` is ignored. After the third failure, keep the last result that passed the grid check, write it, and set `check: failed` on the parts file. The whole-building failure is recorded. It does not block the stamp of a grid-valid result.

## Windmill, first check

The notes for this subject include:

- `pier`, one part id for every column under the arcade
- `pier_ring`, shell, height 0.66 of each pier column, proud 1, vertical slab size 0.25 flush to the pier, stone
- `pier_plinth`, plinth at the foot of each pier column, proud 1, vertical slab size 0.25 flush to the pier
- `cap_lip`, lip under the dome, proud 1, vertical slab size 0.25 flush to the cap
- `window`, the `dark_detail` cluster on the drum, opening of depth 1
- `arch`, a void, so the check can reject a stamp that fills the arcade
- `sail`, left as the plates already in the build

Done means the ring reads as a band that steps out from each pier, the pier shaft is unchanged, the arches stay open, and the sails are the ones from the current mesh.

## Out of scope

- Regenerating the orthographic sheet or the `.glb`
- Sending the part notes to fal.ai
- A prose note on every voxel
- A separate id per pier column
- Lattice holes inside the sails
- Full-cube stamps (the partial shapes are specified in `specs/detail-shapes.md`)
- Turtle, bonsai, and the other organic subjects
