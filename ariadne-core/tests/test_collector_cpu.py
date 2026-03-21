"""CPU Collector 테스트."""

import tempfile
from pathlib import Path

from ariadne.collector.cpu import collect_cpu_cores, collect_caches


def _create_cpu_sysfs(base: Path, cpu_id: int, core_id: int, pkg_id: int, siblings: str):
  """가상 CPU sysfs 구조 생성."""
  cpu_dir = base / f"cpu{cpu_id}"
  topo_dir = cpu_dir / "topology"
  topo_dir.mkdir(parents=True)
  (topo_dir / "core_id").write_text(f"{core_id}\n")
  (topo_dir / "physical_package_id").write_text(f"{pkg_id}\n")
  (topo_dir / "thread_siblings_list").write_text(f"{siblings}\n")


def _create_cache_sysfs(base: Path, cpu_id: int, index: int, level: int,
                        type_str: str, size: str, shared_cpus: str):
  """가상 Cache sysfs 구조 생성."""
  cache_dir = base / f"cpu{cpu_id}" / "cache" / f"index{index}"
  cache_dir.mkdir(parents=True, exist_ok=True)
  (cache_dir / "level").write_text(f"{level}\n")
  (cache_dir / "type").write_text(f"{type_str}\n")
  (cache_dir / "size").write_text(f"{size}\n")
  (cache_dir / "shared_cpu_list").write_text(f"{shared_cpus}\n")
  (cache_dir / "coherency_line_size").write_text("64\n")


def test_collect_cpu_cores_smt():
  """SMT (P-core) 구성 테스트."""
  with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir)
    _create_cpu_sysfs(base, 0, core_id=0, pkg_id=0, siblings="0,1")
    _create_cpu_sysfs(base, 1, core_id=0, pkg_id=0, siblings="0,1")
    _create_cpu_sysfs(base, 2, core_id=4, pkg_id=0, siblings="2,3")
    _create_cpu_sysfs(base, 3, core_id=4, pkg_id=0, siblings="2,3")

    cores = collect_cpu_cores(sysfs_base=base)
    assert len(cores) == 2
    assert cores[0].core_id == 0
    assert cores[0].thread_siblings == [0, 1]
    assert cores[1].core_id == 4
    assert cores[1].thread_siblings == [2, 3]


def test_collect_cpu_cores_no_smt():
  """E-core (SMT 없음) 구성 테스트."""
  with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir)
    _create_cpu_sysfs(base, 0, core_id=32, pkg_id=0, siblings="0")
    _create_cpu_sysfs(base, 1, core_id=33, pkg_id=0, siblings="1")

    cores = collect_cpu_cores(sysfs_base=base)
    assert len(cores) == 2
    assert cores[0].thread_siblings == [0]
    assert cores[1].thread_siblings == [1]


def test_collect_cpu_cores_multi_socket():
  """2-socket 구성 테스트."""
  with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir)
    _create_cpu_sysfs(base, 0, core_id=0, pkg_id=0, siblings="0,1")
    _create_cpu_sysfs(base, 1, core_id=0, pkg_id=0, siblings="0,1")
    _create_cpu_sysfs(base, 2, core_id=0, pkg_id=1, siblings="2,3")
    _create_cpu_sysfs(base, 3, core_id=0, pkg_id=1, siblings="2,3")

    cores = collect_cpu_cores(sysfs_base=base)
    assert len(cores) == 2
    assert cores[0].physical_package_id == 0
    assert cores[1].physical_package_id == 1


def test_collect_caches():
  """Cache 수집 테스트."""
  with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir)
    _create_cpu_sysfs(base, 0, core_id=0, pkg_id=0, siblings="0,1")
    _create_cache_sysfs(base, 0, index=0, level=1, type_str="Data", size="48K", shared_cpus="0,1")
    _create_cache_sysfs(base, 0, index=1, level=1, type_str="Instruction", size="32K", shared_cpus="0,1")
    _create_cache_sysfs(base, 0, index=2, level=2, type_str="Unified", size="2048K", shared_cpus="0,1")
    _create_cache_sysfs(base, 0, index=3, level=3, type_str="Unified", size="33792K", shared_cpus="0-7")

    caches = collect_caches(sysfs_base=base)
    assert len(caches) == 4

    l3 = [c for c in caches if c.level.value == "l3"]
    assert len(l3) == 1
    assert l3[0].size_kb == 33792
    assert l3[0].shared_cpu_list == [0, 1, 2, 3, 4, 5, 6, 7]
