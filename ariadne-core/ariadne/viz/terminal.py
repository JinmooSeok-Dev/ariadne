"""Rich 기반 터미널 토폴로지 출력."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from ariadne.model.types import CacheLevel, ComponentType, SystemTopology
from ariadne.analyzer.trace import TraceResult

console = Console()


def render_topology(topo: SystemTopology, summary: bool = False) -> None:
  """토폴로지를 Rich 트리로 터미널에 출력한다."""
  if summary and topo.pci_devices:
    _render_summary(topo)
    return
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
  from ariadne.collector.pcie import calc_pcie_bandwidth, format_bar_size, get_pcie_gen

  color = TYPE_COLORS.get(ep.type_name, "cyan" if ep.type_name.startswith("NPU") else "white")
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
    bar_parts = [f"BAR{b['index']}: {format_bar_size(b['size'])}" for b in ep.bars if format_bar_size(b["size"])]
    if bar_parts:
      ep_tree.add(f"[dim]{', '.join(bar_parts)}[/]")

  if ep.iommu_group >= 0:
    ep_tree.add(f"[dim]IOMMU Group: {ep.iommu_group}[/]")

  if ep.sriov_totalvfs > 0:
    ep_tree.add(f"[dim]SR-IOV: {ep.sriov_numvfs}/{ep.sriov_totalvfs} VFs[/]")

  if ep.is_vf:
    ep_tree.add(f"[dim]Virtual Function[/]")


def _render_summary(topo: SystemTopology) -> None:
  """토폴로지를 타입별 요약으로 출력."""
  from collections import defaultdict
  from ariadne.collector.pcie import get_pcie_gen, calc_pcie_bandwidth

  root = Tree(f"[bold cyan]{topo.hostname}[/]")

  for node in topo.numa_nodes:
    mem_str = _format_memory(node.memory_mb)
    node_tree = root.add(
      f"[bold yellow]NUMA Node {node.node_id}[/] ({mem_str}, {len(node.cpu_list)} CPUs)"
    )

    socket_ids = _sockets_for_node(topo, node.node_id)
    for sid in socket_ids:
      cores = [c for c in topo.cpu_cores if c.physical_package_id == sid]
      p_cores = [c for c in cores if len(c.thread_siblings) > 1]
      e_cores = [c for c in cores if len(c.thread_siblings) == 1]
      parts = []
      if p_cores:
        parts.append(f"{len(p_cores)}P")
      if e_cores:
        parts.append(f"{len(e_cores)}E")
      core_str = "+".join(parts) if parts else f"{len(cores)}"

      l3 = _l3_for_socket(topo, sid)
      l3_str = f", L3 {l3.size_kb // 1024}MB" if l3 else ""
      node_tree.add(f"[bold green]Socket {sid}[/] ({core_str} cores{l3_str})")

    mc_tree = node_tree.add(f"[bold blue]Memory Controller[/]")
    if topo.memory:
      mem = topo.memory[0]
      if mem.speed_mhz:
        ch = mem.channels // max(len(topo.numa_nodes), 1)
        bw = mem.theoretical_bw_gbps / max(len(topo.numa_nodes), 1)
        mc_tree.add(f"{mem.type}-{mem.speed_mhz} × {ch}ch ({bw:.1f} GB/s)")
      else:
        mc_tree.add(mem_str)

    skip = {"Host Bridge", "PCI-to-PCI Bridge", "ISA Bridge", "SMBus Controller",
            "Serial Bus Controller", "Communication Controller", "RAM Controller"}
    devices = [d for d in topo.pci_devices if d.type_name not in skip]

    groups: dict[str, list] = defaultdict(list)
    for dev in devices:
      key = f"{dev.vendor_name}|{dev.type_name}"
      groups[key].append(dev)

    if groups:
      pcie_tree = node_tree.add("[bold red]PCIe Root Complex[/]")

      type_order = ["VGA Controller", "NPU", "NVMe Controller", "Ethernet Controller"]
      sorted_keys = sorted(groups.keys(), key=lambda k: next(
        (i for i, t in enumerate(type_order) if t in k), 99
      ))

      for key in sorted_keys:
        devs = groups[key]
        vendor, type_name = key.split("|", 1)
        color = TYPE_COLORS.get(type_name, "cyan" if type_name.startswith("NPU") else "white")
        short = _summary_short_type(type_name)

        sample = devs[0]
        gen = get_pcie_gen(sample.max_link_speed or sample.current_link_speed) if sample.max_link_speed or sample.current_link_speed else ""
        width = f"x{sample.max_link_width or sample.current_link_width}" if (sample.max_link_width or sample.current_link_width) else ""
        link_str = f"{gen} {width}".strip()

        iommu_ids = sorted(set(d.iommu_group for d in devs if d.iommu_group >= 0))
        iommu_str = _compact_ranges(iommu_ids) if iommu_ids else ""

        vf_count = sum(1 for d in devs if d.is_vf)
        pf_count = len(devs) - vf_count
        sriov_total = sum(d.sriov_totalvfs for d in devs if d.sriov_totalvfs > 0)

        count_str = f"× {pf_count}"
        if vf_count > 0:
          count_str += f" (+{vf_count} VFs)"

        parts = [f"[{color}]{short} {count_str}[/]", f"[dim][{vendor}][/]"]
        if link_str:
          parts.append(f"[dim]{link_str}[/]")
        if iommu_str:
          parts.append(f"[dim]IOMMU: {iommu_str}[/]")
        if sriov_total > 0:
          parts.append(f"[dim]SR-IOV: {sriov_total} max VFs[/]")

        pcie_tree.add("  ".join(parts))

  console.print(root)
  console.print()

  if len(topo.numa_nodes) > 1:
    _render_distance_matrix(topo)


def _summary_short_type(type_name: str) -> str:
  mapping = {
    "VGA Controller": "GPU",
    "NVMe Controller": "NVMe",
    "Ethernet Controller": "NIC",
    "Audio Device": "Audio",
    "USB Controller": "USB",
    "SATA Controller": "SATA",
    "Processing Accelerator": "NPU",
  }
  if type_name.startswith("NPU"):
    return "NPU"
  return mapping.get(type_name, type_name)


def _compact_ranges(nums: list[int]) -> str:
  """[1,2,3,5,7,8,9] → '1-3,5,7-9'"""
  if not nums:
    return ""
  ranges = []
  start = nums[0]
  end = nums[0]
  for n in nums[1:]:
    if n == end + 1:
      end = n
    else:
      ranges.append(f"{start}" if start == end else f"{start}-{end}")
      start = end = n
  ranges.append(f"{start}" if start == end else f"{start}-{end}")
  return ",".join(ranges)


def render_trace(result: TraceResult) -> None:
  """경로 추적 결과를 터미널에 출력."""
  if not result.path:
    console.print("[red]경로를 찾을 수 없습니다.[/]")
    return

  console.print()

  # 요약 패널
  numa_str = "[green]same-NUMA[/]" if result.same_numa else "[yellow]cross-NUMA[/]"
  bw_str = f"{result.e2e_bandwidth_gbps} GB/s" if result.e2e_bandwidth_gbps > 0 else "—"
  summary = Table.grid(padding=(0, 3))
  summary.add_row(
    f"[bold]{result.source_name}[/] → [bold]{result.destination_name}[/]",
    f"[bold cyan]BW: {bw_str}[/]",
    f"[bold cyan]Latency: {result.e2e_latency_ns:.0f}ns[/]",
    numa_str,
  )
  console.print(Panel(summary, title="[bold]E2E Flow[/]", border_style="cyan"))
  console.print()

  # 경로 다이어그램
  max_bw = max((s.get("theoretical_bw_gbps") or 0) for s in result.segments) if result.segments else 1
  path_tree = Tree("[bold]Path[/]")
  for i, seg in enumerate(result.segments):
    link_type = str(seg.get("link_type", ""))
    theo = seg.get("theoretical_bw_gbps")
    eff = seg.get("effective_bw_gbps")
    lat = seg["latency_ns"]
    is_bottleneck = result.bottleneck and seg["from_name"] in result.bottleneck

    if "pcie" in link_type:
      link_label = "PCIe"
      link_color = "red"
    elif "memory" in link_type:
      link_label = "DDR"
      link_color = "blue"
    elif "upi" in link_type or "infinity" in link_type:
      link_label = "UPI/IF"
      link_color = "yellow"
    else:
      link_label = "internal"
      link_color = "dim"

    # BW 바 차트
    bar = ""
    if theo and theo > 0:
      bar_len = int(20 * theo / max(max_bw, 1))
      eff_len = int(20 * (eff or 0) / max(max_bw, 1))
      bar = f"[green]{'█' * eff_len}[/][dim]{'░' * (bar_len - eff_len)}[/]"
      bw_info = f"  {eff} / {theo} GB/s ({eff / theo * 100:.0f}%)" if eff else f"  {theo} GB/s"
    else:
      bw_info = ""

    bn_mark = " [bold red]◄ BOTTLENECK[/]" if is_bottleneck else ""

    if i == 0:
      path_tree.add(f"[bold]{seg['from_name']}[/]")

    seg_line = f"[{link_color}]──{link_label}──►[/]  [dim]{lat:.0f}ns[/]  {bar}{bw_info}{bn_mark}"
    path_tree.add(seg_line)
    path_tree.add(f"[bold]{seg['to_name']}[/]")

  console.print(path_tree)
  console.print()

  # 상세 breakdown 테이블
  table = Table(title="Segment Breakdown", show_lines=True)
  table.add_column("#", style="dim", width=3)
  table.add_column("Segment", style="bold", min_width=20)
  table.add_column("Link", justify="center", width=8)
  table.add_column("Theo BW", justify="right", width=10)
  table.add_column("Eff BW", justify="right", width=10)
  table.add_column("Efficiency", justify="right", width=10)
  table.add_column("Latency", justify="right", width=8)
  table.add_column("", width=12)

  for i, seg in enumerate(result.segments):
    theo = seg.get("theoretical_bw_gbps")
    eff = seg.get("effective_bw_gbps")
    lat = seg["latency_ns"]
    link_type = str(seg.get("link_type", ""))
    is_bottleneck = result.bottleneck and seg["from_name"] in result.bottleneck

    if "pcie" in link_type:
      link_str = "[red]PCIe[/]"
    elif "memory" in link_type:
      link_str = "[blue]DDR[/]"
    elif "upi" in link_type:
      link_str = "[yellow]UPI[/]"
    else:
      link_str = "[dim]int[/]"

    theo_str = f"{theo} GB/s" if theo else "[dim]—[/]"
    eff_str = f"{eff} GB/s" if eff else "[dim]—[/]"
    eff_pct = f"{eff / theo * 100:.0f}%" if theo and eff else "[dim]—[/]"
    lat_str = f"{lat:.0f}ns"
    bn = "[bold red]◄ BN[/]" if is_bottleneck else ""

    table.add_row(str(i + 1), f"{seg['from_name']} → {seg['to_name']}", link_str, theo_str, eff_str, eff_pct, lat_str, bn)

  table.add_section()
  table.add_row(
    "", "[bold]E2E Total[/]", "",
    "", f"[bold cyan]{bw_str}[/]", "",
    f"[bold cyan]{result.e2e_latency_ns:.0f}ns[/]",
    f"[bold red]{result.bottleneck}[/]" if result.bottleneck else "",
  )

  console.print(table)
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
