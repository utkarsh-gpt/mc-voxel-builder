"""Facade orientation: which end of a generated mesh is the front.

Hyper3D meshes come out with the facade on either +z or -z. shape_fit only aligns walls to the axes (a multiple of 90
degrees), and feature_detect / blueprint.py assume the front elevation is seen from +z. A flipped mesh therefore gets
its front-elevation features (rose, portals, facade windows) stamped on the apse end, and the front check judges the
wrong end.

Convention (same as the sheet and vox.render): the right elevation is seen from +x and its image left is +z, so the
facade is the LEFT end of the right elevation. The mesh is flipped (a 180 degree turn about y) when the facade is on -z.
The facade is the end with the spires/towers; the right drawing only breaks ties (see facade_flip).

    flip = facade_flip(occ, "ortho/NAME_right.png")      # occ[x, y, z] bool
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage

TALL = 0.1        # the tall part must be more than this far from the middle to decide on its own
MARGIN = 0.02     # the flipped fit must beat the plain fit by this much IoU, otherwise keep the mesh as it is (symmetric parts)


def _largest(m):
    lab, n = ndimage.label(m)
    if n <= 1: return m
    return lab == (1 + int(np.argmax(ndimage.sum(m, lab, range(1, n + 1)))))


def _crop(m):
    ys, xs = np.nonzero(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def drawing_mask(path):
    g = np.asarray(Image.open(path).convert("L")) < 235
    g = ndimage.binary_opening(g, iterations=max(1, int(0.004 * max(g.shape))))
    return _crop(_largest(g))


def side_projection(occ):
    """right elevation silhouette from +x: rows top -> bottom (y descending), image left = +z"""
    return _crop(occ.any(0)[::-1, ::-1])


def _iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


def fit_scores(occ, drawing_path):
    """(iou plain, iou flipped) of the right-elevation drawing against the voxel side projection"""
    P = side_projection(occ)
    D = np.asarray(Image.fromarray(drawing_mask(drawing_path).astype(np.uint8) * 255).resize(P.shape[::-1], Image.NEAREST)) > 127
    return _iou(D, P), _iou(D, P[:, ::-1])


def spire_position(occ):
    """z of the tallest part (spires, towers) as a fraction of the length: 0 = -z end, 1 = +z end"""
    xs, ys, zs = np.nonzero(occ)
    top = ys >= 0.8 * ys.max()
    return float(zs[top].mean() / max(occ.shape[2] - 1, 1))


def facade_flip(occ, drawing_path=None, log=print):
    """True when the facade is on the -z end and the model must be turned 180 degrees about y.

    1. The tall end (spires, towers) is the facade. Used whenever the tall part is clearly on one half (|z - 0.5| > TALL).
    2. Otherwise (towers at both ends, or no towers) the right-elevation drawing decides, with a margin.
       The drawing is NOT used first: the sheet's right view is sometimes drawn from the other side (towers at the image
       right), and a silhouette from +z and -z are identical mirror images, so only the side profile can tell the ends apart.
    """
    zt = spire_position(occ)
    if abs(zt - 0.5) > TALL:
        flip = zt < 0.5
        log(f"  orientation: tall end at z={zt:.2f} -> facade on {'-z: FLIP 180' if flip else '+z: keep'}")
        return flip
    if drawing_path:
        try:
            a, b = fit_scores(occ, drawing_path)
            flip = b > a + MARGIN
            log(f"  orientation: tall end ambiguous (z={zt:.2f}); right-elevation fit plain {a:.3f} vs flipped {b:.3f} -> {'FLIP 180' if flip else 'keep'}")
            return flip
        except Exception as e:
            log(f"  orientation: drawing fit failed ({e})")
    log(f"  orientation: ambiguous (tall end z={zt:.2f}), keep")
    return False


def flip_occ(a):
    """turn an [x, y, z, ...] array 180 degrees about y"""
    return a[::-1, :, ::-1]


def flip_voxel_dict(d):
    """the same turn for a voxel JSON ({'size': [W, H, D], 'voxels': [{'x','y','z',...}]}); other fields (shape facings)
    are only rotated by shape_fit before blocks exist, so none are touched here"""
    W, H, D = d["size"]
    for v in d["voxels"]:
        v["x"] = W - 1 - v["x"]; v["z"] = D - 1 - v["z"]
    return d
