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
    f"{len(topo.components)} components"
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


if __name__ == "__main__":
  app()
