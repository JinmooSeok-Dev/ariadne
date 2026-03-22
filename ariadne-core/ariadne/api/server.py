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
  """Cytoscape.js compound node 기반 계층 구조.

  계층:
    NUMA Node (compound)
      ├── Socket
      ├── Memory Controller
      └── Root Complex (compound)
          ├── [chipset device]       ← RC 직결 (bus 0)
          └── Root Port (compound)   ← 별도 bus
              ├── Endpoint
              └── Endpoint
  """
  topo = _get_topology()

  skip_types = {"cpu_core", "cache", "dram"}

  # NUMA → 자식 매핑
  numa_map = {}
  for link in topo.links:
    for comp in topo.components:
      if comp.type.value == "numa_node" and comp.id == link.source:
        numa_map[link.target] = comp.id

  # RC, RP, Endpoint 관계 구축
  rc_ids = {c.id for c in topo.components if c.type.value == "pcie_root_complex"}
  rp_ids = {c.id for c in topo.components if c.type.value == "pcie_root_port"}

  # parent_bdf → component id 매핑
  bdf_to_comp = {}
  for dev in topo.pci_devices:
    bdf_to_comp[dev.bdf] = f"pcie_{dev.bdf}"

  # 노드 생성
  nodes = []
  visible_ids = set()

  # NUMA compound parent
  for comp in topo.components:
    if comp.type.value == "numa_node":
      mem_gb = comp.attrs.get("memory_mb", 0) // 1024 if comp.attrs.get("memory_mb") else 0
      nodes.append({"data": {
        "id": comp.id,
        "label": f"{comp.name} ({mem_gb}GB)" if mem_gb else comp.name,
        "type": "numa_node",
      }})
      visible_ids.add(comp.id)

  # 나머지 컴포넌트
  for comp in topo.components:
    if comp.type.value in skip_types or comp.type.value == "numa_node":
      continue
    visible_ids.add(comp.id)

    # parent 결정
    parent = None
    if comp.type.value in ("socket", "memory_controller"):
      parent = numa_map.get(comp.id)
    elif comp.type.value == "pcie_root_complex":
      parent = numa_map.get(comp.id)
    elif comp.type.value == "pcie_root_port":
      # RP의 parent = RC
      for link in topo.links:
        if link.target == comp.id and link.source in rc_ids:
          parent = link.source
          break
      # RC의 parent가 없으면 NUMA 직결로 찾기
      if not parent:
        for link in topo.links:
          if link.target == comp.id:
            parent = link.source
            break
    else:
      # Endpoint: parent = RP (있으면) 또는 RC
      for dev in topo.pci_devices:
        if f"pcie_{dev.bdf}" == comp.id:
          if dev.parent_bdf:
            parent_comp_id = f"pcie_rp_{dev.parent_bdf}"
            if parent_comp_id in rp_ids:
              parent = parent_comp_id
              break
            # parent가 RP가 아니면 RC 직결
          # parent_bdf 없으면 RC 직결
          if not parent:
            for rc_id in rc_ids:
              parent = rc_id
              break
          break

    # RP에 bus 번호 표시
    label = comp.name
    if comp.type.value == "pcie_root_port":
      bdf = comp.attrs.get("bdf", "")
      # RP 하위 디바이스의 bus 번호 찾기
      child_buses = set()
      for dev in topo.pci_devices:
        if dev.parent_bdf == bdf:
          child_buses.add(dev.bdf.split(":")[1])
      bus_str = ",".join(sorted(child_buses))
      label = f"RP {bdf}"
      if bus_str:
        label += f" [bus {bus_str}]"

    node_data = {
      "id": comp.id,
      "label": label,
      "type": comp.type.value,
    }
    if parent:
      node_data["parent"] = parent

    # 주요 속성 포함
    for k, v in comp.attrs.items():
      if v is not None and v != "" and v != -1:
        node_data[k] = v

    nodes.append({"data": node_data})

  # compound parent-child 관계 수집
  parent_child_pairs = set()
  for n in nodes:
    parent = n["data"].get("parent")
    if parent:
      parent_child_pairs.add((parent, n["data"]["id"]))
      parent_child_pairs.add((n["data"]["id"], parent))

  # Edge — compound 관계의 internal edge만 제외, PCIe edge는 유지
  edges = []
  seen = set()
  for link in topo.links:
    if link.source not in visible_ids or link.target not in visible_ids:
      continue
    # compound parent-child + internal type일 때만 제외
    if (link.source, link.target) in parent_child_pairs and link.type.value == "internal":
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
