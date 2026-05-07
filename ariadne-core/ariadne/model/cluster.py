"""ClusterTopology — 다중 호스트 토폴로지의 단일 직렬화 가능 모델.

소비자(lmtune 등)가 한 번의 JSON 문자열 또는 한 객체로 모든 호스트 정보 +
호스트 간 fabric을 받을 수 있게 한다. 단일 호스트 모드는 cluster_id="local",
hosts={"local": SystemTopology}로 자연 통합된다.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ariadne.cluster.links import InterHostLink
from ariadne.model.types import SystemTopology


class ClusterTopology(BaseModel):
  cluster_id: str
  api_version: str = "ariadne/v1alpha1"
  collected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
  hosts: dict[str, SystemTopology] = Field(default_factory=dict)  # host_id → SystemTopology
  inter_host_links: list[InterHostLink] = Field(default_factory=list)
  groups: dict[str, list[str]] = Field(default_factory=dict)  # group_name → [host_id]

  def host_ids(self) -> list[str]:
    return list(self.hosts.keys())

  def find_component(self, full_id: str) -> tuple[str, str] | None:
    """'host_id::component_id' → (host_id, component_id) 분해. 형식 안 맞으면 None."""
    if "::" not in full_id:
      return None
    host_id, _, comp_id = full_id.partition("::")
    if host_id not in self.hosts:
      return None
    return host_id, comp_id

  def group_host_ids(self, group_name: str) -> list[str]:
    return self.groups.get(group_name, [])
