"""FastAPI 서버 — 토폴로지 API + Web UI serving."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ariadne.model.topology import build_topology
from ariadne.model.types import SystemTopology
from ariadne.analyzer.trace import trace_path

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
    # NUMA→NUMA (UPI) 링크는 트리 edge에서 제외 (peer 관계)
    # cross_links로 별도 전달
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

  # Cross-NUMA 링크 (UPI) — MC 간 연결로 변환
  cross_links = []
  for link in topo.links:
    if link.type.value == "upi":
      # NUMA ID에서 MC ID로 변환
      src_mc = link.source.replace("numa_", "mc_")
      tgt_mc = link.target.replace("numa_", "mc_")
      if src_mc in visible_ids and tgt_mc in visible_ids:
        cross_links.append({
          "source": src_mc,
          "target": tgt_mc,
          "type": "upi",
          "distance": link.attrs.get("distance"),
        })

  # NUMA distance matrix
  numa_distances = {}
  for node in topo.numa_nodes:
    numa_distances[node.node_id] = node.distances

  return {"nodes": nodes, "edges": edges, "cross_links": cross_links, "numa_distances": numa_distances}


@app.get("/api/trace")
async def api_trace(source: str, destination: str):
  topo = _get_topology()
  result = trace_path(topo, source, destination)
  return {
    "source": result.source,
    "destination": result.destination,
    "source_name": result.source_name,
    "destination_name": result.destination_name,
    "path": result.path,
    "segments": result.segments,
    "e2e_bandwidth_gbps": result.e2e_bandwidth_gbps,
    "e2e_latency_ns": result.e2e_latency_ns,
    "bottleneck": result.bottleneck,
    "same_numa": result.same_numa,
  }


@app.post("/api/topology/reload")
async def reload_topology():
  global _cached_topo
  _cached_topo = build_topology()
  return {"status": "ok", "components": len(_cached_topo.components)}
