"""SR-IOV / IOMMU 그룹 / VFIO 패스스루 안전성 분석.

VFIO를 통한 디바이스 패스스루는 같은 IOMMU 그룹의 모든 디바이스를 함께
할당해야 한다. 안전한 사용을 위해 다음을 확인한다:
  1. 같은 IOMMU 그룹에 다른 종류의 디바이스가 섞이지 않았는가
     (GPU와 USB controller가 같은 그룹이면 GPU만 패스스루 불가)
  2. SR-IOV 활성 디바이스에 reset_method이 정의되어 있는가
     (없으면 VF 게스트 종료 시 안전 리셋 불가, 호스트 재부팅 필요 가능)
  3. SR-IOV-capable 디바이스에 ACS extended capability가 있는가
     (없으면 VF 간 P2P가 IOMMU를 우회, 보안 위험)

ariadne는 일반화된 안전성 이슈만 보고하고 어떤 외부 도메인(VFIO/QEMU/libvirt)의
용어도 결과 모델에 포함하지 않는다.
"""

from pydantic import BaseModel

from ariadne.model.types import SystemTopology


class SafetyIssue(BaseModel):
  severity: str           # "warning" | "error"
  category: str           # "iommu_group_mixed" | "sriov_no_reset" | "sriov_no_acs"
  component_id: str       # 문제 발생 컴포넌트 ID
  summary: str            # 한 줄 요약
  detail: str = ""        # 상세 설명
  recommendation: str = ""  # 조치 방법


def analyze_sriov_safety(topo: SystemTopology) -> list[SafetyIssue]:
  """토폴로지에서 SR-IOV/패스스루 관련 안전성 이슈를 감지한다."""
  issues: list[SafetyIssue] = []
  issues.extend(_check_iommu_group_mixed(topo))
  issues.extend(_check_sriov_reset_method(topo))
  issues.extend(_check_sriov_acs(topo))
  return issues


def _check_iommu_group_mixed(topo: SystemTopology) -> list[SafetyIssue]:
  """같은 IOMMU 그룹에 서로 다른 종류의 endpoint가 섞인 경우.

  PCIe Bridge/Root Port는 자식 디바이스의 그룹에 함께 들어가는 게 정상이므로
  endpoint 타입(GPU, NIC, NVMe 등)만 비교한다.
  """
  if not topo.iommu_groups:
    return []

  bdf_to_dev = {d.bdf: d for d in topo.pci_devices}
  endpoint_types = {"GPU", "NIC", "NVMe Controller", "Audio Device",
                    "USB Controller", "SATA Controller", "Processing Accelerator"}
  bridge_types = {"Host Bridge", "PCI-to-PCI Bridge", "Root Port"}

  issues = []
  for group_id, bdfs in topo.iommu_groups.items():
    if len(bdfs) <= 1:
      continue
    endpoint_kinds: dict[str, list[str]] = {}
    for bdf in bdfs:
      dev = bdf_to_dev.get(bdf)
      if not dev:
        continue
      if dev.type_name in bridge_types:
        continue
      kind = _normalize_kind(dev.type_name)
      if kind in endpoint_kinds:
        endpoint_kinds[kind].append(bdf)
      else:
        endpoint_kinds[kind] = [bdf]

    if len(endpoint_kinds) > 1:
      kinds_str = ", ".join(sorted(endpoint_kinds.keys()))
      issues.append(SafetyIssue(
        severity="warning",
        category="iommu_group_mixed",
        component_id=f"iommu_group_{group_id}",
        summary=f"IOMMU 그룹 {group_id}에 혼합된 디바이스 종류: {kinds_str}",
        detail=(
          f"그룹 {group_id}에 {len(bdfs)}개 디바이스: "
          + ", ".join(f"{b} ({bdf_to_dev[b].type_name})"
                      for b in bdfs if b in bdf_to_dev)
        ),
        recommendation=(
          "패스스루 시 그룹 내 모든 디바이스를 함께 할당해야 합니다. "
          "분리가 필요하면 'pcie_acs_override' 커널 부트 파라미터를 검토하세요 "
          "(보안 영향 동반)"
        ),
      ))
  return issues


def _check_sriov_reset_method(topo: SystemTopology) -> list[SafetyIssue]:
  issues = []
  for dev in topo.pci_devices:
    if dev.sriov_numvfs > 0 and not dev.reset_method:
      issues.append(SafetyIssue(
        severity="warning",
        category="sriov_no_reset",
        component_id=f"pcie_{dev.bdf}",
        summary=f"{dev.type_name} ({dev.bdf})에 SR-IOV {dev.sriov_numvfs}개 활성, reset_method 미정의",
        detail=(
          "VF 사용 종료 시 디바이스를 안전하게 리셋할 방법이 없습니다. "
          "FLR/secondary bus reset 미지원이면 호스트 재부팅이 필요할 수 있습니다."
        ),
        recommendation="드라이버가 reset_method를 노출하는지 확인하고, 운영 시 VF 재할당 전후 동작을 검증하세요",
      ))
  return issues


def _check_sriov_acs(topo: SystemTopology) -> list[SafetyIssue]:
  """SR-IOV-capable 디바이스에 ACS extended cap이 없는 경우.

  ACS 미지원 시 VF 간 P2P 트래픽이 IOMMU를 우회할 수 있어 격리가 깨진다.
  capability dict가 비어 있으면 (root 권한 없이 수집) 판단 보류.
  """
  issues = []
  for dev in topo.pci_devices:
    if dev.sriov_totalvfs <= 0:
      continue
    if not dev.capabilities:
      continue  # 권한 부족으로 capability 수집 실패 — 판단 보류
    if dev.capabilities.get("acs"):
      continue
    issues.append(SafetyIssue(
      severity="warning",
      category="sriov_no_acs",
      component_id=f"pcie_{dev.bdf}",
      summary=f"{dev.type_name} ({dev.bdf}) SR-IOV-capable이지만 ACS extended capability 미지원",
      detail=(
        "ACS가 없으면 VF 간 또는 같은 root port 하의 디바이스 간 P2P 트래픽이 "
        "IOMMU를 우회할 수 있어 격리 보장이 약해집니다."
      ),
      recommendation="보안에 민감한 멀티 테넌트 환경에서는 ACS 미지원 디바이스의 SR-IOV 사용을 자제하세요",
    ))
  return issues


def _normalize_kind(type_name: str) -> str:
  """type_name을 일반화된 endpoint 카테고리로 정규화."""
  t = type_name.lower()
  if "vga" in t or "display" in t or t == "gpu":
    return "gpu"
  if "ethernet" in t or "network" in t or t == "nic":
    return "nic"
  if "nvme" in t:
    return "nvme"
  if "sata" in t:
    return "sata"
  if "usb" in t:
    return "usb"
  if "audio" in t:
    return "audio"
  if "processing accelerator" in t or "npu" in t:
    return "npu"
  return type_name
