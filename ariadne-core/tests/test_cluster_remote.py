"""Remote SSH 수집 테스트 — mock SSH runner."""

import asyncio
import json

import pytest

from ariadne.cluster.remote import (
  RemoteResult,
  build_cluster_topology,
  collect_cluster,
)
from ariadne.cluster.spec import ClusterSpec, HostSpec
from ariadne.model.types import SystemTopology


class _MockRunner:
  """asyncssh 없이 zipapp 실행을 mock. 호스트별로 다른 결과를 시뮬레이션."""

  def __init__(self, host: HostSpec, *, exit: int = 0,
               stdout: str = "", stderr: str = ""):
    self.host = host
    self.exit = exit
    self.stdout = stdout
    self.stderr = stderr

  async def run_python_zipapp(self, zipapp_bytes: bytes) -> tuple[int, str, str]:
    return self.exit, self.stdout, self.stderr


def _spec(host_ids: list[str]) -> ClusterSpec:
  return ClusterSpec(
    cluster_id="test",
    hosts={hid: HostSpec(id=hid, ansible_host=f"10.0.0.{i + 11}")
           for i, hid in enumerate(host_ids)},
  )


def _topo_json(hostname: str, nic_ip: str = "10.0.0.11") -> str:
  topo = SystemTopology(
    hostname=hostname,
    network_interfaces=[
      {"name": "eth0", "pci_bdf": "0000:5e:00.0",
       "ip_addresses": [f"{nic_ip}/24"], "link_speed_mbps": 100000},
    ],
  )
  return topo.model_dump_json()


def test_collect_cluster_all_success():
  spec = _spec(["h1", "h2"])

  def factory(host: HostSpec) -> _MockRunner:
    ip = host.ansible_host or "10.0.0.99"
    return _MockRunner(host, stdout=_topo_json(host.id, ip))

  results = asyncio.run(collect_cluster(
    spec, ssh_runner_factory=factory, zipapp_bytes=b"fake",
  ))
  assert len(results) == 2
  for host_id, r in results.items():
    assert r.ok is True
    assert r.topology is not None
    assert r.topology.hostname == host_id


def test_collect_cluster_partial_failure():
  spec = _spec(["good", "bad"])

  def factory(host: HostSpec) -> _MockRunner:
    if host.id == "bad":
      return _MockRunner(host, exit=1, stdout="", stderr="ssh: connection refused")
    return _MockRunner(host, stdout=_topo_json(host.id))

  results = asyncio.run(collect_cluster(
    spec, ssh_runner_factory=factory, zipapp_bytes=b"fake",
  ))
  assert results["good"].ok is True
  assert results["bad"].ok is False
  assert "connection refused" in results["bad"].error


def test_collect_cluster_invalid_json_caught():
  spec = _spec(["h1"])
  factory = lambda h: _MockRunner(h, stdout="this is not json")
  results = asyncio.run(collect_cluster(
    spec, ssh_runner_factory=factory, zipapp_bytes=b"fake",
  ))
  assert results["h1"].ok is False
  assert "JSONDecodeError" in results["h1"].error or "json" in results["h1"].error.lower()


def test_build_cluster_topology_assembles_inter_host_links():
  spec = _spec(["h1", "h2"])

  def factory(host: HostSpec) -> _MockRunner:
    ip = "10.0.0.11" if host.id == "h1" else "10.0.0.12"
    return _MockRunner(host, stdout=_topo_json(host.id, ip))

  cluster = asyncio.run(build_cluster_topology(spec, ssh_runner_factory=factory))
  assert cluster.cluster_id == "test"
  assert set(cluster.hosts.keys()) == {"h1", "h2"}
  # 같은 서브넷이라 inter-host link 자동 추론
  assert len(cluster.inter_host_links) == 1
  assert cluster.inter_host_links[0].fabric == "10.0.0.0/24"


def test_build_cluster_topology_skips_failed_hosts():
  spec = _spec(["h1", "h2"])

  def factory(host: HostSpec) -> _MockRunner:
    if host.id == "h2":
      return _MockRunner(host, exit=1, stderr="failed")
    return _MockRunner(host, stdout=_topo_json(host.id))

  cluster = asyncio.run(build_cluster_topology(spec, ssh_runner_factory=factory))
  assert "h1" in cluster.hosts
  assert "h2" not in cluster.hosts
  # 한 호스트만 성공이므로 inter-host link 없음
  assert cluster.inter_host_links == []
