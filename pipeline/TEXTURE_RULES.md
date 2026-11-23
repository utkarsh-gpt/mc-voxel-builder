# TEXTURE_RULES — colour stage for small plain-RGB voxel builds

Input: model JSON (`size [W,H,D]`, `palette`, `voxels [{x,y,z,c,s?}]`, y up, z+ = front). Output: same voxels and `s`;
only `c` and `palette` change. Do all colour maths in CIELAB (D65) and LCh(ab). ΔE = CIE76 unless noted.

## 0. Pipeline and shared definitions

Order: **zones → material labels → per-voxel score → ramp index → cleanup → blends → step check → palette.**

- `occ[W,H,D]` is 1 where a voxel exists. Sub-blocks count as occupied. For AO, weight = `s.size` if given, otherwise 1.
- **surface** = any of the 6 face neighbours is empty or out of bounds. Interior voxels get the material base and are
  skipped in every statistic below (quantiles, cluster counts, band checks).
- `lab0` = the current palette colour per voxel. `lab_s` = smoothed colour: per-channel **median** over the occupied
  3×3×3 neighbourhood *inside the same zone*, run 2 passes.
- `dist(c, base) = sqrt((0.5·ΔL)² + Δa² + Δb²)`. L is down-weighted because current L errors are mostly baked lighting.
- **Normal**: `n = -∇ gaussian_filter(occ, σ=1.0)`, normalised. **Sun** `Ldir = normalize(-0.5, 1.0, 0.6)` (upper-left-front).
- **Openness**: `g = gaussian_filter(occ_w, σ=1.2)` sampled at the voxel. `open = clip((0.50 - g)/0.15, -1, 1)`.
  Flat face ≈ 0, convex edge > 0, crevice/arch/under-ledge < 0.
- **Cluster noise** `N(scale, seed)`: uniform [-1,1] lattice every `scale` voxels, trilinear upsample
  (`ndimage.zoom(order=1)` or `map_coordinates`). Octaves: `n = N(s) + 0.4·N(s/2)`. Normalise over the material's
  surface voxels: `n = clip(n / (2·std), -1, 1)`. Seed = hash(subject, material, purpose), so it is deterministic and
  independent per use.
- Label cleanup (after nearest-base): 1 pass of 3×3×3 mode filter within the zone, then 26-connected components smaller
  than `min_size[m]` are relabelled to the most common neighbouring label.

## 1. Materials per subject (base hex ≈ L*)

### 1a. Windmill (22×24×12)
| material | base | L* | notes |
|---|---|---|---|
| stone | `#958f81` | 60 | warm limestone grey (photo). Replaces noisy c0/c1/c4/c5/c6/c11/c13… |
| cap_slate | `#4f555c` | 36 | lead/slate dome. Current navy `#102c45` is far too saturated |
| sail_white | `#e2dfd4` | 89 | painted lattice. Remap the blue cloth noise (c3/c12/c10) here |
| dark_detail | `#34312d` | 21 | window glass, hub/axle |

Zones (geometry first, colour second):
1. **core footprint** = xz cells occupied in ≥60% of layers y∈[1, 0.45H]. `zf` = max z of the core footprint.
2. **sail** = (z > zf) OR (y > top of core) OR (xz ∉ dilate(core footprint, 1) and y ≥ 2). These are thin plates in
   the front plane; expected sail plane z≈10–11. Sails are forced to sail_white, except for the hub.
3. **hub** = sail voxels with |x − x_core_centre| ≤ 1, |y − y_cap| ≤ 1, and `lab_s` L* < 45 → dark_detail
   (min_size 2).
4. **cap**: on core voxels, `y_cap` = lowest y ≥ 0.4H where ≥50% of the layer's surface has `lab_s` b* < −2 or
   L* < 42. Fallback: top-of-core − 3. Core voxels with y ≥ y_cap are cap_slate. Expected y_cap = 12, cap y12–15.
5. **stone** = all remaining core voxels. All dark arch-interior noise stays stone; AO darkens it later.
6. **window** = stone surface voxels with `lab_s` L* < 32, y ∈ [0.55·y_cap, y_cap−1], and a component size of 2–6
   that is *not* face-adjacent to an empty cell inside the footprint (that would be an arch) → dark_detail.

### 1b. Cottage (24×15×14)
| material | base | L* | notes |
|---|---|---|---|
| wall_white | `#e6e3dc` | 90 | whitewashed block. Current `#8e8c8c` is baked shadow |
| thatch | `#8d8c74` | 58 | grey-olive weathered reed |
| moss (accent on thatch) | `#6f7a4a` | 49 | placed by rule (§3), not from input colour |
| door_red | `#a1392d` | 39 | door, window frames (photo/sheet red, desaturated) |
| glass_dark | `#3a3e44` | 26 | window panes, door light |
| chimney_brick | `#8a4e3e` | 40 | browner and lower in chroma than door_red |

Zones:
1. **Eave height** `y_e` = lowest y where the occupied footprint area is ≥ 1.15× the layer below (overhang starts).
   Expected y_e = 3, walls y0–2.
2. **Thatch top** `y_r` = highest y where the layer has ≥ 6 voxels (expected 11). **chimney** = all voxels with y > y_r,
   plus the 26-connected component below them whose `lab_s` hue is 15–55° with C* > 8 (min_size 3).
3. **red/glass** (only within 1 voxel of the outer wall faces, or within 2 voxels of y_e, which covers the eyebrow
   arches): `lab_s` a* > 14 and hue 10–45° → door_red (min_size 3). `lab_s` L* < 30 with ≥ 2 door_red neighbours in
   the 26-neighbourhood → glass_dark (min_size 1).
4. **wall_white** = remaining voxels with y < y_e. Ignore the input colour; just remove red/glass first.
5. **thatch** = remaining voxels with y ≥ y_e. The black underside line (c2/c5 at y=3) is thatch; it becomes thatch −2
   via the cause rules.

### 1c. Bonsai (23×24×24)
| material | base | L* | notes |
|---|---|---|---|
| foliage | `#6a9030` | 55 | yellow-green needles. Current `#697914` is too olive/dark |
| trunk | `#9a6234` | 47 | orange-brown bark, includes branches |
| pot | `#7a2a20` | 29 | oxblood glaze |
| soil | `#3d2d1f` | 20 | dark loam |
| moss (accent on soil) | `#55692a` | 41 | placed by rule (§3) |

Zones:
1. **pot top** `y_p` = highest y where ≥ 50% of the layer has `lab_s` a* > 12 and hue 10–45°. Voxels with y ≤ y_p that
   are on the outer xz ring (within 1 of the layer's convex hull) → pot. Expected pot y0–3.
2. **soil** = voxels with y ∈ [y_p−1, y_p+2] that are inside the rim ring and have `lab_s` L* < 30, plus the pot-zone
   interior top.
3. **canopy bottom** `y_c` = lowest y > y_p where the layer area is ≥ 3× the trunk area (expected 13). For y_p < y < y_c,
   everything is trunk.
4. For y ≥ y_c: trunk if `lab_s` hue is 45–80°, C* > 15, L* 28–62, *and* the voxel is 26-connected to the trunk
   column (branches). Everything else is foliage, including grey-white background-bleed specks (c8/c22).

## 2. Ramp construction

Ramp shade `s` is an integer offset from the base. `L = L0 + s·dL_up` for s > 0, `L0 + s·dL_dn` for s < 0.
- **Chromatic** (base C* ≥ 10): rotate the hue `|s|·dh` degrees along the shortest arc, toward **85°** (warm/yellow)
  for s > 0 and toward **250°** (cool/blue) for s < 0. Never rotate past the target. Chroma: `C·(1+cu·s)` for s > 0,
  `C·(1−cd·|s|)` for s < 0. Cap at `C0 + 10`.
- **Near-neutral** (C* < 10): no hue rotation. s > 0: `b += s·db_up`. s < 0: `b −= |s|·db_dn`, `a −= 0.3·|s|`.
- Convert LCh→Lab→sRGB. If out of gamut, reduce C in 2% steps until it fits. Round to 8-bit.

| material | shades | dL_dn | dL_up | mode | dh / db | cd / cu |
|---|---|---|---|---|---|---|
| stone | −2..+2 | 6 | 5 | neutral | db_up 1.5, db_dn 1.0 | – |
| cap_slate | −2..+1 | 5 | 6 | neutral | **db_up −1.5** (sky-blue sheen), db_dn 0.5 | – |
| sail_white | −2..+1 | 5 | 3 | neutral | db_up 1.0, db_dn 1.5 (blue shadow) | – |
| dark_detail | −1..0 | 5 | – | neutral | db_dn 0.5 | – |
| wall_white | −2..+1 | 6 | 3 | neutral | db_up 1.5, db_dn 2.0 | – |
| thatch | −2..+2 | 6 | 6 | chromatic | dh 6 | 0.05 / 0.08 |
| moss (both) | −1..+1 | 6 | 6 | chromatic | dh 8 (+1 = yellow lichen) | 0.05 / 0.06 |
| door_red | −1..+1 | 6 | 5 | chromatic | dh 4 (shadow → crimson) | 0.06 / 0.03 |
| glass_dark | −1..0 | 5 | – | neutral | db_dn 1.0 | – |
| chimney_brick | −2..+1 | 6 | 5 | chromatic | dh 5 | 0.08 / 0.03 |
| foliage | −2..+2 | 8 | 7 | chromatic | dh 7 (lit → yellow-green, shade → blue-green) | 0.08 / 0.06 |
| trunk | −2..+2 | 7 | 6 | chromatic | dh 5 | 0.06 / 0.04 |
| pot | −2..+1 | 5 | 5 | chromatic | dh 4 (lit → orange, shade → plum) | 0.04 / 0.03 |
| soil | −1..+1 | 4 | 4 | chromatic | dh 3 | 0.05 / 0.03 |

Whites only get +1 because they would clip. Dark materials only go down by 1 step because lower values crush to black.
Neighbouring shades of a material should always be about 5–8 ΔE apart: visible, but not a jump.

## 3. Placement: per-voxel score → ramp index

For each surface voxel of material m:
```
hgt = 2*(y - y0_m)/(y1_m - y0_m) - 1          # y0_m/y1_m = material's min/max y
up  = clip(n_y, 0, 1);  dir = dot(n, Ldir)
S   = w_open*open + w_up*up + w_h*hgt + w_dir*dir + w_n*N(scale_m) + cause
```
| material | w_open | w_up | w_h | w_dir | w_n | scale | quantiles q(−2), q(−1) / q(+1), q(+2) |
|---|---|---|---|---|---|---|---|
| default (stone, thatch, trunk) | 0.9 | 0.6 | 0.5 | 0.35 | 0.8 | 4 (trunk 2, stretched ×2 in y) | 3%, 10% / 7%, 2% |
| foliage | 1.3 | 0.7 | 0.5 | 0.4 | 0.9 | 3 | 5%, 12% / 10%, 3% |
| wall_white | 0.7 | 0 | 0.4 | 0.35 | 0.5 | 4 | 3%, 12% / 6%, – |
| cap_slate | 0.6 | 0.8 | 0.3 | 0.3 | 0.4 | 4 | 4%, 10% / 8%, – |
| sail_white | 0.5 | 0.5 | 0 | 0.3 | 0.3 | 5 | 2%, 8% / 6%, – |
| pot | 0.8 | 0.9 | 0.5 | 0.3 | 0.25 | 5 | 6%, 12% / 8%, – |
| soil, brick | 0.8 | 0.4 | 0 | 0.2 | 0.6 | 3 (brick 2) | – , 12% / 10% (brick 4%,10%/8%) |
| small details (door, glass, hub, window) | 1.0 | 0.5 | 0 | 0.3 | 0 | – | absolute: S<−0.6 → −1; S>0.7 → +1 (door) |

Quantisation: thresholds are **quantiles of S over the material's surface voxels**. The bottom q(−2) gets −2, the next
q(−1) gets −1, the top q(+2) gets +2, the next q(+1) gets +1, and the rest is base. That keeps base at ≈ 78–80% and
accents at ≤ 20–22%. Foliage (≈ 70% base) is the deliberate exception, because interior canopy shade is structural.
Use the `y + 1.2·N(2)` jittered height wherever a cause rule tests height, so cause bands come out ragged.

**Cause terms** (added to S before quantising; "force k" means set after quantising and before cleanup):
- *Windmill stone*: damp base `y_eff ≤ 1` → −0.8. Under the cap overhang (y ∈ [y_cap−2, y_cap−1], outward-facing)
  → −0.7. Within Chebyshev distance 1 of an arch void or window → −0.6. Ledge tops (up > 0.7 and not the top layer)
  → +0.8, and the voxel directly below a ledge → −0.4 (drip shadow).
- *Windmill cap*: lowest cap ring with an empty cell below (the lip) → force −2. Up-facing dome → +0.5.
- *Sails*: up-facing top edges → +0.6. Sail voxels directly in front of the cap or tower (z = zf+1) → −0.5
  (their shadow side).
- *Cottage wall*: `y_eff < 0.8` (grime at the foot) → −0.9. Under the eave (a thatch voxel within 3 above in the column,
  or in the column shifted 1 outward) → −1.2. Face-adjacent to door/window → −0.4. The sun-facing gable gets the +1
  share through `dir`.
- *Thatch*: underside (empty cell below) → force −2. Lowest outward row (eave lip) → −0.8. Ridge (y ≥ y_r−1 and
  up > 0.5) → +1.0 (sun-bleached). Within 2 of a door/window top (eyebrow arches) → −0.6.
  **Soot**: within 2.5 (Euclidean) of the chimney footprint and y ≥ chimney base −1 → −1.2.
- *Moss on thatch*: `M = 0.6·(−dir) + 0.4·(−open) + 0.5·N(3, moss) + 0.3·(1−h01) − 1.0·ridge − 0.5·[up>0.7]`.
  The top **9%** of thatch surface by M becomes moss. Drop moss components < 3. Moss shades: up-facing top 20% of moss
  → +1 (lichen), moss with open < −0.3 → −1, else 0.
- *Chimney*: top layer → force −2 (soot). The layer below it → max −1.
- *Foliage*: underside (empty below, lower half of canopy) → −0.8. Horizontal distance to the trunk axis ≤ 2 and not on
  the outer shell (open < 0) → −0.5 (dark inner needles). Top shell up > 0.7 → +0.6.
- *Trunk*: within 2 layers below y_c → −0.6 (canopy shadow). Root flare (y ≤ y_p+2) → handled by blending (§4).
- *Pot*: rim top (up > 0.7, y = y_p) → +1.0. Feet/bottom layer → force −2. The voxel directly under the rim lip → −0.6.
- *Soil*: face-adjacent to the pot → −0.5. **Moss on soil**: soil within 2 of the trunk, plus the top 10% of soil by
  N(3, moss) → moss (components ≥ 2).

**Cleanup** (surface only, same material, in this order):
1. *Anti-speckle* (2 passes): if a non-base voxel has < 2 neighbours (26-nbhd) with the same index, set it to the
   neighbour mode (ties go toward 0). If a voxel has ≥ 6 neighbours sharing index k ≠ its own, set it to k
   (fills holes).
2. *Min cluster*: 26-components of index ±1 with < 3 voxels step one toward 0. A ±2 voxel is allowed only if it touches
   at least one ±1 voxel of the same sign; otherwise it steps one toward 0.
3. *Anti-splatter*: for every face-adjacent pair (18-nbhd on the surface) with |Δidx| ≥ 2, move the voxel farther from
   0 one step toward 0. Repeat until stable (≤ 5 passes).
4. *Anti-sandwich*: for each y layer with ≥ 8 surface voxels, a band exists if one index k ≠ 0 covers ≥ 60% of the
   layer and ≤ 25% of each adjacent layer. Fix it by recomputing S for that layer with w_h = 0 and w_n × 1.5, then
   re-quantising with the same thresholds. Cause-forced voxels are exempt; their ragged y_eff already breaks bands.

## 4. Gradient blending between materials

For each **BLEND** pair (receiver A, donor B):
1. `d = distance_transform_edt(~maskB)` evaluated at surface voxels of A. Jitter: `d' = d + 0.9·N(2, blend)`.
2. Anchors: `cA` = A's ramp colour at the mode shade of A voxels with d' ∈ (n, n+2]. In other words, start from what A
   already looks like just outside the zone. `cB` = B's colour at the shade given in the table.
3. Number of intermediates: `n = clip(round(ΔE(cA, cB)/11) − 1, 0, 3)`. The width comes from the colour gap, not a
   fixed depth. Chain: `m_k = lerp_Lab(cA, cB, k/(n+1))` for k = 1..n. Snap each `m_k` to an existing palette colour if
   ΔE < 3.
4. `k(v) = clip(n + 1 − ceil(d'), 0, n)`. k = 0 keeps the A shade; k = n touches B.
5. Step check along the joint chain [A shades…, m_1..m_n, B]: face-adjacent voxels may differ by at most 1 position.
   If they differ by more, lower the larger k by 1 and repeat. Then rerun §3 cleanup step 3 on the A-only voxels.

| subject | pair (receiver ← donor) | type | cB shade |
|---|---|---|---|
| windmill | stone ← cap_slate (cornice under the dome) | BLEND | cap −1 |
| windmill | sails ↔ anything; window/hub ↔ stone | CRISP | – |
| cottage | wall_white ← thatch (top wall rows under the eave) | BLEND | thatch −2 |
| cottage | thatch ← chimney_brick (soot/crumb ring at the chimney foot) | BLEND | brick −2 |
| cottage | thatch ↔ moss | BLEND (usually n = 0 because they are ΔE ≈ 11 apart, which is fine) | moss 0 |
| cottage | door_red / glass_dark ↔ wall or thatch; door ↔ glass | CRISP | – |
| bonsai | trunk ← soil (root flare) | BLEND | soil 0 |
| bonsai | trunk ← foliage (branches inside the canopy) | BLEND | foliage −2 |
| bonsai | soil ← moss | BLEND | moss −1 |
| bonsai | pot ↔ soil (glazed rim edge); pot ↔ foliage | CRISP | – |

CRISP pairs: no intermediates, and the §3 cleanup never mixes across them. A single-voxel boundary is intended.
Expected chain lengths: soil→trunk ΔE ≈ 30 → n = 2. Wall→thatch−2 ≈ 40 → n = 3. Stone→cap−1 ≈ 30 → n = 2.

## 5. Palette size target

| subject | materials | ramp shades | blend + accents | target total |
|---|---|---|---|---|
| windmill | 4 | 5+4+4+2 = 15 | 2–3 | **16–20** |
| cottage | 6 | 4+5+3+3+2+4 = 21 | 3–5 | **22–28** |
| bonsai | 5 | 5+5+4+3+3 = 20 | 3–5 | **20–26** |

After the final assignment, merge palette colours closer than ΔE2000 < 2.0 (keep the most used one). Drop unused shades.
If a subject goes over its target, first drop the rarest ±2 shades (by moving those voxels to ±1), then merge blend
intermediates into the nearest ramp shade.
Sanity checks to log per material: base share (expect 75–82%, foliage ≈ 70%), mean ±1 cluster size (expect ≥ 4),
the number of isolated non-base voxels (expect 0), and the maximum |Δidx| between neighbours (expect ≤ 1).

STATUS: done
FILES: TEXTURE_RULES.md
NOTES: Geometry-first zoning: the input colours are mostly baked lighting/sky noise, so colour only breaks ties inside a zone.
NOTES: The expected y/z split values (cap y12–15, eave y3, pot y0–3, canopy ≥ y13) come from per-layer colour counts of the current JSONs; use them as test assertions.
NOTES: Python was blocked in this session, so the L* values are hand-calculated (±2) and no rule has been run on the data.
