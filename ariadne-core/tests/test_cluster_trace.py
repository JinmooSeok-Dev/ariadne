"""ClusterTopology + cluster trace + group trace 테스트."""

import pytest

from ariadne.analyzer.cluster_trace import (
  GroupTraceResult,
  trace_cluster,
  trace_group,
)
from ariadne.cluster.links import InterHostLink
from ariadne.model.cluster import ClusterTopology
from ariadne.model.types import (
  Component,
  ComponentType,
  Link,
  LinkType,
  PCIDevice,
  SystemTopology,
)


def _host_with_gpu_and_nic(gpu_bdf: str, nic_bdf: str, nic_name: str = "eth0",
                             nic_ip: str = "10.0.0.1", numa: int = 0) -> SystemTopology:
  return SystemTopology(
    components=[
      Component(id=f"pcie_{gpu_bdf}", type=ComponentType.GPU, name="GPU",
                attrs={"bdf": gpu_bdf}),
      Component(id=f"pcie_{nic_bdf}", type=ComponentType.NIC, name="NIC",
                attrs={"bdf": nic_bdf}),
    ],
    pci_devices=[
      PCIDevice(bdf=gpu_bdf, component_type="gpu", numa_node=numa),
      PCIDevice(bdf=nic_bdf, component_type="nic", numa_node=numa),
    ],
    links=[
      # GPU와 NIC는 같은 root complex 가정 — 직접 PCIe link
      Link(source=f"pcie_{gpu_bdf}", target=f"pcie_{nic_bdf}",
           type=LinkType.PCIE, bandwidth_gbps=64.0),
    ],
    network_interfaces=[
      {"name": nic_name, "pci_bdf": nic_bdf,
       "ip_addresses": [f"{nic_ip}/24"], "link_speed_mbps": 100000,
       "rdma_device": "mlx5_0"},
    ],
  )


def _two_host_cluster() -> ClusterTopology:
  h1 = _host_with_gpu_and_nic("0000:01:00.0", "0000:5e:00.0", "eth0", "10.0.0.11")
  h2 = _host_with_gpu_and_nic("0000:02:00.0", "0000:5f:00.0", "eth0", "10.0.0.12")
  return ClusterTopology(
    cluster_id="test",
    hosts={"h1": h1, "h2": h2},
    inter_host_links=[
      InterHostLink(
        from_host="h1", to_host="h2",
        from_iface="eth0", to_iface="eth0",
        type="rdma", bandwidth_gbps=100.0,
        fabric="10.0.0.0/24",
      ),
    ],
    groups={"workers": ["h1", "h2"]},
  )


def test_cluster_topology_find_component():
  cluster = _two_host_cluster()
  assert cluster.find_component("h1::pcie_0000:01:00.0") == ("h1", "pcie_0000:01:00.0")
  assert cluster.find_component("h99::x") is None
  assert cluster.find_component("invalid") is None


def test_trace_same_host_delegates_to_single_host_trace():
  cluster = _two_host_cluster()
  result = trace_cluster(cluster, "h1::pcie_0000:01:00.0", "h1::pcie_0000:5e:00.0")
  assert result.same_host is True
  assert result.e2e_bandwidth_gbps > 0


def test_trace_cross_host_uses_inter_host_link():
  cluster = _two_host_cluster()
  result = trace_cluster(cluster, "h1::pcie_0000:01:00.0", "h2::pcie_0000:02:00.0")
  assert result.same_host is False
  # segment 중 inter-host link 포함 확인
  link_types = [s.get("link_type") for s in result.segments]
  assert "rdma" in link_types
  # E2E latency는 inter-host latency가 가장 큼
  assert result.e2e_latency_ns > 0


def test_trace_cross_host_no_inter_host_link():
  """두 호스트 사이 link 정보 없으면 적절한 에러 메시지."""
  h1 = _host_with_gpu_and_nic("0000:01:00.0", "0000:5e:00.0")
  h2 = _host_with_gpu_and_nic("0000:02:00.0", "0000:5f:00.0")
  cluster = ClusterTopology(
    cluster_id="test", hosts={"h1": h1, "h2": h2}, inter_host_links=[],
  )
  result = trace_cluster(cluster, "h1::pcie_0000:01:00.0", "h2::pcie_0000:02:00.0")
  assert result.same_host is False
  assert "no inter-host link" in result.bottleneck


def test_group_trace_all_to_all():
  cluster = _two_host_cluster()
  result = trace_group(cluster, ["h1", "h2"], ["h1", "h2"], pattern="all_to_all")
  assert isinstance(result, GroupTraceResult)
  # all_to_all에서 같은 host 페어는 제외 → 2 페어 (h1→h2, h2→h1)
  assert result.total_pairs == 2
  assert result.aggregate_min_bandwidth_gbps > 0


def test_group_trace_one_to_many():
  cluster = _two_host_cluster()
  result = trace_group(cluster, ["h1"], ["h2"], pattern="one_to_many")
  assert result.total_pairs == 1
  assert result.pattern == "one_to_many"


def test_group_trace_pairwise_length_mismatch_raises():
  cluster = _two_host_cluster()
  with pytest.raises(ValueError, match="pairwise"):
    trace_group(cluster, ["h1"], ["h1", "h2"], pattern="pairwise")


def test_group_trace_unknown_pattern_raises():
  cluster = _two_host_cluster()
  with pytest.raises(ValueError, match="unknown pattern"):
    trace_group(cluster, ["h1"], ["h2"], pattern="all_reduce")


def test_group_trace_resolves_host_id_to_first_gpu():
  """member가 host_id만 있으면 첫 GPU 컴포넌트로 자동 매핑."""
  cluster = _two_host_cluster()
  result = trace_group(cluster, ["h1"], ["h2"], pattern="one_to_many")
  pair = result.pair_results[0]
  assert "pcie_0000:01:00.0" in pair.source  # h1의 GPU
  assert "pcie_0000:02:00.0" in pair.destination  # h2의 GPU


def test_cluster_topology_serialization():
  """ClusterTopology가 JSON으로 round-trip 가능."""
  cluster = _two_host_cluster()
  payload = cluster.model_dump_json()
  restored = ClusterTopology.model_validate_json(payload)
  assert restored.cluster_id == "test"
  assert set(restored.hosts.keys()) == {"h1", "h2"}
  assert len(restored.inter_host_links) == 1
