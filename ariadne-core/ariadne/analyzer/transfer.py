"""Transfer mode 식별 — src↔dst 사이에 가능한 일반화된 전송 모드.

ariadne는 일반화된 통신 모드(dma/p2p/nvlink/ucie/rdma/gpudirect_rdma)만 식별하고
외부 도메인(CUDA P2P API, UCX, ucs 등) 용어는 도입하지 않는다.

식별 기준:
  dma            — 표준 PCIe + Host Memory. 항상 사용 가능 (baseline)
  nvlink         — GPU↔GPU 사이에 NVLink edge 존재
  ucie           — 양쪽 모두 ucie_capable이고 같은 vendor
  p2p            — 같은 root complex 하 PCIe 디바이스 (host memory 안 거침)
  gpudirect_rdma — GPU ↔ RDMA-capable NIC 쌍
  rdma           — RDMA-capable NIC가 src 또는 dst (원격 호스트 가정)
"""

from pydantic import BaseModel

from ariadne.model.types import LinkType, PCIDevice, SystemTopology


class TransferModeOption(BaseModel):
  name: str
  available: bool
  reason: str = ""
  estimated_bandwidth_gbps: float = 0.0
  notes: list[str] = []


def list_transfer_modes(
  topo: SystemTopology, src_id: str, dst_id: str
) -> list[TransferModeOption]:
  """src↔dst에 사용 가능한 transfer mode 목록을 반환.

  반환 순서는 일반적으로 더 낮은 latency / 높은 BW를 갖는 모드가 먼저 오도록
  정렬되지만, 정확한 비용 계산은 analyzer/trace.py가 담당한다.
  """
  src = _find_pci_device(topo, src_id)
  dst = _find_pci_device(topo, dst_id)
  modes: list[TransferModeOption] = []

  modes.append(TransferModeOption(
    name="dma",
    available=True,
    reason="표준 PCIe + Host Memory (baseline)",
  ))

  nvlink = _find_link(topo, src_id, dst_id, LinkType.NVLINK.value)
  if nvlink:
    modes.append(TransferModeOption(
      name="nvlink",
      available=True,
      reason=f"GPU↔GPU NVLink edge ({nvlink.attrs.get('link_count', 0)} bonded links)",
      estimated_bandwidth_gbps=nvlink.bandwidth_gbps or 0.0,
    ))

  if src and dst and _is_ucie_pair(src, dst):
    modes.append(TransferModeOption(
      name="ucie",
      available=True,
      reason="같은 chiplet 패키지 내 UCIe interconnect",
      notes=["BW는 vendor-specific. ariadne는 별도 측정값 필요"],
    ))

  if src and dst and _under_same_root_complex(src, dst):
    modes.append(TransferModeOption(
      name="p2p",
      available=True,
      reason="같은 root complex 하 PCIe P2P (host memory 우회)",
      notes=["ACS 활성 시 P2P가 IOMMU로 차단될 수 있음"],
    ))

  if _is_gpu_rdma_nic_pair(src, dst, topo):
    modes.append(TransferModeOption(
      name="gpudirect_rdma",
      available=True,
      reason="GPU ↔ RDMA-capable NIC, host memory bypass",
      notes=["GPU가 GDR 지원, NIC 드라이버 GDR enabled 필요"],
    ))

  if _has_rdma_nic(src, topo) or _has_rdma_nic(dst, topo):
    modes.append(TransferModeOption(
      name="rdma",
      available=True,
      reason="RDMA-capable NIC 존재 (원격 메모리 직접 접근)",
      notes=["원격 호스트 트래픽일 때만 의미 있음"],
    ))

  return modes


def _find_pci_device(topo: SystemTopology, comp_id: str) -> PCIDevice | None:
  if not comp_id.startswith("pcie_"):
    return None
  bdf = comp_id[len("pcie_"):]
  for d in topo.pci_devices:
    if d.bdf == bdf:
      return d
  return None


def _find_link(topo: SystemTopology, src_id: str, dst_id: str, link_type_value: str):
  for link in topo.links:
    same_pair = (
      (link.source == src_id and link.target == dst_id)
      or (link.source == dst_id and link.target == src_id)
    )
    if not same_pair:
      continue
    lt = link.type.value if hasattr(link.type, "value") else link.type
    if lt == link_type_value:
      return link
  return None


def _is_ucie_pair(src: PCIDevice, dst: PCIDevice) -> bool:
  return src.ucie_capable and dst.ucie_capable and src.vendor == dst.vendor


def _under_same_root_complex(src: PCIDevice, dst: PCIDevice) -> bool:
  """단순 휴리스틱: 같은 NUMA 노드면 같은 RC로 가정. 더 정확히는 graph ancestor."""
  if src.numa_node < 0 or dst.numa_node < 0:
    return False
  return src.numa_node == dst.numa_node


def _is_gpu_rdma_nic_pair(src, dst, topo: SystemTopology) -> bool:
  if not src or not dst:
    return False
  src_is_gpu = src.component_type == "gpu"
  dst_is_gpu = dst.component_type == "gpu"
  src_rdma = _device_has_rdma(src, topo)
  dst_rdma = _device_has_rdma(dst, topo)
  return (src_is_gpu and dst_rdma) or (dst_is_gpu and src_rdma)


def _has_rdma_nic(dev: PCIDevice | None, topo: SystemTopology) -> bool:
  if not dev:
    return False
  return _device_has_rdma(dev, topo)


def _device_has_rdma(dev: PCIDevice, topo: SystemTopology) -> bool:
  for nic in topo.network_interfaces:
    if nic.get("pci_bdf") == dev.bdf and nic.get("rdma_device"):
      return True
  return False
