/* Ariadne Web UI — UI: 입력, trace, sidebar, 줌, 이벤트 */

// === 입력 방식 ===
function clickNode(id) {
  const node = App.nodeMap[id];
  if (!node) return;
  // 이전 info 선택 해제
  document.querySelectorAll('.htree-node.info-sel').forEach(el => el.classList.remove('info-sel'));
  if (!TRACEABLE.has(node.type)) {
    // non-traceable: 정보만 표시 + 선택 표시
    hlNode(id, 'info-sel');
    showInfo(node); showTab('info');
    return;
  }
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

  h += '<div class="section"><div class="stitle">Path</div><div class="scroll-box">';
  for (let i = 0; i < r.segments.length; i++) {
    const s = r.segments[i], bn = r.bottleneck && s.from_name && r.bottleneck.includes(s.from_name);
    if (i === 0) h += `<div class="pnode src">${s.from_name}</div>`;
    const lt = (s.link_type || '').includes('pcie') ? 'PCIe' : (s.link_type || '').includes('memory') ? 'DDR' : '→';
    const bw = s.effective_bw_gbps ? ` · ${s.effective_bw_gbps}/${s.theoretical_bw_gbps} GB/s` : '';
    h += `<div class="plink" data-seg="${i}" onmouseenter="hlSeg(${i})" onmouseleave="unhlSeg()" onclick="scrollToSeg(${i})"><b>${i + 1}</b> ${lt} · ${s.latency_ns}ns${bw} ${bn ? ' <span class="text-accent">◄ BN</span>' : ''}</div>`;
    h += `<div class="pnode ${i === r.segments.length - 1 ? 'dst' : ''}" data-seg="${i}" onmouseenter="hlSeg(${i})" onmouseleave="unhlSeg()" onclick="scrollToSeg(${i})">${s.to_name}</div>`;
  }
  h += '</div></div>';

  h += '<div class="section"><div class="stitle">Breakdown</div><div class="scroll-box">';
  h += '<table class="tbl"><tr><th>#</th><th>Segment</th><th>Theo</th><th>Eff</th><th>Lat</th></tr>';
  for (let i = 0; i < r.segments.length; i++) {
    const s = r.segments[i], bn = r.bottleneck && s.from_name && r.bottleneck.includes(s.from_name);
    h += `<tr data-seg="${i}" ${bn ? 'class="text-accent"' : ''} onmouseenter="hlSeg(${i})" onmouseleave="unhlSeg()" onclick="scrollToSeg(${i})">`;
    h += `<td>${i + 1}</td><td>${s.from_name}→${s.to_name}</td><td>${s.theoretical_bw_gbps || '-'}</td><td>${s.effective_bw_gbps || '-'}</td><td>${s.latency_ns}ns</td></tr>`;
  }
  h += `<tr style="border-top:2px solid #333"><td></td><td><b>E2E</b></td><td></td><td><b>${r.e2e_bandwidth_gbps}</b></td><td><b>${r.e2e_latency_ns}ns</b></td></tr>`;
  h += '</table></div></div>';
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
  document.querySelectorAll('.htree-node').forEach(el => el.classList.remove(CSS.SRC_SEL, CSS.DST_SEL, CSS.ON_PATH, 'info-sel'));
  document.querySelectorAll('.edge-line').forEach(el => el.classList.remove(CSS.TRACE_HL, CSS.SEG_HL));
  // pinned trace 다시 적용
  renderPinnedTraces();
}

function clearSel() {
  App.srcId = null; App.dstId = null; App.lastTrace = null;
  clearHL(); updSel();
}

function updSel() {
  const srcIn = document.getElementById('src-input');
  const dstIn = document.getElementById('dst-input');
  const btn = document.getElementById('trace-btn');
  if (App.srcId) {
    srcIn.value = App.nodeMap[App.srcId]?.label || App.srcId;
    srcIn.classList.add('has-value');
  } else {
    srcIn.value = '';
    srcIn.classList.remove('has-value');
  }
  if (App.dstId) {
    dstIn.value = App.nodeMap[App.dstId]?.label || App.dstId;
    dstIn.classList.add('has-value');
  } else {
    dstIn.value = '';
    dstIn.classList.remove('has-value');
  }
  btn.disabled = !(App.srcId && App.dstId);
}

// === Trace Picker (드롭다운) ===
function getTraceableNodes() {
  return Object.values(App.nodeMap)
    .filter(n => TRACEABLE.has(n.type))
    .sort((a, b) => (a.label || a.id).localeCompare(b.label || b.id));
}

function renderPickerList(role, filter) {
  const list = document.getElementById(role + '-list');
  const nodes = getTraceableNodes();
  const q = (filter || '').toLowerCase();
  const filtered = q ? nodes.filter(n =>
    (n.label || '').toLowerCase().includes(q) ||
    (n.id || '').toLowerCase().includes(q) ||
    (n.attrs?.bdf || '').toLowerCase().includes(q) ||
    (n.attrs?.vendor_name || '').toLowerCase().includes(q)
  ) : nodes;

  list.innerHTML = filtered.map(n => {
    const color = COLORS[n.type] || '#6b7280';
    const typeName = (n.attrs?.type_name || n.type || '').replace(/_/g, ' ');
    const bdf = n.attrs?.bdf || '';
    return `<div class="sel-item" onmousedown="selectPicker('${role}','${n.id}')">
      <span class="sel-type" style="background:${color}">${typeName}</span>
      <span class="sel-name">${n.label || n.id}</span>
      ${bdf ? `<span class="sel-bdf">${bdf}</span>` : ''}
    </div>`;
  }).join('');
}

function openPicker(role) {
  const list = document.getElementById(role + '-list');
  renderPickerList(role, document.getElementById(role + '-input').value);
  list.classList.remove('hidden');
  // 다른 picker 닫기
  const other = role === 'src' ? 'dst' : 'src';
  document.getElementById(other + '-list').classList.add('hidden');
}

function filterPicker(role, value) {
  renderPickerList(role, value);
  document.getElementById(role + '-list').classList.remove('hidden');
  // 직접 타이핑으로 입력 변경 시 선택 해제
  if (role === 'src' && App.srcId) {
    App.srcId = null; clearHL(); updTraceBtn();
  } else if (role === 'dst' && App.dstId) {
    App.dstId = null; clearHL(); updTraceBtn();
  }
}

function selectPicker(role, id) {
  if (role === 'src') {
    App.srcId = id;
    clearHL();
    hlNode(id, CSS.SRC_SEL);
  } else {
    App.dstId = id;
    hlNode(id, CSS.DST_SEL);
  }
  document.getElementById(role + '-list').classList.add('hidden');
  updSel();
  // dst 선택하면 자동 trace
  if (App.srcId && App.dstId) doTrace(App.srcId, App.dstId);
}

function updTraceBtn() {
  document.getElementById('trace-btn').disabled = !(App.srcId && App.dstId);
}

function traceFromPicker() {
  if (App.srcId && App.dstId) doTrace(App.srcId, App.dstId);
}

// 외부 클릭 시 picker 닫기
document.addEventListener('click', (e) => {
  if (!e.target.closest('.sel-dropdown')) {
    document.querySelectorAll('.sel-list').forEach(l => l.classList.add('hidden'));
  }
});

// === Sidebar toggle / resize ===
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const toggle = document.getElementById('sb-toggle');
  sb.classList.toggle('collapsed');
  toggle.textContent = sb.classList.contains('collapsed') ? '◀' : '▶';
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
  h += `<div style="font-size:9px;color:#666;margin-bottom:6px;">${App.pinnedTraces.length}/${TRACE_COLORS.length} pinned</div>`;
  App.hist.forEach((t, i) => {
    const pinIdx = App.pinnedTraces.findIndex(p => p.sid === t.sid && p.did === t.did);
    const isPinned = pinIdx >= 0;
    const color = isPinned ? TRACE_COLORS[pinIdx % TRACE_COLORS.length] : 'transparent';
    h += `<div class="hist${isPinned ? ' pinned' : ''}">`;
    h += `<span class="pin-btn" style="color:${isPinned ? color : '#555'}" onclick="event.stopPropagation();togglePin(${i})" title="${isPinned ? 'Unpin' : 'Pin to overlay'}">●</span>`;
    h += `<span class="hist-text" onclick="replay(${i})">${t.sn} → ${t.dn}</span>`;
    h += `<span class="hist-bw" onclick="replay(${i})">${t.bw} GB/s · ${t.lat}ns</span>`;
    h += `</div>`;
  });
  h += '</div>';
  setSB(h);
}

function showIommuTab() {
  const groups = App.iommuGroups || {};
  const ctx = App.iommuCtx || {};
  const groupIds = Object.keys(groups).map(Number).sort((a, b) => a - b);

  if (groupIds.length === 0) {
    setSB('<div class="empty">No IOMMU groups detected</div>');
    return;
  }

  let h = '<div class="section"><div class="stitle">IOMMU Groups</div>';
  h += `<div style="font-size:10px;color:#888;margin-bottom:8px;">${ctx.group_count || groupIds.length} groups · ${ctx.iommu_enabled ? 'IOMMU active' : 'IOMMU inactive'}</div>`;

  for (const gid of groupIds) {
    const compIds = groups[gid];
    if (!compIds || compIds.length === 0) continue;
    const color = IOMMU_COLORS[gid % IOMMU_COLORS.length];
    h += `<div class="iommu-group" data-gid="${gid}" onmouseenter="hlIommuGroup(${gid})" onmouseleave="unhlIommuGroup()">`;
    h += `<div class="iommu-group-hdr"><span style="color:${color}">🔒</span> Group ${gid} <span class="text-muted">(${compIds.length})</span></div>`;
    for (const cid of compIds) {
      const node = App.nodeMap[cid];
      const name = node?.label || cid;
      const bdf = node?.bdf || '';
      h += `<div class="iommu-dev" onclick="scrollToNode('${cid}')"><span class="sel-type" style="background:${COLORS[node?.type] || '#666'}">${(node?.type_name || node?.type || '').replace(/_/g,' ')}</span> ${name} <span class="text-muted">${bdf}</span></div>`;
    }
    h += '</div>';
  }
  h += '</div>';

  // Context: 시스템 상태 + 커널 파라미터
  h += '<div class="section"><div class="stitle">System Context</div>';
  h += '<div style="font-size:10px;">';

  // 현재 상태
  h += `<div class="iommu-ctx-row"><span class="iommu-ctx-label">IOMMU</span><span>${ctx.iommu_enabled ? '✅ Active' : '❌ Inactive'}</span></div>`;
  h += `<div class="iommu-ctx-row"><span class="iommu-ctx-label">Groups</span><span>${ctx.group_count || 0}개</span></div>`;

  // 커널 파라미터
  const knownParams = [
    { key: 'intel_iommu', label: 'intel_iommu' },
    { key: 'amd_iommu', label: 'amd_iommu' },
    { key: 'iommu', label: 'iommu' },
    { key: 'iommu.strict', label: 'iommu.strict' },
    { key: 'pcie_acs_override', label: 'pcie_acs_override' },
    { key: 'intremap', label: 'intremap' },
  ];
  const cmdParams = ctx.cmdline_params || {};

  h += '<div style="margin-top:6px;color:#888;font-size:9px;">Kernel Parameters</div>';
  for (const p of knownParams) {
    const val = cmdParams[p.key];
    if (val) {
      h += `<div class="iommu-param">${p.label}=${val}</div>`;
    } else {
      h += `<div class="iommu-ctx-row" style="color:#555;"><span class="iommu-ctx-label">${p.label}</span><span>(미설정)</span></div>`;
    }
  }
  // pci= 관련
  const pciParams = Object.entries(cmdParams).filter(([k]) => k.startsWith('pci.'));
  if (pciParams.length > 0) {
    for (const [k, v] of pciParams) h += `<div class="iommu-param">${v}</div>`;
  }

  h += '</div></div>';

  setSB(h);
}

function showIommuGroup(gid) {
  showSidebar();
  showTab('iommu');
  showIommuTab();
  hlIommuGroup(gid);
}

function hlIommuGroup(gid) {
  unhlIommuGroup();
  const compIds = (App.iommuGroups || {})[gid] || [];
  const color = IOMMU_COLORS[gid % IOMMU_COLORS.length];
  for (const cid of compIds) {
    const el = document.getElementById(ID.node(cid));
    if (!el) continue;
    el.classList.add('iommu-hl');
    el.style.setProperty('--iommu-color', color);
  }
}

function unhlIommuGroup() {
  document.querySelectorAll('.htree-node.iommu-hl').forEach(el => {
    el.classList.remove('iommu-hl');
    el.style.removeProperty('--iommu-color');
  });
  document.querySelectorAll('.iommu-group-hl').forEach(el => el.classList.remove('iommu-group-hl'));
}

function scrollToNode(id) {
  const el = document.getElementById(ID.node(id));
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
}

function replay(i) {
  const t = App.hist[i];
  clearSel();
  applyTrace(t.r, t.sid, t.did);
}

function togglePin(histIdx) {
  const t = App.hist[histIdx];
  const pinIdx = App.pinnedTraces.findIndex(p => p.sid === t.sid && p.did === t.did);
  if (pinIdx >= 0) {
    App.pinnedTraces.splice(pinIdx, 1);
  } else if (App.pinnedTraces.length < TRACE_COLORS.length) {
    App.pinnedTraces.push({ sid: t.sid, did: t.did, r: t.r });
  }
  renderPinnedTraces();
  showHistory();
}

function renderPinnedTraces() {
  // pinned trace edge 스타일 제거
  document.querySelectorAll('.edge-line.pinned-trace').forEach(el => {
    el.classList.remove('pinned-trace');
    el.style.removeProperty('--pin-color');
  });
  document.querySelectorAll('.htree-node.pinned-node').forEach(el => {
    el.classList.remove('pinned-node');
    el.style.removeProperty('--pin-color');
  });

  // 각 pinned trace를 색상별로 표시
  App.pinnedTraces.forEach((pt, idx) => {
    const color = TRACE_COLORS[idx % TRACE_COLORS.length];
    const r = pt.r;
    if (!r.path?.length) return;

    // edge 하이라이트
    for (let i = 0; i < r.path.length - 1; i++) {
      let el = document.getElementById(ID.edge(r.path[i], r.path[i + 1]));
      if (!el) el = document.getElementById(ID.edge(r.path[i + 1], r.path[i]));
      if (el) {
        el.classList.add('pinned-trace');
        el.style.setProperty('--pin-color', color);
      }
    }
    // src/dst 노드 표시
    [r.path[0], r.path[r.path.length - 1]].forEach(nid => {
      const el = document.getElementById(ID.node(nid));
      if (el) {
        el.classList.add('pinned-node');
        el.style.setProperty('--pin-color', color);
      }
    });
  });
}

function showTab(t) {
  document.querySelectorAll('.tab').forEach(el => el.classList.toggle('on', el.textContent.toLowerCase() === t));
  if (t === 'history') showHistory();
  else if (t === 'iommu') showIommuTab();
  else if (t === 'safety') showSafetyTab();
  else if (t === 'vfio') showVfioTab();
  else if (t === 'whatif') showWhatIfTab();
  else if (t === 'simulate') showSimulateTab();
  else if (t === 'trace' && App.hist.length) renderTrace(App.hist[0].r);
}

async function showSafetyTab() {
  setSB('<div class="safety-empty">Loading…</div>');
  try {
    const r = await fetch('/api/safety/sriov');
    const data = await r.json();
    const issues = data.issues || [];
    if (issues.length === 0) {
      setSB('<div class="safety-empty">✅ 감지된 SR-IOV/IOMMU 안전성 이슈 없음</div>');
      return;
    }
    let html = '<div class="safety-list">';
    issues.forEach(i => {
      html += `<div class="safety-item ${i.severity}">`;
      html += `<div class="sf-summary">⚠ ${escapeHtml(i.summary)}</div>`;
      if (i.detail) html += `<div class="sf-detail">${escapeHtml(i.detail)}</div>`;
      if (i.recommendation) html += `<div class="sf-rec">→ ${escapeHtml(i.recommendation)}</div>`;
      html += `</div>`;
    });
    html += '</div>';
    setSB(html);
  } catch (e) {
    setSB(`<div class="safety-empty">Safety API 호출 실패: ${e}</div>`);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
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

// === IOMMU 그룹 ===
const IOMMU_COLORS = [
  '#ef4444','#f59e0b','#22c55e','#3b82f6','#a855f7','#ec4899',
  '#06b6d4','#84cc16','#f97316','#6366f1','#14b8a6','#e11d48',
  '#8b5cf6','#10b981',
];

// === 디바이스 필터 ===
function toggleFilter(btn) {
  btn.classList.toggle('on');
  applyFilters();
}

function applyFilters() {
  const active = new Set();
  document.querySelectorAll('.fbtn.on').forEach(b => active.add(b.dataset.filter));

  // endpoint 노드의 부모 .htree-child에 filtered 클래스 토글
  document.querySelectorAll('.htree-node').forEach(el => {
    const type = el.dataset.type;
    const cat = FILTER_MAP[type];
    if (!cat) return; // 비-endpoint (NUMA, Socket, RC, RP 등)는 필터 대상 아님
    const child = el.closest('.htree-child');
    if (child) child.classList.toggle('filtered', !active.has(cat));
  });

  setTimeout(() => drawEdges(), 50);
}

// === Simulate / VFIO / What-if 탭 ===

const SimState = {
  flows: [],  // [{flow_id, source, destination, size_bytes, start_ns}]
};

function showSimulateTab() {
  const flowsHtml = SimState.flows.length === 0
    ? '<div class="hint">flow를 추가하세요. 같은 link를 공유하는 다중 flow의 BW 분배·bottleneck을 추정합니다.</div>'
    : SimState.flows.map((f, i) => `
        <div class="sim-flow">
          <span class="flow-x" onclick="simRemoveFlow(${i})">×</span>
          <div class="flow-id">${escapeHtml(f.flow_id)}</div>
          <div style="font-family:monospace;font-size:10px;color:#aaa;">
            ${escapeHtml(f.source)} → ${escapeHtml(f.destination)}<br>
            ${(f.size_bytes / 1e6).toFixed(1)} MB @ start +${f.start_ns} ns
          </div>
        </div>`).join('');

  setSB(`
    <div class="tabform">
      <div class="row"><label>Flow ID</label><input id="sim-fid" value="f${SimState.flows.length + 1}"></div>
      <div class="row"><label>Source</label><input id="sim-src" placeholder="component id" value="${App.sel?.src || ''}"></div>
      <div class="row"><label>Destination</label><input id="sim-dst" placeholder="component id" value="${App.sel?.dst || ''}"></div>
      <div class="row"><label>Size (MB)</label><input id="sim-size" type="number" value="100" min="0.001" step="1"></div>
      <div class="row"><label>Start (ns)</label><input id="sim-start" type="number" value="0" min="0"></div>
      <div class="actions">
        <button onclick="simAddFlow()">+ Flow 추가</button>
        <button class="btn-gray" onclick="simClearFlows()">초기화</button>
        <button onclick="simRun()" ${SimState.flows.length === 0 ? 'disabled' : ''}>Simulate</button>
      </div>
      <div class="sim-flows">${flowsHtml}</div>
      <div id="sim-result"></div>
    </div>
  `);
}

function simAddFlow() {
  const fid = document.getElementById('sim-fid').value.trim();
  const src = document.getElementById('sim-src').value.trim();
  const dst = document.getElementById('sim-dst').value.trim();
  const sizeMb = parseFloat(document.getElementById('sim-size').value);
  const startNs = parseFloat(document.getElementById('sim-start').value || '0');
  if (!fid || !src || !dst || !(sizeMb > 0)) {
    alert('flow_id, source, destination, size 입력 필요');
    return;
  }
  SimState.flows.push({
    flow_id: fid,
    source: src,
    destination: dst,
    size_bytes: Math.round(sizeMb * 1e6),
    start_ns: startNs,
  });
  showSimulateTab();
}

function simRemoveFlow(i) { SimState.flows.splice(i, 1); showSimulateTab(); }
function simClearFlows() { SimState.flows = []; showSimulateTab(); }

async function simRun() {
  document.getElementById('sim-result').innerHTML = '<div class="hint">Running…</div>';
  try {
    const r = await fetch('/api/simulate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({flows: SimState.flows}),
    });
    const data = await r.json();
    renderSimResult(data);
  } catch (e) {
    document.getElementById('sim-result').innerHTML = `<div class="vfio-empty">Simulate 실패: ${escapeHtml(String(e))}</div>`;
  }
}

function renderSimResult(data) {
  let html = `<div class="sim-result"><div class="res-row"><span class="lbl">Total simulated</span><span class="val">${(data.total_simulated_ns / 1e6).toFixed(3)} ms</span></div>`;
  (data.flows || []).forEach(f => {
    html += `<hr style="border:0;border-top:1px dashed #2a2a3e;margin:6px 0;">`;
    html += `<div class="res-row"><span class="lbl">Flow ${escapeHtml(f.flow_id)}</span><span class="val">${(f.duration_ns / 1e6).toFixed(3)} ms</span></div>`;
    html += `<div class="res-row"><span class="lbl">Eff. BW</span><span class="val">${f.effective_bandwidth_gbps.toFixed(2)} GB/s</span></div>`;
    if (f.bottleneck_link) html += `<div class="res-row"><span class="lbl">Bottleneck</span><span class="val bottleneck">${escapeHtml(f.bottleneck_link)}</span></div>`;
    if (f.contended_with && f.contended_with.length) html += `<div class="res-row"><span class="lbl">Contends with</span><span class="val contended">${f.contended_with.map(escapeHtml).join(', ')}</span></div>`;
  });
  const utilEntries = Object.entries(data.link_utilization || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (utilEntries.length) {
    html += `<div class="sim-link-util"><h4>Top link utilization (busy ns)</h4>`;
    utilEntries.forEach(([k, v]) => {
      html += `<div class="util-row"><span>${escapeHtml(k)}</span><span>${(v / 1e6).toFixed(3)} ms</span></div>`;
    });
    html += `</div>`;
  }
  html += `</div>`;
  document.getElementById('sim-result').innerHTML = html;
}

async function showVfioTab() {
  setSB('<div class="vfio-empty">Loading…</div>');
  try {
    const r = await fetch('/api/vfio');
    const data = await r.json();
    renderVfio(data);
  } catch (e) {
    setSB(`<div class="vfio-empty">VFIO API 호출 실패: ${escapeHtml(String(e))}</div>`);
  }
}

function renderVfio(data) {
  const iommu = data.iommu_settings || {};
  const devices = data.vfio_devices || [];
  const vms = data.vms || [];

  let html = `<div class="vfio-section"><h4>IOMMU 부팅 설정</h4><div class="vfio-iommu">`;
  html += `intel_iommu = ${iommu.intel_iommu ?? '<i>(unset)</i>'}<br>`;
  html += `amd_iommu = ${iommu.amd_iommu ?? '<i>(unset)</i>'}<br>`;
  html += `iommu=pt: <b>${iommu.iommu_passthrough ? '✓' : '✗'}</b><br>`;
  if (iommu.pcie_acs_override) html += `pcie_acs_override = ${escapeHtml(iommu.pcie_acs_override)}<br>`;
  if (iommu.isolcpus && iommu.isolcpus.length) html += `isolcpus = ${iommu.isolcpus.join(',')}<br>`;
  if (iommu.hugepages_total != null) html += `hugepages = ${iommu.hugepages_total}`;
  html += `</div></div>`;

  html += `<div class="vfio-section"><h4>vfio-pci 바인딩 디바이스 (${devices.length})</h4>`;
  if (devices.length === 0) html += `<div class="vfio-empty">vfio-pci에 바인딩된 디바이스 없음</div>`;
  else devices.forEach(d => {
    html += `<div class="vfio-item"><div class="vf-title vf-bdf">${escapeHtml(d.bdf)}</div>`;
    html += `<div class="vf-meta">IOMMU group: ${d.iommu_group >= 0 ? d.iommu_group : '?'}<br>`;
    html += `Driver: ${escapeHtml(d.driver)}<br>`;
    html += `Attached VM: ${d.attached_to_vm ? `<b>${escapeHtml(d.attached_to_vm)}</b>` : '<i>(none)</i>'}</div></div>`;
  });
  html += `</div>`;

  html += `<div class="vfio-section"><h4>실행 중인 qemu VM (${vms.length})</h4>`;
  if (vms.length === 0) html += `<div class="vfio-empty">qemu-system-* 프로세스 없음</div>`;
  else vms.forEach(v => {
    html += `<div class="vfio-item"><div class="vf-title">${escapeHtml(v.name || `pid${v.pid}`)}</div>`;
    html += `<div class="vf-meta">PID ${v.pid} · ${v.vcpus} vCPU · ${v.memory_mb} MB<br>`;
    if (v.numa_nodes && v.numa_nodes.length) html += `NUMA nodes: ${v.numa_nodes.join(',')}<br>`;
    if (v.attached_bdfs && v.attached_bdfs.length) {
      html += `Passthrough BDFs:<br>`;
      v.attached_bdfs.forEach(b => html += `&nbsp;&nbsp;<span class="vf-bdf">${escapeHtml(b)}</span><br>`);
    }
    html += `</div></div>`;
  });
  html += `</div>`;

  setSB(html);
}

const WhatIfState = {
  source: '', destination: '',
  iommu_enabled: null, iommu_passthrough: false,
  aspm: 'auto',
  numa_balancing: false,
  transparent_hugepages: '',
  cpu_governor: '',
};

function showWhatIfTab() {
  if (!WhatIfState.source && App.sel?.src) WhatIfState.source = App.sel.src;
  if (!WhatIfState.destination && App.sel?.dst) WhatIfState.destination = App.sel.dst;

  const iommuVal = WhatIfState.iommu_enabled === true ? 'on' : WhatIfState.iommu_enabled === false ? 'off' : '';

  setSB(`
    <div class="tabform">
      <div class="whatif-target">${escapeHtml(WhatIfState.source || '(set Source)')} → ${escapeHtml(WhatIfState.destination || '(set Destination)')}</div>
      <div class="row"><label>Source</label><input id="wi-src" value="${escapeHtml(WhatIfState.source)}" placeholder="component id"></div>
      <div class="row"><label>Destination</label><input id="wi-dst" value="${escapeHtml(WhatIfState.destination)}" placeholder="component id"></div>
      <hr>
      <div class="row"><label>IOMMU</label>
        <select id="wi-iommu">
          <option value="">(default)</option>
          <option value="on" ${iommuVal === 'on' ? 'selected' : ''}>on</option>
          <option value="off" ${iommuVal === 'off' ? 'selected' : ''}>off</option>
        </select>
      </div>
      <div class="row"><label>iommu=pt</label><input id="wi-pt" type="checkbox" ${WhatIfState.iommu_passthrough ? 'checked' : ''}></div>
      <div class="row"><label>ASPM</label>
        <select id="wi-aspm">
          ${['auto', 'disabled', 'l0s', 'l1', 'l1ss'].map(v => `<option value="${v}" ${WhatIfState.aspm === v ? 'selected' : ''}>${v}</option>`).join('')}
        </select>
      </div>
      <div class="row"><label>numa_balancing</label><input id="wi-numa" type="checkbox" ${WhatIfState.numa_balancing ? 'checked' : ''}></div>
      <div class="row"><label>THP</label>
        <select id="wi-thp">
          <option value="">(default)</option>
          ${['always', 'madvise', 'never'].map(v => `<option value="${v}" ${WhatIfState.transparent_hugepages === v ? 'selected' : ''}>${v}</option>`).join('')}
        </select>
      </div>
      <div class="row"><label>cpu_governor</label>
        <select id="wi-gov">
          <option value="">(default)</option>
          ${['performance', 'powersave', 'ondemand'].map(v => `<option value="${v}" ${WhatIfState.cpu_governor === v ? 'selected' : ''}>${v}</option>`).join('')}
        </select>
      </div>
      <div class="actions">
        <button onclick="whatIfRun()">What-if Trace</button>
      </div>
      <div id="wi-result"></div>
    </div>
  `);
}

async function whatIfRun() {
  WhatIfState.source = document.getElementById('wi-src').value.trim();
  WhatIfState.destination = document.getElementById('wi-dst').value.trim();
  const iommuRaw = document.getElementById('wi-iommu').value;
  WhatIfState.iommu_enabled = iommuRaw === 'on' ? true : iommuRaw === 'off' ? false : null;
  WhatIfState.iommu_passthrough = document.getElementById('wi-pt').checked;
  WhatIfState.aspm = document.getElementById('wi-aspm').value;
  WhatIfState.numa_balancing = document.getElementById('wi-numa').checked;
  WhatIfState.transparent_hugepages = document.getElementById('wi-thp').value;
  WhatIfState.cpu_governor = document.getElementById('wi-gov').value;

  if (!WhatIfState.source || !WhatIfState.destination) {
    document.getElementById('wi-result').innerHTML = `<div class="vfio-empty">Source와 Destination 입력 필요</div>`;
    return;
  }

  const settings = {};
  if (WhatIfState.iommu_enabled !== null) {
    settings.iommu_enabled = WhatIfState.iommu_enabled;
    settings.iommu_passthrough = WhatIfState.iommu_passthrough;
  }
  if (WhatIfState.aspm && WhatIfState.aspm !== 'auto') settings.aspm = WhatIfState.aspm;
  if (WhatIfState.numa_balancing) settings.numa_balancing = true;
  if (WhatIfState.transparent_hugepages) settings.transparent_hugepages = WhatIfState.transparent_hugepages;
  if (WhatIfState.cpu_governor) settings.cpu_governor = WhatIfState.cpu_governor;

  document.getElementById('wi-result').innerHTML = '<div class="hint">Running…</div>';
  try {
    const r = await fetch('/api/whatif', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source: WhatIfState.source, destination: WhatIfState.destination, settings}),
    });
    const data = await r.json();
    renderWhatIf(data);
  } catch (e) {
    document.getElementById('wi-result').innerHTML = `<div class="vfio-empty">What-if 실패: ${escapeHtml(String(e))}</div>`;
  }
}

function renderWhatIf(d) {
  if (d.error) {
    document.getElementById('wi-result').innerHTML = `<div class="vfio-empty">${escapeHtml(d.error)}</div>`;
    return;
  }
  const cls = (delta) => delta > 0 ? 'delta-pos' : delta < 0 ? 'delta-neg' : 'delta-zero';
  const sign = (delta) => delta > 0 ? '+' : '';
  let html = `<div class="whatif-result"><div class="whatif-grid">`;
  html += `<div class="gh"></div><div class="gh">Baseline</div><div class="gh">Scenario</div><div class="gh">Δ</div>`;
  html += `<div class="gv">BW (GB/s)</div><div class="gv">${d.baseline_bandwidth_gbps.toFixed(2)}</div><div class="gv">${d.scenario_bandwidth_gbps.toFixed(2)}</div><div class="gv ${cls(d.bandwidth_delta_pct)}">${sign(d.bandwidth_delta_pct)}${d.bandwidth_delta_pct.toFixed(2)}%</div>`;
  html += `<div class="gv">Latency (ns)</div><div class="gv">${d.baseline_latency_ns.toFixed(1)}</div><div class="gv">${d.scenario_latency_ns.toFixed(1)}</div><div class="gv ${cls(-d.latency_delta_pct)}">${sign(d.latency_delta_pct)}${d.latency_delta_pct.toFixed(2)}%</div>`;
  html += `</div>`;
  html += `<div class="sim-link-util"><h4>적용된 trace 파라미터</h4>`;
  Object.entries(d.applied_params || {}).forEach(([k, v]) => {
    html += `<div class="util-row"><span>${escapeHtml(k)}</span><span>${typeof v === 'number' ? v.toFixed(2) : escapeHtml(String(v))}</span></div>`;
  });
  html += `</div></div>`;
  document.getElementById('wi-result').innerHTML = html;
}

init();
