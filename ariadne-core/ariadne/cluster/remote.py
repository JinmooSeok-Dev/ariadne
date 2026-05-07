"""SSH 기반 원격 수집 — asyncssh 사용.

bundler가 만든 zipapp을 sftp로 임시 디렉터리에 업로드 → ssh로 실행 →
stdout JSON 캡쳐 → 임시 파일 정리.

asyncssh는 ~/.ssh/config을 자동 활용하므로 inventory에서 ansible_host만 있으면
일반적으로 동작한다 (ssh_config의 IdentityFile, ProxyJump 등 인식).

mock 가능한 구조: AsyncSSHClientFactory를 인자로 받아 테스트에서 가짜 클라이언트
주입.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from ariadne.cluster.bundler import build_collector_zipapp
from ariadne.cluster.spec import ClusterSpec, HostSpec
from ariadne.model.types import SystemTopology


class RemoteResult(BaseModel):
  host_id: str
  ok: bool
  topology: SystemTopology | None = None
  error: str = ""


class _SSHRunner(Protocol):
  """asyncssh.SSHClientConnection 의 부분 인터페이스. mock 주입용."""

  async def run_python_zipapp(self, zipapp_bytes: bytes) -> tuple[int, str, str]:
    """zipapp을 원격에서 실행하고 (returncode, stdout, stderr) 반환."""
    ...


async def collect_cluster(
  spec: ClusterSpec,
  ssh_runner_factory: Callable[[HostSpec], "_SSHRunner"] | None = None,
  zipapp_bytes: bytes | None = None,
) -> dict[str, RemoteResult]:
  """spec의 모든 호스트에 대해 병렬 원격 수집.

  - ssh_runner_factory: 각 HostSpec에 대해 _SSHRunner 인스턴스를 만드는 팩토리.
    None이면 default(asyncssh) 사용.
  - zipapp_bytes: 미리 빌드한 zipapp. None이면 build_collector_zipapp() 호출.
  """
  if zipapp_bytes is None:
    zipapp_bytes = build_collector_zipapp()
  factory = ssh_runner_factory or _default_ssh_runner

  tasks = {
    host_id: _collect_one(host_id, host, factory, zipapp_bytes)
    for host_id, host in spec.hosts.items()
  }
  results = await asyncio.gather(*tasks.values(), return_exceptions=True)

  out: dict[str, RemoteResult] = {}
  for (host_id, _), result in zip(tasks.items(), results):
    if isinstance(result, BaseException):
      out[host_id] = RemoteResult(host_id=host_id, ok=False, error=str(result))
    else:
      out[host_id] = result
  return out


async def _collect_one(
  host_id: str,
  host: HostSpec,
  factory: Callable[[HostSpec], _SSHRunner],
  zipapp_bytes: bytes,
) -> RemoteResult:
  try:
    runner = factory(host)
    rc, stdout, stderr = await runner.run_python_zipapp(zipapp_bytes)
    if rc != 0:
      return RemoteResult(host_id=host_id, ok=False,
                          error=f"remote exit {rc}: {stderr.strip()}")
    data = json.loads(stdout)
    topo = SystemTopology(**data)
    return RemoteResult(host_id=host_id, ok=True, topology=topo)
  except Exception as e:
    return RemoteResult(host_id=host_id, ok=False, error=f"{type(e).__name__}: {e}")


def _default_ssh_runner(host: HostSpec) -> _SSHRunner:
  """asyncssh 기반 기본 runner. 필요 시점에만 import해서 의존 누수 방지."""
  return _AsyncSSHRunner(host)


class _AsyncSSHRunner:
  """asyncssh로 zipapp을 sftp 업로드 + 원격 실행."""

  def __init__(self, host: HostSpec) -> None:
    self.host = host

  async def run_python_zipapp(self, zipapp_bytes: bytes) -> tuple[int, str, str]:
    import asyncssh

    options: dict = {}
    if self.host.ansible_user:
      options["username"] = self.host.ansible_user
    if self.host.ansible_port:
      options["port"] = self.host.ansible_port
    if self.host.ansible_ssh_private_key_file:
      options["client_keys"] = [self.host.ansible_ssh_private_key_file]
    options.setdefault("known_hosts", None)  # 1차에서는 host key check 생략 (운영 시 정책 결정)

    target = self.host.ssh_hostname()
    remote_path = f"/tmp/ariadne-collector-{self.host.id}.pyz"
    try:
      async with asyncssh.connect(target, **options) as conn:
        async with conn.start_sftp_client() as sftp:
          async with sftp.open(remote_path, "wb") as f:
            await f.write(zipapp_bytes)
        result = await conn.run(f"python3 {remote_path}", check=False, timeout=120)
        # 정리
        await conn.run(f"rm -f {remote_path}", check=False, timeout=10)
        return (
          int(result.exit_status or 0),
          str(result.stdout or ""),
          str(result.stderr or ""),
        )
    except Exception:
      raise


async def build_cluster_topology(
  spec: ClusterSpec,
  ssh_runner_factory: Callable[[HostSpec], _SSHRunner] | None = None,
) -> "ClusterTopology":
  """ClusterSpec → 원격 수집 → ClusterTopology 조립.

  실패한 호스트는 hosts에서 제외하고 inter-host link 추론은 성공한 호스트만 대상.
  실패 정보는 stderr에 요약 출력 — 향후 ClusterTopology에 errors 필드 추가 가능.
  """
  from ariadne.cluster.links import infer_inter_host_links
  from ariadne.model.cluster import ClusterTopology

  remote_results = await collect_cluster(spec, ssh_runner_factory=ssh_runner_factory)
  hosts: dict[str, SystemTopology] = {}
  for host_id, r in remote_results.items():
    if r.ok and r.topology is not None:
      hosts[host_id] = r.topology
    else:
      import sys
      sys.stderr.write(f"[ariadne] host {host_id} 수집 실패: {r.error}\n")

  host_topo_dicts = {h: t.model_dump() for h, t in hosts.items()}
  inter_links = infer_inter_host_links(host_topo_dicts)

  return ClusterTopology(
    cluster_id=spec.cluster_id,
    hosts=hosts,
    inter_host_links=inter_links,
    groups=spec.groups,
  )
