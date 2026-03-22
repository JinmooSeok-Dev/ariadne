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
  """Cytoscape.js용 노드/edge 데이터. Root Port를 숨기고 깔끔한 구조로."""
  topo = _get_topology()

  # 어떤 타입을 표시할지
  skip_comp_types = {"cpu_core", "cache", "dram"}

  # bus 0 직결 칩셋 디바이스 제외 (USB, SATA, Audio 등)
  chipset_direct = set()
  for dev in topo.pci_devices:
    if not dev.parent_bdf and dev.type_name not in ("Host Bridge", "PCI-to-PCI Bridge"):
      chipset_direct.add(f"pcie_{dev.bdf}")

  # Root Port 분석: 자식이 endpoint뿐인 RP는 숨김
  rp_ids = {c.id for c in topo.components if c.type.value == "pcie_root_port"}
  rp_to_parent = {}
  rp_to_children = {}
  for link in topo.links:
    if link.target in rp_ids:
      rp_to_parent[link.target] = link.source
    if link.source in rp_ids:
      rp_to_children.setdefault(link.source, []).append(link.target)

  hide_rps = set()
  for rp_id in rp_ids:
    children = rp_to_children.get(rp_id, [])
    # RP → RP 체인이 아닌 경우 (Switch가 아닌 경우) 숨김
    if not any(c in rp_ids for c in children):
      hide_rps.add(rp_id)

  # 노드 생성
  visible_ids = set()
  nodes = []
  for comp in topo.components:
    if comp.type.value in skip_comp_types:
      continue
    if comp.id in chipset_direct:
      continue
    if comp.id in hide_rps:
      continue
    visible_ids.add(comp.id)

    # NUMA compound node: endpoint의 parent로 사용
    parent = None
    if comp.type.value in ("socket", "memory_controller", "pcie_root_complex"):
      # NUMA node의 자식 찾기
      for link in topo.links:
        if link.target == comp.id:
          for numa_comp in topo.components:
            if numa_comp.id == link.source and numa_comp.type.value == "numa_node":
              parent = numa_comp.id
              break

    nodes.append({
      "data": {
        "id": comp.id,
        "label": comp.name,
        "type": comp.type.value,
        "parent": parent,
        **{k: v for k, v in comp.attrs.items() if v is not None and v != "" and v != -1},
      }
    })

  # NUMA 노드도 추가 (compound parent)
  for comp in topo.components:
    if comp.type.value == "numa_node":
      mem_gb = comp.attrs.get("memory_mb", 0) // 1024 if comp.attrs.get("memory_mb") else 0
      nodes.append({
        "data": {
          "id": comp.id,
          "label": f"{comp.name} ({mem_gb}GB)" if mem_gb else comp.name,
          "type": "numa_node",
        }
      })
      visible_ids.add(comp.id)

  # Edge 생성 — RP를 건너뛰고 직결
  edges = []
  seen_edges = set()
  for link in topo.links:
    src, tgt = link.source, link.target

    # 숨겨진 RP 건너뛰기
    if src in hide_rps:
      src = rp_to_parent.get(src, src)
    if tgt in hide_rps:
      continue

    if src not in visible_ids or tgt not in visible_ids:
      continue
    if src == tgt:
      continue

    edge_key = f"{src}|{tgt}"
    if edge_key in seen_edges:
      continue
    seen_edges.add(edge_key)

    edge_data = {
      "id": edge_key,
      "source": src,
      "target": tgt,
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
