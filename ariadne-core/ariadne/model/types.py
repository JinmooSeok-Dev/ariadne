"""Ariadne 토폴로지 모델의 기본 타입 정의."""

from enum import Enum
from pydantic import BaseModel


class ComponentType(str, Enum):
  NUMA_NODE = "numa_node"
  SOCKET = "socket"
  CPU_CORE = "cpu_core"
  CPU_THREAD = "cpu_thread"
  CACHE = "cache"
  MEMORY_CONTROLLER = "memory_controller"
  DRAM = "dram"
  PCIE_ROOT_COMPLEX = "pcie_root_complex"
  PCIE_ROOT_PORT = "pcie_root_port"
  PCIE_SWITCH = "pcie_switch"
  PCIE_ENDPOINT = "pcie_endpoint"
  GPU = "gpu"
  NIC = "nic"
  NVME = "nvme"


class LinkType(str, Enum):
  INTERNAL = "internal"
  PCIE = "pcie"
  NVLINK = "nvlink"
  MEMORY = "memory"
  UPI = "upi"
  INFINITY_FABRIC = "infinity_fabric"


class CacheLevel(str, Enum):
  L1D = "l1d"
  L1I = "l1i"
  L2 = "l2"
  L3 = "l3"


class Component(BaseModel):
  id: str
  type: ComponentType
  name: str
  attrs: dict = {}


class Link(BaseModel):
  source: str
  target: str
  type: LinkType
  bandwidth_gbps: float | None = None
  latency_ns: float | None = None
  attrs: dict = {}


class NUMANode(BaseModel):
  node_id: int
  cpu_list: list[int] = []
  memory_mb: int = 0
  distances: dict[int, int] = {}


class CPUCore(BaseModel):
  core_id: int
  physical_package_id: int
  thread_siblings: list[int] = []


class CacheInfo(BaseModel):
  level: CacheLevel
  size_kb: int
  shared_cpu_list: list[int] = []
  line_size_bytes: int = 64


class MemoryInfo(BaseModel):
  total_mb: int = 0
  numa_node: int = -1
  channels: int = 0
  speed_mhz: int = 0
  type: str = ""
  theoretical_bw_gbps: float = 0.0


class PCIDevice(BaseModel):
  bdf: str
  class_code: int = 0
  vendor: int = 0
  device_id: int = 0
  numa_node: int = -1
  current_link_speed: str = ""
  current_link_width: int = 0
  max_link_speed: str = ""
  max_link_width: int = 0
  iommu_group: int = -1
  sriov_totalvfs: int = 0
  sriov_numvfs: int = 0
  is_vf: bool = False
  reset_method: str = ""
  bars: list[dict] = []
  parent_bdf: str = ""
  component_type: str = ""
  type_name: str = ""
  vendor_name: str = ""


class SystemTopology(BaseModel):
  hostname: str = ""
  numa_nodes: list[NUMANode] = []
  cpu_cores: list[CPUCore] = []
  caches: list[CacheInfo] = []
  memory: list[MemoryInfo] = []
  pci_devices: list[PCIDevice] = []
  iommu_groups: dict[int, list[str]] = {}
  components: list[Component] = []
  links: list[Link] = []
