"""IOMMU 그룹 + 설정 context 수집 — sysfs/procfs 기반 직접 파싱.

데이터 소스:
  /sys/kernel/iommu_groups/<group_id>/devices/
  /proc/cmdline (커널 부트 파라미터)
"""

import re
from pathlib import Path

SYSFS_IOMMU_BASE = Path("/sys/kernel/iommu_groups")
PROC_CMDLINE = Path("/proc/cmdline")

# IOMMU 그룹 구성에 영향을 주는 커널 부트 파라미터
_IOMMU_PARAMS = [
  "intel_iommu", "amd_iommu", "iommu", "iommu.strict", "iommu.passthrough",
  "pcie_acs_override", "pci", "intremap",
]


def collect_iommu_groups(sysfs_base: Path = SYSFS_IOMMU_BASE) -> dict[int, list[str]]:
  """IOMMU 그룹 → 디바이스 BDF 목록 매핑을 수집."""
  groups: dict[int, list[str]] = {}
  if not sysfs_base.exists():
    return groups

  for group_dir in sorted(sysfs_base.iterdir(), key=lambda d: int(d.name) if d.name.isdigit() else 0):
    if not group_dir.name.isdigit():
      continue
    group_id = int(group_dir.name)
    devices_dir = group_dir / "devices"
    if not devices_dir.exists():
      continue
    bdfs = sorted(d.name for d in devices_dir.iterdir())
    groups[group_id] = bdfs

  return groups


def collect_iommu_context() -> dict:
  """IOMMU 그룹 구성에 영향을 주는 시스템 설정을 수집.

  반환값:
    {
      "cmdline_params": {"intel_iommu": "on", "pcie_acs_override": "downstream,multifunction", ...},
      "iommu_enabled": True/False,
      "group_count": 14,
      "affecting_params": ["intel_iommu=on"]  # 현재 영향을 주고 있는 설정들
    }
  """
  ctx: dict = {
    "cmdline_params": {},
    "iommu_enabled": False,
    "group_count": 0,
    "affecting_params": [],
  }

  # /proc/cmdline에서 IOMMU 관련 파라미터 파싱
  if PROC_CMDLINE.exists():
    cmdline = PROC_CMDLINE.read_text().strip()
    for token in cmdline.split():
      for param in _IOMMU_PARAMS:
        if token.startswith(param + "="):
          value = token.split("=", 1)[1]
          ctx["cmdline_params"][param] = value
          ctx["affecting_params"].append(token)
        elif token == param:
          ctx["cmdline_params"][param] = "enabled"
          ctx["affecting_params"].append(token)
      # pci= 안에 여러 옵션이 있을 수 있음 (disable_acs_redir, realloc, bfsort 등)
      if token.startswith("pci="):
        pci_opts = token[4:].split(",")
        for opt in pci_opts:
          if "acs" in opt or "realloc" in opt:
            ctx["cmdline_params"][f"pci.{opt.split('=')[0]}"] = opt
            ctx["affecting_params"].append(f"pci={opt}")

  # IOMMU 그룹 존재 여부로 활성화 판단
  if SYSFS_IOMMU_BASE.exists():
    group_dirs = [d for d in SYSFS_IOMMU_BASE.iterdir() if d.name.isdigit()]
    ctx["group_count"] = len(group_dirs)
    ctx["iommu_enabled"] = len(group_dirs) > 0

  return ctx
