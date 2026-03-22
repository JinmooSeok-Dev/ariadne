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
  """D3.js용 노드/링크 형식으로 반환."""
  topo = _get_topology()

  skip_types = {"cpu_core", "cache", "dram"}
  nodes = []
  for comp in topo.components:
    if comp.type.value in skip_types:
      continue
    node = {
      "id": comp.id,
      "name": comp.name,
      "type": comp.type.value,
      "attrs": comp.attrs,
    }
    nodes.append(node)

  node_ids = {n["id"] for n in nodes}
  links = []
  for link in topo.links:
    if link.source in node_ids and link.target in node_ids:
      links.append({
        "source": link.source,
        "target": link.target,
        "type": link.type.value,
        "bandwidth_gbps": link.bandwidth_gbps,
        "latency_ns": link.latency_ns,
        "attrs": link.attrs,
      })

  return {"nodes": nodes, "links": links}


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
