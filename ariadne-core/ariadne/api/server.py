"""FastAPI 서버 — 토폴로지 API + Web UI serving."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ariadne.analyzer.cluster_trace import trace_cluster, trace_group
from ariadne.analyzer.safety import analyze_sriov_safety
from ariadne.analyzer.simulation import FlowSpec, simulate_flows
from ariadne.analyzer.trace import trace_group_in_host, trace_path
from ariadne.analyzer.transfer import list_transfer_modes
from ariadne.model.settings import Settings, what_if_trace
from ariadne.cluster.inventory import parse_inventory_dict
from ariadne.cluster.remote import build_cluster_topology
from ariadne.collector.iommu import collect_iommu_context
from ariadne.model.cluster import ClusterTopology
from ariadne.model.topology import build_topology
from ariadne.model.types import SystemTopology

TEMPLATES_DIR = Path(__file__).parent.parent / "web" / "templates"
STATIC_DIR = Path(__file__).parent.parent / "web" / "static"

app = FastAPI(title="Ariadne", description="System topology E2E data flow tracer")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_cached_topo: SystemTopology | None = None


def _get_topology() -> SystemTopology:
  global _cached_topo
  if _cached_topo is None:
    _cached_topo = build_topology()
  return _cached_topo


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
  return templates.TemplateResponse("index.html", {"request": request})


@app.get("/cluster", response_class=HTMLResponse)
async def cluster_page(request: Request):
  return templates.TemplateResponse("cluster.html", {"request": request})


@app.get("/api/topology")
async def get_topology():
  topo = _get_topology()
  return topo.model_dump()


@app.get("/api/topology/graph")
async def get_topology_graph():
  """일반 노드 + edge 트리. CPU/Cache/Memory + PCIe 모든 컴포넌트 표시."""
  topo = _get_topology()

  nodes = []
  visible_ids = set()
  for comp in topo.components:
    visible_ids.add(comp.id)
    node_data = {
      "id": comp.id,
      "label": comp.name,
      "type": comp.type.value,
    }
    for k, v in comp.attrs.items():
      if v is not None and v != "" and v != -1:
        node_data[k] = v
    nodes.append({"data": node_data})

  edges = []
  seen = set()
  for link in topo.links:
    if link.source not in visible_ids or link.target not in visible_ids:
      continue
    # NUMA→NUMA (UPI) 링크는 트리에서 제외 (peer 관계, 부모-자식 아님)
    if link.type.value == "upi":
      continue
    key = f"{link.source}|{link.target}"
    if key in seen:
      continue
    seen.add(key)
    edge_data = {
      "id": key,
      "source": link.source,
      "target": link.target,
      "type": link.type.value,
    }
    if link.bandwidth_gbps:
      edge_data["bandwidth_gbps"] = link.bandwidth_gbps
      edge_data["label"] = f"{link.bandwidth_gbps} GB/s"
    if link.latency_ns:
      edge_data["latency_ns"] = link.latency_ns
    if link.attrs:
      edge_data.update({k: v for k, v in link.attrs.items() if v is not None})
    edges.append({"data": edge_data})

  # IOMMU 그룹: group_id → [component_id, ...]
  iommu_map = {}
  for comp in topo.components:
    ig = comp.attrs.get("iommu_group", -1)
    if ig >= 0:
      iommu_map.setdefault(ig, []).append(comp.id)

  iommu_ctx = collect_iommu_context()

  return {
    "nodes": nodes,
    "edges": edges,
    "iommu_groups": iommu_map,
    "iommu_context": iommu_ctx,
  }


@app.get("/api/trace")
async def api_trace(source: str, destination: str):
  topo = _get_topology()
  return trace_path(topo, source, destination).model_dump()


@app.post("/api/group-trace")
async def api_group_trace(body: dict):
  """단일 호스트 내 그룹 trace.

  Body: {"src_ids": [...], "dst_ids": [...], "pattern": "all_to_all"|...}
  pattern: one_to_many | many_to_one | all_to_all | pairwise
  """
  topo = _get_topology()
  src_ids = body.get("src_ids") or []
  dst_ids = body.get("dst_ids") or []
  pattern = body.get("pattern", "all_to_all")
  try:
    result = trace_group_in_host(topo, src_ids, dst_ids, pattern=pattern)
  except ValueError as e:
    return {"error": str(e)}, 400
  return result.model_dump()


@app.post("/api/topology/reload")
async def reload_topology():
  global _cached_topo
  _cached_topo = build_topology()
  return {"status": "ok", "components": len(_cached_topo.components)}


@app.get("/api/transfer-modes")
async def api_transfer_modes(source: str, destination: str):
  topo = _get_topology()
  modes = list_transfer_modes(topo, source, destination)
  return {"source": source, "destination": destination,
          "modes": [m.model_dump() for m in modes]}


@app.get("/api/safety/sriov")
async def api_safety_sriov():
  topo = _get_topology()
  issues = analyze_sriov_safety(topo)
  return {"issues": [i.model_dump() for i in issues]}


@app.get("/api/vfio")
async def api_vfio():
  topo = _get_topology()
  return topo.vfio


@app.post("/api/whatif")
async def api_whatif(body: dict):
  """Body: {"source": ..., "destination": ..., "settings": {Settings fields}}"""
  topo = _get_topology()
  src = body.get("source")
  dst = body.get("destination")
  if not src or not dst:
    return {"error": "source and destination are required"}, 400
  try:
    settings = Settings(**(body.get("settings") or {}))
  except Exception as e:
    return {"error": f"invalid settings: {e}"}, 400
  result = what_if_trace(topo, src, dst, settings)
  return result.model_dump()


@app.post("/api/simulate")
async def api_simulate(spec: dict):
  """Body: {"flows": [{"flow_id": ..., "source": ..., "destination": ...,
                       "size_bytes": ..., "start_ns": 0}], "params": {...}}"""
  topo = _get_topology()
  flows_raw = spec.get("flows") or []
  params = spec.get("params")
  try:
    flows = [FlowSpec(**f) for f in flows_raw]
  except Exception as e:
    return {"error": f"invalid flow spec: {e}"}, 400
  result = simulate_flows(topo, flows, params=params)
  return result.model_dump()


_cached_clusters: dict[str, ClusterTopology] = {}


@app.post("/api/cluster")
async def api_cluster_build(spec: dict):
  """Inventory dict + cluster_id를 받아 SSH 원격 수집 후 ClusterTopology 캐싱.

  Body 예시: {"cluster_id": "lmtune-prod-a", "inventory": {"all": {"hosts": {...}}}}
  """
  cluster_id = spec.get("cluster_id")
  inventory = spec.get("inventory")
  if not cluster_id or not inventory:
    return {"error": "cluster_id and inventory are required"}, 400

  cluster_spec = parse_inventory_dict(inventory, cluster_id=cluster_id)
  cluster = await build_cluster_topology(cluster_spec)
  _cached_clusters[cluster_id] = cluster
  return cluster.model_dump()


@app.post("/api/cluster/load")
async def api_cluster_load(spec: dict):
  """저장된 cluster.json을 그대로 받아 캐시에 등록 (SSH 재수집 없이).

  Body는 ClusterTopology JSON 자체 (cluster_id 포함). 또는
  {"cluster_id": "...", "cluster": {...}} 형태도 허용.
  """
  payload = spec.get("cluster") if "cluster" in spec else spec
  if not isinstance(payload, dict):
    return {"error": "expected ClusterTopology JSON object"}, 400
  try:
    cluster = ClusterTopology.model_validate(payload)
  except Exception as e:
    return {"error": f"invalid ClusterTopology: {e}"}, 400
  cid = spec.get("cluster_id") or cluster.cluster_id
  cluster.cluster_id = cid
  _cached_clusters[cid] = cluster
  return cluster.model_dump()


@app.get("/api/cluster/{cluster_id}")
async def api_cluster_get(cluster_id: str):
  cluster = _cached_clusters.get(cluster_id)
  if not cluster:
    return {"error": f"cluster '{cluster_id}' not found. POST /api/cluster first"}, 404
  return cluster.model_dump()


@app.get("/api/cluster/{cluster_id}/trace")
async def api_cluster_trace(cluster_id: str, source: str, destination: str):
  cluster = _cached_clusters.get(cluster_id)
  if not cluster:
    return {"error": f"cluster '{cluster_id}' not found"}, 404
  return trace_cluster(cluster, source, destination).model_dump()


@app.post("/api/cluster/{cluster_id}/group-trace")
async def api_cluster_group_trace(cluster_id: str, body: dict):
  """Body: {"src_ids": [...], "dst_ids": [...], "pattern": "all_to_all"|"one_to_many"|...}"""
  cluster = _cached_clusters.get(cluster_id)
  if not cluster:
    return {"error": f"cluster '{cluster_id}' not found"}, 404
  src_ids = body.get("src_ids") or []
  dst_ids = body.get("dst_ids") or []
  pattern = body.get("pattern", "all_to_all")
  try:
    result = trace_group(cluster, src_ids, dst_ids, pattern=pattern)
  except ValueError as e:
    return {"error": str(e)}, 400
  return result.model_dump()
