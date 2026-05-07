"""PCIe 토폴로지 수집 — sysfs 기반 직접 파싱.

데이터 소스:
  /sys/bus/pci/devices/DDDD:BB:DD.F/
    vendor, device, class, numa_node
    current_link_speed, current_link_width
    max_link_speed, max_link_width
    resource (BAR 정보)
    iommu_group (심볼릭 링크)
    sriov_numvfs, sriov_totalvfs
    reset_method
    physfn, virtfn* (SR-IOV 관계)
"""

import re
import subprocess
from pathlib import Path

from ariadne.model.types import (
  Component,
  ComponentType,
  Link,
  LinkType,
)

SYSFS_PCI_BASE = Path("/sys/bus/pci/devices")

PCI_CLASS_NAMES = {
  0x06: "Bridge",
  0x03: "Display",
  0x02: "Network",
  0x01: "Storage",
  0x0c: "Serial Bus",
  0x04: "Multimedia",
  0x07: "Communication",
  0x05: "Memory",
  0x08: "System",
  0x00: "Unclassified",
  0x12: "Processing Accelerator",
}

PCI_SUBCLASS_NAMES = {
  (0x06, 0x00): "Host Bridge",
  (0x06, 0x04): "PCI-to-PCI Bridge",
  (0x06, 0x01): "ISA Bridge",
  (0x03, 0x00): "VGA Controller",
  (0x02, 0x00): "Ethernet Controller",
  (0x01, 0x08): "NVMe Controller",
  (0x01, 0x06): "SATA Controller",
  (0x0c, 0x03): "USB Controller",
  (0x0c, 0x05): "SMBus Controller",
  (0x0c, 0x80): "Serial Bus Controller",
  (0x04, 0x03): "Audio Device",
  (0x07, 0x80): "Communication Controller",
  (0x05, 0x00): "RAM Controller",
  (0x12, 0x00): "Processing Accelerator",
}

PCIE_SPEEDS = {
  "2.5 GT/s PCIe": (1, 2.5),
  "5.0 GT/s PCIe": (2, 5.0),
  "5 GT/s PCIe": (2, 5.0),
  "8.0 GT/s PCIe": (3, 8.0),
  "8 GT/s PCIe": (3, 8.0),
  "16.0 GT/s PCIe": (4, 16.0),
  "16 GT/s PCIe": (4, 16.0),
  "32.0 GT/s PCIe": (5, 32.0),
  "32 GT/s PCIe": (5, 32.0),
  "64.0 GT/s PCIe": (6, 64.0),
}


def _read_sysfs(path: Path) -> str:
  try:
    return path.read_text().strip()
  except (OSError, PermissionError):
    return ""


def _read_sysfs_int(path: Path, base: int = 10) -> int:
  val = _read_sysfs(path)
  if not val:
    return 0
  try:
    return int(val, base)
  except ValueError:
    return 0


def _read_sysfs_hex(path: Path) -> int:
  return _read_sysfs_int(path, 16)


# NVIDIA NVSwitch device id (vendor 0x10de). 세대별:
#   0x1af1: NVSwitch v1 (DGX-1V V100)
#   0x1ac2/0x1ac3: NVSwitch v2 (HGX A100)
#   0x22a3: NVSwitch v3 (HGX H100)
#   0x22a4: NVSwitch v3 변종
#   0x2b1f/0x2b3f: NVSwitch v4 (HGX B200, NVL72)
NVSWITCH_DEVICE_IDS: dict[int, set[int]] = {
  0x10de: {0x1af1, 0x1ac2, 0x1ac3, 0x22a3, 0x22a4, 0x2b1f, 0x2b3f},
}

# UCIe(Universal Chiplet Interconnect Express)는 표준 sysfs 노출이 없다.
# 1차에서는 vendor+device id 기반으로 capability flag만 마킹.
#   Rebellions REBEL CA21: quad chiplet UCIe interconnect
UCIE_CAPABLE_DEVICE_IDS: dict[int, set[int]] = {
  0x1eff: {0x1210, 0x1211},  # REBEL CA21 PF/VF
}


def is_nvswitch(vendor: int, device_id: int) -> bool:
  return device_id in NVSWITCH_DEVICE_IDS.get(vendor, set())


def is_ucie_capable(vendor: int, device_id: int) -> bool:
  return device_id in UCIE_CAPABLE_DEVICE_IDS.get(vendor, set())


def classify_device(class_code: int, vendor: int = 0, device_id: int = 0) -> ComponentType:
  """PCI class code + vendor + device id에서 Ariadne ComponentType 결정."""
  base_class = (class_code >> 16) & 0xFF
  sub_class = (class_code >> 8) & 0xFF

  if is_nvswitch(vendor, device_id):
    return ComponentType.NVSWITCH
  if base_class == 0x06 and sub_class == 0x04:
    return ComponentType.PCIE_ROOT_PORT
  if base_class == 0x06 and sub_class == 0x00:
    return ComponentType.PCIE_ROOT_COMPLEX
  if base_class == 0x03:
    return ComponentType.GPU
  if base_class == 0x02:
    return ComponentType.NIC
  if base_class == 0x01 and sub_class == 0x08:
    return ComponentType.NVME
  if base_class == 0x12:
    return ComponentType.NPU
  if vendor == 0x1eff:
    return ComponentType.NPU
  return ComponentType.PCIE_ENDPOINT


def format_bar_size(size: int) -> str:
  """BAR 크기를 사람이 읽을 수 있는 형식으로 변환."""
  if size >= 1 << 30:
    return f"{size >> 30}GB"
  if size >= 1 << 20:
    return f"{size >> 20}MB"
  if size >= 1 << 10:
    return f"{size >> 10}KB"
  return f"{size}B" if size > 0 else ""


def get_device_type_name(class_code: int, vendor: int = 0, device_id: int = 0) -> str:
  """PCI class code에서 사람이 읽을 수 있는 이름. NPU/NVSwitch는 제품명 포함."""
  if is_nvswitch(vendor, device_id):
    return "NVSwitch"
  if vendor == 0x1eff:
    product = REBELLIONS_DEVICES.get(device_id)
    if product:
      return f"NPU {product}"
    return "NPU"
  base_class = (class_code >> 16) & 0xFF
  sub_class = (class_code >> 8) & 0xFF
  name = PCI_SUBCLASS_NAMES.get((base_class, sub_class))
  if name:
    return name
  if base_class == 0x12:
    return "Processing Accelerator"
  return PCI_CLASS_NAMES.get(base_class, f"Class {base_class:#04x}")


def calc_pcie_bandwidth(speed_str: str, width: int) -> float:
  """PCIe link speed/width에서 이론 BW(GB/s) 계산."""
  speed_info = PCIE_SPEEDS.get(speed_str)
  if not speed_info or width <= 0:
    return 0.0
  gen, rate_gts = speed_info
  if gen <= 2:
    efficiency = 0.8  # 8b/10b
  else:
    efficiency = 128 / 130  # 128b/130b
  bw = rate_gts * width * efficiency / 8
  return round(bw, 1)


def get_pcie_gen(speed_str: str) -> str:
  speed_info = PCIE_SPEEDS.get(speed_str)
  if speed_info:
    return f"Gen{speed_info[0]}"
  return ""


def collect_pci_devices(sysfs_base: Path = SYSFS_PCI_BASE) -> list[dict]:
  """sysfs에서 모든 PCI 디바이스 정보를 수집."""
  devices = []
  if not sysfs_base.exists():
    return devices

  for dev_link in sorted(sysfs_base.iterdir()):
    bdf = dev_link.name
    dev_path = dev_link.resolve() if dev_link.is_symlink() else dev_link

    class_code = _read_sysfs_hex(dev_path / "class")
    vendor = _read_sysfs_hex(dev_path / "vendor")
    device_id = _read_sysfs_hex(dev_path / "device")
    subsys_vendor = _read_sysfs_hex(dev_path / "subsystem_vendor")
    subsys_device = _read_sysfs_hex(dev_path / "subsystem_device")
    numa_node = _read_sysfs_int(dev_path / "numa_node")

    cur_speed = _read_sysfs(dev_path / "current_link_speed")
    cur_width = _read_sysfs_int(dev_path / "current_link_width")
    max_speed = _read_sysfs(dev_path / "max_link_speed")
    max_width = _read_sysfs_int(dev_path / "max_link_width")

    iommu_link = dev_path / "iommu_group"
    iommu_group = -1
    if iommu_link.is_symlink() or iommu_link.exists():
      try:
        iommu_group = int(iommu_link.resolve().name)
      except (ValueError, OSError):
        pass

    sriov_totalvfs = _read_sysfs_int(dev_path / "sriov_totalvfs")
    sriov_numvfs = _read_sysfs_int(dev_path / "sriov_numvfs")

    is_vf = (dev_path / "physfn").exists()

    reset_method = _read_sysfs(dev_path / "reset_method")

    enabled = _read_sysfs_int(dev_path / "enable")

    bars = _parse_resource_file(dev_path / "resource")

    parent_bdf = _find_parent_bdf(dev_path)

    capabilities = collect_pci_capabilities(dev_path)

    devices.append({
      "bdf": bdf,
      "class_code": class_code,
      "vendor": vendor,
      "device_id": device_id,
      "subsys_vendor": subsys_vendor,
      "subsys_device": subsys_device,
      "numa_node": numa_node,
      "current_link_speed": cur_speed,
      "current_link_width": cur_width,
      "max_link_speed": max_speed,
      "max_link_width": max_width,
      "iommu_group": iommu_group,
      "sriov_totalvfs": sriov_totalvfs,
      "sriov_numvfs": sriov_numvfs,
      "is_vf": is_vf,
      "reset_method": reset_method,
      "enabled": enabled,
      "bars": bars,
      "parent_bdf": parent_bdf,
      "component_type": classify_device(class_code, vendor, device_id),
      "type_name": get_device_type_name(class_code, vendor, device_id),
      "ucie_capable": is_ucie_capable(vendor, device_id),
      "capabilities": capabilities,
    })

  return devices


def _parse_resource_file(path: Path) -> list[dict]:
  """sysfs resource 파일에서 BAR 정보 파싱."""
  bars = []
  text = _read_sysfs(path)
  if not text:
    return bars

  for i, line in enumerate(text.splitlines()):
    if i >= 6:
      break
    parts = line.strip().split()
    if len(parts) < 3:
      continue
    start = int(parts[0], 16)
    end = int(parts[1], 16)
    flags = int(parts[2], 16)
    if start == 0 and end == 0:
      continue
    size = end - start + 1
    bars.append({
      "index": i,
      "start": start,
      "size": size,
      "flags": flags,
      "is_memory": bool(flags & 0x200),
      "is_prefetchable": bool(flags & 0x2000),
      "is_64bit": bool(flags & 0x4000000),
    })
  return bars


def _find_parent_bdf(dev_path: Path) -> str:
  """디바이스의 부모 BDF를 찾는다 (sysfs 경로에서 추출)."""
  real = dev_path.resolve()
  parent = real.parent
  parent_name = parent.name
  if re.match(r"\d{4}:[0-9a-f]{2}:[0-9a-f]{2}\.\d", parent_name):
    return parent_name
  return ""


def get_vendor_name(vendor_id: int, device_id: int) -> str:
  """lspci -nn 출력에서 벤더/디바이스 이름을 가져온다."""
  try:
    result = subprocess.run(
      ["lspci", "-nn", "-d", f"{vendor_id:#06x}:{device_id:#06x}"],
      capture_output=True, text=True, timeout=5,
    )
    if result.returncode == 0 and result.stdout.strip():
      line = result.stdout.strip().splitlines()[0]
      match = re.search(r"\d+:\d+\.\d+\s+.+?:\s+(.+?)(?:\s+\[[\da-f:]+\])?$", line)
      if match:
        return match.group(1).strip()
  except (FileNotFoundError, subprocess.TimeoutExpired):
    pass
  return ""


KNOWN_VENDORS = {
  0x10de: "NVIDIA",
  0x1002: "AMD",
  0x8086: "Intel",
  0x14e4: "Broadcom",
  0x15b3: "Mellanox",
  0x10ec: "Realtek",
  0x1344: "Micron",
  0x144d: "Samsung",
  0x1c5c: "SK hynix",
  0x1987: "Phison",
  0x126f: "Silicon Motion",
  0x1e0f: "KIOXIA",
  0x1eff: "Rebellions",
}


REBELLIONS_DEVICES = {
  # ATOM+ — Single chip, PCIe Gen5 x16, 16GB GDDR6, 256GB/s
  0x1220: "ATOM+ CA22 (PF)",
  0x1221: "ATOM+ CA22 (VF)",
  # ATOM Max — 4 chips, PCIe Gen5 x16, 64GB GDDR6, 1024GB/s, 350W
  0x1250: "ATOM-MAX CA25 (PF)",
  0x1251: "ATOM-MAX CA25 (VF)",
  # REBEL — Quad chiplet, UCIe, 144GB HBM3E, 4.8TB/s, PCIe Gen5 x16 dual, 300W
  0x1210: "REBEL CA21 (PF)",
  0x1211: "REBEL CA21 (VF)",
}


def get_short_vendor_name(vendor_id: int) -> str:
  return KNOWN_VENDORS.get(vendor_id, f"{vendor_id:#06x}")


# PCIe Extended Capability IDs (PCI Express Base Spec). Extended capability list는
# config space offset 0x100부터 시작하며 4 byte 헤더가 다음 capability offset을 가리킨다.
#   header[15:0]  = capability ID
#   header[19:16] = version
#   header[31:20] = next capability offset (0이면 list 끝)
EXT_CAP_IDS = {
  0x0001: "aer",            # Advanced Error Reporting
  0x0003: "dsn",            # Device Serial Number
  0x000D: "acs",            # Access Control Services
  0x000E: "ari",            # Alternative Routing-ID Interpretation
  0x000F: "ats",            # Address Translation Services
  0x0010: "sriov",          # SR-IOV (capability 자체. 활성 여부는 sysfs sriov_numvfs)
  0x0013: "pri",            # Page Request Interface
  0x001B: "pasid",          # Process Address Space ID
  0x0023: "dpc",            # Downstream Port Containment
  0x002F: "ide",            # Integrity and Data Encryption (PCIe 6.0+)
}

EXT_CAP_BASE = 0x100


def parse_extended_capabilities(config: bytes) -> dict[str, bool]:
  """PCIe Extended Capability 리스트 파싱.

  Extended cap는 config space 0x100부터 시작하므로 일반 사용자(256B)는
  접근 불가, root에서만 4KB 전체를 읽을 수 있다. 권한 없거나 short read이면
  빈 dict.
  """
  caps: dict[str, bool] = {}
  if len(config) <= EXT_CAP_BASE + 4:
    return caps

  offset = EXT_CAP_BASE
  visited: set[int] = set()
  # 무한 루프 방지: extended cap list는 일반적으로 < 64개
  while offset and offset not in visited and len(visited) < 256:
    if offset + 4 > len(config):
      break
    visited.add(offset)
    header = int.from_bytes(config[offset:offset + 4], "little")
    cap_id = header & 0xFFFF
    next_offset = (header >> 20) & 0xFFF
    # cap_id 0x0000 + next_offset 0 = uninitialized config space
    if cap_id == 0 and next_offset == 0:
      break
    name = EXT_CAP_IDS.get(cap_id)
    if name:
      caps[name] = True
    if next_offset == 0 or next_offset == offset:
      break
    offset = next_offset
  return caps


def collect_pci_capabilities(dev_path: Path) -> dict[str, bool]:
  """sysfs config 파일에서 PCIe Extended Capability 파싱.

  PermissionError(일반 사용자) 또는 short read 시 빈 dict 반환.
  ariadne 정신상 sudo 권장이지만 실패해도 다른 정보 수집은 계속한다.
  """
  config_path = dev_path / "config"
  try:
    with config_path.open("rb") as f:
      data = f.read()
  except (PermissionError, OSError):
    return {}
  return parse_extended_capabilities(data)


def get_device_product_name(vendor_id: int, device_id: int) -> str:
  """벤더별 제품명 반환."""
  if vendor_id == 0x1eff:
    return REBELLIONS_DEVICES.get(device_id, f"RBLN-{device_id:#06x}")
  return ""
