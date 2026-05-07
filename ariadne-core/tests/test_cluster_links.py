"""Inter-host link 추론 테스트."""

from ariadne.cluster.links import infer_inter_host_links


def _host_with_nic(host_id: str, ip: str, prefix: int = 24, *,
                   speed_mbps: int = 10000, rdma: bool = False,
                   name: str = "eth0", bdf: str = "0000:01:00.0") -> dict:
  return {
    "network_interfaces": [{
      "name": name,
      "pci_bdf": bdf,
      "ip_addresses": [f"{ip}/{prefix}"],
      "link_speed_mbps": speed_mbps,
      "rdma_device": "mlx5_0" if rdma else "",
    }],
    "ib_devices": [],
  }


def test_two_hosts_same_subnet_ethernet():
  topos = {
    "h1": _host_with_nic("h1", "10.0.0.11"),
    "h2": _host_with_nic("h2", "10.0.0.12"),
  }
  links = infer_inter_host_links(topos)
  assert len(links) == 1
  link = links[0]
  assert {link.from_host, link.to_host} == {"h1", "h2"}
  assert link.type == "ethernet"
  assert link.bandwidth_gbps == 10.0  # 10000 Mbps
  assert link.fabric == "10.0.0.0/24"


def test_two_hosts_both_rdma_capable():
  topos = {
    "h1": _host_with_nic("h1", "10.0.0.11", rdma=True),
    "h2": _host_with_nic("h2", "10.0.0.12", rdma=True),
  }
  links = infer_inter_host_links(topos)
  assert links[0].type == "rdma"


def test_different_subnets_no_link():
  topos = {
    "h1": _host_with_nic("h1", "10.0.0.11", prefix=24),
    "h2": _host_with_nic("h2", "10.1.0.11", prefix=24),
  }
  links = infer_inter_host_links(topos)
  ethernet_links = [link for link in links if link.type in {"ethernet", "rdma"}]
  assert ethernet_links == []


def test_loopback_and_link_local_excluded():
  topos = {
    "h1": _host_with_nic("h1", "127.0.0.1", prefix=8, name="lo"),
    "h2": _host_with_nic("h2", "169.254.1.1", prefix=16, name="eth0"),
  }
  links = infer_inter_host_links(topos)
  assert links == []


def test_min_bandwidth_used():
  """양쪽 NIC speed가 다르면 작은 쪽이 fabric BW."""
  topos = {
    "h1": _host_with_nic("h1", "10.0.0.11", speed_mbps=100000),  # 100G
    "h2": _host_with_nic("h2", "10.0.0.12", speed_mbps=25000),   # 25G
  }
  links = infer_inter_host_links(topos)
  assert links[0].bandwidth_gbps == 25.0


def test_three_hosts_all_in_same_subnet():
  """3 호스트 → C(3,2) = 3 link."""
  topos = {
    "h1": _host_with_nic("h1", "10.0.0.11"),
    "h2": _host_with_nic("h2", "10.0.0.12"),
    "h3": _host_with_nic("h3", "10.0.0.13"),
  }
  links = infer_inter_host_links(topos)
  pairs = {tuple(sorted([link.from_host, link.to_host])) for link in links}
  assert pairs == {("h1", "h2"), ("h1", "h3"), ("h2", "h3")}


def test_ib_fabric_matched_by_gid_prefix():
  topos = {
    "h1": {
      "network_interfaces": [],
      "ib_devices": [{
        "name": "mlx5_0",
        "ports": [{
          "port": 1,
          "state": "ACTIVE",
          "rate_gbps": 200.0,
          "link_layer": "InfiniBand",
          "gids": ["0fe8:0000:0000:0000:1234:5678:abcd:0001",
                   "fe80:0000:0000:0000:1234:5678:abcd:0001"],  # link-local 제외됨
        }],
      }],
    },
    "h2": {
      "network_interfaces": [],
      "ib_devices": [{
        "name": "mlx5_0",
        "ports": [{
          "port": 1,
          "state": "ACTIVE",
          "rate_gbps": 200.0,
          "link_layer": "InfiniBand",
          "gids": ["0fe8:0000:0000:0000:1234:5678:abcd:0002"],
        }],
      }],
    },
  }
  links = infer_inter_host_links(topos)
  ib = [link for link in links if link.type == "infiniband"]
  assert len(ib) == 1
  assert ib[0].bandwidth_gbps == 200.0
  assert ib[0].fabric.startswith("ib:0fe8:")


def test_ib_inactive_port_skipped():
  topos = {
    "h1": {
      "network_interfaces": [],
      "ib_devices": [{
        "name": "mlx5_0",
        "ports": [{
          "port": 1,
          "state": "DOWN",
          "rate_gbps": 200.0,
          "link_layer": "InfiniBand",
          "gids": ["0fe8:0000:0000:0000:1111:2222:3333:0001"],
        }],
      }],
    },
    "h2": {
      "network_interfaces": [],
      "ib_devices": [{
        "name": "mlx5_0",
        "ports": [{
          "port": 1,
          "state": "ACTIVE",
          "rate_gbps": 200.0,
          "link_layer": "InfiniBand",
          "gids": ["0fe8:0000:0000:0000:1111:2222:3333:0002"],
        }],
      }],
    },
  }
  links = infer_inter_host_links(topos)
  assert [link for link in links if link.type == "infiniband"] == []


def test_empty_topos():
  assert infer_inter_host_links({}) == []
