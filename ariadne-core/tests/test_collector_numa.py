"""NUMA Collector 테스트."""

from pathlib import Path
from textwrap import dedent
import tempfile

from ariadne.collector.numa import parse_cpu_list, collect_numa_nodes


def test_parse_cpu_list_range():
  assert parse_cpu_list("0-3") == [0, 1, 2, 3]


def test_parse_cpu_list_mixed():
  assert parse_cpu_list("0-3,8-11") == [0, 1, 2, 3, 8, 9, 10, 11]


def test_parse_cpu_list_single():
  assert parse_cpu_list("5") == [5]


def test_parse_cpu_list_empty():
  assert parse_cpu_list("") == []


def test_collect_numa_nodes_mock():
  """가상 sysfs 구조로 NUMA 수집 테스트."""
  with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir)

    node0 = base / "node0"
    node0.mkdir()
    (node0 / "cpulist").write_text("0-3\n")
    (node0 / "meminfo").write_text(
      "Node 0 MemTotal:       16384000 kB\n"
      "Node 0 MemFree:         8192000 kB\n"
    )
    (node0 / "distance").write_text("10 21\n")

    node1 = base / "node1"
    node1.mkdir()
    (node1 / "cpulist").write_text("4-7\n")
    (node1 / "meminfo").write_text(
      "Node 1 MemTotal:       16384000 kB\n"
    )
    (node1 / "distance").write_text("21 10\n")

    nodes = collect_numa_nodes(sysfs_base=base)

    assert len(nodes) == 2
    assert nodes[0].node_id == 0
    assert nodes[0].cpu_list == [0, 1, 2, 3]
    assert nodes[0].memory_mb == 16000
    assert nodes[0].distances == {0: 10, 1: 21}
    assert nodes[1].node_id == 1
    assert nodes[1].cpu_list == [4, 5, 6, 7]
