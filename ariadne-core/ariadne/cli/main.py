"""Ariadne CLI — Typer 기반 명령행 인터페이스."""

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
  name="ariadne",
  help="System topology E2E data flow tracer and simulator",
)
console = Console()


@app.command()
def show():
  """현재 호스트의 시스템 토폴로지를 수집하고 터미널에 표시한다."""
  from ariadne.model.topology import build_topology
  from ariadne.viz.terminal import render_topology

  console.print("[dim]Collecting system topology...[/]")
  topo = build_topology()
  console.print()
  render_topology(topo)


@app.command()
def trace(
  source: Optional[str] = typer.Argument(None, help="Source (BDF 또는 타입:인덱스, e.g. gpu:0)"),
  destination: Optional[str] = typer.Argument(None, help="Destination (BDF, 타입:인덱스, 또는 'memory')"),
):
  """두 디바이스 간 E2E 경로를 추적하고 BW/latency breakdown을 표시한다."""
  from ariadne.model.topology import build_topology
  from ariadne.analyzer.trace import trace_path
  from ariadne.viz.terminal import render_trace

  console.print("[dim]Collecting system topology...[/]")
  topo = build_topology()

  if source is None or destination is None:
    source_id, dest_id = _interactive_select(topo, source, destination)
  else:
    source_id = _resolve_target(topo, source)
    dest_id = _resolve_target(topo, destination)

  if not source_id or not dest_id:
    console.print("[red]디바이스를 찾을 수 없습니다.[/]")
    raise typer.Exit(1)

  result = trace_path(topo, source_id, dest_id)
  render_trace(result)


@app.command()
def snapshot(
  output: Path = typer.Argument(..., help="저장할 JSON 파일 경로"),
):
  """현재 토폴로지를 JSON snapshot으로 저장한다."""
  from ariadne.model.topology import build_topology

  console.print("[dim]Collecting system topology...[/]")
  topo = build_topology()

  output.write_text(topo.model_dump_json(indent=2))
  console.print(f"[green]Saved:[/] {output}")
  console.print(
    f"  {len(topo.numa_nodes)} NUMA nodes, "
    f"{len(topo.cpu_cores)} cores, "
    f"{len(topo.components)} components, "
    f"{len(topo.pci_devices)} PCI devices"
  )


@app.command()
def load(
  input_file: Path = typer.Argument(..., help="로드할 JSON 파일 경로"),
):
  """저장된 JSON snapshot을 로드하고 토폴로지를 표시한다."""
  from ariadne.model.types import SystemTopology
  from ariadne.viz.terminal import render_topology

  data = json.loads(input_file.read_text())
  topo = SystemTopology(**data)
  render_topology(topo)


def _interactive_select(topo, source_hint: str | None, dest_hint: str | None):
  """fuzzy 검색으로 source와 destination을 선택."""
  from InquirerPy import inquirer

  choices = _build_device_choices(topo)
  if not choices:
    console.print("[red]선택 가능한 디바이스가 없습니다.[/]")
    return None, None

  memory_choices = _build_memory_choices(topo)
  all_dest_choices = choices + memory_choices

  if source_hint:
    source_id = _resolve_target(topo, source_hint)
  else:
    source_id = inquirer.fuzzy(
      message="Source 선택:",
      choices=[{"name": c["label"], "value": c["id"]} for c in choices],
    ).execute()

  if dest_hint:
    dest_id = _resolve_target(topo, dest_hint)
  else:
    dest_id = inquirer.fuzzy(
      message="Destination 선택:",
      choices=[{"name": c["label"], "value": c["id"]} for c in all_dest_choices],
    ).execute()

  return source_id, dest_id


def _build_device_choices(topo) -> list[dict]:
  """선택 가능한 PCIe 디바이스 목록을 구성."""
  from ariadne.model.types import ComponentType
  choices = []
  type_counters: dict[str, int] = {}

  skip_types = {"Host Bridge", "PCI-to-PCI Bridge", "ISA Bridge",
                "SMBus Controller", "Serial Bus Controller",
                "Communication Controller", "RAM Controller"}

  for dev in topo.pci_devices:
    if dev.type_name in skip_types:
      continue

    short_type = _short_type(dev.type_name)
    idx = type_counters.get(short_type, 0)
    type_counters[short_type] = idx + 1

    speed_info = ""
    if dev.current_link_speed and dev.current_link_width:
      from ariadne.collector.pcie import get_pcie_gen, calc_pcie_bandwidth
      gen = get_pcie_gen(dev.current_link_speed)
      bw = calc_pcie_bandwidth(dev.current_link_speed, dev.current_link_width)
      speed_info = f"{gen} x{dev.current_link_width}"
      if bw > 0:
        speed_info += f" ({bw} GB/s)"

    label = f"{short_type}:{idx}  {dev.vendor_name:10s} {dev.type_name:25s} {dev.bdf}  {speed_info}"
    choices.append({
      "id": f"pcie_{dev.bdf}",
      "label": label,
      "short": f"{short_type}:{idx}",
    })

  return choices


def _build_memory_choices(topo) -> list[dict]:
  """Host Memory 선택지."""
  choices = []
  for node in topo.numa_nodes:
    mem_str = f"{node.memory_mb // 1024}GB" if node.memory_mb >= 1024 else f"{node.memory_mb}MB"
    label = f"memory:{node.node_id}  Host Memory NUMA {node.node_id} ({mem_str})"
    choices.append({
      "id": f"mc_{node.node_id}",
      "label": label,
    })
  return choices


def _resolve_target(topo, spec: str) -> str | None:
  """'gpu:0', 'memory', '0000:01:00.0' 등을 component ID로 변환."""
  if spec.startswith("pcie_") or spec.startswith("mc_") or spec.startswith("numa_") or spec.startswith("dram_"):
    return spec

  if spec.startswith("0000:") or ":" in spec and "." in spec:
    return f"pcie_{spec}"

  if spec == "memory" or spec == "mem":
    if topo.numa_nodes:
      return f"mc_{topo.numa_nodes[0].node_id}"
    return None

  if ":" in spec:
    type_part, _, idx_part = spec.partition(":")
    try:
      idx = int(idx_part)
    except ValueError:
      return None
    return _find_by_type_index(topo, type_part, idx)

  return None


def _find_by_type_index(topo, type_str: str, idx: int) -> str | None:
  """타입:인덱스로 디바이스를 찾는다."""
  skip_types = {"Host Bridge", "PCI-to-PCI Bridge", "ISA Bridge",
                "SMBus Controller", "Serial Bus Controller",
                "Communication Controller", "RAM Controller"}

  type_counters: dict[str, int] = {}
  for dev in topo.pci_devices:
    if dev.type_name in skip_types:
      continue
    short = _short_type(dev.type_name)
    cur_idx = type_counters.get(short, 0)
    if short == type_str.lower() and cur_idx == idx:
      return f"pcie_{dev.bdf}"
    type_counters[short] = cur_idx + 1

  if type_str.lower() in ("memory", "mem"):
    for node in topo.numa_nodes:
      if node.node_id == idx:
        return f"mc_{idx}"

  return None


def _short_type(type_name: str) -> str:
  mapping = {
    "VGA Controller": "gpu",
    "NVMe Controller": "nvme",
    "Ethernet Controller": "nic",
    "Audio Device": "audio",
    "USB Controller": "usb",
    "SATA Controller": "sata",
    "Processing Accelerator": "npu",
  }
  if type_name.startswith("NPU"):
    return "npu"
  return mapping.get(type_name, type_name.lower().split()[0])


if __name__ == "__main__":
  app()
