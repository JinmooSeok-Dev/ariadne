"""API 서버 테스트."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
  from ariadne.api.server import app
  return TestClient(app)


def test_index(client):
  resp = client.get("/")
  assert resp.status_code == 200
  assert "Ariadne" in resp.text


def test_topology(client):
  resp = client.get("/api/topology")
  assert resp.status_code == 200
  data = resp.json()
  assert "hostname" in data
  assert "numa_nodes" in data
  assert "pci_devices" in data
  assert "components" in data
  assert "links" in data


def test_topology_graph(client):
  resp = client.get("/api/topology/graph")
  assert resp.status_code == 200
  data = resp.json()
  assert "nodes" in data
  assert "edges" in data
  assert len(data["nodes"]) > 0
  assert len(data["edges"]) > 0
  # 노드에 id, label, type이 있어야 함
  for node in data["nodes"]:
    assert "id" in node["data"]
    assert "label" in node["data"]
    assert "type" in node["data"]
  # edge에 source, target, type이 있어야 함
  for edge in data["edges"]:
    assert "source" in edge["data"]
    assert "target" in edge["data"]
    assert "type" in edge["data"]


def test_trace(client):
  # 먼저 그래프에서 traceable 노드 2개 찾기
  graph = client.get("/api/topology/graph").json()
  traceable = ["gpu", "npu", "nvme", "nic", "memory_controller", "pcie_endpoint"]
  nodes = [n for n in graph["nodes"] if n["data"]["type"] in traceable]

  if len(nodes) < 2:
    pytest.skip("traceable 노드가 2개 미만")

  src = nodes[0]["data"]["id"]
  dst = nodes[1]["data"]["id"]
  resp = client.get(f"/api/trace?source={src}&destination={dst}")
  assert resp.status_code == 200
  data = resp.json()
  assert "source" in data
  assert "destination" in data
  assert "path" in data
  assert "segments" in data
  assert "e2e_bandwidth_gbps" in data
  assert "e2e_latency_ns" in data


def test_reload(client):
  resp = client.post("/api/topology/reload")
  assert resp.status_code == 200
  assert resp.json()["status"] == "ok"
