"""BIOS/Kernel What-if 설정 모델 테스트."""

from ariadne.analyzer.trace import DEFAULT_PARAMS
from ariadne.model.settings import (
  Settings,
  apply_settings_to_params,
  what_if_trace,
)
from ariadne.model.types import (
  Component,
  ComponentType,
  Link,
  LinkType,
  PCIDevice,
  SystemTopology,
)


def _topo() -> SystemTopology:
  return SystemTopology(
    components=[
      Component(id="pcie_0000:01:00.0", type=ComponentType.GPU, name="GPU 0"),
      Component(id="mc_0", type=ComponentType.MEMORY_CONTROLLER, name="MC 0"),
      Component(id="dram_0", type=ComponentType.DRAM, name="DRAM 0"),
    ],
    pci_devices=[PCIDevice(bdf="0000:01:00.0", component_type="gpu")],
    links=[
      Link(source="pcie_0000:01:00.0", target="mc_0",
           type=LinkType.PCIE, bandwidth_gbps=64.0),
      Link(source="mc_0", target="dram_0",
           type=LinkType.MEMORY, bandwidth_gbps=100.0),
    ],
  )


def test_default_settings_returns_default_params():
  s = Settings()
  out = apply_settings_to_params(s)
  for k, v in DEFAULT_PARAMS.items():
    assert out[k] == v


def test_iommu_passthrough_lower_than_no_pt():
  with_pt = apply_settings_to_params(
    Settings(iommu_enabled=True, iommu_passthrough=True))
  no_pt = apply_settings_to_params(
    Settings(iommu_enabled=True, iommu_passthrough=False))
  assert with_pt["iommu_latency_ns"] < no_pt["iommu_latency_ns"]


def test_iommu_off_zero_latency():
  out = apply_settings_to_params(Settings(iommu_enabled=False))
  assert out["iommu_latency_ns"] == 0


def test_aspm_l1ss_adds_significant_link_latency():
  base = apply_settings_to_params(Settings(aspm="disabled"))
  l1ss = apply_settings_to_params(Settings(aspm="l1ss"))
  assert l1ss["pcie_link_latency_ns"] > base["pcie_link_latency_ns"] + 500


def test_thp_always_lowers_memory_latency():
  always = apply_settings_to_params(
    Settings(transparent_hugepages="always"))
  never = apply_settings_to_params(
    Settings(transparent_hugepages="never"))
  assert always["memory_latency_ns"] < never["memory_latency_ns"]


def test_param_overrides_take_precedence():
  out = apply_settings_to_params(
    Settings(iommu_enabled=True, iommu_passthrough=True,
             param_overrides={"iommu_latency_ns": 999.0}))
  assert out["iommu_latency_ns"] == 999.0


def test_cpu_governor_performance_lowers_internal_latency():
  perf = apply_settings_to_params(Settings(cpu_governor="performance"))
  save = apply_settings_to_params(Settings(cpu_governor="powersave"))
  assert perf["internal_latency_ns"] < save["internal_latency_ns"]


def test_what_if_trace_compares_baseline_and_scenario():
  topo = _topo()
  result = what_if_trace(
    topo, "pcie_0000:01:00.0", "dram_0",
    Settings(aspm="l1ss", iommu_enabled=True, iommu_passthrough=False),
  )
  assert result.source == "pcie_0000:01:00.0"
  assert result.destination == "dram_0"
  # ASPM L1SS + IOMMU on → latency 증가
  assert result.scenario_latency_ns > result.baseline_latency_ns
  assert result.latency_delta_pct > 0
  assert "iommu_latency_ns" in result.applied_params


def test_what_if_trace_no_change_when_default_settings():
  topo = _topo()
  result = what_if_trace(
    topo, "pcie_0000:01:00.0", "dram_0", Settings(),
  )
  assert result.baseline_latency_ns == result.scenario_latency_ns
  assert result.latency_delta_pct == 0.0
