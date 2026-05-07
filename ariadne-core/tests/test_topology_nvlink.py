"""NVLink을 토폴로지 그래프로 통합한 결과 테스트."""

from ariadne.analyzer.trace import trace_path
from ariadne.model.topology import _build_nvlink_links
from ariadne.model.types import (
  Component,
  ComponentType,
  Link,
  LinkType,
  SystemTopology,
)


def _topo_with_two_gpus() -> SystemTopology:
  """두 GPU + 각 GPU의 PCIe parent (root port) 만 있는 최소 토폴로지."""
  topo = SystemTopology(
    components=[
      Component(id="pcie_0000:01:00.0", type=ComponentType.GPU, name="GPU 0",
                attrs={"bdf": "0000:01:00.0"}),
      Component(id="pcie_0000:25:00.0", type=ComponentType.GPU, name="GPU 1",
                attrs={"bdf": "0000:25:00.0"}),
    ],
    links=[],
    nvlink={
      "gpus": {0: "0000:01:00.0", 1: "0000:25:00.0"},
      "connections": [{
        "gpu_a_index": 0,
        "gpu_b_index": 1,
        "gpu_a_bdf": "0000:01:00.0",
        "gpu_b_bdf": "0000:25:00.0",
        "link_count": 12,
        "topology_label": "NV12",
      }],
    },
  )
  return topo


def test_build_nvlink_links_creates_edge():
  topo = _topo_with_two_gpus()
  _build_nvlink_links(topo)
  nvlink_edges = [link for link in topo.links if link.type == LinkType.NVLINK]
  assert len(nvlink_edges) == 1
  e = nvlink_edges[0]
  assert e.source == "pcie_0000:01:00.0"
  assert e.target == "pcie_0000:25:00.0"
  # 12 links × 25 GB/s/link = 300 GB/s (per-link 추정값)
  assert e.bandwidth_gbps == 300.0
  assert e.attrs["link_count"] == 12
  assert e.attrs["topology_label"] == "NV12"


def test_build_nvlink_skips_unknown_components():
  """component map에 없는 BDF는 skip — query 실패 후 부분 데이터에도 안전."""
  topo = SystemTopology(
    components=[
      Component(id="pcie_0000:01:00.0", type=ComponentType.GPU, name="GPU 0"),
    ],  # GPU 1 없음
    nvlink={
      "connections": [{
        "gpu_a_index": 0,
        "gpu_b_index": 1,
        "gpu_a_bdf": "0000:01:00.0",
        "gpu_b_bdf": "0000:99:00.0",  # 없는 BDF
        "link_count": 12,
      }],
    },
  )
  _build_nvlink_links(topo)
  assert [link for link in topo.links if link.type == LinkType.NVLINK] == []


def test_build_nvlink_skips_zero_link_count():
  topo = SystemTopology(
    components=[
      Component(id="pcie_0000:01:00.0", type=ComponentType.GPU, name="GPU 0"),
      Component(id="pcie_0000:25:00.0", type=ComponentType.GPU, name="GPU 1"),
    ],
    nvlink={
      "connections": [{
        "gpu_a_bdf": "0000:01:00.0",
        "gpu_b_bdf": "0000:25:00.0",
        "link_count": 0,
      }],
    },
  )
  _build_nvlink_links(topo)
  assert [link for link in topo.links if link.type == LinkType.NVLINK] == []


def test_trace_uses_nvlink_segment():
  """GPU 0 → GPU 1 trace가 NVLink edge를 사용하고 적절한 BW/latency를 계산한다."""
  topo = _topo_with_two_gpus()
  _build_nvlink_links(topo)

  result = trace_path(topo, "pcie_0000:01:00.0", "pcie_0000:25:00.0")
  assert len(result.path) == 2
  assert len(result.segments) == 1
  seg = result.segments[0]
  assert seg["link_type"] == "nvlink"
  assert seg["theoretical_bw_gbps"] == 300.0
  # 효율 0.95 적용
  assert seg["effective_bw_gbps"] == 285.0
  # nvlink_latency_ns = 30
  assert seg["latency_ns"] == 30
  assert result.e2e_bandwidth_gbps == 285.0


def test_no_nvlink_inventory():
  """nvlink dict 비어 있어도 topology 빌드는 정상."""
  topo = SystemTopology(components=[], links=[], nvlink={})
  _build_nvlink_links(topo)  # raise 없이 종료
  assert topo.links == []
