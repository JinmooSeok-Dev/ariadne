"""Rich 기반 터미널 토폴로지 출력."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from ariadne.model.types import CacheLevel, ComponentType, SystemTopology
from ariadne.analyzer.trace import TraceResult

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

      p_cores = [c for c in cores if len(c.thread_siblings) > 1]
      e_cores = [c for c in cores if len(c.thread_siblings) == 1]

      if p_cores and e_cores:
        p_tree = socket_tree.add(f"[bold]P-cores[/] ({len(p_cores)} cores, {sum(len(c.thread_siblings) for c in p_cores)} threads)")
        for core in p_cores:
          threads = ", ".join(str(t) for t in core.thread_siblings)
          p_tree.add(f"Core {core.core_id}: CPU {threads} (SMT)")

        e_tree = socket_tree.add(f"[bold]E-cores[/] ({len(e_cores)} cores)")
        for core in e_cores:
          e_tree.add(f"Core {core.core_id}: CPU {core.thread_siblings[0]}")
      else:
        for core in cores:
          threads = ", ".join(str(t) for t in core.thread_siblings)
          smt = " (SMT)" if len(core.thread_siblings) > 1 else ""
          socket_tree.add(f"Core {core.core_id}: CPU {threads}{smt}")

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

    _render_pcie_tree(topo, node_tree, node.node_id)

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


TYPE_COLORS = {
  "GPU": "green",
  "VGA Controller": "green",
  "NVMe Controller": "yellow",
  "Ethernet Controller": "magenta",
  "Audio Device": "dim",
  "USB Controller": "dim",
  "SATA Controller": "dim",
  "Serial Bus Controller": "dim",
  "Communication Controller": "dim",
  "RAM Controller": "dim",
}

TYPE_ICONS = {
  "GPU": "🎮",
  "VGA Controller": "🖥️",
  "NVMe Controller": "💾",
  "Ethernet Controller": "🌐",
}


def _render_pcie_tree(topo: SystemTopology, parent_tree, numa_id: int) -> None:
  """NUMA 노드에 연결된 PCIe 디바이스를 트리로 출력."""
  if not topo.pci_devices:
    return

  rc_comp = None
  for comp in topo.components:
    if comp.type == ComponentType.PCIE_ROOT_COMPLEX:
      rc_comp = comp
      break

  if not rc_comp:
    return

  rc_tree = parent_tree.add("[bold red]PCIe Root Complex[/]")

  bridges = {d.bdf: d for d in topo.pci_devices if d.type_name == "PCI-to-PCI Bridge"}
  endpoints = [d for d in topo.pci_devices
               if d.type_name not in ("Host Bridge", "PCI-to-PCI Bridge", "ISA Bridge",
                                       "SMBus Controller", "Serial Bus Controller",
                                       "Communication Controller", "RAM Controller")]

  rendered_bridges = set()
  for ep in endpoints:
    parent_bdf = ep.parent_bdf
    branch = rc_tree

    if parent_bdf and parent_bdf in bridges:
      br = bridges[parent_bdf]
      if parent_bdf not in rendered_bridges:
        rendered_bridges.add(parent_bdf)
      gen = ""
      if br.current_link_speed:
        from ariadne.collector.pcie import get_pcie_gen
        gen = get_pcie_gen(br.current_link_speed)
      width = f"x{br.current_link_width}" if br.current_link_width else ""
      br_label = f"[dim]Root Port {parent_bdf}[/]"
      if gen or width:
        br_label += f" [dim]({gen} {width})[/]"
      branch = rc_tree.add(br_label)

    _render_endpoint(branch, ep)


def _render_endpoint(parent_tree, ep) -> None:
  """단일 PCIe endpoint를 트리에 추가."""
  from ariadne.collector.pcie import calc_pcie_bandwidth, get_pcie_gen

  color = TYPE_COLORS.get(ep.type_name, "white")
  bw = calc_pcie_bandwidth(ep.current_link_speed, ep.current_link_width)
  gen = get_pcie_gen(ep.current_link_speed)
  width = f"x{ep.current_link_width}" if ep.current_link_width else ""

  label = f"[{color}]{ep.vendor_name} {ep.type_name}[/] [dim]{ep.bdf}[/]"

  ep_tree = parent_tree.add(label)

  if gen or width:
    bw_str = f" — {bw} GB/s" if bw > 0 else ""
    max_gen = get_pcie_gen(ep.max_link_speed) if ep.max_link_speed else ""
    max_width = f"x{ep.max_link_width}" if ep.max_link_width else ""
    cur_str = f"{gen} {width}".strip()
    max_str = f"{max_gen} {max_width}".strip()
    if max_str and max_str != cur_str:
      ep_tree.add(f"[dim]{cur_str}{bw_str} (max: {max_str})[/]")
    else:
      ep_tree.add(f"[dim]{cur_str}{bw_str}[/]")

  if ep.bars:
    bar_parts = []
    for bar in ep.bars:
      size = bar["size"]
      if size >= 1 << 30:
        bar_parts.append(f"BAR{bar['index']}: {size >> 30}GB")
      elif size >= 1 << 20:
        bar_parts.append(f"BAR{bar['index']}: {size >> 20}MB")
    if bar_parts:
      ep_tree.add(f"[dim]{', '.join(bar_parts)}[/]")

  if ep.iommu_group >= 0:
    ep_tree.add(f"[dim]IOMMU Group: {ep.iommu_group}[/]")

  if ep.sriov_totalvfs > 0:
    ep_tree.add(f"[dim]SR-IOV: {ep.sriov_numvfs}/{ep.sriov_totalvfs} VFs[/]")

  if ep.is_vf:
    ep_tree.add(f"[dim]Virtual Function[/]")


def render_trace(result: TraceResult) -> None:
  """경로 추적 결과를 터미널에 출력."""
  if not result.path:
    console.print("[red]경로를 찾을 수 없습니다.[/]")
    return

  console.print()
  console.print(f"[bold]Flow: {result.source_name} → {result.destination_name}[/]")
  console.print()

  path_parts = []
  for seg in result.segments:
    if not path_parts:
      path_parts.append(seg["from_name"])
    link_type = seg.get("link_type", "")
    if "pcie" in str(link_type).lower():
      speed = seg.get("theoretical_bw_gbps")
      arrow = f"──PCIe──►" if not speed else f"──PCIe ({speed} GB/s)──►"
    elif "memory" in str(link_type).lower():
      arrow = "──DDR──►"
    else:
      arrow = "──►"
    path_parts.append(arrow)
    path_parts.append(seg["to_name"])

  console.print(f"[dim]Path: {' '.join(path_parts)}[/]")
  console.print()

  table = Table(title="Breakdown")
  table.add_column("구간", style="bold")
  table.add_column("이론 BW", justify="right")
  table.add_column("실효 BW", justify="right")
  table.add_column("latency", justify="right")

  for seg in result.segments:
    seg_name = f"{seg['from_name']} → {seg['to_name']}"
    theo_bw = f"{seg['theoretical_bw_gbps']} GB/s" if seg.get("theoretical_bw_gbps") else "[dim]internal[/]"
    eff_bw = f"{seg['effective_bw_gbps']} GB/s" if seg.get("effective_bw_gbps") else "[dim]—[/]"
    latency = f"{seg['latency_ns']:.0f}ns"
    table.add_row(seg_name, theo_bw, eff_bw, latency)

  table.add_section()

  e2e_bw = f"[bold]{result.e2e_bandwidth_gbps} GB/s[/]" if result.e2e_bandwidth_gbps > 0 else "[dim]—[/]"
  e2e_lat = f"[bold]{result.e2e_latency_ns:.0f}ns[/]"
  table.add_row("[bold]E2E[/]", "", e2e_bw, e2e_lat)

  if result.bottleneck:
    table.add_row("[bold red]Bottleneck[/]", "", f"[red]{result.bottleneck}[/]", "")

  console.print(table)
  console.print()

  if result.same_numa:
    console.print("[green]✅ same-NUMA (cross-NUMA penalty 없음)[/]")
  else:
    console.print("[yellow]⚠️ cross-NUMA (추가 latency 반영됨)[/]")
  console.print()


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
