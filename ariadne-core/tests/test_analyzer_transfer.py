"""Transfer mode 식별 테스트."""

from ariadne.analyzer.transfer import list_transfer_modes
from ariadne.model.types import (
  Component,
  ComponentType,
  Link,
  LinkType,
  PCIDevice,
  SystemTopology,
)


def _topo_with_two_gpus_nvlink() -> SystemTopology:
  return SystemTopology(
    components=[
      Component(id="pcie_0000:01:00.0", type=ComponentType.GPU, name="GPU 0",
                attrs={"bdf": "0000:01:00.0"}),
      Component(id="pcie_0000:25:00.0", type=ComponentType.GPU, name="GPU 1",
                attrs={"bdf": "0000:25:00.0"}),
    ],
    pci_devices=[
      PCIDevice(bdf="0000:01:00.0", component_type="gpu", numa_node=0),
      PCIDevice(bdf="0000:25:00.0", component_type="gpu", numa_node=0),
    ],
    links=[
      Link(source="pcie_0000:01:00.0", target="pcie_0000:25:00.0",
           type=LinkType.NVLINK, bandwidth_gbps=300.0,
           attrs={"link_count": 12}),
    ],
  )


def test_dma_always_available():
  topo = _topo_with_two_gpus_nvlink()
  modes = list_transfer_modes(topo, "pcie_0000:01:00.0", "pcie_0000:25:00.0")
  names = [m.name for m in modes]
  assert "dma" in names


def test_nvlink_detected_when_edge_present():
  topo = _topo_with_two_gpus_nvlink()
  modes = list_transfer_modes(topo, "pcie_0000:01:00.0", "pcie_0000:25:00.0")
  nvlink = next((m for m in modes if m.name == "nvlink"), None)
  assert nvlink is not None
  assert nvlink.estimated_bandwidth_gbps == 300.0
  assert "12" in nvlink.reason


def test_p2p_detected_same_numa_node():
  topo = _topo_with_two_gpus_nvlink()
  modes = list_transfer_modes(topo, "pcie_0000:01:00.0", "pcie_0000:25:00.0")
  assert "p2p" in [m.name for m in modes]


def test_gpudirect_rdma_detected_with_rdma_nic():
  topo = SystemTopology(
    components=[
      Component(id="pcie_0000:01:00.0", type=ComponentType.GPU, name="GPU"),
      Component(id="pcie_0000:5e:00.0", type=ComponentType.NIC, name="NIC"),
    ],
    pci_devices=[
      PCIDevice(bdf="0000:01:00.0", component_type="gpu", numa_node=0),
      PCIDevice(bdf="0000:5e:00.0", component_type="nic", numa_node=0),
    ],
    network_interfaces=[
      {"name": "eth0", "pci_bdf": "0000:5e:00.0", "rdma_device": "mlx5_0"},
    ],
  )
  modes = list_transfer_modes(topo, "pcie_0000:01:00.0", "pcie_0000:5e:00.0")
  names = [m.name for m in modes]
  assert "gpudirect_rdma" in names
  assert "rdma" in names


def test_ucie_detected_for_same_vendor_chiplets():
  topo = SystemTopology(
    components=[
      Component(id="pcie_0000:c0:00.0", type=ComponentType.NPU, name="REBEL chiplet 0"),
      Component(id="pcie_0000:c0:01.0", type=ComponentType.NPU, name="REBEL chiplet 1"),
    ],
    pci_devices=[
      PCIDevice(bdf="0000:c0:00.0", vendor=0x1eff, device_id=0x1210,
                component_type="npu", ucie_capable=True, numa_node=0),
      PCIDevice(bdf="0000:c0:01.0", vendor=0x1eff, device_id=0x1210,
                component_type="npu", ucie_capable=True, numa_node=0),
    ],
  )
  modes = list_transfer_modes(topo, "pcie_0000:c0:00.0", "pcie_0000:c0:01.0")
  assert "ucie" in [m.name for m in modes]
