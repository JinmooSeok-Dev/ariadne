"""BIOS/Kernel 설정 — What-if 분석을 위한 입력 모델.

사용자가 임의의 BIOS/kernel 설정을 가정하여 trace.py DEFAULT_PARAMS에 반영,
"이 설정을 바꾸면 BW/latency가 어떻게 달라지는가?"를 추정할 수 있게 한다.

매핑 원칙:
  - 모든 설정은 best-effort 추정. 실제 효과는 HW/SW 조합에 따라 다름
  - mapping은 multiplicative 또는 additive — 명세는 _PARAM_DELTAS 주석 참조
  - 비교의 기준점은 "kernel/BIOS 권장값 (성능 우선)" — pristine high-perf default
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Settings(BaseModel):
  """What-if BIOS/Kernel 설정. 모든 필드는 optional이며 None이면 기본값 가정."""

  # IOMMU
  iommu_enabled: bool | None = None              # intel_iommu=on / amd_iommu=on
  iommu_passthrough: bool | None = None          # iommu=pt → 성능 향상
  pcie_acs_override: bool | None = None          # ACS override → P2P 가능

  # PCIe ASPM (Active State Power Management) — latency 증가
  aspm: Literal["disabled", "l0s", "l1", "l1ss", "auto"] | None = None

  # NUMA
  numa_balancing: bool | None = None             # /proc/sys/kernel/numa_balancing
  transparent_hugepages: Literal["always", "madvise", "never"] | None = None

  # CPU governor
  cpu_governor: Literal["performance", "powersave", "ondemand"] | None = None

  # GPU/NVLink — best-effort
  gpu_persistence_mode: bool | None = None       # nvidia-smi -pm 1

  # Generic overrides — 사용자가 직접 trace param에 강제 주입
  param_overrides: dict[str, float] = Field(default_factory=dict)


# 설정 → trace param 변경 규칙
# 각 entry: (param_name, mode, value)
#   mode="mul": 기존값 *= value
#   mode="add": 기존값 += value
#   mode="set": 기존값 = value
_PARAM_DELTAS: dict[str, list[tuple[str, str, float]]] = {
  # IOMMU 활성화 — translation 오버헤드. passthrough면 거의 0
  "iommu_on_no_pt": [("iommu_latency_ns", "set", 50.0)],
  "iommu_on_pt": [("iommu_latency_ns", "set", 5.0)],
  "iommu_off": [("iommu_latency_ns", "set", 0.0)],

  # ASPM — link latency 증가 (L1 substate가 가장 큼)
  "aspm_l0s": [("pcie_link_latency_ns", "add", 50.0)],
  "aspm_l1": [("pcie_link_latency_ns", "add", 200.0)],
  "aspm_l1ss": [("pcie_link_latency_ns", "add", 1000.0)],   # μs 단위
  "aspm_disabled": [],

  # numa_balancing on → 백그라운드 page migration. remote latency variance 증가 (대표값 +10ns)
  "numa_balancing_on": [("numa_remote_latency_ns", "mul", 1.1)],

  # THP=always — 큰 페이지 → TLB miss 감소 → memory_latency 약간 개선
  "thp_always": [("memory_latency_ns", "mul", 0.95)],
  "thp_never": [("memory_latency_ns", "mul", 1.05)],

  # CPU governor=performance — internal_latency 약간 개선 (clock variance 제거)
  "cpu_perf": [("internal_latency_ns", "mul", 0.9)],
  "cpu_powersave": [("internal_latency_ns", "mul", 1.3)],
}


def apply_settings_to_params(
  settings: Settings, base_params: dict | None = None,
) -> dict:
  """Settings를 trace.py DEFAULT_PARAMS에 적용. 새 dict 반환 (base_params 변경 X)."""
  from ariadne.analyzer.trace import DEFAULT_PARAMS
  out = {**DEFAULT_PARAMS, **(base_params or {})}

  keys: list[str] = []
  if settings.iommu_enabled is True:
    keys.append("iommu_on_pt" if settings.iommu_passthrough else "iommu_on_no_pt")
  elif settings.iommu_enabled is False:
    keys.append("iommu_off")

  if settings.aspm is not None and settings.aspm != "auto":
    keys.append(f"aspm_{settings.aspm}")

  if settings.numa_balancing is True:
    keys.append("numa_balancing_on")

  if settings.transparent_hugepages == "always":
    keys.append("thp_always")
  elif settings.transparent_hugepages == "never":
    keys.append("thp_never")

  if settings.cpu_governor == "performance":
    keys.append("cpu_perf")
  elif settings.cpu_governor == "powersave":
    keys.append("cpu_powersave")

  for key in keys:
    for param, mode, value in _PARAM_DELTAS.get(key, []):
      cur = out.get(param, 0)
      if mode == "mul":
        out[param] = cur * value
      elif mode == "add":
        out[param] = cur + value
      elif mode == "set":
        out[param] = value

  # 사용자 직접 override (가장 강한 우선순위)
  out.update(settings.param_overrides)
  return out


class WhatIfResult(BaseModel):
  """동일한 trace를 default vs settings로 비교한 결과."""
  source: str
  destination: str
  baseline_bandwidth_gbps: float
  scenario_bandwidth_gbps: float
  baseline_latency_ns: float
  scenario_latency_ns: float
  bandwidth_delta_pct: float
  latency_delta_pct: float
  applied_params: dict


def what_if_trace(
  topo, source: str, destination: str, settings: Settings,
) -> WhatIfResult:
  """default 파라미터와 settings 적용 파라미터로 trace를 비교."""
  from ariadne.analyzer.trace import trace_path
  baseline = trace_path(topo, source, destination)
  applied = apply_settings_to_params(settings)
  scenario = trace_path(topo, source, destination, params=applied)

  def pct(new: float, old: float) -> float:
    if old == 0:
      return 0.0
    return round(100.0 * (new - old) / old, 2)

  return WhatIfResult(
    source=source,
    destination=destination,
    baseline_bandwidth_gbps=baseline.e2e_bandwidth_gbps,
    scenario_bandwidth_gbps=scenario.e2e_bandwidth_gbps,
    baseline_latency_ns=baseline.e2e_latency_ns,
    scenario_latency_ns=scenario.e2e_latency_ns,
    bandwidth_delta_pct=pct(scenario.e2e_bandwidth_gbps, baseline.e2e_bandwidth_gbps),
    latency_delta_pct=pct(scenario.e2e_latency_ns, baseline.e2e_latency_ns),
    applied_params=applied,
  )
