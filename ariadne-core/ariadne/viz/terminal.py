"""Rich 기반 터미널 토폴로지 출력."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from ariadne.model.types import CacheLevel, ComponentType, SystemTopology

console = Console()


def render_topology(topo: SystemTopology) -> None:
  """토폴로지를 Rich 트리로 터미널에 출력한다."""
  root = Tree(f"[bold cyan]{topo.hostname}[/]")

  for node in topo.numa_nodes:
    mem_str = _format_memory(node.memory_mb)
    node_tree = root.add(
      f"[bold yellow]NUMA Node {node.node_id}[/] ({mem_str}, {len(node.cpu_list)} CPUs)"
    )

    socket_ids = _sockets_for_node(topo, node.node_id)
    for sid in socket_ids:
      cores = [c for c in topo.cpu_cores if c.physical_package_id == sid]
      socket_tree = node_tree.add(f"[bold green]Socket {sid}[/] ({len(cores)} cores)")

      l3 = _l3_for_socket(topo, sid)
      if l3:
        socket_tree.add(f"[dim]L3 Cache: {l3.size_kb // 1024}MB (shared)[/]")

      for core in cores[:4]:
        threads = ", ".join(str(t) for t in core.thread_siblings)
        smt = " (SMT)" if len(core.thread_siblings) > 1 else ""
        socket_tree.add(f"Core {core.core_id}: CPU {threads}{smt}")
      if len(cores) > 4:
        socket_tree.add(f"[dim]... ({len(cores) - 4} more cores)[/]")

    mc_tree = node_tree.add(f"[bold blue]Memory Controller[/]")
    if topo.memory:
      mem = topo.memory[0]
      if mem.speed_mhz:
        ch_per_node = mem.channels // max(len(topo.numa_nodes), 1)
        bw_per_node = mem.theoretical_bw_gbps / max(len(topo.numa_nodes), 1)
        mc_tree.add(
          f"{mem.type}-{mem.speed_mhz} × {ch_per_node}ch "
          f"({bw_per_node:.1f} GB/s)"
        )
      else:
        mc_tree.add(f"{mem_str}")

  console.print(root)
  console.print()

  if len(topo.numa_nodes) > 1:
    _render_distance_matrix(topo)


def _render_distance_matrix(topo: SystemTopology) -> None:
  """NUMA distance matrix를 테이블로 출력한다."""
  table = Table(title="NUMA Distance Matrix")
  table.add_column("", style="bold")
  for node in topo.numa_nodes:
    table.add_column(f"Node {node.node_id}", justify="center")

  for node in topo.numa_nodes:
    row = []
    for other in topo.numa_nodes:
      dist = node.distances.get(other.node_id, -1)
      if other.node_id == node.node_id:
        row.append(f"[green]{dist}[/]")
      else:
        color = "yellow" if dist <= 20 else "red"
        row.append(f"[{color}]{dist}[/]")
    table.add_row(f"Node {node.node_id}", *row)

  console.print(table)


def _sockets_for_node(topo: SystemTopology, node_id: int) -> list[int]:
  """NUMA 노드에 속하는 소켓 ID 목록."""
  node_cpus = set()
  for n in topo.numa_nodes:
    if n.node_id == node_id:
      node_cpus = set(n.cpu_list)
      break

  sockets = set()
  for core in topo.cpu_cores:
    if set(core.thread_siblings) & node_cpus:
      sockets.add(core.physical_package_id)
  return sorted(sockets)


def _l3_for_socket(topo: SystemTopology, socket_id: int) -> None:
  """소켓에 해당하는 L3 캐시 정보."""
  socket_cpus = set()
  for core in topo.cpu_cores:
    if core.physical_package_id == socket_id:
      socket_cpus.update(core.thread_siblings)

  for cache in topo.caches:
    if cache.level == CacheLevel.L3 and set(cache.shared_cpu_list) & socket_cpus:
      return cache
  return None


def _format_memory(mb: int) -> str:
  if mb >= 1024:
    return f"{mb / 1024:.0f}GB"
  return f"{mb}MB"
