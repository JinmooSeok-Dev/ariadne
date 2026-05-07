"""NVIDIA Fabric Manager 로그 파서 — DGX/HGX의 NVSwitch fabric 발견 정보 추출.

기본 위치: /var/log/fabricmanager.log

NSCQ/DCGM 없이 NVSwitch 토폴로지를 일부라도 추출하기 위한 best-effort 파서.
boot 시점에 fabricmanager가 NVSwitch와 GPU를 등록하는 로그 라인에서 BDF/UUID/index를
추출한다. 정확한 fabric routing 테이블은 NSCQ가 아니면 못 얻으므로 여기서는
디바이스 inventory만 다룬다.

로그 라인 예시 (driver 버전마다 변형 있음):
  [INFO] [tid 25] NVSwitch 0: pci_dev: 0000:1c:00.0 deviceuuid:1ff8e91d-...
  [INFO] [tid 25] GPU pci_dev: 0000:01:00.0  UUID: GPU-...
  [INFO] [tid 25] Successfully configured all the available GPUs and NVSwitches to route ...
"""

import re
from pathlib import Path

from pydantic import BaseModel

DEFAULT_FM_LOG = Path("/var/log/fabricmanager.log")


class FabricNVSwitch(BaseModel):
  index: int
  pci_bdf: str = ""
  uuid: str = ""


class FabricGPU(BaseModel):
  pci_bdf: str = ""
  uuid: str = ""


class FabricInventory(BaseModel):
  fm_running: bool = False        # "Successfully configured" 메시지 발견 여부
  nvswitches: list[FabricNVSwitch] = []
  gpus: list[FabricGPU] = []
  log_path: str = ""


_NVSWITCH_RE = re.compile(
  r"NVSwitch\s+(?P<index>\d+).*?(?:pci_dev|pci_bdf)[:\s]+(?P<bdf>[0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)"
  r".*?(?:deviceuuid|uuid|UUID)[:\s]+(?P<uuid>[\da-fA-F-]+)",
  re.IGNORECASE,
)
_GPU_RE = re.compile(
  r"GPU.*?(?:pci_dev|pci_bdf|at)[:\s]+(?P<bdf>[0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)"
  r".*?(?:UUID|uuid|deviceuuid)[:\s]+(?P<uuid>GPU-[\da-fA-F-]+)",
  re.IGNORECASE,
)
_FM_RUNNING_RE = re.compile(
  r"Successfully\s+configured\s+all", re.IGNORECASE,
)


def parse_fabricmanager_log(log_path: Path = DEFAULT_FM_LOG) -> FabricInventory:
  """fabricmanager.log 파싱. 파일 없거나 권한 없으면 빈 inventory."""
  inv = FabricInventory(log_path=str(log_path))
  if not log_path.exists():
    return inv
  try:
    text = log_path.read_text(errors="ignore")
  except (OSError, PermissionError):
    return inv

  if _FM_RUNNING_RE.search(text):
    inv.fm_running = True

  seen_switch: set[tuple[int, str]] = set()
  for m in _NVSWITCH_RE.finditer(text):
    idx = int(m.group("index"))
    bdf = _normalize_bdf(m.group("bdf"))
    uuid = m.group("uuid")
    key = (idx, bdf)
    if key in seen_switch:
      continue
    seen_switch.add(key)
    inv.nvswitches.append(FabricNVSwitch(index=idx, pci_bdf=bdf, uuid=uuid))

  seen_gpu: set[str] = set()
  for m in _GPU_RE.finditer(text):
    bdf = _normalize_bdf(m.group("bdf"))
    if bdf in seen_gpu:
      continue
    seen_gpu.add(bdf)
    inv.gpus.append(FabricGPU(pci_bdf=bdf, uuid=m.group("uuid")))

  return inv


def collect_fabricmanager(log_path: Path = DEFAULT_FM_LOG) -> FabricInventory:
  """build_topology()에서 호출되는 진입점. parse_fabricmanager_log의 alias."""
  return parse_fabricmanager_log(log_path)


def _normalize_bdf(bdf: str) -> str:
  bdf = bdf.lower()
  if re.match(r"^[0-9a-f]{8}:", bdf):
    bdf = bdf[4:]
  return bdf
