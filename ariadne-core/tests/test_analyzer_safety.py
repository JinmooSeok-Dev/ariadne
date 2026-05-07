"""SR-IOV / IOMMU 안전성 분석 테스트."""

from ariadne.analyzer.safety import analyze_sriov_safety
from ariadne.model.types import PCIDevice, SystemTopology


def _dev(bdf: str, type_name: str = "Ethernet Controller", *,
         sriov_numvfs: int = 0, sriov_totalvfs: int = 0,
         reset_method: str = "", capabilities: dict | None = None) -> PCIDevice:
  return PCIDevice(
    bdf=bdf,
    type_name=type_name,
    sriov_numvfs=sriov_numvfs,
    sriov_totalvfs=sriov_totalvfs,
    reset_method=reset_method,
    capabilities=capabilities or {},
  )


def test_no_issues_clean_topology():
  topo = SystemTopology(
    pci_devices=[_dev("0000:01:00.0", capabilities={"acs": True})],
    iommu_groups={1: ["0000:01:00.0"]},
  )
  assert analyze_sriov_safety(topo) == []


def test_iommu_group_mixed_endpoints():
  """GPU + USB가 같은 그룹 → warning."""
  topo = SystemTopology(
    pci_devices=[
      _dev("0000:01:00.0", type_name="VGA Controller"),
      _dev("0000:01:00.1", type_name="USB Controller"),
    ],
    iommu_groups={5: ["0000:01:00.0", "0000:01:00.1"]},
  )
  issues = analyze_sriov_safety(topo)
  mixed = [i for i in issues if i.category == "iommu_group_mixed"]
  assert len(mixed) == 1
  assert "5" in mixed[0].summary
  assert "gpu" in mixed[0].summary
  assert "usb" in mixed[0].summary


def test_iommu_group_with_bridges_not_flagged():
  """Bridge가 같은 그룹에 있어도 endpoint 종류가 하나면 OK."""
  topo = SystemTopology(
    pci_devices=[
      _dev("0000:00:01.0", type_name="PCI-to-PCI Bridge"),
      _dev("0000:01:00.0", type_name="VGA Controller"),
    ],
    iommu_groups={3: ["0000:00:01.0", "0000:01:00.0"]},
  )
  issues = analyze_sriov_safety(topo)
  assert [i for i in issues if i.category == "iommu_group_mixed"] == []


def test_iommu_group_same_kind_multiple_endpoints():
  """같은 종류(GPU 2개)는 mixed 아님."""
  topo = SystemTopology(
    pci_devices=[
      _dev("0000:01:00.0", type_name="VGA Controller"),
      _dev("0000:02:00.0", type_name="VGA Controller"),
    ],
    iommu_groups={3: ["0000:01:00.0", "0000:02:00.0"]},
  )
  issues = analyze_sriov_safety(topo)
  assert [i for i in issues if i.category == "iommu_group_mixed"] == []


def test_sriov_no_reset_method():
  topo = SystemTopology(
    pci_devices=[_dev("0000:01:00.0", sriov_numvfs=4, reset_method="")],
  )
  issues = analyze_sriov_safety(topo)
  no_reset = [i for i in issues if i.category == "sriov_no_reset"]
  assert len(no_reset) == 1
  assert "4개" in no_reset[0].summary
  assert "0000:01:00.0" in no_reset[0].component_id


def test_sriov_with_reset_method_ok():
  topo = SystemTopology(
    pci_devices=[_dev("0000:01:00.0", sriov_numvfs=4, reset_method="flr bus")],
  )
  assert [i for i in analyze_sriov_safety(topo) if i.category == "sriov_no_reset"] == []


def test_sriov_inactive_no_warning():
  """sriov_numvfs=0 (활성화 안 됨)이면 reset_method 검사 안 함."""
  topo = SystemTopology(
    pci_devices=[_dev("0000:01:00.0", sriov_totalvfs=4, sriov_numvfs=0)],
  )
  assert [i for i in analyze_sriov_safety(topo) if i.category == "sriov_no_reset"] == []


def test_sriov_capable_without_acs():
  topo = SystemTopology(
    pci_devices=[_dev("0000:01:00.0", sriov_totalvfs=4,
                      capabilities={"sriov": True})],  # ACS 누락
  )
  issues = analyze_sriov_safety(topo)
  no_acs = [i for i in issues if i.category == "sriov_no_acs"]
  assert len(no_acs) == 1


def test_sriov_capable_with_acs_ok():
  topo = SystemTopology(
    pci_devices=[_dev("0000:01:00.0", sriov_totalvfs=4,
                      capabilities={"sriov": True, "acs": True})],
  )
  assert [i for i in analyze_sriov_safety(topo) if i.category == "sriov_no_acs"] == []


def test_capability_dict_empty_skips_acs_check():
  """capability 수집 실패(권한 없음) → ACS 판단 보류."""
  topo = SystemTopology(
    pci_devices=[_dev("0000:01:00.0", sriov_totalvfs=4, capabilities={})],
  )
  assert [i for i in analyze_sriov_safety(topo) if i.category == "sriov_no_acs"] == []


def test_combined_issues():
  topo = SystemTopology(
    pci_devices=[
      _dev("0000:01:00.0", type_name="Ethernet Controller",
           sriov_totalvfs=4, sriov_numvfs=4, reset_method="",
           capabilities={"sriov": True}),
      _dev("0000:01:00.1", type_name="Audio Device"),
    ],
    iommu_groups={5: ["0000:01:00.0", "0000:01:00.1"]},
  )
  issues = analyze_sriov_safety(topo)
  cats = {i.category for i in issues}
  assert "iommu_group_mixed" in cats
  assert "sriov_no_reset" in cats
  assert "sriov_no_acs" in cats
