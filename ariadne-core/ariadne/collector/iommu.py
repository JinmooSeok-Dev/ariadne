"""IOMMU 그룹 수집 — sysfs 기반 직접 파싱.

데이터 소스:
  /sys/kernel/iommu_groups/<group_id>/devices/
"""

from pathlib import Path

SYSFS_IOMMU_BASE = Path("/sys/kernel/iommu_groups")


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
