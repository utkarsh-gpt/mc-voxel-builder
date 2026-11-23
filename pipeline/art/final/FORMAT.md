# Voxel JSON format (for the viewer app)

Files: `<subject>_voxels_subblocks.json` (block grid with sub-block shapes - load this) and `<subject>_voxels_subblocks_fine.json`
(same model pre-expanded to a 4x grid of plain unit cubes - fallback if a viewer only draws full cubes; scale by 1/4).

```json
{"name": "...", "size": [W, H, D], "palette": {"c0": "#rrggbb", ...},
 "voxels": [{"x": 0, "y": 0, "z": 0, "c": "c0", "s": {...optional shape...}}], "source": {...}}
```
- Axes: x = east (object's right), y = up, z = south (toward the model's FRONT). Voxel (x,y,z) occupies the unit cube [x,x+1]x[y,y+1]x[z,z+1].
- `s` absent = full block. Otherwise one of (sizes are fractions of a block; Minecraft mapping in brackets):
  - `{"type":"slab","size":0.5|0.25,"align":"bottom"|"top"}` - full width/depth, reduced height [slab / snow layers]
  - `{"type":"vslab","size":0.5|0.25,"axis":"x"|"z","align":"east"|"west"|"south"|"north"}` - full height, reduced along one horizontal axis, flush to the `align` side [vertical slab]
  - `{"type":"stairs","facing":"north"|"south"|"east"|"west","half":"bottom"|"top"}` - half-height base slab plus a half-block step on the `facing` side
    (half=top: upside-down, base on top, step underneath) [stairs]
