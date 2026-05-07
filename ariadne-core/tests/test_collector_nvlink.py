"""NVLink collector 테스트 — nvidia-smi runner mock."""

from ariadne.collector.nvlink import collect_nvlink


_QUERY_4GPU = """\
0, 00000000:01:00.0
1, 00000000:25:00.0
2, 00000000:41:00.0
3, 00000000:61:00.0
"""

# H100 device id 포함 — 세대 자동 추정 검증용
_QUERY_4GPU_H100 = """\
0, 00000000:01:00.0, 0x10de2330
1, 00000000:25:00.0, 0x10de2330
2, 00000000:41:00.0, 0x10de2330
3, 00000000:61:00.0, 0x10de2330
"""

# nvidia-smi nvlink -p 출력 예시 (DGX-style: peer가 NVSwitch BDF인 경우)
_PEERS_4GPU_NVSWITCH = """\
GPU 0: NVIDIA H100 80GB HBM3 (UUID: GPU-aaaa)
\t Link 0: Remote info pci_dev: 0000:1c:00.0
\t Link 1: Remote info pci_dev: 0000:1d:00.0
\t Link 2: Remote info pci_dev: 0000:1e:00.0
GPU 1: NVIDIA H100 80GB HBM3 (UUID: GPU-bbbb)
\t Link 0: Remote info pci_dev: 0000:1c:00.0
\t Link 1: Remote info pci_dev: 0000:1d:00.0
"""

# 직결 GPU↔GPU peer (NVSwitch 없는 시스템)
_PEERS_DIRECT = """\
GPU 0: NVIDIA A100
\t Link 0: Remote info pci_dev: 0000:25:00.0
\t Link 1: Remote info pci_dev: 0000:25:00.0
GPU 1: NVIDIA A100
\t Link 0: Remote info pci_dev: 0000:01:00.0
\t Link 1: Remote info pci_dev: 0000:01:00.0
"""

# DGX A100/H100 류: GPU 4개 풀 NVLink 연결 + NIC + CPU Affinity 컬럼 포함
_TOPO_4GPU = """\
\tGPU0\tGPU1\tGPU2\tGPU3\tNIC0\tCPU Affinity\tNUMA Affinity
GPU0\tX\tNV12\tNV12\tNV12\tSYS\t0-23,48-71\t0
GPU1\tNV12\tX\tNV12\tNV12\tSYS\t0-23,48-71\t0
GPU2\tNV12\tNV12\tX\tNV12\tSYS\t0-23,48-71\t0
GPU3\tNV12\tNV12\tNV12\tX\tSYS\t0-23,48-71\t0
NIC0\tSYS\tSYS\tSYS\tSYS\tX
"""


def test_parse_gpu_query():
  inv = collect_nvlink(
    smi_query_runner=lambda: _QUERY_4GPU,
    smi_topo_runner=lambda: "",
  )
  assert inv.gpus == {
    0: "0000:01:00.0",
    1: "0000:25:00.0",
    2: "0000:41:00.0",
    3: "0000:61:00.0",
  }


def test_full_nvlink_matrix():
  inv = collect_nvlink(
    smi_query_runner=lambda: _QUERY_4GPU,
    smi_topo_runner=lambda: _TOPO_4GPU,
  )
  # 4 GPU 풀 메쉬 → C(4,2) = 6 connections
  assert len(inv.connections) == 6

  pairs = {(c.gpu_a_index, c.gpu_b_index) for c in inv.connections}
  assert pairs == {(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)}

  for c in inv.connections:
    assert c.link_count == 12
    assert c.topology_label == "NV12"
    assert c.gpu_a_bdf in inv.gpus.values()
    assert c.gpu_b_bdf in inv.gpus.values()


def test_no_nvlink_only_pcie():
  """GPU 간 NV 셀이 없고 SYS/PHB만 있는 경우 — connections 비어야 함."""
  topo = """\
\tGPU0\tGPU1
GPU0\tX\tSYS
GPU1\tSYS\tX
"""
  inv = collect_nvlink(
    smi_query_runner=lambda: "0, 00000000:01:00.0\n1, 00000000:02:00.0\n",
    smi_topo_runner=lambda: topo,
  )
  assert inv.connections == []
  assert len(inv.gpus) == 2


def test_mixed_nv_counts():
  """비대칭 — NV4와 NV2가 섞인 경우."""
  topo = """\
\tGPU0\tGPU1\tGPU2
GPU0\tX\tNV4\tNV2
GPU1\tNV4\tX\tNV4
GPU2\tNV2\tNV4\tX
"""
  inv = collect_nvlink(
    smi_query_runner=lambda: "0, 00000000:01:00.0\n1, 00000000:02:00.0\n2, 00000000:03:00.0\n",
    smi_topo_runner=lambda: topo,
  )
  by_pair = {(c.gpu_a_index, c.gpu_b_index): c.link_count for c in inv.connections}
  assert by_pair == {(0, 1): 4, (0, 2): 2, (1, 2): 4}


def test_nvidia_smi_unavailable():
  """nvidia-smi 미설치/실패 — 빈 inventory 반환."""
  inv = collect_nvlink(
    smi_query_runner=lambda: "",
    smi_topo_runner=lambda: "",
  )
  assert inv.gpus == {}
  assert inv.connections == []


def test_topo_without_query():
  """query 실패해도 topo만으로 connection 추출 가능 (BDF는 빈 문자열)."""
  inv = collect_nvlink(
    smi_query_runner=lambda: "",
    smi_topo_runner=lambda: _TOPO_4GPU,
    smi_peer_runner=lambda: "",
  )
  assert len(inv.connections) == 6
  assert all(c.gpu_a_bdf == "" and c.gpu_b_bdf == "" for c in inv.connections)


def test_query_extracts_device_id():
  """device_id 컬럼이 있는 출력 → gpu_device_ids 채워짐."""
  inv = collect_nvlink(
    smi_query_runner=lambda: _QUERY_4GPU_H100,
    smi_topo_runner=lambda: "",
    smi_peer_runner=lambda: "",
  )
  assert inv.gpu_device_ids == {0: 0x2330, 1: 0x2330, 2: 0x2330, 3: 0x2330}


def test_per_link_bandwidth_by_generation():
  from ariadne.collector.nvlink import nvlink_generation, per_link_bandwidth_gbps

  # H100
  assert nvlink_generation(0x2330) == 4
  assert per_link_bandwidth_gbps(0x2330) == 25.0
  # A100
  assert nvlink_generation(0x20b0) == 3
  assert per_link_bandwidth_gbps(0x20b0) == 25.0
  # B200
  assert nvlink_generation(0x2941) == 5
  assert per_link_bandwidth_gbps(0x2941) == 50.0
  # 미매핑 → default
  assert nvlink_generation(0x9999) == 0
  assert per_link_bandwidth_gbps(0x9999) == 25.0


def test_peer_parsing_nvswitch_kind():
  """peer BDF가 GPU dict에 없으면 switch_or_unknown."""
  inv = collect_nvlink(
    smi_query_runner=lambda: _QUERY_4GPU,
    smi_topo_runner=lambda: "",
    smi_peer_runner=lambda: _PEERS_4GPU_NVSWITCH,
  )
  assert len(inv.peers) >= 5
  # GPU 0의 link 0/1/2 모두 NVSwitch (gpu dict에 없음)
  gpu0_peers = [p for p in inv.peers if p.gpu_index == 0]
  assert len(gpu0_peers) == 3
  for p in gpu0_peers:
    assert p.peer_kind == "switch_or_unknown"


def test_peer_parsing_direct_gpu_kind():
  """peer BDF가 GPU dict에 있으면 'gpu'."""
  inv = collect_nvlink(
    smi_query_runner=lambda: _QUERY_4GPU,
    smi_topo_runner=lambda: "",
    smi_peer_runner=lambda: _PEERS_DIRECT,
  )
  gpu0_peers = [p for p in inv.peers if p.gpu_index == 0]
  assert all(p.peer_kind == "gpu" for p in gpu0_peers)
  assert all(p.peer_bdf == "0000:25:00.0" for p in gpu0_peers)
