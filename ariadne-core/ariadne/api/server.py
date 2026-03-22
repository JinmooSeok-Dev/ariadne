"""FastAPI 서버 — 토폴로지 API + Web UI serving."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ariadne.model.topology import build_topology
from ariadne.model.types import SystemTopology
from ariadne.analyzer.trace import trace_path

TEMPLATES_DIR = Path(__file__).parent.parent / "web" / "templates"

app = FastAPI(title="Ariadne", description="System topology E2E data flow tracer")
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
  """일반 노드 + edge 트리. 모든 디바이스 표시."""
  topo = _get_topology()

  skip_types = {"cpu_core", "cache", "dram"}

  nodes = []
  visible_ids = set()
  for comp in topo.components:
    if comp.type.value in skip_types:
      continue
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

  return {"nodes": nodes, "edges": edges}


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
