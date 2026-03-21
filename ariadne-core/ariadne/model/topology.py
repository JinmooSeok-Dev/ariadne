"""토폴로지 그래프 구축 — Collector 결과를 NetworkX 그래프로 통합."""

import socket as sock_mod

import networkx as nx

from ariadne.model.types import (
  CacheLevel,
  Component,
  ComponentType,
  Link,
  LinkType,
  SystemTopology,
)
from ariadne.collector.numa import collect_numa_nodes
from ariadne.collector.cpu import collect_cpu_cores, collect_caches
from ariadne.collector.memory import collect_total_memory, collect_dimm_info


def build_topology() -> SystemTopology:
  """현재 호스트의 토폴로지를 수집하고 SystemTopology를 구축한다."""
  topo = SystemTopology(hostname=sock_mod.gethostname())

  topo.numa_nodes = collect_numa_nodes()
  topo.cpu_cores = collect_cpu_cores()
  topo.caches = collect_caches()
  topo.memory = collect_dimm_info()
  if not topo.memory:
    total = collect_total_memory()
    if total > 0:
      from ariadne.model.types import MemoryInfo
      topo.memory = [MemoryInfo(total_mb=total)]

  _build_components_and_links(topo)
  return topo


def _build_components_and_links(topo: SystemTopology) -> None:
  """수집된 데이터로 Component/Link 목록을 생성한다."""
  components = []
  links = []

  socket_ids = sorted({c.physical_package_id for c in topo.cpu_cores})

  for node in topo.numa_nodes:
    node_id = f"numa_{node.node_id}"
    components.append(Component(
      id=node_id,
      type=ComponentType.NUMA_NODE,
      name=f"NUMA Node {node.node_id}",
      attrs={"memory_mb": node.memory_mb, "cpu_count": len(node.cpu_list)},
    ))

  for sid in socket_ids:
    sock_id = f"socket_{sid}"
    components.append(Component(
      id=sock_id,
      type=ComponentType.SOCKET,
      name=f"Socket {sid}",
    ))

    node_for_socket = _find_numa_for_socket(topo, sid)
    if node_for_socket is not None:
      links.append(Link(
        source=f"numa_{node_for_socket}",
        target=sock_id,
        type=LinkType.INTERNAL,
      ))

  for core in topo.cpu_cores:
    core_id = f"core_{core.physical_package_id}_{core.core_id}"
    components.append(Component(
      id=core_id,
      type=ComponentType.CPU_CORE,
      name=f"Core {core.core_id}",
      attrs={
        "socket": core.physical_package_id,
        "threads": core.thread_siblings,
        "smt": len(core.thread_siblings) > 1,
      },
    ))
    links.append(Link(
      source=f"socket_{core.physical_package_id}",
      target=core_id,
      type=LinkType.INTERNAL,
    ))

  l3_caches = [c for c in topo.caches if c.level == CacheLevel.L3]
  for i, cache in enumerate(l3_caches):
    cache_id = f"l3_{i}"
    components.append(Component(
      id=cache_id,
      type=ComponentType.CACHE,
      name=f"L3 Cache ({cache.size_kb // 1024}MB)",
      attrs={"level": "L3", "size_kb": cache.size_kb, "shared_cpus": cache.shared_cpu_list},
    ))

    core_socket = _find_socket_for_cpus(topo, cache.shared_cpu_list)
    if core_socket is not None:
      links.append(Link(
        source=f"socket_{core_socket}",
        target=cache_id,
        type=LinkType.INTERNAL,
      ))

  for node in topo.numa_nodes:
    mc_id = f"mc_{node.node_id}"
    components.append(Component(
      id=mc_id,
      type=ComponentType.MEMORY_CONTROLLER,
      name=f"Memory Controller {node.node_id}",
    ))
    links.append(Link(
      source=f"numa_{node.node_id}",
      target=mc_id,
      type=LinkType.INTERNAL,
    ))

    if topo.memory:
      mem = topo.memory[0]
      bw = mem.theoretical_bw_gbps
      if len(topo.numa_nodes) > 1 and bw > 0:
        bw = round(bw / len(topo.numa_nodes), 1)

      dram_id = f"dram_{node.node_id}"
      speed_str = f"{mem.type} {mem.speed_mhz}MHz" if mem.speed_mhz else "Unknown"
      components.append(Component(
        id=dram_id,
        type=ComponentType.DRAM,
        name=f"DRAM ({speed_str})",
        attrs={"memory_mb": node.memory_mb},
      ))
      links.append(Link(
        source=mc_id,
        target=dram_id,
        type=LinkType.MEMORY,
        bandwidth_gbps=bw if bw > 0 else None,
      ))

  for node in topo.numa_nodes:
    for other_id, dist in node.distances.items():
      if other_id > node.node_id and dist > node.distances.get(node.node_id, 10):
        links.append(Link(
          source=f"numa_{node.node_id}",
          target=f"numa_{other_id}",
          type=LinkType.UPI,
          attrs={"distance": dist},
        ))

  topo.components = components
  topo.links = links


def _find_numa_for_socket(topo: SystemTopology, socket_id: int) -> int | None:
  """소켓에 속하는 CPU들이 어떤 NUMA 노드에 있는지 찾는다."""
  socket_cpus = set()
  for core in topo.cpu_cores:
    if core.physical_package_id == socket_id:
      socket_cpus.update(core.thread_siblings)

  for node in topo.numa_nodes:
    if socket_cpus & set(node.cpu_list):
      return node.node_id
  return None


def _find_socket_for_cpus(topo: SystemTopology, cpu_list: list[int]) -> int | None:
  """CPU 리스트가 속하는 소켓을 찾는다."""
  if not cpu_list:
    return None
  target = cpu_list[0]
  for core in topo.cpu_cores:
    if target in core.thread_siblings:
      return core.physical_package_id
  return None


def to_networkx(topo: SystemTopology) -> nx.DiGraph:
  """SystemTopology를 NetworkX DiGraph로 변환한다."""
  g = nx.DiGraph()
  for comp in topo.components:
    g.add_node(comp.id, **comp.model_dump())
  for link in topo.links:
    g.add_edge(link.source, link.target, **link.model_dump())
  return g
