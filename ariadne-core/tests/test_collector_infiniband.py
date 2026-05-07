"""InfiniBand collector 테스트 — 가짜 /sys/class/infiniband 디렉터리."""

import tempfile
from pathlib import Path

from ariadne.collector.infiniband import collect_ib_devices


def _make_pci(pci_root: Path, bdf: str, vendor: str = "0x15b3", device: str = "0x101d") -> Path:
  pci = pci_root / bdf
  pci.mkdir()
  (pci / "vendor").write_text(vendor + "\n")
  (pci / "device").write_text(device + "\n")
  return pci


def _make_ib_device(ib_root: Path, name: str, *, fw_ver="20.31.1014",
                    node_guid="0x506b4b03004cd5a0",
                    sys_image_guid="0x506b4b03004cd5a0",
                    hca_type="MT4129",
                    pci_dev: Path | None = None) -> Path:
  dev = ib_root / name
  dev.mkdir()
  (dev / "fw_ver").write_text(fw_ver + "\n")
  (dev / "node_guid").write_text(node_guid + "\n")
  (dev / "sys_image_guid").write_text(sys_image_guid + "\n")
  (dev / "hca_type").write_text(hca_type + "\n")
  if pci_dev is not None:
    (dev / "device").symlink_to(pci_dev)
  return dev


def _make_port(ib_dev: Path, port_num: int, *, state="4: ACTIVE",
               phys_state="5: LinkUp", rate="200 Gb/sec (4X HDR)",
               link_layer="InfiniBand", gids: list[str] | None = None):
  port = ib_dev / "ports" / str(port_num)
  port.mkdir(parents=True)
  (port / "state").write_text(state + "\n")
  (port / "phys_state").write_text(phys_state + "\n")
  (port / "rate").write_text(rate + "\n")
  (port / "link_layer").write_text(link_layer + "\n")
  gids_dir = port / "gids"
  gids_dir.mkdir()
  for i, gid in enumerate(gids or []):
    (gids_dir / str(i)).write_text(gid + "\n")


def test_collect_active_ib_hca():
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    ib_root = tmp / "infiniband"
    ib_root.mkdir()
    pci_root = tmp / "pci"
    pci_root.mkdir()

    pci = _make_pci(pci_root, "0000:5e:00.0", vendor="0x15b3", device="0x101d")
    ib_dev = _make_ib_device(ib_root, "mlx5_0", pci_dev=pci)
    _make_port(ib_dev, 1, gids=[
      "fe80:0000:0000:0000:0250:56ff:fe89:abcd",
      "0000:0000:0000:0000:0000:0000:0000:0000",  # 빈 GID — 제외되어야 함
      "fe80:0000:0000:0000:0250:56ff:fe89:abce",
    ])

    devs = collect_ib_devices(sysfs_infiniband=ib_root)
    assert len(devs) == 1
    d = devs[0]
    assert d.name == "mlx5_0"
    assert d.pci_bdf == "0000:5e:00.0"
    assert d.vendor == 0x15b3
    assert d.device_id == 0x101d
    assert d.fw_ver == "20.31.1014"
    assert d.node_guid == "0x506b4b03004cd5a0"
    assert d.hca_type == "MT4129"
    assert len(d.ports) == 1

    p = d.ports[0]
    assert p.port == 1
    assert p.state == "ACTIVE"          # "4: ACTIVE" → "ACTIVE"
    assert p.phys_state == "LinkUp"
    assert p.rate == "200 Gb/sec (4X HDR)"
    assert p.rate_gbps == 200.0
    assert p.link_layer == "InfiniBand"
    assert len(p.gids) == 2  # 빈 GID 제외
    assert p.gids[0] == "fe80:0000:0000:0000:0250:56ff:fe89:abcd"


def test_collect_roce_link_layer():
  """RoCE: link_layer=Ethernet인 IB HCA."""
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    ib_root = tmp / "infiniband"
    ib_root.mkdir()
    ib_dev = _make_ib_device(ib_root, "mlx5_1")
    _make_port(ib_dev, 1, link_layer="Ethernet", rate="100 Gb/sec (4X EDR)",
               gids=["fe80:0000:0000:0000:1234:5678:abcd:ef00"])

    devs = collect_ib_devices(sysfs_infiniband=ib_root)
    assert devs[0].ports[0].link_layer == "Ethernet"
    assert devs[0].ports[0].rate_gbps == 100.0


def test_collect_down_port():
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    ib_root = tmp / "infiniband"
    ib_root.mkdir()
    ib_dev = _make_ib_device(ib_root, "mlx5_0")
    _make_port(ib_dev, 1, state="1: DOWN", phys_state="3: Disabled",
               rate="10 Gb/sec (4X)", link_layer="InfiniBand", gids=[])

    devs = collect_ib_devices(sysfs_infiniband=ib_root)
    p = devs[0].ports[0]
    assert p.state == "DOWN"
    assert p.phys_state == "Disabled"
    assert p.gids == []


def test_collect_dual_port_hca():
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    ib_root = tmp / "infiniband"
    ib_root.mkdir()
    ib_dev = _make_ib_device(ib_root, "mlx5_0")
    _make_port(ib_dev, 1, gids=["fe80::1"])
    _make_port(ib_dev, 2, gids=["fe80::2"])

    devs = collect_ib_devices(sysfs_infiniband=ib_root)
    ports = devs[0].ports
    assert [p.port for p in ports] == [1, 2]
    assert ports[0].gids == ["fe80::1"]
    assert ports[1].gids == ["fe80::2"]


def test_collect_no_pci_link():
  """일부 가상/특수 HCA는 device 심볼릭 링크가 없을 수 있다."""
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    ib_root = tmp / "infiniband"
    ib_root.mkdir()
    _make_ib_device(ib_root, "rxe0")  # pci_dev=None

    devs = collect_ib_devices(sysfs_infiniband=ib_root)
    assert devs[0].pci_bdf == ""
    assert devs[0].vendor == 0


def test_collect_missing_sysfs():
  assert collect_ib_devices(sysfs_infiniband=Path("/nonexistent")) == []


def test_rate_parsing_variants():
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    ib_root = tmp / "infiniband"
    ib_root.mkdir()
    ib_dev = _make_ib_device(ib_root, "mlx5_0")
    _make_port(ib_dev, 1, rate="400 Gb/sec (4X NDR)")  # NDR 400Gbps

    devs = collect_ib_devices(sysfs_infiniband=ib_root)
    assert devs[0].ports[0].rate_gbps == 400.0
