"""DES (Discrete-Event Simulation) 기반 다중 흐름 경합 시뮬레이션.

여러 flow가 같은 link/memory channel을 공유할 때 BW를 어떻게 나누어 갖는지,
큐잉 latency가 얼마나 발생하는지 추정한다.

모델 개요:
  - 각 flow는 (src, dst, size_bytes, start_ns) 튜플
  - 각 flow의 path는 trace_path()로 구해 일련의 link 시퀀스로 펼쳐짐
  - 같은 link을 동시에 사용하는 flow는 그 link의 BW를 1/N로 나눠 가짐 (max-min fair)
  - 한 link의 latency는 모든 flow에 한 번씩 더해짐 (전파 지연 + queueing은 모델 단순화 위해 별도 처리)

ariadne의 시뮬레이션은 일반화된 비용 모델만 제공하며, 외부 도메인 용어
(collective, NCCL ring 등) 명칭은 사용하지 않는다.
"""

import simpy
from pydantic import BaseModel, Field

from ariadne.analyzer.trace import trace_path
from ariadne.model.types import SystemTopology


class FlowSpec(BaseModel):
  flow_id: str
  source: str
  destination: str
  size_bytes: int
  start_ns: float = 0.0       # 시뮬레이션 시작 후 spawn 시각


class FlowResult(BaseModel):
  flow_id: str
  source: str
  destination: str
  size_bytes: int
  start_ns: float
  finish_ns: float
  duration_ns: float
  effective_bandwidth_gbps: float
  bottleneck_link: str = ""
  contended_with: list[str] = Field(default_factory=list)  # 같은 link을 공유한 다른 flow들


class SimulationResult(BaseModel):
  total_simulated_ns: float
  flows: list[FlowResult] = Field(default_factory=list)
  link_utilization: dict[str, float] = Field(default_factory=dict)  # link key → 점유 시간 ns


def simulate_flows(
  topo: SystemTopology,
  flows: list[FlowSpec],
  params: dict | None = None,
) -> SimulationResult:
  """다중 flow를 SimPy로 시뮬레이션.

  공유 모델 (1차 단순화):
    - 모든 flow의 path를 사전 계산하고 link → 사용 flow 집합을 정적으로 구함
    - 한 link을 N개 flow가 사용하면 각자 BW/N 사용 (정적 max-min 추정)
    - simpy는 시간 진행 + latency 누적에 사용. 동적 join/leave는 모델링하지 않음
    - start_ns 차이는 absolute finish time에 반영되지만 contention 판정에는 정적 결과 사용

  실제 PCIe arbitration / NIC scheduling은 더 복잡하나 1차 근사로 충분. 정밀
  모델이 필요하면 후속 phase에서 link 단위 simpy.Resource + queue로 확장.
  """
  flow_paths: dict[str, list[dict]] = {}
  results_by_id: dict[str, FlowResult] = {}
  for fs in flows:
    trace = trace_path(topo, fs.source, fs.destination, params=params)
    flow_paths[fs.flow_id] = trace.segments
    results_by_id[fs.flow_id] = FlowResult(
      flow_id=fs.flow_id,
      source=fs.source,
      destination=fs.destination,
      size_bytes=fs.size_bytes,
      start_ns=fs.start_ns,
      finish_ns=0.0,
      duration_ns=0.0,
      effective_bandwidth_gbps=0.0,
    )

  # 정적 link users: link_key → 그 link을 사용하는 flow_id 집합
  link_users: dict[str, set[str]] = {}
  for fid, segs in flow_paths.items():
    for seg in segs:
      lk = _link_key(seg)
      link_users.setdefault(lk, set()).add(fid)

  env = simpy.Environment()
  link_busy: dict[str, float] = {}

  def flow_process(env, fs: FlowSpec):
    yield env.timeout(fs.start_ns)
    segments = flow_paths[fs.flow_id]
    if not segments:
      results_by_id[fs.flow_id].finish_ns = env.now
      results_by_id[fs.flow_id].duration_ns = env.now - fs.start_ns
      return

    bottleneck_lk = ""
    min_eff_bw = float("inf")
    contended: set[str] = set()

    for seg in segments:
      lk = _link_key(seg)
      n_users = max(1, len(link_users.get(lk, {fs.flow_id})))
      seg_bw = seg.get("effective_bw_gbps") or 0
      latency = seg.get("latency_ns", 0) or 0

      if seg_bw > 0:
        per_flow_bw = seg_bw / n_users  # GB/s
        bytes_per_ns = per_flow_bw  # 1 GB/s == 1 byte/ns
        transfer_ns = fs.size_bytes / bytes_per_ns if bytes_per_ns > 0 else 0
        yield env.timeout(transfer_ns)
        link_busy[lk] = link_busy.get(lk, 0.0) + transfer_ns
        if per_flow_bw < min_eff_bw:
          min_eff_bw = per_flow_bw
          bottleneck_lk = lk
      yield env.timeout(latency)

      if n_users > 1:
        contended.update(link_users[lk] - {fs.flow_id})

    r = results_by_id[fs.flow_id]
    r.finish_ns = env.now
    r.duration_ns = env.now - fs.start_ns
    if r.duration_ns > 0:
      # 1 GB/s = 1 byte/ns이므로 size/duration이 GB/s
      r.effective_bandwidth_gbps = round(fs.size_bytes / r.duration_ns, 2)
    r.bottleneck_link = bottleneck_lk
    r.contended_with = sorted(contended)

  for fs in flows:
    env.process(flow_process(env, fs))

  env.run()

  return SimulationResult(
    total_simulated_ns=env.now,
    flows=[results_by_id[f.flow_id] for f in flows],
    link_utilization=link_busy,
  )


def _link_key(seg: dict) -> str:
  return f"{seg.get('from', '')}|{seg.get('to', '')}"
