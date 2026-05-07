"""Inter-host link 추론 — IP 서브넷 매칭, IB GID prefix 매칭.

각 호스트의 SystemTopology에서 network_interfaces / ib_devices 정보를
사용해 호스트 간 fabric을 자동 발견한다.

매칭 규칙:
  Ethernet/RoCE — 같은 IPv4 서브넷에 IP를 갖는 NIC들을 동일 fabric으로 묶음
                  (양쪽 모두 RDMA-capable이면 type=rdma, 아니면 ethernet)
  InfiniBand    — 같은 GID subnet prefix(상위 64-bit)를 가진 IB port 쌍
                  (link_layer=InfiniBand이고 GID가 link-local fe80:: 제외)

자동 추론은 best-effort. 정확한 BW/fabric 분리가 필요한 환경에서는 다음
phase에서 사용자 명시 link 입력을 옵션으로 추가한다.
"""

import ipaddress
from itertools import combinations

from pydantic import BaseModel


class InterHostLink(BaseModel):
  from_host: str
  to_host: str
  from_iface: str = ""        # NIC name (eth0) 또는 IB device name (mlx5_0)
  to_iface: str = ""
  type: str = "ethernet"      # "ethernet" | "rdma" | "infiniband"
  bandwidth_gbps: float = 0.0
  latency_ns: float = 0.0
  fabric: str = ""            # subnet CIDR 또는 GID prefix


def infer_inter_host_links(host_topos: dict[str, dict]) -> list[InterHostLink]:
  """host_id → SystemTopology(model_dump 결과 dict) 맵에서 inter-host link 추론.

  SystemTopology 객체가 아닌 dict를 받는 이유: cluster 단계에서 원격 수집된
  결과를 JSON으로 받아 그대로 처리할 수 있게 하기 위함 (Pydantic round-trip 비용 절감).
  """
  links: list[InterHostLink] = []
  links.extend(_infer_ip_subnet_links(host_topos))
  links.extend(_infer_ib_fabric_links(host_topos))
  return links


def _infer_ip_subnet_links(host_topos: dict[str, dict]) -> list[InterHostLink]:
  """같은 IPv4 서브넷에 속하는 NIC 쌍을 묶는다."""
  # (host_id, iface_name, network, prefix-len, link_speed_mbps, has_rdma)
  endpoints: list[tuple[str, str, ipaddress.IPv4Network, int, int, bool]] = []
  for host_id, topo in host_topos.items():
    for nic in topo.get("network_interfaces") or []:
      ip_addrs = nic.get("ip_addresses") or []
      for ip_str in ip_addrs:
        if "/" not in ip_str:
          continue
        try:
          iface = ipaddress.ip_interface(ip_str)
        except ValueError:
          continue
        if iface.version != 4:
          continue  # IPv6는 향후
        if iface.ip.is_loopback or iface.ip.is_link_local:
          continue
        endpoints.append((
          host_id,
          nic.get("name", ""),
          iface.network,
          iface.network.prefixlen,
          int(nic.get("link_speed_mbps", 0)),
          bool(nic.get("rdma_device")),
        ))

  by_subnet: dict[ipaddress.IPv4Network, list] = {}
  for ep in endpoints:
    by_subnet.setdefault(ep[2], []).append(ep)

  links: list[InterHostLink] = []
  for subnet, members in by_subnet.items():
    # /32 (point-to-point host route 등)는 inter-host fabric으로 보지 않음
    if subnet.prefixlen >= 31:
      continue
    for a, b in combinations(members, 2):
      if a[0] == b[0]:
        continue  # 같은 호스트 내 두 NIC
      bw_mbps = min(a[4], b[4])
      bw_gbps = round(bw_mbps / 1000.0, 1) if bw_mbps > 0 else 0.0
      both_rdma = a[5] and b[5]
      links.append(InterHostLink(
        from_host=a[0],
        to_host=b[0],
        from_iface=a[1],
        to_iface=b[1],
        type="rdma" if both_rdma else "ethernet",
        bandwidth_gbps=bw_gbps,
        fabric=str(subnet),
      ))
  return links


_IB_LINK_LOCAL_PREFIX = "fe80:0000:0000:0000"


def _infer_ib_fabric_links(host_topos: dict[str, dict]) -> list[InterHostLink]:
  """InfiniBand HCA의 GID subnet prefix(상위 64-bit) 매칭."""
  endpoints = []  # (host_id, dev_name, port_num, gid, rate_gbps)
  for host_id, topo in host_topos.items():
    for ibdev in topo.get("ib_devices") or []:
      dev_name = ibdev.get("name", "")
      for port in ibdev.get("ports") or []:
        if port.get("link_layer") != "InfiniBand":
          continue
        if port.get("state") != "ACTIVE":
          continue
        for gid in port.get("gids") or []:
          # GID는 16-byte hex. 상위 64-bit가 subnet prefix.
          # link-local fe80::는 같은 IB subnet 내 항상 동일 → fabric 식별에 무의미
          if gid.startswith(_IB_LINK_LOCAL_PREFIX):
            continue
          subnet_prefix = ":".join(gid.split(":")[:4])
          endpoints.append((host_id, dev_name, port["port"], subnet_prefix,
                            float(port.get("rate_gbps", 0))))

  by_prefix: dict[str, list] = {}
  for ep in endpoints:
    by_prefix.setdefault(ep[3], []).append(ep)

  links: list[InterHostLink] = []
  for prefix, members in by_prefix.items():
    for a, b in combinations(members, 2):
      if a[0] == b[0]:
        continue
      bw = min(a[4], b[4])
      links.append(InterHostLink(
        from_host=a[0],
        to_host=b[0],
        from_iface=f"{a[1]}.p{a[2]}",
        to_iface=f"{b[1]}.p{b[2]}",
        type="infiniband",
        bandwidth_gbps=bw,
        fabric=f"ib:{prefix}",
      ))
  return links
