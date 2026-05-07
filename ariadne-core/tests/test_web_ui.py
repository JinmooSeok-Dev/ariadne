"""Web UI 엔드포인트 + 정적 자산 런타임 테스트."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
  from ariadne.api.server import app
  return TestClient(app)


def test_index_html_includes_safety_tab(client):
  r = client.get("/")
  assert r.status_code == 200
  assert "Safety" in r.text  # Safety 탭 추가됨
  assert "Cluster" in r.text  # Cluster 링크 추가됨


def test_cluster_page_renders(client):
  r = client.get("/cluster")
  assert r.status_code == 200
  assert "cluster.js" in r.text
  assert "inventory" in r.text.lower()


def test_static_cluster_js_served(client):
  r = client.get("/static/cluster.js")
  assert r.status_code == 200
  assert "buildCluster" in r.text
  assert "renderCluster" in r.text


def test_static_style_css_has_nvlink_edge(client):
  r = client.get("/static/style.css")
  assert r.status_code == 200
  assert ".edge-line.nvlink" in r.text
  assert ".edge-line.ucie" in r.text
  assert ".htree-cap" in r.text  # capability 뱃지 스타일


def test_safety_endpoint_returns_issues_list(client):
  r = client.get("/api/safety/sriov")
  assert r.status_code == 200
  data = r.json()
  assert "issues" in data
  assert isinstance(data["issues"], list)


def test_transfer_modes_endpoint(client):
  graph = client.get("/api/topology/graph").json()
  traceable = ["gpu", "npu", "nvme", "nic", "memory_controller", "pcie_endpoint"]
  nodes = [n for n in graph["nodes"] if n["data"]["type"] in traceable]
  if len(nodes) < 2:
    pytest.skip("traceable 노드 2개 미만")
  src = nodes[0]["data"]["id"]
  dst = nodes[1]["data"]["id"]
  r = client.get(f"/api/transfer-modes?source={src}&destination={dst}")
  assert r.status_code == 200
  data = r.json()
  assert "modes" in data
  names = [m["name"] for m in data["modes"]]
  assert "dma" in names  # 항상 가능


def test_static_core_js_capability_badges(client):
  r = client.get("/static/core.js")
  assert r.status_code == 200
  assert "capabilities" in r.text
  assert "ucie" in r.text.lower()


def test_static_ui_js_safety_tab(client):
  r = client.get("/static/ui.js")
  assert r.status_code == 200
  assert "showSafetyTab" in r.text
  assert "/api/safety/sriov" in r.text


def test_index_html_has_new_tabs(client):
  r = client.get("/")
  assert r.status_code == 200
  assert "showTab('simulate')" in r.text
  assert "showTab('vfio')" in r.text
  assert "showTab('whatif')" in r.text


def test_static_ui_js_new_tab_handlers(client):
  r = client.get("/static/ui.js")
  assert r.status_code == 200
  assert "showSimulateTab" in r.text
  assert "showVfioTab" in r.text
  assert "showWhatIfTab" in r.text
  assert "/api/simulate" in r.text
  assert "/api/vfio" in r.text
  assert "/api/whatif" in r.text


def test_static_style_css_has_new_panels(client):
  r = client.get("/static/style.css")
  assert r.status_code == 200
  assert ".sim-flow" in r.text
  assert ".vfio-section" in r.text
  assert ".whatif-grid" in r.text


def test_vfio_endpoint_returns_inventory(client):
  r = client.get("/api/vfio")
  assert r.status_code == 200
  data = r.json()
  # 호스트에 VFIO가 없어도 빈 list가 반환되어야 함
  assert "vfio_devices" in data
  assert "iommu_settings" in data
  assert "vms" in data


def test_whatif_endpoint_compares_baseline(client):
  graph = client.get("/api/topology/graph").json()
  traceable = ["gpu", "npu", "nvme", "nic", "memory_controller", "pcie_endpoint"]
  nodes = [n for n in graph["nodes"] if n["data"]["type"] in traceable]
  if len(nodes) < 2:
    pytest.skip("traceable 노드 2개 미만")
  src = nodes[0]["data"]["id"]
  dst = nodes[1]["data"]["id"]
  body = {
    "source": src,
    "destination": dst,
    "settings": {"aspm": "l1ss", "iommu_enabled": True, "iommu_passthrough": False},
  }
  r = client.post("/api/whatif", json=body)
  assert r.status_code == 200
  data = r.json()
  assert "baseline_latency_ns" in data
  assert "scenario_latency_ns" in data
  assert "applied_params" in data


def test_simulate_endpoint_runs(client):
  graph = client.get("/api/topology/graph").json()
  traceable = ["gpu", "npu", "nvme", "nic", "memory_controller", "pcie_endpoint"]
  nodes = [n for n in graph["nodes"] if n["data"]["type"] in traceable]
  if len(nodes) < 2:
    pytest.skip("traceable 노드 2개 미만")
  src = nodes[0]["data"]["id"]
  dst = nodes[1]["data"]["id"]
  body = {
    "flows": [
      {"flow_id": "f1", "source": src, "destination": dst, "size_bytes": 10**6}
    ]
  }
  r = client.post("/api/simulate", json=body)
  assert r.status_code == 200
  data = r.json()
  assert "flows" in data
  assert len(data["flows"]) == 1
