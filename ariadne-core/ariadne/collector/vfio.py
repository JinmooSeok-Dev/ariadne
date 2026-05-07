"""VFIO/VM 정보 수집 — VFIO에 바인딩된 디바이스, IOMMU 부팅 옵션, qemu VM cmdline.

외부 도구(libvirt, virsh) 의존 없이 sysfs/procfs/proc/<pid>/cmdline 파싱만 사용.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field


class VFIODevice(BaseModel):
  """vfio-pci 드라이버에 바인딩된 PCI 디바이스."""
  bdf: str
  iommu_group: int = -1
  driver: str = "vfio-pci"
  attached_to_vm: str | None = None  # qemu cmdline에서 매칭되면 VM name


class IOMMUBootSettings(BaseModel):
  """/proc/cmdline에서 추출한 IOMMU 관련 부팅 옵션."""
  intel_iommu: str | None = None       # "on" | "off" | None
  amd_iommu: str | None = None
  iommu_passthrough: bool = False      # iommu=pt
  pcie_acs_override: str | None = None # pcie_acs_override=...
  isolcpus: list[int] = Field(default_factory=list)
  hugepages_total: int | None = None   # default_hugepagesz / hugepages= 파싱


class QemuVM(BaseModel):
  """qemu-system-* 프로세스로 식별된 가상 머신."""
  pid: int
  name: str = ""
  vcpus: int = 0
  memory_mb: int = 0
  attached_bdfs: list[str] = Field(default_factory=list)  # vfio-pci로 패스스루된 BDF
  cpu_pinning: list[int] = Field(default_factory=list)    # -smp ... ,sockets=... + taskset/cpuset
  numa_nodes: list[int] = Field(default_factory=list)


class VFIOInventory(BaseModel):
  vfio_devices: list[VFIODevice] = Field(default_factory=list)
  iommu_settings: IOMMUBootSettings = Field(default_factory=IOMMUBootSettings)
  vms: list[QemuVM] = Field(default_factory=list)


VFIO_DRIVER_PATH = Path("/sys/bus/pci/drivers/vfio-pci")
PCI_DEVICES_PATH = Path("/sys/bus/pci/devices")
PROC_PATH = Path("/proc")
CMDLINE_PATH = Path("/proc/cmdline")


def collect_vfio_devices(
  vfio_path: Path = VFIO_DRIVER_PATH,
  pci_devices_path: Path = PCI_DEVICES_PATH,
) -> list[VFIODevice]:
  """vfio-pci 드라이버 디렉토리에서 BDF symlink를 읽는다."""
  devices: list[VFIODevice] = []
  if not vfio_path.exists():
    return devices

  bdf_re = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
  for entry in vfio_path.iterdir():
    if not bdf_re.match(entry.name):
      continue
    bdf = entry.name
    group_id = -1
    iommu_link = pci_devices_path / bdf / "iommu_group"
    if iommu_link.exists():
      try:
        group_id = int(iommu_link.resolve().name)
      except (ValueError, OSError):
        pass
    devices.append(VFIODevice(bdf=bdf, iommu_group=group_id))
  return devices


def parse_iommu_cmdline(cmdline: str) -> IOMMUBootSettings:
  """/proc/cmdline 문자열에서 IOMMU 관련 토큰만 추출."""
  s = IOMMUBootSettings()
  tokens = cmdline.split()
  for tok in tokens:
    if tok.startswith("intel_iommu="):
      s.intel_iommu = tok.split("=", 1)[1]
    elif tok.startswith("amd_iommu="):
      s.amd_iommu = tok.split("=", 1)[1]
    elif tok in ("iommu=pt", "iommu=passthrough"):
      s.iommu_passthrough = True
    elif tok.startswith("pcie_acs_override="):
      s.pcie_acs_override = tok.split("=", 1)[1]
    elif tok.startswith("isolcpus="):
      val = tok.split("=", 1)[1]
      s.isolcpus = _parse_cpu_list(val)
    elif tok.startswith("hugepages="):
      try:
        s.hugepages_total = int(tok.split("=", 1)[1])
      except ValueError:
        pass
  return s


def collect_iommu_boot_settings(cmdline_path: Path = CMDLINE_PATH) -> IOMMUBootSettings:
  if not cmdline_path.exists():
    return IOMMUBootSettings()
  return parse_iommu_cmdline(cmdline_path.read_text())


_QEMU_BIN_RE = re.compile(r"qemu-system-[a-z0-9_]+")


def parse_qemu_cmdline(argv: list[str], pid: int) -> QemuVM | None:
  """qemu-system-* argv를 파싱해 VM 정보 추출. qemu가 아니면 None."""
  if not argv:
    return None
  if not _QEMU_BIN_RE.search(argv[0]):
    return None

  vm = QemuVM(pid=pid)
  i = 0
  while i < len(argv):
    tok = argv[i]
    if tok == "-name" and i + 1 < len(argv):
      raw = argv[i + 1]
      # "-name guest=foo,..." 또는 그냥 "-name foo"
      if raw.startswith("guest="):
        vm.name = raw[len("guest="):].split(",", 1)[0]
      else:
        vm.name = raw.split(",", 1)[0]
      i += 2
      continue
    if tok == "-smp" and i + 1 < len(argv):
      vm.vcpus = _parse_smp(argv[i + 1])
      i += 2
      continue
    if tok == "-m" and i + 1 < len(argv):
      vm.memory_mb = _parse_memory(argv[i + 1])
      i += 2
      continue
    if tok == "-device" and i + 1 < len(argv):
      bdf = _extract_vfio_bdf(argv[i + 1])
      if bdf:
        vm.attached_bdfs.append(bdf)
      i += 2
      continue
    if tok == "-numa" and i + 1 < len(argv):
      node_id = _extract_numa_node(argv[i + 1])
      if node_id is not None and node_id not in vm.numa_nodes:
        vm.numa_nodes.append(node_id)
      i += 2
      continue
    i += 1
  return vm


def collect_vms(proc_path: Path = PROC_PATH) -> list[QemuVM]:
  """/proc 아래 qemu-system-* 프로세스를 찾아 cmdline 파싱."""
  vms: list[QemuVM] = []
  if not proc_path.exists():
    return vms
  for entry in proc_path.iterdir():
    if not entry.name.isdigit():
      continue
    cmdline_file = entry / "cmdline"
    if not cmdline_file.exists():
      continue
    try:
      raw = cmdline_file.read_bytes()
    except OSError:
      continue
    if not raw:
      continue
    argv = raw.split(b"\x00")
    argv = [a.decode("utf-8", errors="replace") for a in argv if a]
    vm = parse_qemu_cmdline(argv, pid=int(entry.name))
    if vm is not None:
      vms.append(vm)
  return vms


def collect_vfio_inventory(
  vfio_path: Path = VFIO_DRIVER_PATH,
  pci_devices_path: Path = PCI_DEVICES_PATH,
  cmdline_path: Path = CMDLINE_PATH,
  proc_path: Path = PROC_PATH,
) -> VFIOInventory:
  inv = VFIOInventory(
    vfio_devices=collect_vfio_devices(vfio_path, pci_devices_path),
    iommu_settings=collect_iommu_boot_settings(cmdline_path),
    vms=collect_vms(proc_path),
  )
  # VFIO 디바이스 BDF가 어떤 VM에 attach되었는지 매칭
  bdf_to_vm: dict[str, str] = {}
  for vm in inv.vms:
    for bdf in vm.attached_bdfs:
      bdf_to_vm[bdf] = vm.name or f"pid{vm.pid}"
  for d in inv.vfio_devices:
    d.attached_to_vm = bdf_to_vm.get(d.bdf)
  return inv


def _parse_cpu_list(s: str) -> list[int]:
  """isolcpus=0-3,8,10 형식 파싱. managed_irq= 같은 prefix는 무시."""
  if "=" in s:  # "managed_irq=0-3" 같은 형태
    s = s.split("=", 1)[1]
  cpus: list[int] = []
  for part in s.split(","):
    part = part.strip()
    if "-" in part:
      try:
        a, b = part.split("-", 1)
        cpus.extend(range(int(a), int(b) + 1))
      except ValueError:
        continue
    elif part.isdigit():
      cpus.append(int(part))
  return cpus


def _parse_smp(s: str) -> int:
  """qemu -smp '4' 또는 '4,sockets=1,cores=4,threads=1' → 4."""
  first = s.split(",", 1)[0]
  if first.isdigit():
    return int(first)
  # cpus=N 형식
  for part in s.split(","):
    if part.startswith("cpus="):
      try:
        return int(part.split("=", 1)[1])
      except ValueError:
        return 0
  return 0


def _parse_memory(s: str) -> int:
  """qemu -m '8G' / '8192M' / '8192' → MB."""
  first = s.split(",", 1)[0].strip()
  m = re.match(r"^(\d+)([KMGkmg]?)$", first)
  if not m:
    return 0
  val = int(m.group(1))
  unit = m.group(2).upper()
  if unit == "G":
    return val * 1024
  if unit == "K":
    return max(0, val // 1024)
  return val  # M 또는 단위없음 (M 가정)


def _extract_vfio_bdf(device_arg: str) -> str | None:
  """-device vfio-pci,host=0000:01:00.0,... → '0000:01:00.0'."""
  if "vfio-pci" not in device_arg:
    return None
  for part in device_arg.split(","):
    if part.startswith("host="):
      return part.split("=", 1)[1]
  return None


def _extract_numa_node(numa_arg: str) -> int | None:
  """-numa 'node,nodeid=0,cpus=0-3,memdev=ram-node0' → 0."""
  for part in numa_arg.split(","):
    if part.startswith("nodeid="):
      try:
        return int(part.split("=", 1)[1])
      except ValueError:
        return None
  return None
