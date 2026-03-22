/* Ariadne Web UI — UI: 입력, trace, sidebar, 줌, 이벤트 */

// === 입력 방식 ===
function clickNode(id) {
  const node = App.nodeMap[id];
  if (!node || !TRACEABLE.has(node.type)) { showInfo(node); showTab('info'); return; }
  pickNode(id);
}

function pickNode(id) {
  if (!App.srcId) {
    setSrc(id);
  } else if (!App.dstId) {
    if (id === App.srcId) return;
    setDst(id);
    doTrace(App.srcId, App.dstId);
  } else {
    clearSel();
    setSrc(id);
  }
}

function setSrc(id) {
  App.srcId = id; App.dstId = null;
  clearHL();
  hlNode(id, CSS.SRC_SEL);
  updSel();
  showInfo(App.nodeMap[id]); showTab('info');
  document.getElementById('bclear').classList.remove('hidden');
}

function setDst(id) {
  App.dstId = id;
  hlNode(id, CSS.DST_SEL);
  updSel();
}

// === 우클릭 메뉴 ===
function showCtx(e, id) {
  e.preventDefault(); e.stopPropagation();
  if (!TRACEABLE.has(App.nodeMap[id]?.type)) return;
  App.ctxNodeId = id;
  const m = document.getElementById('ctx');
  m.style.display = 'block';
  m.style.left = e.pageX + 'px';
  m.style.top = e.pageY + 'px';
}

function hideCtx() { document.getElementById('ctx').style.display = 'none'; }

function ctxDo(action) {
  hideCtx();
  if (!App.ctxNodeId) return;
  if (action === 'src') { setSrc(App.ctxNodeId); }
  else if (action === 'dst' && App.srcId) { setDst(App.ctxNodeId); doTrace(App.srcId, App.dstId); }
  else if (action === 'mem') { setSrc(App.ctxNodeId); setDst('mc_0'); doTrace(App.srcId, 'mc_0'); }
  else if (action === 'swap' && App.srcId && App.dstId) {
    const s = App.srcId, d = App.dstId;
    clearSel(); setSrc(d); setDst(s); doTrace(d, s);
  }
  else if (action === 'info') { showInfo(App.nodeMap[App.ctxNodeId]); showTab('info'); }
}

// === 검색 ===
function searchDev(q) {
  const nodes = document.querySelectorAll('.htree-node');
  if (!q) { nodes.forEach(el => el.classList.remove(CSS.SEARCH_HL, CSS.SEARCH_DIM)); return; }
  q = q.toLowerCase();
  nodes.forEach(el => {
    const id = el.dataset.id || '';
    const label = el.querySelector('.htree-label')?.textContent || '';
    const match = label.toLowerCase().includes(q) || id.toLowerCase().includes(q);
    el.classList.toggle(CSS.SEARCH_HL, match);
    el.classList.toggle(CSS.SEARCH_DIM, !match);
  });
}

// === Trace ===
async function doTrace(sid, did) {
  const r = await fetch(`/api/trace?source=${sid}&destination=${did}`).then(r => r.json());
  App.hist.unshift({ sn: r.source_name, dn: r.destination_name, bw: r.e2e_bandwidth_gbps, lat: r.e2e_latency_ns, sid, did, r });
  if (App.hist.length > LAYOUT.maxHistory) App.hist.pop();
  applyTrace(r, sid, did);
}

function applyTrace(r, sid, did) {
  App.srcId = sid; App.dstId = did; App.lastTrace = r;
  clearHL();
  hlNode(sid, CSS.SRC_SEL);
  hlNode(did, CSS.DST_SEL);
  if (r.path?.length > 0) {
    r.path.forEach(nid => { if (nid !== sid && nid !== did) hlNode(nid, CSS.ON_PATH); });
    for (let i = 0; i < r.path.length - 1; i++) {
      hlEdge(r.path[i], r.path[i + 1], CSS.TRACE_HL);
    }
  }
  updSel();
  showSidebar();
  renderTrace(r);
  showTab('trace');
  document.getElementById('bclear').classList.remove('hidden');
}

function renderTrace(r) {
  if (!r.segments?.length) { setSB('<div class="empty">No path found</div>'); return; }
  const ns = r.same_numa
    ? '<span class="text-source">same</span>'
    : '<span class="text-dest">cross</span>';
  let h = '<div class="section"><div class="stitle">' + r.source_name + ' → ' + r.destination_name + '</div>';
  h += '<div class="cards">';
  h += `<div class="card"><div class="card-l">BW</div><div class="card-v">${r.e2e_bandwidth_gbps} GB/s</div></div>`;
  h += `<div class="card"><div class="card-l">Latency</div><div class="card-v">${r.e2e_latency_ns}ns</div></div>`;
  h += `<div class="card"><div class="card-l">NUMA</div><div class="card-v" style="font-size:12px">${ns}</div></div>`;
  h += '</div>';
  if (r.bottleneck) h += `<div class="text-accent" style="font-size:10px;margin-bottom:8px;">⚠ ${r.bottleneck}</div>`;
  h += '</div>';

  h += '<div class="section"><div class="stitle">Path</div>';
  for (let i = 0; i < r.segments.length; i++) {
    const s = r.segments[i], bn = r.bottleneck && s.from_name && r.bottleneck.includes(s.from_name);
    if (i === 0) h += `<div class="pnode src">${s.from_name}</div>`;
    const lt = (s.link_type || '').includes('pcie') ? 'PCIe' : (s.link_type || '').includes('memory') ? 'DDR' : '→';
    const bw = s.effective_bw_gbps ? ` · ${s.effective_bw_gbps}/${s.theoretical_bw_gbps} GB/s` : '';
    h += `<div class="plink" data-seg="${i}" onmouseenter="hlSeg(${i})" onmouseleave="unhlSeg()" onclick="scrollToSeg(${i})"><b>${i + 1}</b> ${lt} · ${s.latency_ns}ns${bw} ${bn ? ' <span class="text-accent">◄ BN</span>' : ''}</div>`;
    h += `<div class="pnode ${i === r.segments.length - 1 ? 'dst' : ''}" data-seg="${i}" onmouseenter="hlSeg(${i})" onmouseleave="unhlSeg()" onclick="scrollToSeg(${i})">${s.to_name}</div>`;
  }
  h += '</div>';

  h += '<div class="section"><div class="stitle">Breakdown</div>';
  h += '<table class="tbl"><tr><th>#</th><th>Segment</th><th>Theo</th><th>Eff</th><th>Lat</th></tr>';
  for (let i = 0; i < r.segments.length; i++) {
    const s = r.segments[i], bn = r.bottleneck && s.from_name && r.bottleneck.includes(s.from_name);
    h += `<tr data-seg="${i}" ${bn ? 'class="text-accent"' : ''} onmouseenter="hlSeg(${i})" onmouseleave="unhlSeg()" onclick="scrollToSeg(${i})">`;
    h += `<td>${i + 1}</td><td>${s.from_name}→${s.to_name}</td><td>${s.theoretical_bw_gbps || '-'}</td><td>${s.effective_bw_gbps || '-'}</td><td>${s.latency_ns}ns</td></tr>`;
  }
  h += `<tr style="border-top:2px solid #333"><td></td><td><b>E2E</b></td><td></td><td><b>${r.e2e_bandwidth_gbps}</b></td><td><b>${r.e2e_latency_ns}ns</b></td></tr>`;
  h += '</table></div>';
  setSB(h);
}

// === Breakdown ↔ 트리 양방향 연동 ===
function hlSeg(i) {
  if (!App.lastTrace?.path || i >= App.lastTrace.path.length - 1) return;
  const from = App.lastTrace.path[i], to = App.lastTrace.path[i + 1];
  hlNode(from, CSS.ON_PATH); hlNode(to, CSS.ON_PATH);
  hlEdge(from, to, CSS.SEG_HL);
  document.querySelectorAll('[data-seg]').forEach(el => {
    if (parseInt(el.dataset.seg) === i) el.classList.add('hl');
  });
}

function hlSegFromEdge(source, target) {
  if (!App.lastTrace?.path) return;
  for (let i = 0; i < App.lastTrace.path.length - 1; i++) {
    const a = App.lastTrace.path[i], b = App.lastTrace.path[i + 1];
    if ((a === source && b === target) || (a === target && b === source)) {
      hlSeg(i);
      return;
    }
  }
}

function unhlSeg() {
  document.querySelectorAll('.' + CSS.SEG_HL).forEach(el => el.classList.remove(CSS.SEG_HL));
  document.querySelectorAll('[data-seg].hl').forEach(el => el.classList.remove('hl'));
  document.querySelectorAll('.tbl tr.hl').forEach(el => el.classList.remove('hl'));
  document.querySelectorAll('.htree-node.' + CSS.ON_PATH).forEach(el => {
    if (!el.classList.contains(CSS.SRC_SEL) && !el.classList.contains(CSS.DST_SEL)) el.classList.remove(CSS.ON_PATH);
  });
  if (App.lastTrace?.path) {
    App.lastTrace.path.forEach(nid => { if (nid !== App.srcId && nid !== App.dstId) hlNode(nid, CSS.ON_PATH); });
  }
}

function scrollToSeg(i) {
  if (!App.lastTrace?.path || i >= App.lastTrace.path.length - 1) return;
  const nodeEl = document.getElementById(ID.node(App.lastTrace.path[i]));
  if (nodeEl) nodeEl.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
}

// === 노드/Edge 하이라이트 ===
function hlNode(id, cls) {
  const el = document.getElementById(ID.node(id));
  if (el) el.classList.add(cls);
}

function hlEdge(fromId, toId, cls) {
  let el = document.getElementById(ID.edge(fromId, toId));
  if (!el) el = document.getElementById(ID.edge(toId, fromId));
  if (el) el.classList.add(cls);
}

function clearHL() {
  document.querySelectorAll('.htree-node').forEach(el => el.classList.remove(CSS.SRC_SEL, CSS.DST_SEL, CSS.ON_PATH));
  document.querySelectorAll('.edge-line').forEach(el => el.classList.remove(CSS.TRACE_HL, CSS.SEG_HL));
}

function clearSel() {
  App.srcId = null; App.dstId = null; App.lastTrace = null;
  clearHL(); updSel();
  document.getElementById('bclear').classList.add('hidden');
}

function updSel() {
  const bar = document.getElementById('sel-bar'), txt = document.getElementById('sel-text');
  if (!App.srcId) { bar.style.display = 'none'; return; }
  bar.style.display = 'block';
  const sn = App.nodeMap[App.srcId]?.label || App.srcId;
  if (!App.dstId) {
    txt.innerHTML = `<span class="text-source">SRC: ${sn}</span> <span style="color:#ccc;font-size:16px;padding:0 6px">→</span> <span class="text-muted">click destination...</span>`;
  } else {
    const dn = App.nodeMap[App.dstId]?.label || App.dstId;
    txt.innerHTML = `<span class="text-source">${sn}</span> <span style="color:#ccc;font-size:16px;padding:0 6px">→</span> <span class="text-dest">${dn}</span>`;
  }
}

// === Sidebar toggle / resize ===
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const toggle = document.getElementById('sb-toggle');
  sb.classList.toggle('collapsed');
  toggle.textContent = sb.classList.contains('collapsed') ? '▶' : '◀';
}

function showSidebar() {
  const sb = document.getElementById('sidebar');
  if (sb.classList.contains('collapsed')) toggleSidebar();
}

// 드래그 리사이즈
(function initResize() {
  const handle = document.getElementById('sb-resize');
  const sidebar = document.getElementById('sidebar');
  if (!handle || !sidebar) return;

  let startX, startW;
  handle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    startX = e.clientX;
    startW = sidebar.offsetWidth;
    document.addEventListener('mousemove', onDrag);
    document.addEventListener('mouseup', stopDrag);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });

  function onDrag(e) {
    const w = startW - (e.clientX - startX);
    sidebar.style.width = Math.max(250, Math.min(700, w)) + 'px';
  }
  function stopDrag() {
    document.removeEventListener('mousemove', onDrag);
    document.removeEventListener('mouseup', stopDrag);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }
})();

// === Sidebar content ===
function showInfo(d) {
  if (!d) return;
  let h = `<div class="section"><div class="stitle">${d.label || d.id}</div>`;
  for (const [k, v] of Object.entries(d)) {
    if (['id', 'label', 'source', 'target', 'parent'].includes(k)) continue;
    if (v === null || v === undefined || v === '' || v === -1) continue;
    h += `<div class="field"><span class="flabel">${k}</span><br><span class="fval">${typeof v === 'object' ? JSON.stringify(v) : v}</span></div>`;
  }
  h += '</div>';
  setSB(h);
}

function showHistory() {
  if (!App.hist.length) { setSB('<div class="empty">No history</div>'); return; }
  let h = '<div class="section"><div class="stitle">History</div>';
  App.hist.forEach((t, i) => {
    h += `<div class="hist" onclick="replay(${i})"><span>${t.sn} → ${t.dn}</span><span style="color:var(--color-cyan)">${t.bw} GB/s · ${t.lat}ns</span></div>`;
  });
  h += '</div>';
  setSB(h);
}

function replay(i) {
  const t = App.hist[i];
  clearSel();
  applyTrace(t.r, t.sid, t.did);
}

function showTab(t) {
  document.querySelectorAll('.tab').forEach(el => el.classList.toggle('on', el.textContent.toLowerCase() === t));
  if (t === 'history') showHistory();
  else if (t === 'trace' && App.hist.length) renderTrace(App.hist[0].r);
}

function setSB(h) { document.getElementById('sb').innerHTML = h; }

// === 줌 ===
function setZoom(s) {
  App.zoomScale = Math.max(LAYOUT.zoomMin, Math.min(LAYOUT.zoomMax, s));
  document.getElementById('tree-content').style.transform = `scale(${App.zoomScale})`;
  document.getElementById('zoom-level').textContent = `${Math.round(App.zoomScale * 100)}%`;
}
function zoomIn() { setZoom(App.zoomScale + LAYOUT.zoomStep); }
function zoomOut() { setZoom(App.zoomScale - LAYOUT.zoomStep); }
function zoomFit() {
  const p = document.getElementById('tree-panel'), c = document.getElementById('tree-content');
  if (!c.firstChild) return;
  c.style.transform = 'scale(1)';
  const s = Math.min(
    (p.clientWidth - LAYOUT.panelMargin) / c.scrollWidth,
    (p.clientHeight - LAYOUT.panelMargin) / c.scrollHeight,
    1
  );
  setZoom(s);
}

document.getElementById('tree-panel').addEventListener('wheel', function (e) {
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    setZoom(App.zoomScale + (e.deltaY > 0 ? -LAYOUT.zoomWheelStep : LAYOUT.zoomWheelStep));
  }
}, { passive: false });

init();
