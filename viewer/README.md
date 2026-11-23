# Voxel Viewer

Public 3D viewer for the voxel models in `pipeline/art/`.

**Live URL:** https://voxel-viewer-ten.vercel.app

Orbit, zoom and pan the model. The dropdown lists every `art/*.json` file; featured chips are the newest finals (`*_t_half_sub`, `*_t2_half_sub`, and the best available pass for the other subjects). Sub-block shapes (slabs, vertical slabs, stairs) render at their true sizes. You can also drop a voxel JSON onto the page.

## Update after new models

From the box:

```bash
viewer/sync.sh
```

That recopies `art/*.json` and reference photos, rebuilds `manifest.json`, and redeploys to production. To refresh local files only:

```bash
SYNC_NO_DEPLOY=1 viewer/sync.sh
```
