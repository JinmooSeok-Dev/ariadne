"""Ariadne — System topology E2E data flow tracer and simulator.

Public API for consumers (lmtune 등):

  Single-host:
    build_topology() → SystemTopology
    trace_path(topo, src_id, dst_id) → TraceResult
    list_transfer_modes(topo, src_id, dst_id) → list[TransferModeOption]
    analyze_sriov_safety(topo) → list[SafetyIssue]

  Multi-host:
    parse_inventory(yaml_path) → ClusterSpec
    build_cluster_topology(spec) → ClusterTopology  (asyncio coroutine)
    trace_cluster(cluster, src, dst) → ClusterTraceResult
    trace_group(cluster, src_ids, dst_ids, pattern) → GroupTraceResult

모든 응답은 Pydantic BaseModel이므로 model_dump_json()으로 직렬화 가능.

import는 PEP 562 lazy 방식 — 원격 zipapp(cluster 모듈 제외)에서도
`from ariadne.model.topology import build_topology`가 동작한다.
"""

import importlib
from typing import TYPE_CHECKING

__version__ = "0.1.0"

_LAZY_ATTRS = {
  "build_topology": "ariadne.model.topology",
  "trace_path": "ariadne.analyzer.trace",
  "TraceResult": "ariadne.analyzer.trace",
  "list_transfer_modes": "ariadne.analyzer.transfer",
  "TransferModeOption": "ariadne.analyzer.transfer",
  "analyze_sriov_safety": "ariadne.analyzer.safety",
  "SafetyIssue": "ariadne.analyzer.safety",
  "simulate_flows": "ariadne.analyzer.simulation",
  "FlowSpec": "ariadne.analyzer.simulation",
  "FlowResult": "ariadne.analyzer.simulation",
  "SimulationResult": "ariadne.analyzer.simulation",
  "collect_vfio_inventory": "ariadne.collector.vfio",
  "VFIOInventory": "ariadne.collector.vfio",
  "VFIODevice": "ariadne.collector.vfio",
  "QemuVM": "ariadne.collector.vfio",
  "Settings": "ariadne.model.settings",
  "apply_settings_to_params": "ariadne.model.settings",
  "what_if_trace": "ariadne.model.settings",
  "WhatIfResult": "ariadne.model.settings",
  "parse_inventory": "ariadne.cluster.inventory",
  "ClusterSpec": "ariadne.cluster.spec",
  "HostSpec": "ariadne.cluster.spec",
  "ClusterTopology": "ariadne.model.cluster",
  "InterHostLink": "ariadne.cluster.links",
  "infer_inter_host_links": "ariadne.cluster.links",
  "trace_cluster": "ariadne.analyzer.cluster_trace",
  "trace_group": "ariadne.analyzer.cluster_trace",
  "ClusterTraceResult": "ariadne.analyzer.cluster_trace",
  "GroupTraceResult": "ariadne.analyzer.cluster_trace",
  "build_cluster_topology": "ariadne.cluster.remote",
  "SystemTopology": "ariadne.model.types",
  "PCIDevice": "ariadne.model.types",
  "Component": "ariadne.model.types",
  "Link": "ariadne.model.types",
  "ComponentType": "ariadne.model.types",
  "LinkType": "ariadne.model.types",
}


def __getattr__(name: str):
  if name in _LAZY_ATTRS:
    mod = importlib.import_module(_LAZY_ATTRS[name])
    return getattr(mod, name)
  raise AttributeError(f"module 'ariadne' has no attribute {name!r}")


def __dir__() -> list[str]:
  return sorted(_LAZY_ATTRS.keys()) + ["__version__"]


__all__ = list(_LAZY_ATTRS.keys())


if TYPE_CHECKING:  # 타입 체커가 보는 정적 import (런타임 영향 없음)
  from ariadne.analyzer.cluster_trace import (
    ClusterTraceResult,
    GroupTraceResult,
    trace_cluster,
    trace_group,
  )
  from ariadne.analyzer.safety import SafetyIssue, analyze_sriov_safety
  from ariadne.analyzer.trace import TraceResult, trace_path
  from ariadne.analyzer.transfer import TransferModeOption, list_transfer_modes
  from ariadne.cluster.inventory import parse_inventory
  from ariadne.cluster.links import InterHostLink, infer_inter_host_links
  from ariadne.cluster.remote import build_cluster_topology
  from ariadne.cluster.spec import ClusterSpec, HostSpec
  from ariadne.model.cluster import ClusterTopology
  from ariadne.model.topology import build_topology
  from ariadne.model.types import (
    Component,
    ComponentType,
    Link,
    LinkType,
    PCIDevice,
    SystemTopology,
  )
