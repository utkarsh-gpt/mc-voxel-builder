/**
 * Voxel viewer UI glue. Hooks (keep these IDs/attrs if you restyle):
 *   #viewport, #view (canvas), #model-search + #model-tree (catalogue picker),
 *   #featured (chips), #ref-thumb, #ref-wrap,
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
  markCurrent(id);
  syncUrl(id);
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
  markCurrent(null, file.name);
  syncUrl(null);
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

// The picker is a search box (role=combobox) driving a subject → variant tree
// (role=tree, aria-activedescendant). Subjects collapse; inside a subject the
// featured / highlight builds show first and earlier passes sit behind a
// "+ N earlier passes" row. A search or filter opens every matching subject.

const SUBJECT_ORDER = ["windmill", "cottage", "bonsai"];
const WORDS = {
  mc: "MC", fd: "FD", hy: "HY", hymv: "HYMV", fbt: "FBT", "1m": "1M",
  lowpoly: "low-poly", subblocks: "sub-blocks", shapefit: "shape-fit",
};
const narrow = window.matchMedia?.("(max-width: 720px)");

const cat = {
  groups: [], // [{ subject, title, ref, models }] in display order
  info: new Map(), // id -> { label, tier, hay, meta }
  query: "",
  tokens: [],
  filter: "all", // all | highlight | mc
  expanded: new Set(), // subjects open while browsing
  collapsed: new Set(), // subjects closed by hand while a search/filter is active
  showAll: new Set(), // subjects whose earlier passes are revealed
  activeKey: null, // keyboard cursor: "g:<subject>", "m:<id>" or "more:<subject>"
};

const capitalise = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const subjectOf = (m) => m.subject || "other";

// Pass/variant name with the subject prefix stripped: "cottage_v2_mc_blocks"
// reads "v2 · MC blocks", "bonsai_lowpoly_half_sub" reads "low-poly half sub".
function variantLabel(m) {
  const pre = `${m.subject}_`;
  let rest = m.id === m.subject ? "" : m.id.startsWith(pre) ? m.id.slice(pre.length) : m.id;
  const mc = /(^|_)mc_blocks$/.test(rest);
  if (mc) rest = rest.replace(/_?mc_blocks$/, "");
  const words = rest.split("_").filter(Boolean).map((w) => WORDS[w] || w).join(" ");
  if (mc) return words ? `${words} · MC blocks` : "MC blocks";
  return words || "base";
}

function compactCount(n) {
  if (n == null) return "—";
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(n < 10000 ? 1 : 0)}k`;
}

function rowMeta(m) {
  if (m.format !== "mc_blocks" && m.subPct) return `${m.subPct}% sub`;
  return `${compactCount(m.voxelCount)} blk`;
}

function buildCatalogue(models) {
  cat.info.clear();
  const bySubj = new Map();
  for (const m of models) {
    const label = variantLabel(m);
    const hay = [
      m.id, m.id.replace(/_/g, " "), m.subject, m.kind, label,
      m.format === "mc_blocks" ? "mc minecraft blocks" : "voxels",
      m.featured ? "featured latest" : "",
      m.highlight ? "highlight final" : "",
    ].join(" ").toLowerCase();
    cat.info.set(m.id, { label, hay, tier: m.featured ? 0 : m.highlight ? 1 : 2, meta: rowMeta(m) });
    const s = subjectOf(m);
    if (!bySubj.has(s)) bySubj.set(s, []);
    bySubj.get(s).push(m);
  }
  const rank = (s) => {
    const i = SUBJECT_ORDER.indexOf(s);
    return i === -1 ? SUBJECT_ORDER.length : i;
  };
  const info = (m) => cat.info.get(m.id);
  cat.groups = [...bySubj.keys()]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((subject) => {
      const items = bySubj.get(subject);
      items.sort((a, b) => info(a).tier - info(b).tier || info(a).label.localeCompare(info(b).label));
      const withRef = items.find((m) => m.featured && m.ref) || items.find((m) => m.ref);
      return { subject, title: capitalise(subject), ref: withRef?.ref, models: items };
    });

  const counts = {
    all: models.length,
    highlight: models.filter((m) => m.highlight || m.featured).length,
    mc: models.filter((m) => m.format === "mc_blocks").length,
  };
  for (const n of document.querySelectorAll(".filter-n")) n.textContent = counts[n.dataset.n] ?? "";
  const input = $("model-search");
  if (input) input.placeholder = `Search ${models.length} models`;
  renderTree();
}

const isFiltering = () => cat.tokens.length > 0 || cat.filter !== "all";

function passesFilter(m) {
  if (cat.filter === "highlight" && !(m.highlight || m.featured)) return false;
  if (cat.filter === "mc" && m.format !== "mc_blocks") return false;
  const hay = cat.info.get(m.id).hay;
  return cat.tokens.every((t) => hay.includes(t));
}

function visibleGroups() {
  return cat.groups
    .map((group) => ({ group, items: group.models.filter(passesFilter) }))
    .filter((g) => g.items.length);
}

// Full grouped order, or just the matches while a search / filter is active.
function orderedIds() {
  return visibleGroups().flatMap((g) => g.items.map((m) => m.id));
}

function highlightText(text) {
  const frag = document.createDocumentFragment();
  if (!cat.tokens.length) {
    frag.append(text);
    return frag;
  }
  const esc = cat.tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  text.split(new RegExp(`(${esc.join("|")})`, "gi")).forEach((part, i) => {
    if (part) frag.append(i % 2 ? el("mark", { text: part }) : part);
  });
  return frag;
}

const chevron = () => {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 12 12");
  svg.setAttribute("class", "chev");
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", "M4.5 3 7.5 6 4.5 9");
  p.setAttribute("fill", "none");
  p.setAttribute("stroke", "currentColor");
  p.setAttribute("stroke-width", "1.5");
  p.setAttribute("stroke-linecap", "round");
  p.setAttribute("stroke-linejoin", "round");
  svg.append(p);
  return svg;
};

function leafNode(m) {
  const info = cat.info.get(m.id);
  const mark = m.featured ? "★" : m.highlight ? "◆" : "";
  const li = el(
    "li",
    {
      class: "tnode tleaf",
      id: `opt-${m.id}`,
      role: "treeitem",
      "aria-level": "2",
      "aria-selected": String(m.id === currentId),
      "aria-label": `${info.label}${m.featured ? ", featured" : m.highlight ? ", highlight" : ""}, ${info.meta}`,
      title: m.id,
    },
    [
      el("span", { class: "tl-mark", "aria-hidden": "true", text: mark }),
      el("span", { class: "tl-label" }, [highlightText(info.label)]),
      el("span", { class: "tl-meta", "aria-hidden": "true", text: info.meta }),
    ]
  );
  li.dataset.key = `m:${m.id}`;
  return li;
}

function renderTree() {
  const tree = $("model-tree");
  if (!tree) return;
  const filtering = isFiltering();
  const groups = visibleGroups();
  const total = groups.reduce((n, g) => n + g.items.length, 0);

  tree.replaceChildren(
    ...groups.map(({ group, items }) => {
      const { subject } = group;
      const open = filtering ? !cat.collapsed.has(subject) : cat.expanded.has(subject);
      const thumb = group.ref
        ? el("img", { class: "tg-thumb", src: group.ref, alt: "", loading: "lazy", decoding: "async" })
        : el("span", { class: "tg-thumb", "aria-hidden": "true" });
      const count = filtering ? `${items.length}/${group.models.length}` : String(items.length);
      const li = el(
        "li",
        {
          class: `tnode tgroup${items.some((m) => m.id === currentId) ? " has-current" : ""}`,
          id: `grp-${subject}`,
          role: "treeitem",
          "aria-level": "1",
          "aria-expanded": String(open),
          "aria-label": `${group.title}, ${items.length} model${items.length === 1 ? "" : "s"}`,
        },
        [
          el("div", { class: "tg-head" }, [
            chevron(),
            thumb,
            el("span", { class: "tg-name", text: group.title }),
            el("span", { class: "tg-count", "aria-hidden": "true", text: count }),
          ]),
        ]
      );
      li.dataset.key = `g:${subject}`;
      if (open) {
        let shown = items;
        if (!filtering && !cat.showAll.has(subject)) {
          const top = items.filter((m) => cat.info.get(m.id).tier < 2);
          if (top.length && items.length - top.length > 2) shown = top;
        }
        const ul = el("ul", { role: "group" }, shown.map(leafNode));
        const hidden = items.length - shown.length;
        if (hidden) {
          const more = el(
            "li",
            { class: "tnode tmore", id: `more-${subject}`, role: "treeitem", "aria-level": "2" },
            [el("span", { text: `+ ${hidden} earlier passes` })]
          );
          more.dataset.key = `more:${subject}`;
          ul.append(more);
        }
        li.append(ul);
      }
      return li;
    })
  );

  tree.hidden = !total;
  const empty = $("picker-empty");
  if (empty) empty.hidden = !!total;
  setText(
    "picker-empty-q",
    cat.query || { highlight: "highlights", mc: "MC blocks" }[cat.filter] || ""
  );
  setText("picker-count", filtering ? `${total} of ${manifest.models.length}` : `${manifest.models.length} models`);
  setActive(nodeFor(cat.activeKey) ? cat.activeKey : null, { scroll: false });
}

function nodeFor(key) {
  return key ? $("model-tree")?.querySelector(`[data-key="${CSS.escape(key)}"]`) : null;
}

function ensureVisible(node) {
  const tree = $("model-tree");
  if (!tree || !node) return;
  const isGroup = node.classList.contains("tgroup");
  // Group heads are sticky, so measure the row itself; leaves must clear their head.
  const head = isGroup ? node.firstElementChild : node.closest(".tgroup")?.firstElementChild;
  const r = node.getBoundingClientRect();
  const t = tree.getBoundingClientRect();
  const top = t.top + (isGroup ? 0 : head?.offsetHeight || 0);
  const bottom = isGroup ? r.top + (head?.offsetHeight || 0) : r.bottom;
  if (r.top < top) tree.scrollTop -= top - r.top;
  else if (bottom > t.bottom) tree.scrollTop += bottom - t.bottom;
}

function setActive(key, { scroll = true } = {}) {
  const tree = $("model-tree");
  if (!tree) return;
  cat.activeKey = key;
  for (const n of tree.querySelectorAll(".tnode.is-active")) n.classList.remove("is-active");
  const node = nodeFor(key);
  for (const host of [tree, $("model-search")]) {
    if (!host) continue;
    if (node) host.setAttribute("aria-activedescendant", node.id);
    else host.removeAttribute("aria-activedescendant");
  }
  if (!node) return;
  node.classList.add("is-active");
  if (scroll) ensureVisible(node);
}

function moveActive(step) {
  const nodes = [...($("model-tree")?.querySelectorAll(".tnode") || [])];
  if (!nodes.length) return;
  let i = nodes.findIndex((n) => n.dataset.key === cat.activeKey);
  if (step === "first") i = 0;
  else if (step === "last") i = nodes.length - 1;
  else if (i === -1) i = step > 0 ? 0 : nodes.length - 1;
  else i = Math.max(0, Math.min(nodes.length - 1, i + step));
  setActive(nodes[i].dataset.key);
}

// Open (true), close (false) or flip a subject. Returns whether anything changed.
function toggleGroup(subject, want) {
  const filtering = isFiltering();
  const isOpen = filtering ? !cat.collapsed.has(subject) : cat.expanded.has(subject);
  const open = want ?? !isOpen;
  if (open === isOpen) return false;
  if (filtering) open ? cat.collapsed.delete(subject) : cat.collapsed.add(subject);
  else open ? cat.expanded.add(subject) : cat.expanded.delete(subject);
  const groupKey = `g:${subject}`;
  if (!open && nodeFor(cat.activeKey)?.closest(".tgroup")?.dataset.key === groupKey) cat.activeKey = groupKey;
  renderTree();
  return true;
}

function revealMore(subject) {
  const tree = $("model-tree");
  const before = [...tree.querySelectorAll(".tnode")].findIndex((n) => n.dataset.key === `more:${subject}`);
  cat.showAll.add(subject);
  renderTree();
  const first = tree.querySelectorAll(".tnode")[before]; // first revealed pass takes the "more" row's place
  if (first) setActive(first.dataset.key);
}

function chooseModel(id) {
  if (narrow?.matches) setPickerOpen(false);
  if (id === currentId && document.body.dataset.state === "ready") return;
  loadModel(id).catch(fail);
}

function activate(key) {
  if (!key) return;
  const i = key.indexOf(":");
  const kind = key.slice(0, i);
  const rest = key.slice(i + 1);
  if (kind === "g") toggleGroup(rest);
  else if (kind === "more") revealMore(rest);
  else if (kind === "m") chooseModel(rest);
}

// Sync chips, tree selection and the compact trigger with the loaded model
// (null after a local file drop: nothing in the catalogue is selected).
function markCurrent(id, droppedName) {
  for (const chip of document.querySelectorAll("#featured .chip")) {
    chip.setAttribute("aria-pressed", chip.dataset.id === id ? "true" : "false");
  }
  const meta = id ? modelById(id) : null;
  setText("pt-subject", meta ? capitalise(subjectOf(meta)) : droppedName ? "Dropped file…" : "—");
  setText("pt-label", meta ? cat.info.get(id)?.label || id : droppedName || "—");
  const trigger = $("picker-trigger");
  if (trigger) trigger.title = meta ? meta.id : droppedName || "";
  if (meta) {
    const s = subjectOf(meta);
    cat.expanded.add(s);
    cat.collapsed.delete(s);
    if (cat.info.get(id)?.tier === 2) cat.showAll.add(s);
    cat.activeKey = `m:${id}`;
  }
  renderTree();
  if (meta) ensureVisible(nodeFor(cat.activeKey));
}

function setPickerOpen(open) {
  const picker = $("picker");
  if (!picker) return;
  picker.toggleAttribute("data-open", open);
  document.body.classList.toggle("picker-open", open);
  $("picker-trigger")?.setAttribute("aria-expanded", String(open));
  if (open) requestAnimationFrame(() => ensureVisible(nodeFor(cat.activeKey)));
}

function focusSearch() {
  const input = $("model-search");
  if (!input) return;
  if (narrow?.matches) setPickerOpen(true);
  input.focus();
  input.select();
}

function setQuery(q) {
  cat.query = q;
  cat.tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
  cat.collapsed.clear();
  const clear = $("search-clear");
  if (clear) clear.hidden = !q;
  $("model-search")?.parentElement.classList.toggle("has-value", !!q);
  renderTree();
  // Put the cursor on the best hit so Enter loads it.
  const first = isFiltering() ? $("model-tree")?.querySelector(".tleaf") : nodeFor(`m:${currentId}`);
  setActive(first?.dataset.key ?? null);
}

function setFilter(f) {
  cat.filter = f;
  for (const b of document.querySelectorAll(".filter")) {
    b.setAttribute("aria-pressed", String(b.dataset.filter === f));
  }
  setQuery($("model-search")?.value.trim() || "");
}

function onNavKey(e, fromInput) {
  if (e.altKey || e.metaKey || e.ctrlKey) return;
  const key = cat.activeKey;
  const kind = key?.slice(0, key.indexOf(":"));
  const subject = kind === "g" ? key.slice(2) : null;
  switch (e.key) {
    case "ArrowDown": moveActive(1); break;
    case "ArrowUp": moveActive(-1); break;
    case "PageDown": moveActive(8); break;
    case "PageUp": moveActive(-8); break;
    case "Home":
    case "End":
      if (fromInput && e.target.value) return; // keep caret movement while typing
      moveActive(e.key === "Home" ? "first" : "last");
      break;
    case "Enter":
      if (!nodeFor(key)) return;
      activate(key);
      break;
    case " ":
      if (fromInput || !nodeFor(key)) return;
      activate(key);
      break;
    case "ArrowRight":
      if (fromInput || !subject) return;
      if (!toggleGroup(subject, true)) moveActive(1);
      break;
    case "ArrowLeft":
      if (fromInput) return;
      if (subject) toggleGroup(subject, false);
      else if (nodeFor(key)) setActive(nodeFor(key).closest(".tgroup").dataset.key);
      break;
    case "Escape":
      if (fromInput && e.target.value) {
        e.target.value = "";
        setQuery("");
      } else {
        if (narrow?.matches) setPickerOpen(false);
        canvas.focus();
      }
      break;
    default:
      return;
  }
  e.preventDefault();
}

function bindPicker() {
  const input = $("model-search");
  const tree = $("model-tree");
  if (!input || !tree) return;
  const reset = () => {
    input.value = "";
    setQuery("");
    input.focus();
  };
  input.addEventListener("input", () => setQuery(input.value.trim()));
  input.addEventListener("keydown", (e) => onNavKey(e, true));
  tree.addEventListener("keydown", (e) => onNavKey(e, false));
  tree.addEventListener("click", (e) => {
    const node = e.target.closest(".tnode");
    if (!node || (node.classList.contains("tgroup") && !e.target.closest(".tg-head"))) return;
    setActive(node.dataset.key, { scroll: false });
    activate(node.dataset.key);
  });
  $("search-clear")?.addEventListener("click", reset);
  $("picker-empty-clear")?.addEventListener("click", () => {
    cat.filter = "all";
    for (const b of document.querySelectorAll(".filter")) {
      b.setAttribute("aria-pressed", String(b.dataset.filter === "all"));
    }
    reset();
  });
  for (const b of document.querySelectorAll(".filter")) {
    b.addEventListener("click", () => setFilter(b.dataset.filter));
  }
  $("picker-trigger")?.addEventListener("click", () => {
    setPickerOpen(!$("picker").hasAttribute("data-open"));
  });
  $("skip-picker")?.addEventListener("click", (e) => {
    e.preventDefault();
    focusSearch();
  });
  // Narrow screens: the drawer gets out of the way once you go back to the model.
  canvas.addEventListener("pointerdown", () => {
    if (narrow?.matches) setPickerOpen(false);
  });
  narrow?.addEventListener?.("change", (e) => {
    if (!e.matches) setPickerOpen(false);
  });
}

/* ---------- deep link: ?m=<id> (or #m=<id>) ---------- */

function idFromUrl() {
  const id =
    new URLSearchParams(location.search).get("m") ||
    new URLSearchParams(location.hash.replace(/^#/, "")).get("m");
  return id && modelById(id) ? id : null;
}

function syncUrl(id) {
  try {
    const url = new URL(location.href);
    // Leave a bare URL bare for the default model.
    if (id && id === manifest.default_id && !url.searchParams.has("m")) return;
    if (id) url.searchParams.set("m", id);
    else url.searchParams.delete("m");
    if (/^#m=/.test(url.hash)) url.hash = "";
    if (url.href !== location.href) history.replaceState(history.state, "", url);
  } catch {
    /* file:// or sandboxed frames */
  }
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

// [ / ] walk the filtered list while a search or filter is active, else the full grouped order.
function stepModel(delta) {
  const ids = orderedIds();
  if (!ids.length) return;
  const i = ids.indexOf(currentId);
  const next = i === -1 ? ids[delta > 0 ? 0 : ids.length - 1] : ids[(i + delta + ids.length) % ids.length];
  loadModel(next).catch(fail);
}

/* ---------- wiring ---------- */

function bindUi() {
  bindBlockInspector();
  bindPicker();
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

  // Keyboard: W wireframe, G grid, R reset, [ / ] previous / next model,
  // / or Cmd/Ctrl+K search the catalogue.
  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      focusSearch();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest?.("input, select, textarea, [contenteditable]")) return;
    const k = e.key.toLowerCase();
    if (k === "/") {
      focusSearch();
    } else if (k === "w" || k === "g") {
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
  buildCatalogue(manifest.models);
  populateFeatured(manifest.models);
  const start = idFromUrl() || manifest.default_id || manifest.models[0]?.id;
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
