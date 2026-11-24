/**
 * Voxel viewer UI glue. Hooks (keep these IDs/attrs if you restyle):
 *   #viewport, #view (canvas), #model-select, #ref-thumb, #ref-wrap,
 *   #stat-blocks, #stat-sub, #stat-size, #stat-name,
 *   #toggle-wireframe, #toggle-grid, #btn-reset, #status, #drop-overlay,
 *   #palette-section, #palette-list, #block-info, #block-tip (mc_blocks models)
 *   body[data-state=loading|ready|error|idle]
 */
import { parseVoxelArt, loadVoxelUrl } from "./loader.js";
import { createViewer } from "./scene.js";

const $ = (id) => document.getElementById(id);

const STAGE_COLOR = 0x191814; // matches --stage in styles.css

const canvas = $("view");
const viewer = createViewer(canvas);
viewer.setBackground?.(STAGE_COLOR);

let manifest = { models: [], default_id: null };
let currentId = null;
let loadToken = 0; // ignore results from loads that were superseded
let retryAction = null;

/* ---------- small helpers ---------- */

function formatBytes(n) {
  if (!n && n !== 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k in node) node[k] = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

function setText(id, text) {
  const node = $(id);
  if (node) node.textContent = text;
}

/* ---------- state ---------- */

function setState(state, message) {
  document.body.dataset.state = state;
  document.body.dataset.ready = state === "ready" ? "1" : "0";
  document.body.classList.remove("error-dismissed");
  const status = $("status");
  if (status) {
    status.textContent = message || "";
    status.hidden = !message;
  }
  if (state === "loading") setText("veil-title", message || "Loading…");
  if (state === "error") {
    setText("veil-error-msg", message || "Something went wrong.");
    const retry = $("btn-retry");
    if (retry) retry.hidden = !retryAction;
  }
}

function fail(err) {
  console.error(err);
  setState("error", err?.message || String(err));
}

function modelById(id) {
  return manifest.models.find((m) => m.id === id);
}

/* ---------- presentation ---------- */

function fillStats(stats, meta) {
  // While loading, preview the catalogue numbers so the panel doesn't go blank.
  const blocks = stats ? stats.blockCount : meta?.voxelCount;
  const subCount = stats ? stats.subCount : meta?.subCount;
  const subPct = stats ? stats.subPct : meta?.subPct;
  const size = stats?.size || meta?.size;

  setText("stat-name", stats?.name || meta?.name || "—");
  setText("stat-blocks", blocks != null ? blocks.toLocaleString() : "—");
  setText("stat-size", size ? size.join(" × ") : "—");

  if (subPct == null) {
    setText("stat-sub", "—");
    setText("stat-sub-count", "");
  } else {
    setText("stat-sub", `${Number(subPct).toFixed(1)}%`);
    const isMc = (stats?.format || meta?.format) === "mc_blocks";
    setText(
      "stat-sub-count",
      subCount
        ? `${subCount.toLocaleString()} of ${blocks.toLocaleString()} blocks are ${
            isMc ? "partial (slabs, stairs, trapdoors…)" : "slabs or stairs"
          }`
        : "All full blocks"
    );
  }
  const meter = $("sub-meter");
  if (meter) meter.style.width = `${Math.min(100, Math.max(0, Number(subPct) || 0))}%`;
}

function setPlate({ eyebrow, title, badges = [] }) {
  setText("plate-subject", eyebrow || "—");
  setText("plate-title", title || "—");
  const box = $("plate-badges");
  if (!box) return;
  box.replaceChildren(
    ...badges.map((b) => el("span", { class: `badge ${b.cls || ""}`, text: b.text }))
  );
}

function plateForMeta(meta, subPct) {
  const badges = [];
  if (meta.featured) badges.push({ text: "Featured", cls: "badge-featured" });
  else if (meta.highlight) badges.push({ text: "Highlight", cls: "badge-featured" });
  if (subPct) badges.push({ text: `${Number(subPct).toFixed(1)}% sub-blocks`, cls: "badge-sub" });
  if (meta.kind) badges.push({ text: meta.kind.replace(/_/g, " ") });
  setPlate({ eyebrow: meta.subject, title: meta.name || meta.id, badges });
}

function setRef(meta) {
  const img = $("ref-thumb");
  const wrap = $("ref-wrap");
  if (!img) return;
  if (meta && meta.ref) {
    img.src = meta.ref;
    img.alt = `Reference photo for ${meta.subject || meta.name}`;
    img.hidden = false;
    if (wrap) wrap.hidden = false;
    const link = $("ref-link");
    if (link) link.href = meta.ref;
    setText("ref-caption", meta.subject || meta.ref.split("/").pop());
    const cap = $("ref-credit");
    if (cap) {
      const c = meta.refCredit;
      cap.hidden = !c;
      cap.textContent = "";
      if (c) {
        const a = document.createElement("a");
        a.href = c.url; a.target = "_blank"; a.rel = "noopener"; a.textContent = c.text;
        cap.append(a);
        if (c.license_url) {
          const l = document.createElement("a");
          l.href = c.license_url; l.target = "_blank"; l.rel = "noopener license"; l.textContent = " (licence)";
          cap.append(l);
        }
      }
    }
  } else {
    img.removeAttribute("src");
    img.hidden = true;
    if ($("ref-credit")) $("ref-credit").hidden = true;
    if (wrap) wrap.hidden = true;
  }
}

/* ---------- Minecraft block palette + inspector ---------- */

let mcPalette = null; // palette of the loaded mc_blocks model, else null
let pinnedBlock = null; // block clicked in the view, shown in #block-info

// 4x4 bake → tiny pixelated data URL for a legend swatch.
function bakeSwatch(grid, res) {
  const c = document.createElement("canvas");
  c.width = c.height = res;
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(res, res);
  grid.forEach((rgba, i) => rgba && img.data.set(rgba, i * 4));
  ctx.putImageData(img, 0, 0);
  return c.toDataURL();
}

function blockMetaParts(entry) {
  const parts = [];
  if (entry.material) parts.push(["material", entry.material]);
  if (entry.technique) parts.push(["technique", entry.technique]);
  return parts;
}

function showPalette(parsed) {
  const section = $("palette-section");
  pinnedBlock = null;
  viewer.setHighlight?.(null);
  hideTip();
  if (parsed?.format !== "mc_blocks") {
    mcPalette = null;
    if (section) section.hidden = true;
    return;
  }
  mcPalette = parsed.palette;
  const entries = Object.values(parsed.palette)
    .filter((e) => e.count)
    .sort((a, b) => b.count - a.count || a.id.localeCompare(b.id));
  setText("palette-note", `${entries.length} block types`);
  renderBlockInfo(null);
  $("palette-list")?.replaceChildren(
    ...entries.map((e) => {
      const sw = el("span", { class: "swatch", "aria-hidden": "true" });
      sw.style.backgroundImage = `url(${bakeSwatch(e.bake.side, parsed.bakeRes)})`;
      const li = el("li", { title: e.state }, [
        sw,
        el("span", { class: "palette-id", text: e.id }),
        el("span", { class: "palette-count", text: e.count.toLocaleString() }),
      ]);
      li.dataset.key = e.key;
      return li;
    })
  );
  if (section) section.hidden = false;
}

function renderBlockInfo(block) {
  const box = $("block-info");
  if (!box) return;
  for (const li of document.querySelectorAll("#palette-list li")) {
    li.classList.toggle("is-current", !!block && li.dataset.key === block.key);
  }
  if (!block) {
    box.replaceChildren(el("p", { class: "block-info-hint", text: "Hover a block to read it, click to pin it here." }));
    return;
  }
  const meta = el("p", { class: "block-meta" }, [`at ${block.x}, ${block.y}, ${block.z}`]);
  for (const [k, v] of blockMetaParts(block.entry)) meta.append(` · ${k} `, el("b", { text: v }));
  box.replaceChildren(el("p", { class: "block-state", text: block.entry.state }), meta);
}

function showTip(block, clientX, clientY) {
  const tip = $("block-tip");
  const host = $("viewport");
  if (!tip || !host) return;
  const meta = el("span", { class: "block-meta" }, [`${block.x}, ${block.y}, ${block.z}`]);
  for (const [k, v] of blockMetaParts(block.entry)) meta.append(` · ${k}: ${v}`);
  tip.replaceChildren(block.entry.state, meta);
  tip.hidden = false;
  const r = host.getBoundingClientRect();
  const x = Math.min(clientX - r.left + 14, r.width - tip.offsetWidth - 8);
  const y = Math.min(clientY - r.top + 16, r.height - tip.offsetHeight - 8);
  tip.style.transform = `translate(${Math.max(8, x)}px, ${Math.max(8, y)}px)`;
}

function hideTip() {
  const tip = $("block-tip");
  if (tip) tip.hidden = true;
}

function bindBlockInspector() {
  let pending = null;
  let down = null;
  const pick = (e) => (mcPalette && viewer.pickBlock ? viewer.pickBlock(e.clientX, e.clientY) : null);

  canvas.addEventListener("pointermove", (e) => {
    if (!mcPalette || e.pointerType === "touch") return;
    if (e.buttons) {
      // orbiting / panning: keep the view clean
      hideTip();
      return;
    }
    pending = e;
    requestAnimationFrame(() => {
      if (!pending) return;
      const ev = pending;
      pending = null;
      const block = pick(ev);
      if (block) {
        viewer.setHighlight(block);
        showTip(block, ev.clientX, ev.clientY);
      } else {
        hideTip();
        viewer.setHighlight(pinnedBlock);
      }
    });
  });
  canvas.addEventListener("pointerleave", () => {
    pending = null;
    hideTip();
    viewer.setHighlight?.(pinnedBlock);
  });
  canvas.addEventListener("pointerdown", (e) => {
    down = { x: e.clientX, y: e.clientY };
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!mcPalette || !down) return;
    const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
    down = null;
    if (moved > 4) return; // a drag, not a click
    const block = pick(e);
    pinnedBlock = block; // re-outlined when the pointer leaves other blocks
    viewer.setHighlight(block);
    renderBlockInfo(block);
  });
}

function markCurrent(id) {
  for (const chip of document.querySelectorAll("#featured .chip")) {
    chip.setAttribute("aria-pressed", chip.dataset.id === id ? "true" : "false");
  }
}

function statusExtra(stats) {
  if (stats.format === "mc_blocks") return ` · ${stats.paletteSize} block types`;
  return stats.subCount ? ` · ${stats.subPct.toFixed(1)}% sub-blocks` : "";
}

/* ---------- loading ---------- */

async function loadModel(id, { fromDrop } = {}) {
  const meta = modelById(id);
  if (!meta && !fromDrop) throw new Error(`Unknown model ${id}`);
  const token = ++loadToken;
  currentId = id;
  retryAction = () => loadModel(id);
  if ($("model-select") && !fromDrop) $("model-select").value = id;
  markCurrent(id);
  setText("veil-sub", meta?.bytes ? `${formatBytes(meta.bytes)} of voxel data` : "");
  setState("loading", `Loading ${meta?.name || id}…`);
  fillStats(null, meta);
  plateForMeta(meta, meta.subPct);
  setRef(meta);
  let parsed;
  try {
    parsed = await loadVoxelUrl(meta.file);
  } catch (err) {
    if (token !== loadToken) return null; // a newer load owns the screen
    throw err;
  }
  if (token !== loadToken) return null;
  const stats = viewer.loadParsed(parsed);
  showPalette(parsed);
  fillStats(stats, meta);
  plateForMeta(meta, stats.subPct);
  setState("ready", `${stats.blockCount.toLocaleString()} blocks${statusExtra(stats)}`);
  return stats;
}

async function loadDroppedFile(file) {
  const token = ++loadToken;
  retryAction = null;
  setText("veil-sub", file.size ? formatBytes(file.size) : "");
  setState("loading", `Reading ${file.name}…`);
  const text = await file.text();
  if (token !== loadToken) return;
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("That file is not valid JSON");
  }
  const parsed = parseVoxelArt(data, { dropped: true });
  const stats = viewer.loadParsed(parsed);
  showPalette(parsed);
  currentId = null;
  if ($("model-select")) $("model-select").value = "";
  markCurrent(null);
  fillStats(stats, { name: parsed.name || file.name, ref: null });
  setRef(null);
  setPlate({
    eyebrow: "Local file",
    title: parsed.name && parsed.name !== "untitled" ? parsed.name : file.name,
    badges: [
      ...(stats.subCount ? [{ text: `${stats.subPct.toFixed(1)}% sub-blocks`, cls: "badge-sub" }] : []),
      { text: file.name },
    ],
  });
  setState("ready", `Dropped ${file.name}: ${stats.blockCount.toLocaleString()} blocks${statusExtra(stats)}`);
}

/* ---------- catalogue UI ---------- */

function populateSelect(models, defaultId) {
  const sel = $("model-select");
  if (!sel) return;
  sel.innerHTML = "";
  const SUBJECT_ORDER = ["windmill", "cottage", "bonsai"];
  const capitalise = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  // Pass/variant name with the subject prefix stripped (e.g. "voxels_textured");
  // Minecraft block builds read as "mc blocks".
  const variantLabel = (m) => {
    const pre = `${m.subject}_`;
    let label = m.id === m.subject ? "base" : m.id.startsWith(pre) ? m.id.slice(pre.length) : m.id;
    if (m.format === "mc_blocks") label = label.replace(/_/g, " ");
    return label;
  };

  const addGroup = (label, items) => {
    if (!items.length) return;
    const og = document.createElement("optgroup");
    og.label = label;
    for (const m of items) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.title = m.id;
      const mark = m.featured ? "★ " : m.highlight ? "◆ " : "";
      const sub = m.format === "mc_blocks" && m.paletteSize
        ? ` · ${m.paletteSize} types`
        : m.subPct ? ` · ${m.subPct}% sub` : "";
      opt.textContent = `${mark}${variantLabel(m)}${sub}`;
      opt.dataset.featured = m.featured ? "1" : "0";
      opt.dataset.highlight = m.highlight ? "1" : "0";
      opt.dataset.subject = m.subject;
      if (m.id === defaultId) opt.selected = true;
      og.appendChild(opt);
    }
    sel.appendChild(og);
  };

  const bySubj = new Map();
  for (const m of models) {
    if (!bySubj.has(m.subject)) bySubj.set(m.subject, []);
    bySubj.get(m.subject).push(m);
  }
  const rank = (s) => {
    const i = SUBJECT_ORDER.indexOf(s);
    return i === -1 ? SUBJECT_ORDER.length : i;
  };
  const subjects = [...bySubj.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const tier = (m) => (m.featured ? 0 : m.highlight ? 1 : 2);
  for (const subj of subjects) {
    const items = bySubj.get(subj);
    items.sort((a, b) => tier(a) - tier(b) || variantLabel(a).localeCompare(variantLabel(b)));
    addGroup(capitalise(subj), items);
  }

  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = "Dropped file…";
  blank.hidden = true;
  sel.appendChild(blank);
}

function populateFeatured(models) {
  const list = $("featured");
  if (!list) return;
  const featured = models.filter((m) => m.featured);
  list.closest("section").hidden = !featured.length;
  list.replaceChildren(
    ...featured.map((m) => {
      const thumb = m.ref
        ? el("img", { src: m.ref, alt: "", loading: "lazy", decoding: "async" })
        : el("span", { class: "chip-ph", "aria-hidden": "true" });
      const meta = el("span", { class: "chip-meta" });
      if (m.format === "mc_blocks") meta.append(el("b", { text: "mc" }), ` ${(m.voxelCount || 0).toLocaleString()} blk`);
      else if (m.subPct) meta.append(el("b", { text: `${m.subPct}%` }), " sub");
      else meta.append(`${(m.voxelCount || 0).toLocaleString()} blk`);
      const btn = el(
        "button",
        {
          type: "button",
          class: "chip",
          title: m.id,
          "aria-pressed": "false",
          "aria-label": `${m.subject}: ${m.id}${
            m.format === "mc_blocks" ? ", Minecraft blocks" : m.subPct ? `, ${m.subPct}% sub-blocks` : ""
          }`,
        },
        [thumb, el("span", { class: "chip-name", text: m.subject }), meta]
      );
      btn.dataset.id = m.id;
      btn.addEventListener("click", () => {
        if (m.id === currentId && document.body.dataset.state === "ready") return;
        loadModel(m.id).catch(fail);
      });
      return el("li", {}, [btn]);
    })
  );
}

function stepModel(delta) {
  const sel = $("model-select");
  if (!sel) return;
  const opts = [...sel.options].filter((o) => o.value);
  if (!opts.length) return;
  const i = opts.findIndex((o) => o.value === currentId);
  const next = opts[(i + delta + opts.length) % opts.length];
  loadModel(next.value).catch(fail);
}

/* ---------- wiring ---------- */

function bindUi() {
  bindBlockInspector();
  $("model-select")?.addEventListener("change", async (e) => {
    const id = e.target.value;
    if (!id) return;
    try {
      await loadModel(id);
    } catch (err) {
      fail(err);
    }
  });
  $("toggle-wireframe")?.addEventListener("change", (e) => {
    viewer.setWireframe(e.target.checked);
  });
  $("toggle-grid")?.addEventListener("change", (e) => {
    viewer.setGrid(e.target.checked);
  });
  $("btn-reset")?.addEventListener("click", () => viewer.resetCamera());

  $("btn-retry")?.addEventListener("click", () => {
    if (retryAction) Promise.resolve(retryAction()).catch(fail);
  });
  $("btn-dismiss")?.addEventListener("click", () => {
    document.body.classList.add("error-dismissed");
    canvas.focus();
  });

  $("file-input")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      await loadDroppedFile(file);
    } catch (err) {
      fail(err);
    }
  });

  // Keyboard: W wireframe, G grid, R reset, [ / ] previous / next model.
  window.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest?.("input, select, textarea, [contenteditable]")) return;
    const k = e.key.toLowerCase();
    if (k === "w" || k === "g") {
      const box = $(k === "w" ? "toggle-wireframe" : "toggle-grid");
      if (!box) return;
      box.checked = !box.checked;
      box.dispatchEvent(new Event("change"));
    } else if (k === "r") {
      viewer.resetCamera();
    } else if (k === "[" || k === "]") {
      stepModel(k === "]" ? 1 : -1);
    } else if (k === "escape" && document.body.dataset.state === "error") {
      document.body.classList.add("error-dismissed");
    } else {
      return;
    }
    e.preventDefault();
  });

  if (window.matchMedia?.("(pointer: coarse)").matches) {
    const hint = $("hint");
    if (hint) hint.innerHTML =
      "<span><kbd>1 finger</kbd> orbit</span><span><kbd>Pinch</kbd> zoom</span><span><kbd>2 fingers</kbd> pan</span>";
  }

  // Drag and drop anywhere
  const overlay = $("drop-overlay");
  let dragDepth = 0;
  const hasFile = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  window.addEventListener("dragenter", (e) => {
    if (!hasFile(e)) return;
    e.preventDefault();
    dragDepth++;
    if (overlay) overlay.hidden = false;
    document.body.classList.add("dragging");
  });
  window.addEventListener("dragover", (e) => {
    if (!hasFile(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("dragleave", (e) => {
    if (!hasFile(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
      if (overlay) overlay.hidden = true;
      document.body.classList.remove("dragging");
    }
  });
  window.addEventListener("drop", async (e) => {
    e.preventDefault();
    dragDepth = 0;
    if (overlay) overlay.hidden = true;
    document.body.classList.remove("dragging");
    const file = [...(e.dataTransfer?.files || [])].find((f) =>
      f.name.toLowerCase().endsWith(".json")
    );
    if (!file) {
      retryAction = null;
      setState("error", "Drop a .json voxel model");
      return;
    }
    try {
      await loadDroppedFile(file);
    } catch (err) {
      fail(err);
    }
  });
}

async function loadCatalogue() {
  retryAction = loadCatalogue;
  setText("veil-sub", "");
  setState("loading", "Loading catalogue…");
  try {
    const res = await fetch("manifest.json");
    if (!res.ok) throw new Error("Could not load manifest.json");
    manifest = await res.json();
  } catch (err) {
    setState("error", err.message || String(err));
    return;
  }
  populateSelect(manifest.models, manifest.default_id);
  populateFeatured(manifest.models);
  const start = manifest.default_id || manifest.models[0]?.id;
  if (!start) {
    setPlate({ eyebrow: "Catalogue", title: "No models yet" });
    setState("idle", "No models in the catalogue. Drop a JSON file to view one.");
    return;
  }
  try {
    await loadModel(start);
  } catch (err) {
    fail(err);
  }
}

async function main() {
  bindUi();
  // default toggles
  if ($("toggle-grid")) $("toggle-grid").checked = true;
  if ($("toggle-wireframe")) $("toggle-wireframe").checked = false;
  viewer.setGrid($("toggle-grid")?.checked ?? true);
  viewer.setWireframe(false);

  await loadCatalogue();
}

main();
