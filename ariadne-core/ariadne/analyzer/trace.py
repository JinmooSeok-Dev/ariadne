"""E2E 경로 추적 및 BW/latency 분석."""

import networkx as nx

from ariadne.model.types import SystemTopology, ComponentType, LinkType
from ariadne.model.topology import to_networkx
from ariadne.collector.pcie import calc_pcie_bandwidth


# 기본 모델 파라미터
DEFAULT_PARAMS = {
  "pcie_efficiency": 0.90,
  "iommu_latency_ns": 0,
  "numa_remote_latency_ns": 40,
  "internal_latency_ns": 20,
  "pcie_link_latency_ns": 100,
  "memory_latency_ns": 80,
}


class TraceResult:
  def __init__(self):
    self.source: str = ""
    self.destination: str = ""
    self.source_name: str = ""
    self.destination_name: str = ""
    self.path: list[str] = []
    self.segments: list[dict] = []
    self.e2e_bandwidth_gbps: float = 0.0
    self.e2e_latency_ns: float = 0.0
    self.bottleneck: str = ""
    self.same_numa: bool = True


def trace_path(
  topo: SystemTopology,
  source_id: str,
  dest_id: str,
  params: dict | None = None,
) -> TraceResult:
  """source에서 destination까지의 E2E 경로를 추적하고 BW/latency를 계산."""
  p = {**DEFAULT_PARAMS, **(params or {})}
  g = to_networkx(topo)
  ug = g.to_undirected()

  result = TraceResult()
  result.source = source_id
  result.destination = dest_id
  result.source_name = _get_component_name(topo, source_id)
  result.destination_name = _get_component_name(topo, dest_id)

  try:
    path = nx.shortest_path(ug, source_id, dest_id)
  except (nx.NetworkXNoPath, nx.NodeNotFound):
    return result

  result.path = path
  result.same_numa = _check_same_numa(topo, source_id, dest_id)

  min_bw = float("inf")
  total_latency = 0.0
  bottleneck_seg = ""

  for i in range(len(path) - 1):
    src, tgt = path[i], path[i + 1]
    edge = _get_edge_data(g, src, tgt)
    src_node = _get_node_data(g, src)
    tgt_node = _get_node_data(g, tgt)

    seg = {
      "from": src,
      "to": tgt,
      "from_name": src_node.get("name", src),
      "to_name": tgt_node.get("name", tgt),
      "link_type": edge.get("type", ""),
      "theoretical_bw_gbps": None,
      "effective_bw_gbps": None,
      "latency_ns": 0.0,
    }

    link_type = edge.get("type", "")

    if link_type == LinkType.PCIE.value or link_type == LinkType.PCIE:
      bw = edge.get("bandwidth_gbps")
      if bw and bw > 0:
        eff_bw = round(bw * p["pcie_efficiency"], 1)
        seg["theoretical_bw_gbps"] = bw
        seg["effective_bw_gbps"] = eff_bw
        if eff_bw < min_bw:
          min_bw = eff_bw
          bottleneck_seg = f"{seg['from_name']} → {seg['to_name']}"
      seg["latency_ns"] = p["pcie_link_latency_ns"]

    elif link_type == LinkType.MEMORY.value or link_type == LinkType.MEMORY:
      bw = edge.get("bandwidth_gbps")
      if bw and bw > 0:
        seg["theoretical_bw_gbps"] = bw
        seg["effective_bw_gbps"] = round(bw * 0.75, 1)
        if seg["effective_bw_gbps"] < min_bw:
          min_bw = seg["effective_bw_gbps"]
          bottleneck_seg = f"{seg['from_name']} → {seg['to_name']}"
      seg["latency_ns"] = p["memory_latency_ns"]

    elif link_type == LinkType.UPI.value or link_type == LinkType.UPI:
      seg["latency_ns"] = p["numa_remote_latency_ns"]

    else:
      seg["latency_ns"] = p["internal_latency_ns"]

    total_latency += seg["latency_ns"]
    result.segments.append(seg)

  if p["iommu_latency_ns"] > 0:
    total_latency += p["iommu_latency_ns"]

  if not result.same_numa:
    total_latency += p["numa_remote_latency_ns"]

  result.e2e_bandwidth_gbps = min_bw if min_bw < float("inf") else 0.0
  result.e2e_latency_ns = total_latency
  result.bottleneck = bottleneck_seg

  return result


def _get_component_name(topo: SystemTopology, comp_id: str) -> str:
  for c in topo.components:
    if c.id == comp_id:
      return c.name
  return comp_id


def _get_edge_data(g: nx.DiGraph, src: str, tgt: str) -> dict:
  if g.has_edge(src, tgt):
    return dict(g.edges[src, tgt])
  if g.has_edge(tgt, src):
    return dict(g.edges[tgt, src])
  return {}


def _get_node_data(g: nx.DiGraph, node: str) -> dict:
  if node in g.nodes:
    return dict(g.nodes[node])
  return {}


def _check_same_numa(topo: SystemTopology, src: str, dst: str) -> bool:
  src_numa = _find_numa_for_component(topo, src)
  dst_numa = _find_numa_for_component(topo, dst)
  if src_numa is None or dst_numa is None:
    return True
  return src_numa == dst_numa


def _find_numa_for_component(topo: SystemTopology, comp_id: str) -> int | None:
  for dev in topo.pci_devices:
    if f"pcie_{dev.bdf}" == comp_id:
      if dev.numa_node >= 0:
        return dev.numa_node
      if topo.numa_nodes:
        return topo.numa_nodes[0].node_id
  if comp_id.startswith("numa_"):
    try:
      return int(comp_id.split("_")[1])
    except (IndexError, ValueError):
      pass
  if comp_id.startswith("mc_") or comp_id.startswith("dram_"):
    try:
      return int(comp_id.split("_")[1])
    except (IndexError, ValueError):
      pass
  return None
