# Blueprint before the build

This spec writes the parts of a structure down before any mesh is requested.
The sheet, the mesh, and the voxels are then checked against that list.
The first subject is the cathedral.
`specs/part-detail.md` still runs after the voxels exist, and only on parts the build already contains.

## Problem

The cathedral photo shows three separate doors, a rose window, a pointed window on each side of the rose, and one tall pointed window in each nave bay.
The voxel build shows a dark patch and a dark stripe.
A placed description gets those openings onto the orthographic sheet.
`ortho/cathedral_bp3_front.png` and `ortho/cathedral_bp3_right.png` are that sheet.
The 27-block-wide voxels made from it close the openings again.
A part that is only in the sheet is still missing.

## Goal

List every component of the structure before generating it.
Build the mass first.
Fill the named features into that mass.
A part on the list that is missing from the voxels fails the check.

The pass is for structures.
Organic subjects stay on the current pipeline.

## What a blueprint is

A blueprint is a file, one part id per component.
Repeated pieces share one id and a count.
The three doors are `door` with count `3`.
The rose is `rose` with count `1`.
The two towers are `tower` with count `2`.

Each part stores `kind`, `count`, `material`, and a note.
`kind` is `mass` or `feature`.
A feature also stores `parent`, the mass part it sits on, and `face` (`front`, `right`, `back`, `left`, or `top`).
The note says where the part sits and what it must still read as.
The numbers that place it live in the fields, not in the sentence.

One summary paragraph sits beside the parts.
It says what the finished building must still read as.
The generator does not execute the paragraph.
The check reads it.

## Mass and feature

Mass is the outline.
For the cathedral that is the plinth, the nave, the roof, the two towers, and the two spires.
The first mesh is built from these parts only.

A feature is a part the photo can lose without the mass collapsing.
For the cathedral that includes the three doors, the rose, the pointed window on each side of the rose, the nave windows, the buttresses, and the pinnacles.
Each feature names the mass part it belongs to, the face it sits on, and the band it sits in.

## Data

The list is written to `art/final/meta/{name}_blueprint.json` before `ortho_gen.py` runs.

```json
{
  "subject": "cathedral",
  "summary": "A honey limestone cathedral. Two towers and two spires stand on the west front. Three pointed doors sit at the bottom of that front. A rose window sits between the towers, with one pointed window on each side. Each nave bay has its own tall pointed window. The nave runs back under a dark slate roof.",
  "parts": {
    "tower": {"kind": "mass", "count": 2, "material": "limestone", "colour": "#ceb183", "note": "the two square west towers"},
    "spire": {"kind": "mass", "count": 2, "parent": "tower", "material": "limestone", "colour": "#ceb183", "note": "one slender spire on each tower, the highest points"},
    "nave": {"kind": "mass", "count": 1, "material": "limestone", "colour": "#ceb183", "note": "the long body running back from the west front"},
    "roof": {"kind": "mass", "count": 1, "parent": "nave", "material": "roof_slate", "colour": "#35322f", "note": "the steep dark slate roof"},
    "plinth": {"kind": "mass", "count": 1, "material": "limestone", "colour": "#ceb183", "note": "the thin flat base"},
    "door": {"kind": "feature", "count": 3, "parent": "nave", "face": "front", "material": "door_dark", "colour": "#2c2824", "note": "bottom band of the west front: a wide centre door and one narrower door in each tower base"},
    "rose": {"kind": "feature", "count": 1, "parent": "nave", "face": "front", "material": "glass", "colour": "#5e626d", "note": "middle band, centred between the towers, halfway up the wall under the belfries"},
    "front_window": {"kind": "feature", "count": 2, "parent": "tower", "face": "front", "material": "glass", "colour": "#5e626d", "note": "one tall pointed window immediately left of the rose and one immediately right"},
    "window": {"kind": "feature", "count": 8, "parent": "nave", "face": "right", "material": "glass", "colour": "#5e626d", "note": "one tall pointed window in the lower half of each nave bay, stone between them"}
  }
}
```

`parent` on a mass part is optional.
`face` is required on a feature.
The note states the band and the neighbours, so a window has a place and not only a name.
`colour` is the colour of that part, taken from the photo.
The colour pass paints the part's own blocks with that colour.
A window's pane is `#5e626d`, the blue-grey glass.
An empty opening has no blocks, so it cannot show that colour.
`window` count `8` is one side of the nave.
The other side is the same count on `face` `left`.

The file is not pasted into fal as a paragraph.
Each part becomes one line of the sheet prompt: the count, the note, and the face.

## Visible

Every part in the blueprint is required.
The build is unfinished while any required part is missing from a render of the voxels.
A sheet that draws the part does not satisfy the check.
A repeated part must show its count as separate shapes.
For a window, stone between one opening and the next is part of the requirement.
A dark stripe that joins a row of windows fails the same way a missing door fails.
`check: failed` records the missing ids.
It does not accept the build.

On the cathedral, `door` count 3, `rose` count 1, the pointed window on each side of the rose, and one tall window in each nave bay are required.
There is no separate clock in the photo, so the list does not add one.

A part is a physical component.
A window is an opening with a frame, or a thin pane set in that opening.
A dark colour on a solid block is not the window.
Structure is fixed first.
Colour is applied after, and a coarser grid may change the colour while the component stays.

## Steps

1. **List.** `claude` CLI, model `sonnet`, the same call shape as `ortho_verify.py`. It sees the photo (`refs/{name}.jpg`). It returns one JSON object: the summary and the parts. It does not emit voxels or coordinates.
2. **Check the list.** `claude` CLI, model `haiku`, sees the photo and the blueprint. It rejects a list that drops a separate object in the photo, or a count that disagrees with the photo. For the cathedral, a `door` count other than `3`, a missing `rose`, or a `window` count that is not one per nave bay, is a failure. The list step may run at most 3 times, the same cap as `ortho_verify.py`. On a retry it may add a part or correct a count, a parent, or a face. It may not remove a part the previous check said was present.
3. **Outline.** Build one mesh from the `mass` lines only, through the current path: an orthographic sheet, then `ortho_lowpoly.py` or `ortho_hunyuan.py`, then the local voxelize. Features are absent from this call. Keep these voxels. They are the body the features are added to.
4. **Fill.** Draw a second sheet of that same outline with every feature line required. Build a second mesh from that sheet and voxelize it. This mesh is the one that must contain the features. fal is not asked to edit the outline `.glb`.
5. **Check the build.** Haiku sees the photo, the blueprint, and a render of the feature voxels. Every required part must be visible as its own shape, at its count. For the cathedral the build fails while the three doors are merged, the rose is a solid dark patch, or the nave windows are one stripe. On a failure, redo the fill, at most 3 times, and name the missing part ids. A part the sheet already drew and the voxels swallowed is still missing. The next fill cuts that opening back into the voxels, or rebuilds on a grid where the part is at least one block wide. After the last failure, keep the blueprint, set `check: failed`, and record the missing ids. The build stays unfinished.

## Cathedral, first list

The list for this subject includes:

- `tower`, mass, count 2
- `spire`, mass, count 2, parent `tower`
- `nave`, mass, count 1
- `roof`, mass, count 1
- `plinth`, mass, count 1
- `door`, feature, count 3, face `front`, bottom band, colour `#2c2824`
- `rose`, feature, count 1, face `front`, middle band between the towers, colour `#5e626d`
- `front_window`, feature, count 2, one immediately each side of the rose, colour `#5e626d`
- `window`, feature, count 8 on each long side, one tall pointed window per bay, colour `#5e626d`
- `buttress`, feature, one per nave bay, on the sides, colour `#ceb183`
- `pinnacle`, feature, one on each buttress, colour `#ceb183`

Done means each of those parts is visible in the voxel render, as its own shape, at its count. A sheet that shows them and a voxel render that hides them is unfinished.

## Out of scope

- A markup or HTML pipeline.
- Sending the blueprint to fal as one long paragraph, or asking fal to edit an existing `.glb`.
- Placing Minecraft blocks. That stays with `mc_map.py` after the parts exist.
- Slab and shelf stamps. Those stay with `specs/detail-shapes.md`, and only for parts the voxels already contain.
- Inventing a part the photo does not show.
- Turtle and the other organic subjects.
