"""Network interface 수집 — NIC IP/MAC/RDMA capability.

데이터 소스:
  /sys/class/net/<iface>/
    address                       MAC
    speed                         link speed Mbps (down 시 -1)
    mtu, operstate, carrier
    device → PCI 디바이스 디렉터리 (BDF 추출)
    device/infiniband/<rdma_dev>/ → RoCE 매핑
  /sys/class/infiniband/<rdma_dev>/ports/<port>/gids/0
                                  port GID (inter-host fabric 매칭용)
  ip -j addr show                 IP 주소 (sysfs에 IP는 없음)

inter-host link 추론(step 5)이 사용할 정보를 수집한다. 같은 서브넷의
NIC들은 ethernet fabric으로, 같은 GID prefix를 공유하는 RDMA 포트들은
IB/RoCE fabric으로 묶인다.
"""

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

SYSFS_CLASS_NET = Path("/sys/class/net")
SYSFS_INFINIBAND = Path("/sys/class/infiniband")

_LOOPBACK_IFACES = {"lo"}
_BDF_RE = re.compile(r"^\d{4}:[0-9a-f]{2}:[0-9a-f]{2}\.\d$")


class NetworkInterface(BaseModel):
  name: str
  mac_address: str = ""
  pci_bdf: str = ""               # 연결된 PCI 디바이스 (가상/브리지면 빈 문자열)
  link_speed_mbps: int = 0        # /sys/class/net/.../speed
  mtu: int = 0
  operstate: str = ""             # up | down | unknown | dormant ...
  carrier: bool = False           # 물리 링크 활성 여부
  ip_addresses: list[str] = []    # ["10.0.0.11/24", "fe80::1/64", ...]
  rdma_device: str = ""           # mlx5_0 등 (없으면 빈 문자열)
  port_gid: str = ""              # IB port GID (default index 0). fabric 매칭에 사용


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


def _default_ip_runner() -> list:
  """`ip -j addr show` 실행 결과(JSON)를 리스트로 반환. 실패 시 빈 리스트."""
  try:
    result = subprocess.run(
      ["ip", "-j", "addr", "show"],
      capture_output=True, text=True, timeout=5,
    )
    if result.returncode == 0 and result.stdout.strip():
      data = json.loads(result.stdout)
      return data if isinstance(data, list) else []
  except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
    pass
  return []


def collect_network_interfaces(
  sysfs_class_net: Path = SYSFS_CLASS_NET,
  sysfs_infiniband: Path = SYSFS_INFINIBAND,
  ip_runner: Callable[[], list] = _default_ip_runner,
  include_loopback: bool = False,
) -> list[NetworkInterface]:
  """모든 네트워크 인터페이스 정보를 수집한다."""
  if not sysfs_class_net.exists():
    return []

  ip_by_name = _index_ip_addresses(ip_runner())

  ifaces: list[NetworkInterface] = []
  for iface_dir in sorted(sysfs_class_net.iterdir()):
    name = iface_dir.name
    if not include_loopback and name in _LOOPBACK_IFACES:
      continue

    speed = _read_int(iface_dir / "speed")
    rdma_dev, port_gid = _resolve_rdma(iface_dir / "device", sysfs_infiniband)

    ifaces.append(NetworkInterface(
      name=name,
      mac_address=_read(iface_dir / "address"),
      pci_bdf=_resolve_pci_bdf(iface_dir / "device"),
      link_speed_mbps=speed if speed > 0 else 0,  # down 상태는 -1 반환됨
      mtu=_read_int(iface_dir / "mtu"),
      operstate=_read(iface_dir / "operstate"),
      carrier=_read_int(iface_dir / "carrier") == 1,
      ip_addresses=ip_by_name.get(name, []),
      rdma_device=rdma_dev,
      port_gid=port_gid,
    ))

  return ifaces


def _index_ip_addresses(ip_data: list) -> dict[str, list[str]]:
  """ip -j addr 출력에서 ifname → ["addr/prefixlen", ...] 인덱스 구성."""
  result: dict[str, list[str]] = {}
  for entry in ip_data:
    ifname = entry.get("ifname")
    if not ifname:
      continue
    addrs = []
    for addr in entry.get("addr_info") or []:
      local = addr.get("local")
      prefixlen = addr.get("prefixlen")
      if local and prefixlen is not None:
        addrs.append(f"{local}/{prefixlen}")
    result[ifname] = addrs
  return result


def _resolve_pci_bdf(device_link: Path) -> str:
  """/sys/class/net/<iface>/device 가 가리키는 PCI 디바이스 BDF."""
  if not device_link.exists():
    return ""
  try:
    real = device_link.resolve()
  except OSError:
    return ""
  if _BDF_RE.match(real.name):
    return real.name
  return ""


def _resolve_rdma(device_link: Path, sysfs_infiniband: Path) -> tuple[str, str]:
  """net interface에 연결된 RDMA 디바이스 이름과 default port GID."""
  if not device_link.exists():
    return "", ""
  try:
    real = device_link.resolve()
  except OSError:
    return "", ""

  ib_dir = real / "infiniband"
  if not ib_dir.is_dir():
    return "", ""

  for rdma_subdir in sorted(ib_dir.iterdir()):
    rdma_dev = rdma_subdir.name
    return rdma_dev, _read_first_port_gid(sysfs_infiniband / rdma_dev)
  return "", ""


def _read_first_port_gid(rdma_dev_path: Path) -> str:
  ports_dir = rdma_dev_path / "ports"
  if not ports_dir.is_dir():
    return ""
  for port_dir in sorted(ports_dir.iterdir()):
    gid_file = port_dir / "gids" / "0"
    gid = _read(gid_file)
    if gid:
      return gid
  return ""
