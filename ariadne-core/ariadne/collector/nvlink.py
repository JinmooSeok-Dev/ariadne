"""NVLink topology 수집 — nvidia-smi 출력 파싱.

NVIDIA driver는 sysfs에 NVLink 토폴로지를 노출하지 않는다. nvidia-smi가
거의 유일한 사용자 공간 소스. 외부 의존성 추가 없이 subprocess로 호출하고,
nvidia-smi 미설치/실패 시 graceful empty 반환한다.

수집 정보:
  - GPU index → PCI BDF (`nvidia-smi --query-gpu=index,pci.bus_id`)
  - GPU 쌍별 bonded NVLink count (`nvidia-smi topo -m` 매트릭스의 NV<n>)

per-link BW는 GPU 세대에 따라 다르므로(V100/A100/H100 = 25 GB/s, B200 = 50 GB/s)
호출자(또는 analyzer)가 link_count에 곱해 사용한다. 여기서는 raw count만 노출.
"""

import re
import subprocess
from collections.abc import Callable

from pydantic import BaseModel


# NVIDIA GPU device id → NVLink generation. driver/datasheet 기반 (R570 시점).
# NVLink 세대별 단방향 per-link BW (GB/s):
#   NVLink 1 (P100):  20.0 GB/s
#   NVLink 2 (V100):  25.0 GB/s
#   NVLink 3 (A100):  25.0 GB/s
#   NVLink 4 (H100):  25.0 GB/s
#   NVLink 5 (B200):  50.0 GB/s
NVLINK_GEN_BY_DEVICE_ID: dict[int, int] = {
  # NVLink 2 — V100
  0x1db1: 2, 0x1db3: 2, 0x1db4: 2, 0x1db5: 2, 0x1db6: 2,
  # NVLink 3 — A100 (PCIe device IDs vary by SKU)
  0x20b0: 3, 0x20b1: 3, 0x20b2: 3, 0x20b3: 3, 0x20b5: 3, 0x20b7: 3, 0x20f1: 3, 0x20f3: 3,
  # NVLink 4 — H100
  0x2330: 4, 0x2331: 4, 0x232c: 4, 0x233a: 4,
  # NVLink 5 — B100/B200 / GB200
  0x2941: 5, 0x2942: 5, 0x2901: 5,
}

PER_LINK_BW_BY_GEN: dict[int, float] = {
  1: 20.0, 2: 25.0, 3: 25.0, 4: 25.0, 5: 50.0,
}


def per_link_bandwidth_gbps(device_id: int, default: float = 25.0) -> float:
  """device id로부터 NVLink per-link BW 추정. 미매핑이면 default(25 GB/s)."""
  gen = NVLINK_GEN_BY_DEVICE_ID.get(device_id)
  if gen is None:
    return default
  return PER_LINK_BW_BY_GEN.get(gen, default)


def nvlink_generation(device_id: int) -> int:
  return NVLINK_GEN_BY_DEVICE_ID.get(device_id, 0)


class NVLinkConnection(BaseModel):
  gpu_a_index: int
  gpu_b_index: int
  gpu_a_bdf: str = ""
  gpu_b_bdf: str = ""
  link_count: int                  # 두 GPU 사이 bonded NVLink 갯수
  topology_label: str = ""         # 매트릭스 원본 셀 ("NV12" 등)


class NVLinkPeer(BaseModel):
  """nvidia-smi nvlink -p 출력의 단일 link → peer 매핑.

  NVSwitch 시스템에서는 peer가 NVSwitch이고, peer GPU 직결 시스템에서는 GPU.
  peer_kind는 추론 — peer BDF가 NVLinkInventory.gpus에 있으면 'gpu', 아니면 'switch_or_unknown'.
  """
  gpu_index: int
  link: int
  peer_bdf: str = ""
  peer_kind: str = ""              # "gpu" | "switch_or_unknown"


class NVLinkInventory(BaseModel):
  gpus: dict[int, str] = {}        # GPU index → PCI BDF (정규화된 0000:BB:DD.F)
  gpu_device_ids: dict[int, int] = {}  # GPU index → PCI device id (세대 식별용)
  connections: list[NVLinkConnection] = []
  peers: list[NVLinkPeer] = []     # 각 GPU의 각 link의 peer (옵션)


_NV_LINK_RE = re.compile(r"^NV(\d+)$")
_GPU_HEADER_RE = re.compile(r"^GPU(\d+)$")


def _default_smi_query_runner() -> str:
  try:
    r = subprocess.run(
      ["nvidia-smi", "--query-gpu=index,pci.bus_id,pci.device_id",
       "--format=csv,noheader,nounits"],
      capture_output=True, text=True, timeout=5,
    )
    if r.returncode == 0:
      return r.stdout
  except (FileNotFoundError, subprocess.TimeoutExpired):
    pass
  return ""


def _default_smi_topo_runner() -> str:
  try:
    r = subprocess.run(
      ["nvidia-smi", "topo", "-m"],
      capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0:
      return r.stdout
  except (FileNotFoundError, subprocess.TimeoutExpired):
    pass
  return ""


def _default_smi_peer_runner() -> str:
  try:
    r = subprocess.run(
      ["nvidia-smi", "nvlink", "-p"],
      capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0:
      return r.stdout
  except (FileNotFoundError, subprocess.TimeoutExpired):
    pass
  return ""


def collect_nvlink(
  smi_query_runner: Callable[[], str] = _default_smi_query_runner,
  smi_topo_runner: Callable[[], str] = _default_smi_topo_runner,
  smi_peer_runner: Callable[[], str] = _default_smi_peer_runner,
) -> NVLinkInventory:
  inv = NVLinkInventory()
  inv.gpus, inv.gpu_device_ids = _parse_gpu_query(smi_query_runner())
  inv.connections = _parse_topo_matrix(smi_topo_runner(), inv.gpus)
  inv.peers = _parse_peer_output(smi_peer_runner(), inv.gpus)
  return inv


def _parse_gpu_query(text: str) -> tuple[dict[int, str], dict[int, int]]:
  """`index, pci.bus_id [, pci.device_id]` CSV 라인을 파싱.

  반환:
    (index → BDF, index → device_id_int)
  device_id가 없는 출력 형식(예전 옵션)은 device_id dict를 비워둔다.
  """
  bdfs: dict[int, str] = {}
  device_ids: dict[int, int] = {}
  for line in text.splitlines():
    line = line.strip()
    if not line:
      continue
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 2:
      continue
    try:
      idx = int(parts[0])
    except ValueError:
      continue
    bdf = parts[1].lower()
    if re.match(r"^[0-9a-f]{8}:[0-9a-f]{2}:[0-9a-f]{2}\.\d$", bdf):
      bdf = bdf[4:]
    bdfs[idx] = bdf
    if len(parts) >= 3:
      raw = parts[2].strip().lower()
      # nvidia-smi pci.device_id는 "0x10de2330" 형식 (vendor + device)
      # 실제 device id는 하위 16-bit
      try:
        if raw.startswith("0x"):
          full = int(raw, 16)
          device_ids[idx] = full & 0xFFFF
        elif raw.isdigit():
          device_ids[idx] = int(raw)
      except ValueError:
        pass
  return bdfs, device_ids


_PEER_LINK_RE = re.compile(
  r"Link\s+(?P<link>\d+):\s*Remote\s+(?:info|Device)\s+pci_dev[:\s]+(?P<bdf>[0-9a-fA-F:.]+)",
  re.IGNORECASE,
)
_PEER_LINK_RE_SHORT = re.compile(
  r"Link\s+(?P<link>\d+):\s*Remote\s+(?:info|Device)[:\s]+(?P<bdf>[0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)",
  re.IGNORECASE,
)


def _parse_peer_output(text: str, gpus: dict[int, str]) -> list[NVLinkPeer]:
  """`nvidia-smi nvlink -p` 출력에서 (gpu_index, link, peer_bdf) 추출."""
  if not text:
    return []
  gpu_bdfs = set(gpus.values())
  peers: list[NVLinkPeer] = []
  current_gpu: int | None = None
  for line in text.splitlines():
    m = re.match(r"^\s*GPU\s+(\d+):", line)
    if m:
      current_gpu = int(m.group(1))
      continue
    if current_gpu is None:
      continue
    m = _PEER_LINK_RE.search(line) or _PEER_LINK_RE_SHORT.search(line)
    if not m:
      continue
    bdf = m.group("bdf").lower()
    if re.match(r"^[0-9a-f]{8}:[0-9a-f]{2}:[0-9a-f]{2}\.\d$", bdf):
      bdf = bdf[4:]
    kind = "gpu" if bdf in gpu_bdfs else "switch_or_unknown"
    peers.append(NVLinkPeer(
      gpu_index=current_gpu,
      link=int(m.group("link")),
      peer_bdf=bdf,
      peer_kind=kind,
    ))
  return peers


def _parse_topo_matrix(text: str, gpus: dict[int, str]) -> list[NVLinkConnection]:
  """nvidia-smi topo -m 매트릭스에서 GPU↔GPU NVLink만 추출."""
  if not text:
    return []

  lines = text.splitlines()
  header_idx = -1
  for i, line in enumerate(lines):
    if "GPU0" in line and "GPU1" in line:
      header_idx = i
      break
  if header_idx < 0:
    return []

  header_tokens = lines[header_idx].split()
  gpu_col_to_idx: dict[int, int] = {}  # cell column index → GPU index
  for j, tok in enumerate(header_tokens):
    m = _GPU_HEADER_RE.match(tok)
    if m:
      gpu_col_to_idx[j] = int(m.group(1))

  connections: list[NVLinkConnection] = []
  seen: set[tuple[int, int]] = set()

  for line in lines[header_idx + 1:]:
    parts = line.split()
    if not parts:
      break
    m_row = _GPU_HEADER_RE.match(parts[0])
    if not m_row:
      # NIC0/CPU Affinity 같은 비-GPU 행이지만 매트릭스 안쪽일 수 있으므로 break하지 않고 skip
      continue
    row_gpu = int(m_row.group(1))
    cells = parts[1:]

    for col_idx, col_gpu in gpu_col_to_idx.items():
      if col_idx >= len(cells):
        continue
      cell = cells[col_idx]
      if row_gpu == col_gpu:
        continue
      pair = (min(row_gpu, col_gpu), max(row_gpu, col_gpu))
      if pair in seen:
        continue
      m_link = _NV_LINK_RE.match(cell)
      if not m_link:
        continue
      seen.add(pair)
      a, b = pair
      connections.append(NVLinkConnection(
        gpu_a_index=a,
        gpu_b_index=b,
        gpu_a_bdf=gpus.get(a, ""),
        gpu_b_bdf=gpus.get(b, ""),
        link_count=int(m_link.group(1)),
        topology_label=cell,
      ))

  return connections
