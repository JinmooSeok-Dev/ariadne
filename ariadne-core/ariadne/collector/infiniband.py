"""InfiniBand HCA 수집 — /sys/class/infiniband/ 직접 순회.

network.py가 net interface(IPoIB/RoCE) 측에서 RDMA 매핑을 잡는 반면,
이 모듈은 IB HCA 자체와 모든 포트의 GID/state/rate를 수집한다.
순수 IB(IPoIB 미설정), RoCE(link_layer=Ethernet) 모두 포함.

데이터 소스:
  /sys/class/infiniband/<dev>/
    fw_ver, node_guid, sys_image_guid, hca_type
    device → PCI 디바이스 디렉터리 (BDF, vendor, device id)
    ports/<n>/
      state              "4: ACTIVE", "1: DOWN" 등
      phys_state         "5: LinkUp", "3: Disabled" 등
      rate               "200 Gb/sec (4X HDR)"
      link_layer         InfiniBand | Ethernet
      gids/<idx>         port GID (보통 0..N)
"""

import re
from pathlib import Path

from pydantic import BaseModel

SYSFS_INFINIBAND = Path("/sys/class/infiniband")

_BDF_RE = re.compile(r"^\d{4}:[0-9a-f]{2}:[0-9a-f]{2}\.\d$")
# IB sysfs의 state/phys_state는 "<숫자>: <NAME>" 형식
_IB_ENUM_RE = re.compile(r"^\d+:\s*(.+)$")


class IBPort(BaseModel):
  port: int
  state: str = ""           # ACTIVE | DOWN | INIT | ARMED
  phys_state: str = ""      # LinkUp | Disabled | Polling | Sleep ...
  rate: str = ""            # "200 Gb/sec (4X HDR)" — 그대로 보존
  rate_gbps: float = 0.0    # rate 문자열에서 추출한 정량값 (Gb/s)
  link_layer: str = ""      # InfiniBand | Ethernet (RoCE)
  gids: list[str] = []      # 모든 GID (default index 0이 fabric 매칭에 주로 사용)


class IBDevice(BaseModel):
  name: str                 # mlx5_0, mlx4_0, hfi1_0 등
  pci_bdf: str = ""
  vendor: int = 0
  device_id: int = 0
  fw_ver: str = ""
  node_guid: str = ""       # device-wide GUID
  sys_image_guid: str = ""  # 동일 node 내 멀티 HCA 묶음 식별
  hca_type: str = ""        # MT4129 등
  ports: list[IBPort] = []


def _read(path: Path) -> str:
  try:
    return path.read_text().strip()
  except (OSError, PermissionError):
    return ""


def _read_int(path: Path) -> int:
  v = _read(path)
  if not v:
    return 0
  try:
    return int(v)
  except ValueError:
    return 0


def _read_hex(path: Path) -> int:
  v = _read(path)
  if not v:
    return 0
  try:
    return int(v, 16)
  except ValueError:
    return 0


def _parse_ib_enum(raw: str) -> str:
  """'4: ACTIVE' → 'ACTIVE'. 형식 다르면 원본 반환."""
  m = _IB_ENUM_RE.match(raw)
  return m.group(1).strip() if m else raw


def _parse_rate(raw: str) -> float:
  """'200 Gb/sec (4X HDR)' → 200.0. 파싱 실패 시 0.0."""
  if not raw:
    return 0.0
  m = re.match(r"^([\d.]+)\s*Gb/sec", raw)
  if m:
    try:
      return float(m.group(1))
    except ValueError:
      return 0.0
  return 0.0


def collect_ib_devices(sysfs_infiniband: Path = SYSFS_INFINIBAND) -> list[IBDevice]:
  """모든 InfiniBand HCA + 포트 정보를 수집한다."""
  if not sysfs_infiniband.exists():
    return []

  devices: list[IBDevice] = []
  for dev_dir in sorted(sysfs_infiniband.iterdir()):
    if not dev_dir.is_dir():
      continue

    pci_bdf = ""
    vendor = 0
    device_id = 0
    device_link = dev_dir / "device"
    if device_link.exists():
      try:
        real = device_link.resolve()
        if _BDF_RE.match(real.name):
          pci_bdf = real.name
        vendor = _read_hex(real / "vendor")
        device_id = _read_hex(real / "device")
      except OSError:
        pass

    devices.append(IBDevice(
      name=dev_dir.name,
      pci_bdf=pci_bdf,
      vendor=vendor,
      device_id=device_id,
      fw_ver=_read(dev_dir / "fw_ver"),
      node_guid=_read(dev_dir / "node_guid"),
      sys_image_guid=_read(dev_dir / "sys_image_guid"),
      hca_type=_read(dev_dir / "hca_type"),
      ports=_collect_ports(dev_dir / "ports"),
    ))

  return devices


def _collect_ports(ports_dir: Path) -> list[IBPort]:
  if not ports_dir.is_dir():
    return []
  ports: list[IBPort] = []
  for port_dir in sorted(ports_dir.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 0):
    if not port_dir.name.isdigit():
      continue
    rate_raw = _read(port_dir / "rate")
    ports.append(IBPort(
      port=int(port_dir.name),
      state=_parse_ib_enum(_read(port_dir / "state")),
      phys_state=_parse_ib_enum(_read(port_dir / "phys_state")),
      rate=rate_raw,
      rate_gbps=_parse_rate(rate_raw),
      link_layer=_read(port_dir / "link_layer"),
      gids=_collect_gids(port_dir / "gids"),
    ))
  return ports


def _collect_gids(gids_dir: Path) -> list[str]:
  if not gids_dir.is_dir():
    return []
  gids: list[str] = []
  for gid_file in sorted(gids_dir.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 0):
    if not gid_file.name.isdigit():
      continue
    g = _read(gid_file)
    if g and g != "0000:0000:0000:0000:0000:0000:0000:0000":
      gids.append(g)
  return gids
