/* Ariadne Cluster page — inventory POST + cluster topology 시각화 */

const EXAMPLE_INVENTORY = `all:
  hosts:
    gpu-01:
      ansible_host: 10.0.0.11
      ansible_user: root
    gpu-02:
      ansible_host: 10.0.0.12
      ansible_user: ubuntu
    head-01:
      ansible_host: head.lab
  children:
    gpu_workers:
      hosts:
        gpu-01: {}
        gpu-02: {}
    head_nodes:
      hosts:
        head-01: {}
`;

function loadExample() {
  document.getElementById('c-inventory').value = EXAMPLE_INVENTORY;
  document.getElementById('c-cluster-id').value = 'lmtune-prod-a';
}

function setStatus(s) { document.getElementById('c-status').textContent = s; }

function showError(msg) {
  const el = document.getElementById('c-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideError() {
  document.getElementById('c-error').classList.add('hidden');
}

async function buildCluster() {
  hideError();
  const cluster_id = document.getElementById('c-cluster-id').value.trim();
  const yamlText = document.getElementById('c-inventory').value.trim();
  if (!cluster_id || !yamlText) {
    showError('cluster_id와 inventory YAML이 필요합니다.');
    return;
  }
  let inventory;
  try {
    inventory = parseSimpleYaml(yamlText);
  } catch (e) {
    showError('YAML parse 실패: ' + e);
    return;
  }
  setStatus('수집 중… (호스트 SSH 연결, 수십 초 소요 가능)');
  try {
    const r = await fetch('/api/cluster', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cluster_id, inventory}),
    });
    if (!r.ok) {
      showError('API 실패: ' + r.status);
      setStatus('실패');
      return;
    }
    const cluster = await r.json();
    setStatus(`완료 — ${Object.keys(cluster.hosts || {}).length} 호스트, ${(cluster.inter_host_links||[]).length} fabric link`);
    renderCluster(cluster);
  } catch (e) {
    showError('Build 실패: ' + e);
    setStatus('에러');
  }
}

async function loadClusterFile(ev) {
  hideError();
  const file = ev.target.files && ev.target.files[0];
  if (!file) return;
  setStatus(`Loading ${file.name}…`);
  let payload;
  try {
    payload = JSON.parse(await file.text());
  } catch (e) {
    showError('JSON parse 실패: ' + e);
    setStatus('실패');
    return;
  }
  const overrideId = document.getElementById('c-cluster-id').value.trim();
  const body = overrideId
    ? {cluster_id: overrideId, cluster: payload}
    : payload;
  try {
    const r = await fetch('/api/cluster/load', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      showError('Load 실패: ' + (err.error || r.status));
      setStatus('실패');
      return;
    }
    const cluster = await r.json();
    document.getElementById('c-cluster-id').value = cluster.cluster_id;
    setStatus(`로드 완료 — ${Object.keys(cluster.hosts || {}).length} 호스트, ${(cluster.inter_host_links||[]).length} fabric link`);
    renderCluster(cluster);
  } catch (e) {
    showError('Load 실패: ' + e);
    setStatus('에러');
  } finally {
    ev.target.value = '';  // 같은 파일 재선택 가능하게
  }
}

function renderCluster(cluster) {
  // Summary
  const sum = document.getElementById('c-summary');
  sum.textContent = `cluster_id: ${cluster.cluster_id} · collected_at: ${cluster.collected_at} · hosts: ${Object.keys(cluster.hosts||{}).length} · groups: ${Object.keys(cluster.groups||{}).length}`;

  // Hosts grid
  const grid = document.getElementById('c-grid');
  grid.innerHTML = '';
  const hosts = cluster.hosts || {};
  const groups = cluster.groups || {};
  const hostGroupMap = {};
  for (const [g, members] of Object.entries(groups)) {
    members.forEach(m => { (hostGroupMap[m] = hostGroupMap[m] || []).push(g); });
  }
  for (const [hostId, topo] of Object.entries(hosts)) {
    const card = document.createElement('div');
    card.className = 'c-host';
    const groupsTxt = (hostGroupMap[hostId]||[]).join(', ') || '—';
    let html = `<h3>${escHtml(hostId)}</h3>`;
    html += `<div class="meta">groups: ${escHtml(groupsTxt)}</div>`;
    if (topo.hostname) html += `<div class="row">hostname: ${escHtml(topo.hostname)}</div>`;
    const numCpu = (topo.cpu_cores||[]).length;
    const numNuma = (topo.numa_nodes||[]).length;
    const numPci = (topo.pci_devices||[]).length;
    const gpuCount = (topo.pci_devices||[]).filter(d=>d.component_type==='gpu').length;
    const npuCount = (topo.pci_devices||[]).filter(d=>d.component_type==='npu').length;
    const nicCount = (topo.pci_devices||[]).filter(d=>d.component_type==='nic').length;
    const nvmeCount = (topo.pci_devices||[]).filter(d=>d.component_type==='nvme').length;
    html += `<div class="row">CPU cores: ${numCpu} · NUMA: ${numNuma}</div>`;
    html += `<div class="row">PCI: ${numPci} (GPU ${gpuCount} · NPU ${npuCount} · NIC ${nicCount} · NVMe ${nvmeCount})</div>`;
    const fm = topo.fabric_manager;
    if (fm && fm.fm_running) {
      html += `<div class="row" style="color:#06b6d4">NVSwitch fabric: ${(fm.nvswitches||[]).length}개</div>`;
    }
    const sysid = topo.system_identity;
    if (sysid && sysid.baseboard_product_name) {
      html += `<div class="row" style="color:#888">${escHtml(sysid.baseboard_manufacturer || '')} ${escHtml(sysid.baseboard_product_name)}</div>`;
    }
    const nvlink = topo.nvlink;
    if (nvlink && (nvlink.connections||[]).length) {
      html += `<div class="row" style="color:#22c55e">NVLink connections: ${nvlink.connections.length}</div>`;
    }
    card.innerHTML = html;
    grid.appendChild(card);
  }

  // Inter-host links
  const linksEl = document.getElementById('c-links-list');
  const links = cluster.inter_host_links || [];
  if (!links.length) {
    linksEl.innerHTML = '<h2>Inter-host fabric — 추론된 link 없음</h2>';
    return;
  }
  let html = `<h2>Inter-host fabric (${links.length}개)</h2>`;
  links.forEach(l => {
    html += `<div class="c-link ${l.type}">`;
    html += `<span class="ltype">[${l.type}]</span> `;
    html += `${escHtml(l.from_host)}/${escHtml(l.from_iface||'')} ↔ ${escHtml(l.to_host)}/${escHtml(l.to_iface||'')}`;
    if (l.bandwidth_gbps) html += ` · ${l.bandwidth_gbps} GB/s`;
    if (l.fabric) html += ` · <span style="color:#666">fabric: ${escHtml(l.fabric)}</span>`;
    html += `</div>`;
  });
  linksEl.innerHTML = html;
}

/* Browser-side simple Ansible inventory YAML parser.
   Full YAML 라이브러리 없이 인벤토리 표준 구조 (들여쓰기 + key:value + dict children)만 처리.
*/
function parseSimpleYaml(text) {
  const lines = text.split('\n').filter(l => !/^\s*(#|$)/.test(l));
  const root = {};
  const stack = [{indent: -1, obj: root}];
  for (const line of lines) {
    const m = line.match(/^(\s*)(\S.*?)\s*$/);
    if (!m) continue;
    const indent = m[1].length;
    const content = m[2];
    while (stack.length > 1 && stack[stack.length-1].indent >= indent) stack.pop();
    const parent = stack[stack.length-1].obj;

    if (content.includes(':')) {
      const idx = content.indexOf(':');
      const key = content.substring(0, idx).trim();
      let val = content.substring(idx + 1).trim();
      if (val === '' || val === '{}' || val === 'null') {
        const child = (val === '{}') ? {} : {};
        parent[key] = child;
        stack.push({indent, obj: child});
      } else {
        // 단순 scalar
        if (val.match(/^\d+$/)) val = parseInt(val);
        parent[key] = val;
      }
    }
  }
  return root;
}

function escHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
