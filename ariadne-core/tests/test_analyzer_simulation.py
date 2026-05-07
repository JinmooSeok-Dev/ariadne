"""DES 시뮬레이션 테스트 — 다중 flow 경합."""

from ariadne.analyzer.simulation import FlowSpec, simulate_flows
from ariadne.model.types import (
  Component,
  ComponentType,
  Link,
  LinkType,
  PCIDevice,
  SystemTopology,
)


def _simple_topo() -> SystemTopology:
  """GPU0 → MC0 → DRAM0 + GPU1 → MC0 → DRAM0 형태. 두 GPU가 같은 메모리 사용."""
  return SystemTopology(
    components=[
      Component(id="pcie_0000:01:00.0", type=ComponentType.GPU, name="GPU 0"),
      Component(id="pcie_0000:02:00.0", type=ComponentType.GPU, name="GPU 1"),
      Component(id="mc_0", type=ComponentType.MEMORY_CONTROLLER, name="MC 0"),
      Component(id="dram_0", type=ComponentType.DRAM, name="DRAM 0"),
    ],
    pci_devices=[
      PCIDevice(bdf="0000:01:00.0", component_type="gpu"),
      PCIDevice(bdf="0000:02:00.0", component_type="gpu"),
    ],
    links=[
      Link(source="pcie_0000:01:00.0", target="mc_0",
           type=LinkType.PCIE, bandwidth_gbps=64.0),
      Link(source="pcie_0000:02:00.0", target="mc_0",
           type=LinkType.PCIE, bandwidth_gbps=64.0),
      Link(source="mc_0", target="dram_0",
           type=LinkType.MEMORY, bandwidth_gbps=100.0),
    ],
  )


def test_single_flow_completes():
  topo = _simple_topo()
  flows = [FlowSpec(flow_id="f1", source="pcie_0000:01:00.0",
                   destination="dram_0", size_bytes=64 * 10**9)]  # 64 GB
  result = simulate_flows(topo, flows)
  assert len(result.flows) == 1
  r = result.flows[0]
  assert r.duration_ns > 0
  assert r.effective_bandwidth_gbps > 0


def test_two_flows_share_memory_link():
  """두 flow가 같은 MC→DRAM link에 동시 진입하면 BW를 나눠 가져 더 느려진다."""
  topo = _simple_topo()
  flows = [
    FlowSpec(flow_id="a", source="pcie_0000:01:00.0",
             destination="dram_0", size_bytes=10 * 10**9, start_ns=0),
    FlowSpec(flow_id="b", source="pcie_0000:02:00.0",
             destination="dram_0", size_bytes=10 * 10**9, start_ns=0),
  ]
  result = simulate_flows(topo, flows)
  assert len(result.flows) == 2
  # 같은 시작 시각이면 적어도 한 flow는 다른 flow와의 경합을 기록해야 함
  contended_any = any(len(f.contended_with) > 0 for f in result.flows)
  assert contended_any


def test_independent_paths_no_contention():
  """두 flow가 완전히 독립된 link만 사용하면 경합 없음 (정적 분석)."""
  topo = SystemTopology(
    components=[
      Component(id="g0", type=ComponentType.GPU, name="GPU 0"),
      Component(id="g1", type=ComponentType.GPU, name="GPU 1"),
      Component(id="mc0", type=ComponentType.MEMORY_CONTROLLER, name="MC 0"),
      Component(id="mc1", type=ComponentType.MEMORY_CONTROLLER, name="MC 1"),
      Component(id="d0", type=ComponentType.DRAM, name="DRAM 0"),
      Component(id="d1", type=ComponentType.DRAM, name="DRAM 1"),
    ],
    links=[
      Link(source="g0", target="mc0", type=LinkType.PCIE, bandwidth_gbps=64.0),
      Link(source="mc0", target="d0", type=LinkType.MEMORY, bandwidth_gbps=100.0),
      Link(source="g1", target="mc1", type=LinkType.PCIE, bandwidth_gbps=64.0),
      Link(source="mc1", target="d1", type=LinkType.MEMORY, bandwidth_gbps=100.0),
    ],
  )
  flows = [
    FlowSpec(flow_id="a", source="g0", destination="d0", size_bytes=10**6),
    FlowSpec(flow_id="b", source="g1", destination="d1", size_bytes=10**6),
  ]
  result = simulate_flows(topo, flows)
  for f in result.flows:
    assert f.contended_with == []


def test_link_utilization_recorded():
  topo = _simple_topo()
  flows = [FlowSpec(flow_id="f1", source="pcie_0000:01:00.0",
                   destination="dram_0", size_bytes=10**9, start_ns=0)]
  result = simulate_flows(topo, flows)
  assert len(result.link_utilization) > 0
  # 모든 link 점유 시간은 양수
  for k, busy_ns in result.link_utilization.items():
    assert busy_ns >= 0


def test_no_path_between_components_does_not_crash():
  topo = SystemTopology(
    components=[
      Component(id="a", type=ComponentType.GPU, name="A"),
      Component(id="b", type=ComponentType.GPU, name="B"),
    ],
    links=[],  # 연결 없음
  )
  flows = [FlowSpec(flow_id="f", source="a", destination="b", size_bytes=10**9)]
  result = simulate_flows(topo, flows)
  assert len(result.flows) == 1
  # path 없으면 즉시 종료
  assert result.flows[0].duration_ns == 0
