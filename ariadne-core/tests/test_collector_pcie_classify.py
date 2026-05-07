"""PCIe device 분류 — NVSwitch, UCIe, 일반 vendor 매핑."""

from ariadne.collector.pcie import (
  classify_device,
  get_device_type_name,
  is_nvswitch,
  is_ucie_capable,
)
from ariadne.model.types import ComponentType


def test_nvswitch_v1_v2_v3_v4_classification():
  """NVSwitch는 PCI bridge class여도 NVSWITCH로 분류된다."""
  assert is_nvswitch(0x10de, 0x1af1)   # v1 V100
  assert is_nvswitch(0x10de, 0x1ac2)   # v2 A100
  assert is_nvswitch(0x10de, 0x22a3)   # v3 H100
  assert is_nvswitch(0x10de, 0x2b1f)   # v4 B200

  bridge_class = 0x060400  # PCI-to-PCI Bridge
  assert classify_device(bridge_class, vendor=0x10de, device_id=0x22a3) == ComponentType.NVSWITCH
  assert get_device_type_name(bridge_class, 0x10de, 0x22a3) == "NVSwitch"


def test_non_nvswitch_nvidia_gpu_still_gpu():
  """NVIDIA GPU(VGA controller class)는 GPU로 분류되어야 한다."""
  vga_class = 0x030000
  assert classify_device(vga_class, vendor=0x10de, device_id=0x2330) == ComponentType.GPU
  assert not is_nvswitch(0x10de, 0x2330)


def test_non_nvidia_vendor_with_nvswitch_devid_is_not_nvswitch():
  """다른 vendor가 우연히 같은 device id를 가져도 NVSwitch 아님."""
  assert not is_nvswitch(0x1234, 0x22a3)


def test_ucie_capable_rebellions_rebel():
  """REBEL CA21은 UCIe-capable로 마킹되어야 한다."""
  assert is_ucie_capable(0x1eff, 0x1210)  # PF
  assert is_ucie_capable(0x1eff, 0x1211)  # VF


def test_ucie_capable_atom_is_not():
  """Rebellions ATOM 시리즈는 UCIe 아니다 (single chip / 4-chip GDDR6)."""
  assert not is_ucie_capable(0x1eff, 0x1220)  # ATOM+ CA22
  assert not is_ucie_capable(0x1eff, 0x1250)  # ATOM-MAX CA25


def test_ucie_capable_other_vendors():
  assert not is_ucie_capable(0x10de, 0x22a3)  # NVIDIA NVSwitch
  assert not is_ucie_capable(0x8086, 0x0000)  # Intel
