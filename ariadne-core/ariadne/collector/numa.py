"""NUMA 토폴로지 수집 — sysfs 기반 직접 파싱.

데이터 소스:
  /sys/devices/system/node/nodeN/cpulist
  /sys/devices/system/node/nodeN/meminfo
  /sys/devices/system/node/nodeN/distance
"""

from pathlib import Path

from ariadne.model.types import NUMANode

SYSFS_NODE_BASE = Path("/sys/devices/system/node")


def parse_cpu_list(cpu_list_str: str) -> list[int]:
  """'0-3,8-11' 형태의 CPU 리스트 문자열을 정수 리스트로 변환."""
  cpus = []
  for part in cpu_list_str.strip().split(","):
    if not part:
      continue
    if "-" in part:
      start, end = part.split("-", 1)
      cpus.extend(range(int(start), int(end) + 1))
    else:
      cpus.append(int(part))
  return cpus


def collect_numa_nodes(sysfs_base: Path = SYSFS_NODE_BASE) -> list[NUMANode]:
  """sysfs에서 NUMA 노드 정보를 수집한다."""
  nodes = []
  if not sysfs_base.exists():
    return nodes

  node_dirs = sorted(
    [d for d in sysfs_base.iterdir() if d.name.startswith("node") and d.is_dir()],
    key=lambda d: int(d.name.removeprefix("node")),
  )

  for node_dir in node_dirs:
    node_id = int(node_dir.name.removeprefix("node"))
    node = NUMANode(node_id=node_id)

    cpulist_path = node_dir / "cpulist"
    if cpulist_path.exists():
      node.cpu_list = parse_cpu_list(cpulist_path.read_text())

    meminfo_path = node_dir / "meminfo"
    if meminfo_path.exists():
      for line in meminfo_path.read_text().splitlines():
        if "MemTotal" in line:
          parts = line.split()
          node.memory_mb = int(parts[-2]) // 1024
          break

    distance_path = node_dir / "distance"
    if distance_path.exists():
      distances_raw = distance_path.read_text().strip().split()
      node.distances = {i: int(d) for i, d in enumerate(distances_raw)}

    nodes.append(node)

  return nodes
