/**
 * Parse voxel-art JSON (art/*.json) into a flat list of coloured blocks.
 *
 * Schema (see pipeline/vox.py and subblock.py):
 *   { name, size: [W,H,D], camera: {azim, elev}, palette: {key: "#rrggbb"|["#..",...]},
 *     shapes?: [...], voxels?: [{x,y,z,c, s?: shape}] }
 *
 * Colour "." / "air" carves empty space. Palette lists are a deterministic
 * per-voxel pick. Sub-block shape lives in voxel.s (absent = full block).
 *
 * Axes: +x east, +y up, +z south (model front; toward the viewer at azim 0).
 *
 * Minecraft block models ({format: "mc_blocks"}) use a palette of blockstates
 * with block-space boxes and 4x4 baked face colours instead; see parseMcBlocks.
 */
const AIR = new Set([".", "air", "", null, undefined]);

function hexToRgb(h) {
  if (Array.isArray(h) && h.length >= 3 && typeof h[0] === "number") {
    return [h[0], h[1], h[2]];
  }
  const s = String(h).trim().replace(/^#/, "");
  if (s.length === 3) {
    return [
      parseInt(s[0] + s[0], 16),
      parseInt(s[1] + s[1], 16),
      parseInt(s[2] + s[2], 16),
    ];
  }
  if (s.length >= 6) {
    return [
      parseInt(s.slice(0, 2), 16),
      parseInt(s.slice(2, 4), 16),
      parseInt(s.slice(4, 6), 16),
    ];
  }
  return [200, 200, 200];
}

function normalizePalette(pal) {
  const out = {};
  if (!pal || typeof pal !== "object") return out;
  for (const [k, v] of Object.entries(pal)) {
    const list = Array.isArray(v) ? v : [v];
    out[k] = list.map(hexToRgb);
  }
  return out;
}

function hashPick(n, x, y, z) {
  // deterministic, well-mixed 32-bit hash
  let h = (Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(z | 0, 2147483647)) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return n ? h % n : 0;
}

function resolveColor(palette, key, x, y, z) {
  if (AIR.has(key)) return null;
  if (typeof key === "string" && key.startsWith("#")) return hexToRgb(key);
  const list = palette[key];
  if (!list || !list.length) {
    // unknown key: mid grey, still visible
    return [160, 160, 160];
  }
  return list[hashPick(list.length, x, y, z)];
}

function inferSize(voxels) {
  let W = 1, H = 1, D = 1;
  for (const v of voxels || []) {
    if (v.x + 1 > W) W = v.x + 1;
    if (v.y + 1 > H) H = v.y + 1;
    if (v.z + 1 > D) D = v.z + 1;
  }
  return [W, H, D];
}

function idx(W, H, D, x, y, z) {
  return x * H * D + y * D + z;
}

function rasterize(data, palette) {
  const [W, H, D] = data.size;
  const occ = new Uint8Array(W * H * D);
  const keys = new Array(W * H * D);

  const paintMask = (cells, c) => {
    if (AIR.has(c)) {
      for (const i of cells) {
        occ[i] = 0;
        keys[i] = null;
      }
      return;
    }
    for (const i of cells) {
      occ[i] = 1;
      keys[i] = c;
    }
  };

  const paintIf = (pred, c) => {
    const cells = [];
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        for (let z = 0; z < D; z++) {
          if (pred(x, y, z)) cells.push(idx(W, H, D, x, y, z));
        }
      }
    }
    paintMask(cells, c);
  };

  for (const s of data.shapes || []) {
    const t = s.type;
    try {
      if (t === "box") {
        const [x0, y0, z0] = s.from;
        const [x1, y1, z1] = s.to;
        const xa = Math.min(x0, x1), xb = Math.max(x0, x1);
        const ya = Math.min(y0, y1), yb = Math.max(y0, y1);
        const za = Math.min(z0, z1), zb = Math.max(z0, z1);
        const hollow = !!s.hollow;
        paintIf((x, y, z) => {
          if (x < xa || x > xb || y < ya || y > yb || z < za || z > zb) return false;
          if (!hollow) return true;
          return x === xa || x === xb || y === ya || y === yb || z === za || z === zb;
        }, s.c);
      } else if (t === "ellipsoid") {
        const [cx, cy, cz] = s.center;
        const r = s.radius;
        const [rx, ry, rz] = typeof r === "number" ? [r, r, r] : r;
        const rx2 = Math.max(rx, 0.5) ** 2;
        const ry2 = Math.max(ry, 0.5) ** 2;
        const rz2 = Math.max(rz, 0.5) ** 2;
        const clip = s.clip_y;
        paintIf((x, y, z) => {
          if (clip && (y < clip[0] || y > clip[1])) return false;
          const dx = x - cx, dy = y - cy, dz = z - cz;
          return (dx * dx) / rx2 + (dy * dy) / ry2 + (dz * dz) / rz2 <= 1;
        }, s.c);
      } else if (t === "cylinder") {
        const [bx, by, bz] = s.base;
        const r0 = s.radius;
        const r1 = s.r_top != null ? s.r_top : r0;
        const h = s.height;
        const ax = s.axis || "y";
        paintIf((x, y, z) => {
          let A, P, Q, a0, p0, q0;
          if (ax === "y") { A = y; P = x; Q = z; a0 = by; p0 = bx; q0 = bz; }
          else if (ax === "x") { A = x; P = y; Q = z; a0 = bx; p0 = by; q0 = bz; }
          else { A = z; P = x; Q = y; a0 = bz; p0 = bx; q0 = by; }
          if (A < a0 || A >= a0 + h) return false;
          const tt = Math.max(0, Math.min(1, (A - a0) / Math.max(h - 1, 1)));
          const rr = r0 + (r1 - r0) * tt;
          return (P - p0) ** 2 + (Q - q0) ** 2 <= rr * rr + 0.25;
        }, s.c);
      } else if (t === "shell_shade") {
        const srcC = s.c_from;
        const [dx, dy, dz] = s.dir || [0, -1, 0];
        const depth = s.depth != null ? s.depth : 1;
        const cells = [];
        for (let x = 0; x < W; x++) {
          for (let y = 0; y < H; y++) {
            for (let z = 0; z < D; z++) {
              const i = idx(W, H, D, x, y, z);
              if (!occ[i]) continue;
              if (srcC && keys[i] !== srcC) continue;
              let exposed = false;
              for (let k = 1; k <= depth; k++) {
                const nx = x + dx * k, ny = y + dy * k, nz = z + dz * k;
                if (nx < 0 || ny < 0 || nz < 0 || nx >= W || ny >= H || nz >= D) {
                  exposed = true;
                  break;
                }
                if (!occ[idx(W, H, D, nx, ny, nz)]) {
                  exposed = true;
                  break;
                }
              }
              if (exposed) cells.push(i);
            }
          }
        }
        paintMask(cells, s.c_to);
      }
    } catch (e) {
      console.warn("shape error", t, e);
    }
  }

  for (const v of data.voxels || []) {
    const x = v.x | 0, y = v.y | 0, z = v.z | 0;
    if (x < 0 || y < 0 || z < 0 || x >= W || y >= H || z >= D) continue;
    const i = idx(W, H, D, x, y, z);
    if (AIR.has(v.c)) {
      occ[i] = 0;
      keys[i] = null;
    } else {
      occ[i] = 1;
      keys[i] = v.c;
    }
  }

  const voxels = [];
  for (let x = 0; x < W; x++) {
    for (let y = 0; y < H; y++) {
      for (let z = 0; z < D; z++) {
        const i = idx(W, H, D, x, y, z);
        if (!occ[i]) continue;
        const color = resolveColor(palette, keys[i], x, y, z);
        if (!color) continue;
        voxels.push({ x, y, z, color, shape: null });
      }
    }
  }
  return voxels;
}

/* ---------- Minecraft block models (format: "mc_blocks") ---------- */

const BAKE_FACES = ["top", "side", "bottom"];

/** "#rrggbb" / "#rrggbbaa" → [r,g,b,a]; null / invalid → transparent. */
function bakeCell(c) {
  if (c == null) return null;
  const s = String(c).trim().replace(/^#/, "");
  if (s.length !== 6 && s.length !== 8) return null;
  const a = s.length === 8 ? parseInt(s.slice(6, 8), 16) : 255;
  if (a < 128) return null;
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16), 255];
}

function normalizeBake(bake, res) {
  const n = res * res;
  const grids = {};
  for (const f of BAKE_FACES) {
    const src = bake && Array.isArray(bake[f]) ? bake[f] : null;
    grids[f] = src ? Array.from({ length: n }, (_, i) => bakeCell(src[i])) : null;
  }
  // Missing faces borrow from a sibling so every face has something to show.
  const any = grids.side || grids.top || grids.bottom || new Array(n).fill([150, 150, 150, 255]);
  for (const f of BAKE_FACES) if (!grids[f]) grids[f] = any;
  return grids;
}

function isUnitBox(b) {
  return b[0] <= 0 && b[1] <= 0 && b[2] <= 0 && b[3] >= 1 && b[4] >= 1 && b[5] >= 1;
}

function parseMcBlocks(data, dropped) {
  const res = Math.max(1, data.bake_res | 0 || 4);
  const voxelsIn = Array.isArray(data.voxels) ? data.voxels : [];
  const size = Array.isArray(data.size) && data.size.length >= 3
    ? [data.size[0] | 0, data.size[1] | 0, data.size[2] | 0]
    : inferSize(voxelsIn);

  const palette = {};
  for (const [key, e] of Object.entries(data.palette || {})) {
    if (!e || typeof e !== "object") continue;
    const boxes = (Array.isArray(e.boxes) && e.boxes.length ? e.boxes : [[0, 0, 0, 1, 1, 1]])
      .filter((b) => Array.isArray(b) && b.length >= 6)
      .map((b) => b.slice(0, 6).map(Number));
    const bake = normalizeBake(e.bake, res);
    const solid = BAKE_FACES.every((f) => bake[f].every(Boolean));
    palette[key] = {
      key,
      id: e.id || key,
      state: e.state || (e.id ? `minecraft:${e.id}` : key),
      props: e.props || {},
      boxes,
      bake,
      material: e.material || null,
      technique: e.technique || null,
      // Hides neighbouring faces only if it is a whole, hole-free cube.
      fullOpaque: boxes.length === 1 && isUnitBox(boxes[0]) && solid,
      fullCube: boxes.length === 1 && isUnitBox(boxes[0]),
      count: 0,
    };
  }

  const blocks = [];
  for (const v of voxelsIn) {
    const x = v.x | 0, y = v.y | 0, z = v.z | 0;
    if (x < 0 || y < 0 || z < 0 || x >= size[0] || y >= size[1] || z >= size[2]) continue;
    const entry = palette[v.b];
    if (!entry) continue;
    entry.count++;
    blocks.push({ x, y, z, key: v.b });
  }

  const name = data.name || "untitled";
  const camera = {
    azim: data.camera && data.camera.azim != null ? Number(data.camera.azim) : 35,
    elev: data.camera && data.camera.elev != null ? Number(data.camera.elev) : 20,
  };
  let subCount = 0;
  for (const b of blocks) if (!palette[b.key].fullCube) subCount++;
  const stats = {
    name,
    size,
    format: "mc_blocks",
    blockCount: blocks.length,
    subCount,
    subPct: blocks.length ? (100 * subCount) / blocks.length : 0,
    paletteSize: Object.values(palette).filter((e) => e.count).length,
  };
  return { format: "mc_blocks", name, size, camera, bakeRes: res, palette, blocks, voxels: [], stats, dropped };
}

/**
 * @param {object} data parsed JSON
 * @returns {{name:string, size:number[], camera:{azim:number,elev:number}, voxels:object[], stats:object, dropped:boolean}}
 *   mc_blocks models additionally carry {format, bakeRes, palette, blocks}.
 */
export function parseVoxelArt(data, { dropped = false } = {}) {
  if (!data || typeof data !== "object") throw new Error("Not a voxel JSON object");
  if (data.format === "mc_blocks") return parseMcBlocks(data, dropped);
  const voxelsIn = Array.isArray(data.voxels) ? data.voxels : [];
  const shapesIn = Array.isArray(data.shapes) ? data.shapes : [];
  if (!data.size && !voxelsIn.length && !shapesIn.length) {
    throw new Error("JSON has no size, voxels, or shapes");
  }
  const size = Array.isArray(data.size) && data.size.length >= 3
    ? [data.size[0] | 0, data.size[1] | 0, data.size[2] | 0]
    : inferSize(voxelsIn);
  const camera = {
    azim: data.camera && data.camera.azim != null ? Number(data.camera.azim) : 35,
    elev: data.camera && data.camera.elev != null ? Number(data.camera.elev) : 20,
  };
  const palette = normalizePalette(data.palette);
  const name = data.name || "untitled";

  let voxels;
  if (shapesIn.length) {
    voxels = rasterize({ ...data, size }, palette);
  } else {
    voxels = [];
    for (const v of voxelsIn) {
      const x = v.x | 0, y = v.y | 0, z = v.z | 0;
      if (x < 0 || y < 0 || z < 0 || x >= size[0] || y >= size[1] || z >= size[2]) continue;
      if (AIR.has(v.c)) continue;
      const color = resolveColor(palette, v.c, x, y, z);
      if (!color) continue;
      const shape = v.s && typeof v.s === "object" ? v.s : null;
      voxels.push({ x, y, z, color, shape });
    }
  }

  let subCount = 0;
  for (const v of voxels) {
    if (v.shape && v.shape.type && v.shape.type !== "full") subCount++;
  }
  const stats = {
    name,
    size,
    blockCount: voxels.length,
    subCount,
    subPct: voxels.length ? (100 * subCount) / voxels.length : 0,
  };
  return { name, size, camera, voxels, stats, dropped };
}

export async function loadVoxelUrl(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load ${url} (${res.status})`);
  const data = await res.json();
  return parseVoxelArt(data);
}
