"""Bundler — collector zipapp 빌드 + 로컬 실행 검증."""

import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from ariadne.cluster.bundler import (
  build_collector_zipapp,
  list_collector_files,
  write_zipapp,
)


def test_zipapp_includes_collector_and_model():
  data = build_collector_zipapp()
  with zipfile.ZipFile(io.BytesIO(data)) as zf:
    names = zf.namelist()
  joined = "\n".join(names)
  assert any("collector/cpu.py" in n for n in names)
  assert any("collector/network.py" in n for n in names)
  assert any("collector/infiniband.py" in n for n in names)
  assert any("collector/nvlink.py" in n for n in names)
  assert any("model/types.py" in n for n in names)
  assert any("model/topology.py" in n for n in names)
  assert "__main__.py" in names, joined


def test_zipapp_excludes_cluster_web_api_cli_viz():
  data = build_collector_zipapp()
  with zipfile.ZipFile(io.BytesIO(data)) as zf:
    names = zf.namelist()
  for excluded in ("cluster/", "/web/", "/api/", "/cli/", "/viz/"):
    assert not any(excluded in n for n in names), f"{excluded} found in {names}"


def test_list_collector_files_excludes_subpkgs():
  files = list_collector_files()
  parts = {part for f in files for part in f.parts}
  for excluded in ("cluster", "web", "api", "cli", "viz"):
    assert excluded not in parts


def test_zipapp_runs_locally_and_outputs_json():
  """빌드된 zipapp을 로컬에서 실행 → SystemTopology JSON 출력 확인.

  이 테스트는 sysfs를 읽으므로 Linux 환경 + 일반 사용자 권한에서만 동작.
  """
  data = build_collector_zipapp()
  with tempfile.NamedTemporaryFile(suffix=".pyz", delete=False) as f:
    f.write(data)
    tmp_path = Path(f.name)
  try:
    result = subprocess.run(
      [sys.executable, str(tmp_path)],
      capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = json.loads(result.stdout)
    assert "hostname" in payload
    assert "components" in payload
    assert "links" in payload
    assert "pci_devices" in payload
  finally:
    tmp_path.unlink(missing_ok=True)


def test_write_zipapp_to_disk():
  with tempfile.TemporaryDirectory() as tmpdir:
    path = Path(tmpdir) / "ariadne-collector.pyz"
    written = write_zipapp(path)
    assert written == path
    assert path.exists()
    assert path.stat().st_mode & 0o100  # 실행 권한
