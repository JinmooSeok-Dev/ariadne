"""Analyzer (Trace) 테스트."""

from ariadne.model.types import (
  SystemTopology, NUMANode, CPUCore, Component, ComponentType, Link, LinkType, PCIDevice,
)
from ariadne.analyzer.trace import trace_path


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
