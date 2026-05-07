"""Network interface collector 테스트 — 가짜 sysfs 디렉터리 + ip runner mock."""

import tempfile
from pathlib import Path

from ariadne.collector.network import collect_network_interfaces


def _make_sysfs(tmp: Path):
  cls_net = tmp / "class" / "net"
  cls_net.mkdir(parents=True)
  cls_ib = tmp / "class" / "infiniband"
  cls_ib.mkdir(parents=True)
  pci_devices = tmp / "pci_devices"
  pci_devices.mkdir()
  return cls_net, cls_ib, pci_devices


def _make_iface(cls_net: Path, name: str, mac: str = "", speed: int = 1000,
                mtu: int = 1500, operstate: str = "up", carrier: bool = True,
                pci_dev: Path | None = None):
  iface = cls_net / name
  iface.mkdir()
  (iface / "address").write_text(mac + "\n")
  (iface / "speed").write_text(f"{speed}\n")
  (iface / "mtu").write_text(f"{mtu}\n")
  (iface / "operstate").write_text(operstate + "\n")
  (iface / "carrier").write_text("1\n" if carrier else "0\n")
  if pci_dev is not None:
    (iface / "device").symlink_to(pci_dev)


def _make_pci_dev(pci_devices: Path, bdf: str) -> Path:
  p = pci_devices / bdf
  p.mkdir()
  return p


def test_collect_simple_ethernet():
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    cls_net, cls_ib, pci_devices = _make_sysfs(tmp)
    pci_dev = _make_pci_dev(pci_devices, "0000:01:00.0")
    _make_iface(cls_net, "eth0", mac="aa:bb:cc:dd:ee:00", speed=10000, pci_dev=pci_dev)

    def mock_ip():
      return [{
        "ifname": "eth0",
        "addr_info": [
          {"family": "inet", "local": "10.0.0.11", "prefixlen": 24},
          {"family": "inet6", "local": "fe80::1", "prefixlen": 64},
        ],
      }]

    result = collect_network_interfaces(
      sysfs_class_net=cls_net,
      sysfs_infiniband=cls_ib,
      ip_runner=mock_ip,
    )
    assert len(result) == 1
    eth0 = result[0]
    assert eth0.name == "eth0"
    assert eth0.mac_address == "aa:bb:cc:dd:ee:00"
    assert eth0.pci_bdf == "0000:01:00.0"
    assert eth0.link_speed_mbps == 10000
    assert eth0.mtu == 1500
    assert eth0.operstate == "up"
    assert eth0.carrier is True
    assert eth0.ip_addresses == ["10.0.0.11/24", "fe80::1/64"]
    assert eth0.rdma_device == ""
    assert eth0.port_gid == ""


def test_collect_excludes_loopback_by_default():
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    cls_net, cls_ib, _ = _make_sysfs(tmp)
    _make_iface(cls_net, "lo", speed=0, mtu=65536)
    _make_iface(cls_net, "eth0")

    result = collect_network_interfaces(
      sysfs_class_net=cls_net, sysfs_infiniband=cls_ib, ip_runner=lambda: [],
    )
    assert {i.name for i in result} == {"eth0"}

    result_with_lo = collect_network_interfaces(
      sysfs_class_net=cls_net, sysfs_infiniband=cls_ib, ip_runner=lambda: [],
      include_loopback=True,
    )
    assert "lo" in {i.name for i in result_with_lo}


def test_collect_rdma_roce_mapping():
  """RoCE NIC: /sys/class/net/eth1/device/infiniband/mlx5_0 + GID는 /sys/class/infiniband에서 읽음."""
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    cls_net, cls_ib, pci_devices = _make_sysfs(tmp)
    pci_dev = _make_pci_dev(pci_devices, "0000:5e:00.0")
    (pci_dev / "infiniband" / "mlx5_0").mkdir(parents=True)

    ib_dev = cls_ib / "mlx5_0"
    port = ib_dev / "ports" / "1"
    port.mkdir(parents=True)
    (port / "gids").mkdir()
    (port / "gids" / "0").write_text("fe80:0000:0000:0000:0250:56ff:fe89:abcd\n")

    _make_iface(cls_net, "eth1", mac="aa:bb:cc:dd:ee:11", pci_dev=pci_dev)

    result = collect_network_interfaces(
      sysfs_class_net=cls_net, sysfs_infiniband=cls_ib, ip_runner=lambda: [],
    )
    assert len(result) == 1
    nic = result[0]
    assert nic.rdma_device == "mlx5_0"
    assert nic.port_gid == "fe80:0000:0000:0000:0250:56ff:fe89:abcd"


def test_collect_no_pci_device():
  """가상/브리지 인터페이스 — pci_bdf 비어 있어도 정상 동작."""
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    cls_net, cls_ib, _ = _make_sysfs(tmp)
    _make_iface(cls_net, "br0", mac="aa:bb:cc:dd:ee:22")

    result = collect_network_interfaces(
      sysfs_class_net=cls_net, sysfs_infiniband=cls_ib, ip_runner=lambda: [],
    )
    assert result[0].pci_bdf == ""
    assert result[0].rdma_device == ""


def test_collect_speed_negative_when_down():
  """down 상태의 NIC는 speed -1을 반환할 수 있다 → 0으로 정규화."""
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    cls_net, cls_ib, _ = _make_sysfs(tmp)
    _make_iface(cls_net, "eth0", speed=-1, operstate="down", carrier=False)

    result = collect_network_interfaces(
      sysfs_class_net=cls_net, sysfs_infiniband=cls_ib, ip_runner=lambda: [],
    )
    assert result[0].link_speed_mbps == 0
    assert result[0].operstate == "down"
    assert result[0].carrier is False


def test_collect_no_ip_data():
  """ip 명령 미설치/실패 시 IP는 빈 리스트, NIC 자체는 정상 수집."""
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    cls_net, cls_ib, _ = _make_sysfs(tmp)
    _make_iface(cls_net, "eth0")

    result = collect_network_interfaces(
      sysfs_class_net=cls_net, sysfs_infiniband=cls_ib, ip_runner=lambda: [],
    )
    assert result[0].ip_addresses == []


def test_collect_missing_sysfs():
  result = collect_network_interfaces(
    sysfs_class_net=Path("/nonexistent/path"),
    sysfs_infiniband=Path("/nonexistent/ib"),
    ip_runner=lambda: [],
  )
  assert result == []


def test_collect_multiple_interfaces():
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    cls_net, cls_ib, pci_devices = _make_sysfs(tmp)
    _make_iface(cls_net, "eth0", mac="00:11:22:33:44:00",
                pci_dev=_make_pci_dev(pci_devices, "0000:01:00.0"))
    _make_iface(cls_net, "eth1", mac="00:11:22:33:44:01",
                pci_dev=_make_pci_dev(pci_devices, "0000:01:00.1"))

    def mock_ip():
      return [
        {"ifname": "eth0", "addr_info": [
          {"family": "inet", "local": "10.0.0.11", "prefixlen": 24}]},
        {"ifname": "eth1", "addr_info": [
          {"family": "inet", "local": "10.1.0.11", "prefixlen": 24}]},
      ]

    result = collect_network_interfaces(
      sysfs_class_net=cls_net, sysfs_infiniband=cls_ib, ip_runner=mock_ip,
    )
    assert {i.name for i in result} == {"eth0", "eth1"}
    by_name = {i.name: i for i in result}
    assert by_name["eth0"].ip_addresses == ["10.0.0.11/24"]
    assert by_name["eth1"].ip_addresses == ["10.1.0.11/24"]
