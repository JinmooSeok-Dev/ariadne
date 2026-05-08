"""Analyzer (Trace) 테스트."""

import pytest

from ariadne.model.types import (
  SystemTopology, NUMANode, CPUCore, Component, ComponentType, Link, LinkType, PCIDevice,
)
from ariadne.analyzer.trace import (
  HostGroupTraceResult,
  TraceResult,
  trace_group_in_host,
  trace_path,
)


def _make_simple_topology():
  """간단한 토폴로지: NUMA0 → RC → RP → GPU, NUMA0 → MC."""
  topo = SystemTopology(hostname="test")
  topo.numa_nodes = [NUMANode(node_id=0, cpu_list=[0, 1], memory_mb=16000)]
  topo.components = [
    Component(id="numa_0", type=ComponentType.NUMA_NODE, name="NUMA 0"),
    Component(id="rc_0", type=ComponentType.PCIE_ROOT_COMPLEX, name="RC"),
    Component(id="rp_0", type=ComponentType.PCIE_ROOT_PORT, name="RP 0"),
    Component(id="gpu_0", type=ComponentType.GPU, name="GPU 0"),
    Component(id="mc_0", type=ComponentType.MEMORY_CONTROLLER, name="MC 0"),
  ]
  topo.links = [
    Link(source="numa_0", target="rc_0", type=LinkType.INTERNAL),
    Link(source="numa_0", target="mc_0", type=LinkType.INTERNAL),
    Link(source="rc_0", target="rp_0", type=LinkType.INTERNAL),
    Link(source="rp_0", target="gpu_0", type=LinkType.PCIE, bandwidth_gbps=32.0),
  ]
  return topo


def test_trace_gpu_to_memory():
  topo = _make_simple_topology()
  result = trace_path(topo, "gpu_0", "mc_0")
  assert result.path
  assert len(result.path) > 2
  assert result.e2e_bandwidth_gbps > 0
  assert result.e2e_latency_ns > 0
  assert result.same_numa


def test_trace_no_path():
  topo = _make_simple_topology()
  result = trace_path(topo, "gpu_0", "nonexistent")
  assert result.path == []


def test_trace_segments():
  topo = _make_simple_topology()
  result = trace_path(topo, "gpu_0", "mc_0")
  assert len(result.segments) > 0
  for seg in result.segments:
    assert "from" in seg
    assert "to" in seg
    assert "latency_ns" in seg


def test_trace_bottleneck():
  topo = _make_simple_topology()
  result = trace_path(topo, "gpu_0", "mc_0")
  # PCIe link가 bottleneck이어야 함
  assert result.bottleneck


def test_trace_result_is_pydantic_model():
  """TraceResult는 BaseModel이어야 한다 — model_dump_json()으로 직렬화 보장."""
  topo = _make_simple_topology()
  result = trace_path(topo, "gpu_0", "mc_0")
  # Pydantic v2 BaseModel API
  payload = result.model_dump()
  assert payload["source"] == "gpu_0"
  assert payload["destination"] == "mc_0"
  assert "segments" in payload
  # JSON 직렬화도 가능해야 한다 (lmtune이 그대로 적재 가능)
  s = result.model_dump_json()
  assert '"source":"gpu_0"' in s.replace(" ", "")


def _make_dual_gpu_topology():
  """GPU 2개를 같은 RC 아래 두는 토폴로지."""
  topo = SystemTopology(hostname="test")
  topo.numa_nodes = [NUMANode(node_id=0, cpu_list=[0], memory_mb=16000)]
  topo.components = [
    Component(id="numa_0", type=ComponentType.NUMA_NODE, name="NUMA 0"),
    Component(id="rc_0", type=ComponentType.PCIE_ROOT_COMPLEX, name="RC"),
    Component(id="rp_0", type=ComponentType.PCIE_ROOT_PORT, name="RP 0"),
    Component(id="rp_1", type=ComponentType.PCIE_ROOT_PORT, name="RP 1"),
    Component(id="gpu_0", type=ComponentType.GPU, name="GPU 0"),
    Component(id="gpu_1", type=ComponentType.GPU, name="GPU 1"),
  ]
  topo.links = [
    Link(source="numa_0", target="rc_0", type=LinkType.INTERNAL),
    Link(source="rc_0", target="rp_0", type=LinkType.INTERNAL),
    Link(source="rc_0", target="rp_1", type=LinkType.INTERNAL),
    Link(source="rp_0", target="gpu_0", type=LinkType.PCIE, bandwidth_gbps=32.0),
    Link(source="rp_1", target="gpu_1", type=LinkType.PCIE, bandwidth_gbps=32.0),
  ]
  return topo


def test_group_trace_all_to_all():
  topo = _make_dual_gpu_topology()
  result = trace_group_in_host(topo, ["gpu_0", "gpu_1"], ["gpu_0", "gpu_1"], pattern="all_to_all")
  assert isinstance(result, HostGroupTraceResult)
  # all_to_all은 self pair 제외 — 2개 src × 2개 dst − 2개 self = 2 페어
  assert result.total_pairs == 2
  assert len(result.pair_results) == 2
  for pr in result.pair_results:
    assert isinstance(pr, TraceResult)
    assert pr.path  # 실제 경로가 있어야 함


def test_group_trace_one_to_many():
  topo = _make_dual_gpu_topology()
  result = trace_group_in_host(topo, ["gpu_0"], ["gpu_1"], pattern="one_to_many")
  assert result.total_pairs == 1
  assert result.aggregate_min_bandwidth_gbps > 0


def test_group_trace_pairwise_unequal_raises():
  topo = _make_dual_gpu_topology()
  with pytest.raises(ValueError, match="pairwise pattern requires equal length"):
    trace_group_in_host(topo, ["gpu_0", "gpu_1"], ["gpu_0"], pattern="pairwise")


def test_group_trace_unknown_pattern_raises():
  topo = _make_dual_gpu_topology()
  with pytest.raises(ValueError, match="unknown pattern"):
    trace_group_in_host(topo, ["gpu_0"], ["gpu_1"], pattern="all_reduce")
