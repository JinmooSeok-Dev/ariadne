"""CPU 토폴로지 수집 — sysfs/procfs 기반 직접 파싱.

데이터 소스:
  /sys/devices/system/cpu/cpuN/topology/core_id
  /sys/devices/system/cpu/cpuN/topology/physical_package_id
  /sys/devices/system/cpu/cpuN/topology/thread_siblings_list
  /sys/devices/system/cpu/cpuN/cache/indexN/{level,size,type,shared_cpu_list}
"""

from pathlib import Path

from ariadne.model.types import CPUCore, CacheInfo, CacheLevel
from ariadne.collector.numa import parse_cpu_list

SYSFS_CPU_BASE = Path("/sys/devices/system/cpu")


def collect_cpu_cores(sysfs_base: Path = SYSFS_CPU_BASE) -> list[CPUCore]:
  """sysfs에서 CPU 코어 토폴로지를 수집한다."""
  seen_cores: dict[tuple[int, int], CPUCore] = {}

  cpu_dirs = sorted(
    [d for d in sysfs_base.iterdir() if d.name.startswith("cpu") and d.name[3:].isdigit()],
    key=lambda d: int(d.name[3:]),
  )

  for cpu_dir in cpu_dirs:
    topo_dir = cpu_dir / "topology"
    if not topo_dir.exists():
      continue

    cpu_id = int(cpu_dir.name[3:])
    core_id = int((topo_dir / "core_id").read_text().strip())
    pkg_id = int((topo_dir / "physical_package_id").read_text().strip())

    siblings_path = topo_dir / "thread_siblings_list"
    siblings = parse_cpu_list(siblings_path.read_text()) if siblings_path.exists() else [cpu_id]

    key = (pkg_id, core_id)
    if key not in seen_cores:
      seen_cores[key] = CPUCore(
        core_id=core_id,
        physical_package_id=pkg_id,
        thread_siblings=sorted(siblings),
      )

  return sorted(seen_cores.values(), key=lambda c: (c.physical_package_id, c.core_id))


def collect_caches(sysfs_base: Path = SYSFS_CPU_BASE) -> list[CacheInfo]:
  """sysfs에서 캐시 정보를 수집한다. 중복 제거 (shared_cpu_list 기준)."""
  seen: set[tuple[str, str]] = set()
  caches = []

  cpu0_cache = sysfs_base / "cpu0" / "cache"
  if not cpu0_cache.exists():
    return caches

  for index_dir in sorted(cpu0_cache.iterdir()):
    if not index_dir.name.startswith("index"):
      continue

    level_val = int((index_dir / "level").read_text().strip())
    type_val = (index_dir / "type").read_text().strip()

    level_map = {
      (1, "Data"): CacheLevel.L1D,
      (1, "Instruction"): CacheLevel.L1I,
      (2, "Unified"): CacheLevel.L2,
      (3, "Unified"): CacheLevel.L3,
    }
    level = level_map.get((level_val, type_val))
    if level is None:
      continue

    size_str = (index_dir / "size").read_text().strip()
    size_kb = int(size_str.rstrip("K"))

    shared_path = index_dir / "shared_cpu_list"
    shared_cpus = parse_cpu_list(shared_path.read_text()) if shared_path.exists() else []

    line_size_path = index_dir / "coherency_line_size"
    line_size = int(line_size_path.read_text().strip()) if line_size_path.exists() else 64

    dedup_key = (level.value, ",".join(map(str, shared_cpus)))
    if dedup_key in seen:
      continue
    seen.add(dedup_key)

    caches.append(CacheInfo(
      level=level,
      size_kb=size_kb,
      shared_cpu_list=shared_cpus,
      line_size_bytes=line_size,
    ))

  return caches
