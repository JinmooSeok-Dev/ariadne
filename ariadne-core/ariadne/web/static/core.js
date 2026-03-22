/* Ariadne Web UI — Core: 상수, 상태, 유틸, 데이터 로딩, edge 렌더링 */

// === 상수 ===
const COLORS = {
  numa_node:'#f0c040', socket:'#4ecdc4', memory_controller:'#3b82f6',
  cpu_core:'#38bdf8', cache:'#94a3b8', dram:'#60a5fa',
  pcie_root_complex:'#e94560', pcie_root_port:'#7c3aed',
  gpu:'#22c55e', npu:'#06b6d4', nic:'#a855f7', nvme:'#f59e0b', pcie_endpoint:'#6b7280',
};

const TRACEABLE = new Set(['gpu','npu','nvme','nic','memory_controller','pcie_endpoint']);

const LAYOUT = {
  childIndent: 60,
  childGap: 2,
  childPadding: 4,
  nodeMinWidth: 160,
  bwLabelOffset: 4,
  bwLabelBoxWidth: 32,
  bwLabelBoxHeight: 14,
  bwLabelBoxRadius: 3,
  hitAreaWidth: 16,
  zoomMin: 0.2,
  zoomMax: 2,
  zoomStep: 0.1,
  zoomWheelStep: 0.05,
  panelMargin: 40,
  maxHistory: 10,
};

const CSS = {
  SRC_SEL: 'src-sel',
  DST_SEL: 'dst-sel',
  ON_PATH: 'on-path',
  TRACE_HL: 'trace-hl',
  SEG_HL: 'seg-hl',
  SEARCH_HL: 'search-hl',
  SEARCH_DIM: 'search-dim',
};

// === ID 생성 유틸 ===
function esc(id) { return id.replace(/[:.]/g, '_'); }

const ID = {
  node: (id) => 'n_' + esc(id),
  edge: (src, tgt) => 'e_' + esc(src) + '_' + esc(tgt),
  children: (id) => 'ch_' + esc(id),
  count: (id) => 'ct_' + esc(id),
};

// === App 상태 ===
const App = {
  graph: null,
  topo: null,
  nodeMap: {},
  childrenOf: {},
  edgeMap: {},
  srcId: null,
  dstId: null,
  hist: [],
  ctxNodeId: null,
  lastTrace: null,
  zoomScale: 1,
};

// === 데이터 로딩 ===
async function init() {
  [App.graph, App.topo] = await Promise.all([
    fetch('/api/topology/graph').then(r => r.json()),
    fetch('/api/topology').then(r => r.json()),
  ]);
  document.getElementById('hinfo').textContent =
    `${App.topo.hostname} · ${App.topo.numa_nodes.length} NUMA · ${App.topo.cpu_cores.length} cores · ${App.topo.pci_devices.length} PCI`;

  App.nodeMap = {};
  App.graph.nodes.forEach(n => App.nodeMap[n.data.id] = n.data);
  App.childrenOf = {};
  App.graph.edges.forEach(e => {
    if (!App.childrenOf[e.data.source]) App.childrenOf[e.data.source] = [];
    App.childrenOf[e.data.source].push(e.data);
  });

  renderTree();
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { clearSel(); hideCtx(); } });
  document.addEventListener('click', () => hideCtx());
}

// === 트리 렌더링 ===
function renderTree() {
  const hasParent = new Set();
  App.graph.edges.forEach(e => hasParent.add(e.data.target));
  const roots = App.graph.nodes.filter(n => !hasParent.has(n.data.id)).map(n => n.data.id);
  let html = '';
  roots.forEach(r => { html += buildNode(r); });
  document.getElementById('tree-nodes').innerHTML = html;
  requestAnimationFrame(() => drawEdges());
  zoomFit();
}

function buildNode(id) {
  const node = App.nodeMap[id];
  if (!node) return '';
  const kids = App.childrenOf[id] || [];
  const color = COLORS[node.type] || '#666';
  const nid = esc(id);

  let badges = buildBadges(node);
  const cnt = countDesc(id);
  const chId = ID.children(id);

  let h = `<div class="htree">`;
  h += `<div class="htree-node" id="${ID.node(id)}" data-id="${id}" style="background:${color}22;border-color:${color}44" onclick="clickNode('${id}')" oncontextmenu="showCtx(event,'${id}')">`;
  if (kids.length > 0) h += `<span class="htree-toggle" onclick="event.stopPropagation();fold('${chId}',this)">▼</span>`;
  h += `<span class="htree-dot" style="background:${color}"></span>`;
  h += `<span class="htree-label">${node.label}</span>`;
  h += badges;
  if (kids.length > 0) h += `<span class="htree-count" id="${ID.count(id)}" class="hidden">${cnt}</span>`;
  h += `</div>`;

  if (kids.length > 0) {
    h += `<div class="htree-children" id="${chId}">`;
    kids.forEach(edge => {
      h += `<div class="htree-child">${buildNode(edge.target)}</div>`;
    });
    h += `</div>`;
  }
  h += `</div>`;
  return h;
}

function buildBadges(node) {
  let b = '';
  if (node.link) b += `<span class="htree-badge">${node.link}</span>`;
  if (node.iommu_group >= 0) b += `<span class="htree-iommu">G${node.iommu_group}</span>`;
  if (node.sriov_totalvfs > 0) b += `<span class="htree-badge">VF:${node.sriov_numvfs || 0}/${node.sriov_totalvfs}</span>`;
  if (node.memory_mb) b += `<span class="htree-badge">${Math.round(node.memory_mb / 1024)}GB</span>`;
  if (node.cpu_count) b += `<span class="htree-badge">${node.cpu_count}CPU</span>`;
  return b;
}

function countDesc(id) {
  const k = App.childrenOf[id] || [];
  let c = k.length;
  k.forEach(e => { c += countDesc(e.target); });
  return c;
}

function fold(chId, el) {
  const ch = document.getElementById(chId);
  if (!ch) return;
  const folding = !ch.classList.contains('folded');
  ch.classList.toggle('folded');
  el.textContent = folding ? '▶' : '▼';
  const ct = document.getElementById(chId.replace('ch_', 'ct_'));
  if (ct) ct.classList.toggle('hidden', !folding);
  // 접기/펼치기 후 edge 재그리기 (레이아웃 정착 대기)
  setTimeout(() => drawEdges(), 50);
}

// === Edge 렌더링 (SVG) ===
function drawEdges() {
  const svg = document.getElementById('edge-svg');
  const container = document.getElementById('tree-content');
  svg.setAttribute('width', container.scrollWidth);
  svg.setAttribute('height', container.scrollHeight);
  svg.innerHTML = '';
  App.edgeMap = {};

  App.graph.edges.forEach(e => {
    const coords = calcEdgeCoords(e.data, container);
    if (!coords) return;
    registerEdge(e.data, coords);
    svg.appendChild(createEdgeGroup(e.data, coords));
  });
}

function getOffsetTo(el, ancestor) {
  let x = 0, y = 0;
  while (el && el !== ancestor) {
    x += el.offsetLeft;
    y += el.offsetTop;
    el = el.offsetParent;
  }
  return { x, y };
}

function calcEdgeCoords(edgeData, container) {
  const srcEl = document.getElementById(ID.node(edgeData.source));
  const tgtEl = document.getElementById(ID.node(edgeData.target));
  if (!srcEl || !tgtEl) return null;
  if (srcEl.offsetParent === null || tgtEl.offsetParent === null) return null;

  const sp = getOffsetTo(srcEl, container);
  const tp = getOffsetTo(tgtEl, container);
  const x1 = sp.x + srcEl.offsetWidth;
  const y1 = sp.y + srcEl.offsetHeight / 2;
  const x2 = tp.x;
  const y2 = tp.y + tgtEl.offsetHeight / 2;
  return { x1, y1, x2, y2, mx: (x1 + x2) / 2 };
}

function registerEdge(edgeData, coords) {
  const eId = ID.edge(edgeData.source, edgeData.target);
  App.edgeMap[eId] = {
    id: eId,
    source: edgeData.source,
    target: edgeData.target,
    type: edgeData.type === 'internal' ? 'internal' : 'pcie',
    bandwidth_gbps: edgeData.bandwidth_gbps || null,
    latency_ns: edgeData.latency_ns || null,
    speed: edgeData.speed || null,
    width: edgeData.width || null,
    path: coords,
  };
}

function createEdgeGroup(edgeData, coords) {
  const { x1, y1, x2, y2, mx } = coords;
  const eId = ID.edge(edgeData.source, edgeData.target);
  const edgeType = edgeData.type === 'internal' ? 'internal' : 'pcie';
  const pathD = `M${x1},${y1} L${mx},${y1} L${mx},${y2} L${x2},${y2}`;

  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.setAttribute('class', 'edge-group');
  g.setAttribute('data-source', edgeData.source);
  g.setAttribute('data-target', edgeData.target);
  g.style.cursor = 'pointer';
  g.addEventListener('click', () => showEdgeDetail(eId));
  g.addEventListener('mouseenter', () => hlSegFromEdge(edgeData.source, edgeData.target));
  g.addEventListener('mouseleave', () => unhlSeg());

  // 히트 영역
  const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  hit.setAttribute('d', pathD);
  hit.setAttribute('stroke', 'transparent');
  hit.setAttribute('stroke-width', String(LAYOUT.hitAreaWidth));
  hit.setAttribute('fill', 'none');
  hit.setAttribute('pointer-events', 'stroke');
  g.appendChild(hit);

  // 보이는 edge
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  line.setAttribute('d', pathD);
  line.setAttribute('class', `edge-line ${edgeType}`);
  line.setAttribute('id', eId);
  g.appendChild(line);

  // BW 라벨
  if (edgeData.bandwidth_gbps) {
    const lx = mx + LAYOUT.bwLabelOffset;
    const ly = (y1 + y2) / 2;
    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    bg.setAttribute('x', lx - 2);
    bg.setAttribute('y', ly - 8);
    bg.setAttribute('width', LAYOUT.bwLabelBoxWidth);
    bg.setAttribute('height', LAYOUT.bwLabelBoxHeight);
    bg.setAttribute('rx', LAYOUT.bwLabelBoxRadius);
    bg.setAttribute('fill', '#0f0f1a');
    bg.setAttribute('class', 'edge-bg');
    g.appendChild(bg);

    const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    txt.setAttribute('x', lx);
    txt.setAttribute('y', ly + 3);
    txt.setAttribute('class', 'edge-bw');
    txt.textContent = edgeData.bandwidth_gbps;
    g.appendChild(txt);
  }

  return g;
}

function showEdgeDetail(eId) {
  const edge = App.edgeMap[eId];
  if (!edge) return;
  const srcName = App.nodeMap[edge.source]?.label || edge.source;
  const tgtName = App.nodeMap[edge.target]?.label || edge.target;
  let h = `<div class="section"><div class="stitle">Edge: ${srcName} → ${tgtName}</div>`;
  h += `<div class="field"><span class="flabel">Type</span><br><span class="fval">${edge.type}</span></div>`;
  if (edge.bandwidth_gbps) h += `<div class="field"><span class="flabel">Bandwidth</span><br><span class="fval">${edge.bandwidth_gbps} GB/s</span></div>`;
  if (edge.latency_ns) h += `<div class="field"><span class="flabel">Latency</span><br><span class="fval">${edge.latency_ns} ns</span></div>`;
  if (edge.speed) h += `<div class="field"><span class="flabel">Speed</span><br><span class="fval">${edge.speed}</span></div>`;
  if (edge.width) h += `<div class="field"><span class="flabel">Width</span><br><span class="fval">x${edge.width}</span></div>`;
  h += '</div>';
  setSB(h); showTab('info');
}
