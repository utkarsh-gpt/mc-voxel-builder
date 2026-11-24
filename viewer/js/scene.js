/**
 * three.js voxel scene: instanced boxes at true sub-block sizes,
 * orbit/zoom/pan, soft lighting, cheap neighbour AO.
 *
 * Sub-block semantics (subblock.py, F=4, +x east, +z south = front):
 *   full | slab {size: 0.5|0.25, align: bottom|top}
 *   vslab {size: 0.5|0.25, axis: x|z, align: west|east|north|south}
 *   stairs {facing: north|south|east|west, half: bottom|top}
 * Stairs 'facing' is the side of the tall step.
 *
 * mc_blocks models are one merged, atlas-textured mesh instead (buildMcMesh).
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/**
 * A shape occupies the unit cube [0,1]^3 at the voxel origin.
 * Returns one or two axis-aligned boxes {sx,sy,sz, ox,oy,oz} (size + centre).
 */
export function shapeToBoxes(s) {
  // box from min/max corners (block units)
  const bx = (x0, y0, z0, x1, y1, z1) => ({ sx: x1 - x0, sy: y1 - y0, sz: z1 - z0, ox: (x0 + x1) / 2, oy: (y0 + y1) / 2, oz: (z0 + z1) / 2 });
  if (!s || !s.type || s.type === "full") return [bx(0, 0, 0, 1, 1, 1)];
  const size = typeof s.size === "number" && s.size > 0 && s.size < 1 ? s.size : 0.5;   // 0.5, 0.25, or 3/16 (trapdoor)
  if (s.type === "slab") return [s.align === "top" ? bx(0, 1 - size, 0, 1, 1, 1) : bx(0, 0, 0, 1, size, 1)];
  if (s.type === "vslab") {
    const k = size;
    return [{ west: bx(0, 0, 0, k, 1, 1), east: bx(1 - k, 0, 0, 1, 1, 1), north: bx(0, 0, 0, 1, 1, k), south: bx(0, 0, 1 - k, 1, 1, 1) }[s.align] || bx(0, 0, 0, k, 1, 1)];
  }
  if (s.type === "stairs") {
    // Minecraft stairs: half-block base + step on the 'facing' side; outer = quarter step at facing+left/right,
    // inner = facing half + the left/right quarter at the back. left = counter-clockwise of facing (seen from above).
    const top = s.half === "top", f = s.facing || "east", sh = s.shape || "straight";
    const cw = { north: "east", east: "south", south: "west", west: "north" }, ccw = { east: "north", south: "east", west: "south", north: "west" };
    const opp = { north: "south", south: "north", east: "west", west: "east" };
    const half = { north: [0, 0, 1, 0.5], south: [0, 0.5, 1, 1], west: [0, 0, 0.5, 1], east: [0.5, 0, 1, 1] };   // x0,z0,x1,z1
    const isect = (p, q) => [Math.max(p[0], q[0]), Math.max(p[1], q[1]), Math.min(p[2], q[2]), Math.min(p[3], q[3])];
    const y0 = top ? 0 : 0.5, y1 = top ? 0.5 : 1;
    const out = [top ? bx(0, 0.5, 0, 1, 1, 1) : bx(0, 0, 0, 1, 0.5, 1)];
    const side = sh.endsWith("left") ? ccw[f] : cw[f];
    let steps = [half[f]];
    if (sh.startsWith("outer")) steps = [isect(half[f], half[side])];
    else if (sh.startsWith("inner")) steps = [half[f], isect(half[side], half[opp[f]])];
    for (const r of steps) out.push(bx(r[0], y0, r[1], r[2], y1, r[3]));
    return out;
  }
  if (s.type === "wall" || s.type === "fence") {
    // vanilla geometry: wall post 4..12/16, arms 5..11 wide x 14 (16 = tall); fence post 6..10, bars 7..9 at y 6..9 and 12..15
    const p = 1 / 16, wall = s.type === "wall";
    const post = wall ? [4 * p, 12 * p] : [6 * p, 10 * p], arm = wall ? [5 * p, 11 * p] : [7 * p, 9 * p];
    const out = [];
    if (!wall || s.up !== false) out.push(bx(post[0], 0, post[0], post[1], 1, post[1]));
    for (const d of ["north", "east", "south", "west"]) {
      const v = s[d];
      if (!v || v === "none" || v === "false") continue;
      const ys = wall ? [[0, v === "tall" ? 1 : 14 * p]] : [[6 * p, 9 * p], [12 * p, 15 * p]];
      for (const [ya, yb] of ys) {
        if (d === "east") out.push(bx(post[1], ya, arm[0], 1, yb, arm[1]));
        else if (d === "west") out.push(bx(0, ya, arm[0], post[0], yb, arm[1]));
        else if (d === "south") out.push(bx(arm[0], ya, post[1], arm[1], yb, 1));
        else out.push(bx(arm[0], ya, 0, arm[1], yb, post[0]));
      }
    }
    return out.length ? out : [bx(post[0], 0, post[0], post[1], 1, post[1])];
  }
  return [bx(0, 0, 0, 1, 1, 1)];
}

function neighbourAo(voxels) {
  const occ = new Set();
  for (const v of voxels) occ.add(`${v.x},${v.y},${v.z}`);
  const dirs = [
    [1, 0, 0], [-1, 0, 0],
    [0, 1, 0], [0, -1, 0],
    [0, 0, 1], [0, 0, -1],
  ];
  const ao = new Array(voxels.length);
  for (let i = 0; i < voxels.length; i++) {
    const v = voxels[i];
    let n = 0;
    for (const [dx, dy, dz] of dirs) {
      if (occ.has(`${v.x + dx},${v.y + dy},${v.z + dz}`)) n++;
    }
    // 6-neighbour occupancy → subtle corner darkening
    ao[i] = 1 - 0.085 * n;
  }
  return ao;
}

/* ---------- Minecraft block models ---------- */

// Each face: neighbour offset, bake grid, and its corners as (a = left→right,
// b = bottom→top seen from outside) → position, plus the Minecraft-style UV
// window inside the 0..1 texture (u left→right, row 0 = texture top).
const MC_FACES = [
  { n: [0, 0, 1], tex: "side", onEdge: (b) => b[5] >= 1,
    pos: (b, a, t) => [a ? b[3] : b[0], t ? b[4] : b[1], b[5]],
    uv: (b) => [b[0], b[3], 1 - b[1], 1 - b[4]] },
  { n: [0, 0, -1], tex: "side", onEdge: (b) => b[2] <= 0,
    pos: (b, a, t) => [a ? b[0] : b[3], t ? b[4] : b[1], b[2]],
    uv: (b) => [1 - b[3], 1 - b[0], 1 - b[1], 1 - b[4]] },
  { n: [1, 0, 0], tex: "side", onEdge: (b) => b[3] >= 1,
    pos: (b, a, t) => [b[3], t ? b[4] : b[1], a ? b[2] : b[5]],
    uv: (b) => [1 - b[5], 1 - b[2], 1 - b[1], 1 - b[4]] },
  { n: [-1, 0, 0], tex: "side", onEdge: (b) => b[0] <= 0,
    pos: (b, a, t) => [b[0], t ? b[4] : b[1], a ? b[5] : b[2]],
    uv: (b) => [b[2], b[5], 1 - b[1], 1 - b[4]] },
  { n: [0, 1, 0], tex: "top", onEdge: (b) => b[4] >= 1,
    pos: (b, a, t) => [a ? b[3] : b[0], b[4], t ? b[2] : b[5]],
    uv: (b) => [b[0], b[3], b[5], b[2]] },
  { n: [0, -1, 0], tex: "bottom", onEdge: (b) => b[1] <= 0,
    pos: (b, a, t) => [a ? b[3] : b[0], b[1], t ? b[5] : b[2]],
    uv: (b) => [b[0], b[3], 1 - b[2], 1 - b[5]] },
];

/**
 * Pack every distinct bake grid into one RGBA atlas. Tiles get a 1px gutter
 * that repeats their edge so nearest sampling never bleeds into a neighbour.
 */
function buildAtlas(palette, res) {
  const tiles = [];
  const seen = new Map();
  const tileOf = {};
  for (const e of Object.values(palette)) {
    if (!e.count) continue;
    tileOf[e.key] = {};
    for (const f of ["top", "side", "bottom"]) {
      const grid = e.bake[f];
      const sig = grid.map((c) => (c ? c.join(",") : "-")).join("|");
      if (!seen.has(sig)) {
        seen.set(sig, tiles.length);
        tiles.push(grid);
      }
      tileOf[e.key][f] = seen.get(sig);
    }
  }
  const cell = res + 2;
  const cols = Math.max(1, Math.ceil(Math.sqrt(tiles.length)));
  const rows = Math.max(1, Math.ceil(tiles.length / cols));
  const W = cols * cell, H = rows * cell;
  const data = new Uint8Array(W * H * 4);
  tiles.forEach((grid, t) => {
    const ox = (t % cols) * cell, oy = Math.floor(t / cols) * cell;
    for (let py = 0; py < cell; py++) {
      const r = Math.min(res - 1, Math.max(0, py - 1));
      for (let px = 0; px < cell; px++) {
        const c = Math.min(res - 1, Math.max(0, px - 1));
        const rgba = grid[r * res + c];
        if (!rgba) continue;
        data.set(rgba, ((oy + py) * W + ox + px) * 4);
      }
    }
  });
  // Atlas pixel (tile t, texel u/row in 0..1) → texture coords. DataTexture
  // rows run bottom-up in v, so storing image row y at v = y / H keeps it simple.
  const uvAt = (t, u, row) => [
    ((t % cols) * cell + 1 + u * res) / W,
    (Math.floor(t / cols) * cell + 1 + row * res) / H,
  ];
  return { data, W, H, tileOf, uvAt };
}

export function buildMcMesh(parsed) {
  const { blocks, palette, size, bakeRes } = parsed;
  const [W, H, D] = size;
  const ox = W / 2, oz = D / 2;
  const atlas = buildAtlas(palette, bakeRes);

  const at = new Map();
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    at.set(b.x + "," + b.y + "," + b.z, palette[b.key]);
  }
  const ao = neighbourAo(blocks);
  const shadeColor = new THREE.Color();

  const pos = [], nrm = [], uvs = [], col = [], idxs = [];
  const quadBlock = [];
  let minY = Infinity;
  for (let i = 0; i < blocks.length; i++) {
    const blk = blocks[i];
    const e = palette[blk.key];
    // Match the instanced renderer: shade is applied in sRGB, so convert.
    shadeColor.setRGB(ao[i], ao[i], ao[i], THREE.SRGBColorSpace);
    const s = shadeColor.r;
    for (const box of e.boxes) {
      if (blk.y + box[1] < minY) minY = blk.y + box[1];
      for (const f of MC_FACES) {
        if (f.onEdge(box)) {
          const nb = at.get((blk.x + f.n[0]) + "," + (blk.y + f.n[1]) + "," + (blk.z + f.n[2]));
          if (nb && nb.fullOpaque) continue;
        }
        const [uL, uR, rB, rT] = f.uv(box);
        const tile = atlas.tileOf[blk.key][f.tex];
        const base = pos.length / 3;
        for (const [a, t] of [[0, 0], [1, 0], [1, 1], [0, 1]]) {
          const p = f.pos(box, a, t);
          pos.push(blk.x + p[0] - ox, blk.y + p[1], blk.z + p[2] - oz);
          nrm.push(f.n[0], f.n[1], f.n[2]);
          uvs.push(...atlas.uvAt(tile, a ? uR : uL, t ? rT : rB));
          col.push(s, s, s);
        }
        idxs.push(base, base + 1, base + 2, base, base + 2, base + 3);
        quadBlock.push(i);
      }
    }
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute("normal", new THREE.Float32BufferAttribute(nrm, 3));
  geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geo.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  geo.setIndex(pos.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(idxs, 1) : new THREE.Uint16BufferAttribute(idxs, 1));
  geo.computeBoundingSphere();
  geo.computeBoundingBox();

  const tex = new THREE.DataTexture(atlas.data, atlas.W, atlas.H, THREE.RGBAFormat);
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;

  const mat = new THREE.MeshStandardMaterial({
    roughness: 0.86,
    metalness: 0.04,
    flatShading: true,
    map: tex,
    vertexColors: true,
    alphaTest: 0.5,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.userData.mc = { quadBlock: Uint32Array.from(quadBlock), atlas };
  return { mesh, minY };
}

function cameraPosition(azim, elev, dist) {
  const a = (azim * Math.PI) / 180;
  const e = (elev * Math.PI) / 180;
  const ce = Math.cos(e);
  return new THREE.Vector3(
    -Math.sin(a) * ce * dist,
    Math.sin(e) * dist,
    Math.cos(a) * ce * dist
  );
}

export function createViewer(canvas) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x12141a, 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x12141a, 80, 220);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
  camera.position.set(40, 28, 40);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = true;
  controls.zoomToCursor = true;
  controls.minDistance = 2;
  controls.maxDistance = 400;
  controls.target.set(0, 0, 0);

  const hemi = new THREE.HemisphereLight(0xd8e2f0, 0x3a3228, 0.72);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xfff3e0, 1.05);
  key.position.set(-0.45, 0.85, 0.5);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xb8c8e0, 0.28);
  fill.position.set(0.7, 0.25, -0.4);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0xc9d4e8, 0.18);
  rim.position.set(0.2, 0.5, -0.85);
  scene.add(rim);

  const grid = new THREE.GridHelper(64, 64, 0x3a4150, 0x222830);
  grid.material.transparent = true;
  grid.material.opacity = 0.55;
  grid.visible = true;
  scene.add(grid);

  const ground = new THREE.Mesh(
    new THREE.CircleGeometry(80, 64),
    new THREE.MeshBasicMaterial({ color: 0x0c0e12, transparent: true, opacity: 0.35 })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.01;
  scene.add(ground);

  const boxGeo = new THREE.BoxGeometry(1, 1, 1);
  boxGeo.translate(0, 0, 0);
  const material = new THREE.MeshStandardMaterial({
    roughness: 0.86,
    metalness: 0.04,
    vertexColors: false,
    flatShading: true,
  });
  // instanceColor is applied automatically by InstancedMesh when setColorAt is used

  let instanced = null;
  let mcMesh = null; // merged mesh for mc_blocks models (pickable)
  let mcParsed = null;
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const highlight = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
    new THREE.LineBasicMaterial({ color: 0xd6a54e, depthTest: false, transparent: true, opacity: 0.9 })
  );
  highlight.renderOrder = 10;
  highlight.visible = false;
  scene.add(highlight);
  let modelRoot = new THREE.Group();
  scene.add(modelRoot);
  let currentStats = null;
  let currentCamera = { azim: 35, elev: 20 };
  let wireframe = false;
  let raf = 0;

  function resize() {
    const parent = canvas.parentElement || canvas;
    const w = Math.max(1, parent.clientWidth || window.innerWidth);
    const h = Math.max(1, parent.clientHeight || window.innerHeight);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function clearModel() {
    if (instanced) {
      modelRoot.remove(instanced);
      instanced.geometry = boxGeo; // shared, don't dispose
      instanced.material.dispose?.();
      instanced.dispose?.();
      instanced = null;
    }
    mcMesh = null;
    mcParsed = null;
    highlight.visible = false;
    // dispose previous unique material
    while (modelRoot.children.length) {
      const ch = modelRoot.children[0];
      modelRoot.remove(ch);
      if (ch !== instanced) {
        ch.geometry && ch.geometry !== boxGeo && ch.geometry.dispose?.();
        if (Array.isArray(ch.material)) ch.material.forEach((m) => m.dispose?.());
        else if (ch.material && ch.material !== material) {
          ch.material.map?.dispose?.();
          ch.material.dispose?.();
        }
      }
    }
  }

  function fitCamera(azim, elev) {
    const box = new THREE.Box3().setFromObject(modelRoot);
    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    if (!isFinite(box.min.x)) {
      center.set(0, 0, 0);
      size.set(8, 8, 8);
    } else {
      box.getCenter(center);
      box.getSize(size);
    }
    const maxDim = Math.max(size.x, size.y, size.z, 1);
    const fov = (camera.fov * Math.PI) / 180;
    const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.45 + maxDim * 0.2;
    controls.target.copy(center);
    const pos = cameraPosition(azim, elev, dist);
    camera.position.copy(center).add(pos);
    camera.near = Math.max(0.05, dist / 200);
    camera.far = Math.max(1000, dist * 20);
    camera.updateProjectionMatrix();
    controls.minDistance = Math.max(1, maxDim * 0.2);
    controls.maxDistance = Math.max(40, maxDim * 20);
    // scale grid to the model
    const g = Math.max(16, Math.ceil(maxDim * 2.2 / 8) * 8);
    grid.scale.set(1, 1, 1);
    grid.position.set(center.x, box.isEmpty() ? 0 : box.min.y, center.z);
    ground.position.set(center.x, (box.isEmpty() ? 0 : box.min.y) - 0.02, center.z);
    const gs = Math.max(20, maxDim * 2.5);
    ground.scale.set(gs / 80, gs / 80, gs / 80);
    // rebuild grid helper size by scaling a unit? GridHelper is already 64 wide; scale it
    grid.scale.set(gs / 64, 1, gs / 64);
    controls.update();
  }

  function loadParsed(parsed) {
    clearModel();
    const { voxels, size, camera: cam, stats } = parsed;
    currentStats = stats;
    currentCamera = cam || { azim: 35, elev: 20 };

    if (parsed.format === "mc_blocks") {
      const { mesh, minY } = buildMcMesh(parsed);
      mesh.material.wireframe = wireframe;
      mcMesh = mesh;
      mcParsed = parsed;
      modelRoot.add(mesh);
      modelRoot.position.y = isFinite(minY) ? -minY : 0;
      fitCamera(currentCamera.azim, currentCamera.elev);
      return stats;
    }

    const [W, H, D] = size;
    // centre the model on XZ, sit on y=0
    const ox = W / 2;
    const oz = D / 2;

    const ao = neighbourAo(voxels);
    let instanceCount = 0;
    const boxesPer = new Array(voxels.length);
    for (let i = 0; i < voxels.length; i++) {
      const boxes = shapeToBoxes(voxels[i].shape);
      boxesPer[i] = boxes;
      instanceCount += boxes.length;
    }

    const mat = material.clone();
    mat.wireframe = wireframe;
    instanced = new THREE.InstancedMesh(boxGeo, mat, Math.max(instanceCount, 1));
    instanced.instanceMatrix.setUsage(THREE.StaticDrawUsage);
    instanced.castShadow = false;
    instanced.receiveShadow = false;
    instanced.frustumCulled = false;

    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    let k = 0;
    let minY = Infinity;
    for (let i = 0; i < voxels.length; i++) {
      const v = voxels[i];
      const shade = ao[i];
      color.setRGB(
        (v.color[0] / 255) * shade,
        (v.color[1] / 255) * shade,
        (v.color[2] / 255) * shade,
        THREE.SRGBColorSpace
      );
      for (const b of boxesPer[i]) {
        dummy.position.set(v.x + b.ox - ox, v.y + b.oy, v.z + b.oz - oz);
        dummy.scale.set(b.sx, b.sy, b.sz);
        dummy.rotation.set(0, 0, 0);
        dummy.updateMatrix();
        instanced.setMatrixAt(k, dummy.matrix);
        instanced.setColorAt(k, color);
        if (v.y + b.oy - b.sy / 2 < minY) minY = v.y + b.oy - b.sy / 2;
        k++;
      }
    }
    instanced.instanceMatrix.needsUpdate = true;
    if (instanced.instanceColor) instanced.instanceColor.needsUpdate = true;
    instanced.count = k;
    modelRoot.add(instanced);

    // drop the model so the lowest box sits on y=0
    if (isFinite(minY)) {
      modelRoot.position.y = -minY;
    } else {
      modelRoot.position.y = 0;
    }

    fitCamera(currentCamera.azim, currentCamera.elev);
    return stats;
  }

  function setWireframe(on) {
    wireframe = !!on;
    if (instanced && instanced.material) instanced.material.wireframe = wireframe;
    if (mcMesh) mcMesh.material.wireframe = wireframe;
  }

  /**
   * mc_blocks only: the block under a viewport point, skipping cut-out
   * (transparent) texels. Returns {x, y, z, key, entry} or null.
   */
  function pickBlock(clientX, clientY) {
    if (!mcMesh) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const { quadBlock, atlas } = mcMesh.userData.mc;
    for (const hit of raycaster.intersectObject(mcMesh, false)) {
      if (hit.uv && !wireframe) {
        const px = Math.min(atlas.W - 1, Math.floor(hit.uv.x * atlas.W));
        const py = Math.min(atlas.H - 1, Math.floor(hit.uv.y * atlas.H));
        if (atlas.data[(py * atlas.W + px) * 4 + 3] < 128) continue;
      }
      const blk = mcParsed.blocks[quadBlock[Math.floor(hit.faceIndex / 2)]];
      return { x: blk.x, y: blk.y, z: blk.z, key: blk.key, entry: mcParsed.palette[blk.key] };
    }
    return null;
  }

  /** Outline one block (its boxes' bounds), or hide the outline with null. */
  function setHighlight(block) {
    if (!block || !mcParsed) {
      highlight.visible = false;
      return;
    }
    const lo = [1, 1, 1], hi = [0, 0, 0];
    for (const b of block.entry.boxes) {
      for (let k = 0; k < 3; k++) {
        lo[k] = Math.min(lo[k], b[k]);
        hi[k] = Math.max(hi[k], b[k + 3]);
      }
    }
    const [W, , D] = mcParsed.size;
    const pad = 0.02;
    highlight.scale.set(hi[0] - lo[0] + pad, hi[1] - lo[1] + pad, hi[2] - lo[2] + pad);
    highlight.position.set(
      block.x + (lo[0] + hi[0]) / 2 - W / 2,
      block.y + (lo[1] + hi[1]) / 2 + modelRoot.position.y,
      block.z + (lo[2] + hi[2]) / 2 - D / 2
    );
    highlight.visible = true;
  }

  function setGrid(on) {
    grid.visible = !!on;
    ground.visible = !!on;
  }

  function resetCamera() {
    fitCamera(currentCamera.azim, currentCamera.elev);
  }

  function setBackground(hex) {
    const c = new THREE.Color(hex);
    renderer.setClearColor(c, 1);
    scene.fog.color.copy(c);
  }

  function frame() {
    raf = requestAnimationFrame(frame);
    controls.update();
    renderer.render(scene, camera);
  }

  const ro = new ResizeObserver(() => resize());
  ro.observe(canvas.parentElement || canvas);
  resize();
  frame();

  function dispose() {
    cancelAnimationFrame(raf);
    ro.disconnect();
    clearModel();
    controls.dispose();
    renderer.dispose();
    boxGeo.dispose();
    material.dispose();
    highlight.geometry.dispose();
    highlight.material.dispose();
  }

  return {
    loadParsed,
    pickBlock,
    setHighlight,
    setWireframe,
    setGrid,
    resetCamera,
    setBackground,
    dispose,
    resize,
    getStats: () => currentStats,
    renderer,
    scene,
    camera,
    controls,
  };
}
