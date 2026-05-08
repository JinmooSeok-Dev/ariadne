"""E2E 경로 추적 및 BW/latency 분석."""

import networkx as nx
from pydantic import BaseModel, Field

from ariadne.model.types import SystemTopology, ComponentType, ComponentPrefix as P, LinkType
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
  "nvlink_efficiency": 0.95,    # NVLink는 PCIe보다 효율 높음
  "nvlink_latency_ns": 30,      # GPU↔GPU NVLink (NVSwitch 없는 P2P 가정)
  "ucie_efficiency": 0.95,
  "ucie_latency_ns": 5,         # 칩렛 간 — 매우 짧음
}


class TraceResult(BaseModel):
  source: str = ""
  destination: str = ""
  source_name: str = ""
  destination_name: str = ""
  path: list[str] = Field(default_factory=list)
  segments: list[dict] = Field(default_factory=list)
  e2e_bandwidth_gbps: float = 0.0
  e2e_latency_ns: float = 0.0
  bottleneck: str = ""
  same_numa: bool = True


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

    elif link_type == LinkType.NVLINK.value or link_type == LinkType.NVLINK:
      bw = edge.get("bandwidth_gbps")
      if bw and bw > 0:
        eff_bw = round(bw * p["nvlink_efficiency"], 1)
        seg["theoretical_bw_gbps"] = bw
        seg["effective_bw_gbps"] = eff_bw
        if eff_bw < min_bw:
          min_bw = eff_bw
          bottleneck_seg = f"{seg['from_name']} → {seg['to_name']}"
      seg["latency_ns"] = p["nvlink_latency_ns"]

    elif link_type == LinkType.UCIE.value or link_type == LinkType.UCIE:
      bw = edge.get("bandwidth_gbps")
      if bw and bw > 0:
        eff_bw = round(bw * p["ucie_efficiency"], 1)
        seg["theoretical_bw_gbps"] = bw
        seg["effective_bw_gbps"] = eff_bw
        if eff_bw < min_bw:
          min_bw = eff_bw
          bottleneck_seg = f"{seg['from_name']} → {seg['to_name']}"
      seg["latency_ns"] = p["ucie_latency_ns"]

    else:
      # 링크에 명시적 latency가 있으면 우선 사용 (NUMA→Socket 등 조직적 링크는 0)
      explicit = edge.get("latency_ns")
      seg["latency_ns"] = explicit if explicit is not None else p["internal_latency_ns"]

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


class HostGroupTraceResult(BaseModel):
  """단일 호스트 내 group communication 비용. cluster 단위는 cluster_trace.GroupTraceResult."""
  pattern: str
  src_ids: list[str]
  dst_ids: list[str]
  pair_results: list[TraceResult] = Field(default_factory=list)
  aggregate_min_bandwidth_gbps: float = 0.0
  aggregate_max_latency_ns: float = 0.0
  total_pairs: int = 0


def trace_group_in_host(
  topo: SystemTopology,
  src_ids: list[str],
  dst_ids: list[str],
  pattern: str = "all_to_all",
  params: dict | None = None,
) -> HostGroupTraceResult:
  """단일 호스트 내 component 그룹 간 통신 비용을 페어별로 계산.

  pattern: one_to_many | many_to_one | all_to_all | pairwise
  ariadne는 collective(all-reduce 등) 명칭에 대한 가정 없이 일반화된 패턴만 노출.
  소비자(예: lmtune)가 측면에서 자체 도메인에 매핑한다.
  """
  from itertools import product as _product

  if pattern == "pairwise":
    if len(src_ids) != len(dst_ids):
      raise ValueError(
        f"pairwise pattern requires equal length: src={len(src_ids)}, dst={len(dst_ids)}"
      )
    pairs = list(zip(src_ids, dst_ids))
  elif pattern == "one_to_many":
    if len(src_ids) != 1:
      raise ValueError(f"one_to_many requires exactly 1 src, got {len(src_ids)}")
    pairs = [(src_ids[0], d) for d in dst_ids]
  elif pattern == "many_to_one":
    if len(dst_ids) != 1:
      raise ValueError(f"many_to_one requires exactly 1 dst, got {len(dst_ids)}")
    pairs = [(s, dst_ids[0]) for s in src_ids]
  elif pattern == "all_to_all":
    pairs = [(s, d) for s, d in _product(src_ids, dst_ids) if s != d]
  else:
    raise ValueError(f"unknown pattern: {pattern}. one_to_many|many_to_one|all_to_all|pairwise")

  results = [trace_path(topo, s, d, params=params) for s, d in pairs]

  bws = [r.e2e_bandwidth_gbps for r in results if r.e2e_bandwidth_gbps > 0]
  latencies = [r.e2e_latency_ns for r in results if r.e2e_latency_ns > 0]

  return HostGroupTraceResult(
    pattern=pattern,
    src_ids=src_ids,
    dst_ids=dst_ids,
    pair_results=results,
    aggregate_min_bandwidth_gbps=min(bws) if bws else 0.0,
    aggregate_max_latency_ns=max(latencies) if latencies else 0.0,
    total_pairs=len(pairs),
  )


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
    if f"{P.PCIE}{dev.bdf}" == comp_id:
      if dev.numa_node >= 0:
        return dev.numa_node
      if topo.numa_nodes:
        return topo.numa_nodes[0].node_id
  if comp_id.startswith(P.NUMA):
    try:
      return int(comp_id.split("_")[1])
    except (IndexError, ValueError):
      pass
  if comp_id.startswith(P.MC) or comp_id.startswith(P.DRAM):
    try:
      return int(comp_id.split("_")[1])
    except (IndexError, ValueError):
      pass
  return None
