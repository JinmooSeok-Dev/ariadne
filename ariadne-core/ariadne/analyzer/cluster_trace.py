"""Cluster topology 기반 trace + group communication 분석.

src/dst는 'host_id::component_id' 형식.
같은 호스트면 단일 호스트 trace로 위임, 다른 호스트면 src 호스트 내부 → fabric →
dst 호스트 내부로 분할 trace한다.

group trace의 통신 패턴은 일반화된 명칭만 사용:
  one_to_many   — 1 src → N dst (broadcast 형태)
  many_to_one   — N src → 1 dst (gather 형태)
  all_to_all    — N×N 모든 페어
  pairwise      — len(src)==len(dst)인 pair-wise

ariadne는 이 패턴이 어떤 collective(all-reduce, all-gather 등)에 매핑되는지에
대해 어떤 가정도 하지 않는다. 매핑은 소비자 측에서 처리.
"""

from itertools import product

from pydantic import BaseModel, Field

from ariadne.analyzer.trace import DEFAULT_PARAMS, TraceResult, trace_path
from ariadne.cluster.links import InterHostLink
from ariadne.model.cluster import ClusterTopology
from ariadne.model.types import SystemTopology

_INTER_HOST_LATENCY_NS_BY_TYPE = {
  "ethernet": 50_000,    # TCP/IP. 1 GbE round trip ~50us 정도
  "rdma": 5_000,         # RoCE
  "infiniband": 1_500,
}


class ClusterTraceResult(BaseModel):
  source: str
  destination: str
  same_host: bool
  source_name: str = ""
  destination_name: str = ""
  e2e_bandwidth_gbps: float = 0.0
  e2e_latency_ns: float = 0.0
  bottleneck: str = ""
  segments: list[dict] = Field(default_factory=list)


class GroupTraceResult(BaseModel):
  pattern: str
  src_ids: list[str]
  dst_ids: list[str]
  pair_results: list[ClusterTraceResult] = Field(default_factory=list)
  aggregate_min_bandwidth_gbps: float = 0.0  # 페어 중 최소 BW (bottleneck)
  aggregate_max_latency_ns: float = 0.0      # 페어 중 최대 latency
  total_pairs: int = 0


def trace_cluster(
  cluster: ClusterTopology,
  src_full_id: str,
  dst_full_id: str,
  params: dict | None = None,
) -> ClusterTraceResult:
  """src/dst가 'host_id::component_id' 형식.

  - 같은 호스트: trace_path(host_topo, src_comp, dst_comp)에 위임
  - 다른 호스트: src 측 component → src 호스트의 NIC → inter-host link → dst 호스트의 NIC → dst component
  """
  src_parts = cluster.find_component(src_full_id)
  dst_parts = cluster.find_component(dst_full_id)
  if not src_parts or not dst_parts:
    return ClusterTraceResult(
      source=src_full_id,
      destination=dst_full_id,
      same_host=False,
    )
  src_host, src_comp = src_parts
  dst_host, dst_comp = dst_parts

  if src_host == dst_host:
    inner = trace_path(cluster.hosts[src_host], src_comp, dst_comp, params=params)
    return _wrap_single_host(src_full_id, dst_full_id, inner)

  return _trace_cross_host(
    cluster, src_host, src_comp, dst_host, dst_comp,
    src_full_id, dst_full_id, params,
  )


def _wrap_single_host(src_full: str, dst_full: str, inner: TraceResult) -> ClusterTraceResult:
  return ClusterTraceResult(
    source=src_full,
    destination=dst_full,
    same_host=True,
    source_name=inner.source_name,
    destination_name=inner.destination_name,
    e2e_bandwidth_gbps=inner.e2e_bandwidth_gbps,
    e2e_latency_ns=inner.e2e_latency_ns,
    bottleneck=inner.bottleneck,
    segments=inner.segments,
  )


def _trace_cross_host(
  cluster: ClusterTopology,
  src_host: str, src_comp: str,
  dst_host: str, dst_comp: str,
  src_full: str, dst_full: str,
  params: dict | None,
) -> ClusterTraceResult:
  """다른 호스트 간 trace. NIC 브릿지를 자동으로 선택."""
  link, src_nic_comp, dst_nic_comp = _select_inter_host_path(
    cluster, src_host, dst_host,
  )
  if not link:
    return ClusterTraceResult(
      source=src_full,
      destination=dst_full,
      same_host=False,
      bottleneck="no inter-host link found",
    )

  src_topo = cluster.hosts[src_host]
  dst_topo = cluster.hosts[dst_host]
  src_inner = trace_path(src_topo, src_comp, src_nic_comp, params=params)
  dst_inner = trace_path(dst_topo, dst_nic_comp, dst_comp, params=params)

  inter_segment = {
    "from": f"{src_host}::{src_nic_comp}",
    "to": f"{dst_host}::{dst_nic_comp}",
    "from_name": f"{src_host} NIC {link.from_iface}",
    "to_name": f"{dst_host} NIC {link.to_iface}",
    "link_type": link.type,
    "theoretical_bw_gbps": link.bandwidth_gbps,
    "effective_bw_gbps": link.bandwidth_gbps,  # 외부 fabric 효율은 1차에서 1.0
    "latency_ns": link.latency_ns or _INTER_HOST_LATENCY_NS_BY_TYPE.get(link.type, 100_000),
    "fabric": link.fabric,
  }

  segments = []
  segments.extend(_prefix_segments(src_inner.segments, src_host))
  segments.append(inter_segment)
  segments.extend(_prefix_segments(dst_inner.segments, dst_host))

  bw_candidates = [s["effective_bw_gbps"] for s in segments
                   if s.get("effective_bw_gbps") and s["effective_bw_gbps"] > 0]
  e2e_bw = min(bw_candidates) if bw_candidates else 0.0
  e2e_latency = sum(s.get("latency_ns", 0) for s in segments)

  bottleneck = ""
  if bw_candidates:
    min_bw = min(bw_candidates)
    for s in segments:
      if s.get("effective_bw_gbps") == min_bw:
        bottleneck = f"{s['from_name']} → {s['to_name']}"
        break

  return ClusterTraceResult(
    source=src_full,
    destination=dst_full,
    same_host=False,
    source_name=src_inner.source_name,
    destination_name=dst_inner.destination_name,
    e2e_bandwidth_gbps=e2e_bw,
    e2e_latency_ns=e2e_latency,
    bottleneck=bottleneck,
    segments=segments,
  )


def _prefix_segments(segments: list[dict], host_id: str) -> list[dict]:
  """단일 호스트 trace segment의 from/to에 host_id prefix 부여."""
  out = []
  for s in segments:
    s2 = dict(s)
    s2["from"] = f"{host_id}::{s.get('from', '')}"
    s2["to"] = f"{host_id}::{s.get('to', '')}"
    s2["from_name"] = f"{host_id}/{s.get('from_name', '')}"
    s2["to_name"] = f"{host_id}/{s.get('to_name', '')}"
    out.append(s2)
  return out


def _select_inter_host_path(
  cluster: ClusterTopology, src_host: str, dst_host: str,
) -> tuple[InterHostLink | None, str, str]:
  """src_host ↔ dst_host inter-host link 중 가장 좋은 것 + 양쪽 NIC component ID."""
  candidates = [
    link for link in cluster.inter_host_links
    if {link.from_host, link.to_host} == {src_host, dst_host}
  ]
  if not candidates:
    return None, "", ""

  # 우선순위: infiniband > rdma > ethernet, 그 다음 BW 큰 것
  type_rank = {"infiniband": 0, "rdma": 1, "ethernet": 2}
  candidates.sort(key=lambda link: (type_rank.get(link.type, 9), -link.bandwidth_gbps))
  link = candidates[0]

  src_nic_comp = _resolve_nic_component(cluster.hosts[src_host],
                                          link.from_iface if link.from_host == src_host else link.to_iface)
  dst_nic_comp = _resolve_nic_component(cluster.hosts[dst_host],
                                          link.to_iface if link.to_host == dst_host else link.from_iface)
  return link, src_nic_comp, dst_nic_comp


def _resolve_nic_component(topo: SystemTopology, iface_name: str) -> str:
  """NIC interface name → 그 NIC의 PCIe component ID."""
  for nic in topo.network_interfaces:
    name = nic.get("name", "")
    # IB는 'mlx5_0.p1' 같은 가상 이름 — 실제 device 이름만 비교
    base_name = iface_name.split(".")[0] if "." in iface_name else iface_name
    if name == base_name:
      bdf = nic.get("pci_bdf")
      if bdf:
        return f"pcie_{bdf}"
  # 이름 매칭 실패 시 첫 NIC component로 fallback
  for c in topo.components:
    if c.type.value == "nic":
      return c.id
  return ""


def trace_group(
  cluster: ClusterTopology,
  src_ids: list[str],
  dst_ids: list[str],
  pattern: str = "all_to_all",
  params: dict | None = None,
) -> GroupTraceResult:
  """그룹 간 통신 비용을 페어별로 계산.

  src_ids / dst_ids는 host_id 또는 'host_id::component_id'를 받는다.
  host_id만 주면 그 호스트의 첫 GPU(없으면 첫 NIC)로 자동 매핑.
  """
  src_resolved = [_resolve_member(cluster, m) for m in src_ids]
  dst_resolved = [_resolve_member(cluster, m) for m in dst_ids]
  src_resolved = [m for m in src_resolved if m]
  dst_resolved = [m for m in dst_resolved if m]

  if pattern == "pairwise":
    if len(src_resolved) != len(dst_resolved):
      raise ValueError(
        f"pairwise pattern requires equal length: src={len(src_resolved)}, dst={len(dst_resolved)}"
      )
    pairs = list(zip(src_resolved, dst_resolved))
  elif pattern == "one_to_many":
    if len(src_resolved) != 1:
      raise ValueError(f"one_to_many requires exactly 1 src, got {len(src_resolved)}")
    pairs = [(src_resolved[0], d) for d in dst_resolved]
  elif pattern == "many_to_one":
    if len(dst_resolved) != 1:
      raise ValueError(f"many_to_one requires exactly 1 dst, got {len(dst_resolved)}")
    pairs = [(s, dst_resolved[0]) for s in src_resolved]
  elif pattern == "all_to_all":
    pairs = [(s, d) for s, d in product(src_resolved, dst_resolved) if s != d]
  else:
    raise ValueError(f"unknown pattern: {pattern}. one_to_many|many_to_one|all_to_all|pairwise")

  results = [trace_cluster(cluster, s, d, params=params) for s, d in pairs]

  bws = [r.e2e_bandwidth_gbps for r in results if r.e2e_bandwidth_gbps > 0]
  latencies = [r.e2e_latency_ns for r in results if r.e2e_latency_ns > 0]

  return GroupTraceResult(
    pattern=pattern,
    src_ids=src_ids,
    dst_ids=dst_ids,
    pair_results=results,
    aggregate_min_bandwidth_gbps=min(bws) if bws else 0.0,
    aggregate_max_latency_ns=max(latencies) if latencies else 0.0,
    total_pairs=len(pairs),
  )


def _resolve_member(cluster: ClusterTopology, member: str) -> str:
  """member가 host_id인지 host_id::component_id인지 판별 후 정규화.

  host_id만 있으면 그 호스트의 첫 GPU 컴포넌트 (없으면 첫 NIC)를 자동 선택.
  """
  if "::" in member:
    return member
  if member not in cluster.hosts:
    return ""
  topo = cluster.hosts[member]
  for c in topo.components:
    if c.type.value == "gpu":
      return f"{member}::{c.id}"
  for c in topo.components:
    if c.type.value == "nic":
      return f"{member}::{c.id}"
  return ""
