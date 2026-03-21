"""메모리 정보 수집 — procfs + dmidecode 기반.

데이터 소스:
  /proc/meminfo
  dmidecode --type 17 (DIMM 정보, root 필요)
"""

import subprocess
from pathlib import Path

from ariadne.model.types import MemoryInfo


def collect_total_memory() -> int:
  """procfs에서 전체 메모리 용량(MB)을 수집한다."""
  meminfo = Path("/proc/meminfo")
  if not meminfo.exists():
    return 0
  for line in meminfo.read_text().splitlines():
    if line.startswith("MemTotal"):
      return int(line.split()[1]) // 1024
  return 0


def collect_dimm_info() -> list[MemoryInfo]:
  """dmidecode에서 DIMM 정보를 수집한다. root 권한 필요."""
  try:
    result = subprocess.run(
      ["dmidecode", "--type", "17"],
      capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
      return []
  except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
    return []

  dimms = []
  current: dict = {}

  for line in result.stdout.splitlines():
    line = line.strip()
    if line.startswith("Memory Device"):
      if current.get("size_mb"):
        dimms.append(current)
      current = {}
    elif ":" in line:
      key, _, val = line.partition(":")
      val = val.strip()
      if key == "Size" and val != "No Module Installed":
        parts = val.split()
        if len(parts) == 2:
          size = int(parts[0])
          if parts[1] == "GB":
            size *= 1024
          current["size_mb"] = size
      elif key == "Speed" and val not in ("Unknown", ""):
        current["speed_mhz"] = int(val.split()[0]) if val.split()[0].isdigit() else 0
      elif key == "Type":
        current["type"] = val
      elif key == "Locator":
        current["locator"] = val

  if current.get("size_mb"):
    dimms.append(current)

  return _aggregate_dimms(dimms)


def _aggregate_dimms(dimms: list[dict]) -> list[MemoryInfo]:
  """DIMM 정보를 채널/속도별로 집계한다."""
  if not dimms:
    return []

  populated = [d for d in dimms if d.get("size_mb", 0) > 0]
  if not populated:
    return []

  speed = populated[0].get("speed_mhz", 0)
  mem_type = populated[0].get("type", "Unknown")
  channels = len(populated)
  total_mb = sum(d["size_mb"] for d in populated)

  bw_gbps = 0.0
  if speed > 0:
    bw_gbps = channels * speed * 8 / 1000

  return [MemoryInfo(
    total_mb=total_mb,
    channels=channels,
    speed_mhz=speed,
    type=mem_type,
    theoretical_bw_gbps=round(bw_gbps, 1),
  )]
