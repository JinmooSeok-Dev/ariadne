"""Self-contained collector zipapp 빌더.

원격 호스트의 sysfs/procfs를 수집하기 위해 ariadne의 collector + model + analyzer를
하나의 zipapp(.pyz)으로 패키징한다. SSH로 전송해 `python3 path/to/collector.pyz`
실행 시 stdout으로 SystemTopology JSON을 출력한다.

원격 의존성: python3.10+, pydantic>=2, networkx, pyyaml.
ariadne 자체는 원격에 설치할 필요 없음.

UI/API/cluster 코드는 zipapp에서 제외 — collector에 불필요하고 원격 의존성을 늘림.
"""

import io
import zipfile
from pathlib import Path

_MAIN_SCRIPT = '''\
"""Remote collector entry point. SystemTopology를 stdout JSON으로 출력."""
import sys
from ariadne.model.topology import build_topology


def main() -> None:
  topo = build_topology()
  sys.stdout.write(topo.model_dump_json())


if __name__ == "__main__":
  main()
'''

_EXCLUDED_SUBPKGS = {"cluster", "web", "api", "cli", "viz"}


def _ariadne_pkg_root() -> Path:
  return Path(__file__).resolve().parent.parent  # .../ariadne-core/ariadne/


def list_collector_files() -> list[Path]:
  """zipapp에 포함될 .py 파일 목록. 테스트 + 디버깅용 노출."""
  pkg_root = _ariadne_pkg_root()
  files: list[Path] = []
  for py_file in sorted(pkg_root.rglob("*.py")):
    if "__pycache__" in py_file.parts:
      continue
    rel_parts = py_file.relative_to(pkg_root).parts
    if rel_parts and rel_parts[0] in _EXCLUDED_SUBPKGS:
      continue
    files.append(py_file)
  return files


def build_collector_zipapp() -> bytes:
  """ariadne collector + model + analyzer를 self-contained zipapp(.pyz)으로 빌드.

  반환값을 그대로 .pyz 파일에 쓰거나 SSH stdin으로 전송해 원격에서 `python3 -`
  형태로 실행할 수 있다 (단 stdin 실행은 zip binary가 깨질 수 있어 임시 파일
  업로드 후 실행이 권장됨 — remote.py 참조).
  """
  pkg_root = _ariadne_pkg_root()
  pkg_parent = pkg_root.parent  # .../ariadne-core/

  buf = io.BytesIO()
  with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for py_file in list_collector_files():
      arcname = str(py_file.relative_to(pkg_parent))
      zf.write(py_file, arcname)
    zf.writestr("__main__.py", _MAIN_SCRIPT)
  return buf.getvalue()


def write_zipapp(path: Path) -> Path:
  """zipapp을 디스크에 쓰고 실행 권한 부여."""
  data = build_collector_zipapp()
  path.write_bytes(data)
  path.chmod(0o755)
  return path
