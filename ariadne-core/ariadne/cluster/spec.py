"""Cluster 입력 스펙 — Ansible inventory에서 정규화된 형태.

ariadne는 lmtune 등 외부 소비자에 대한 의존을 갖지 않는다. 입력 포맷만
ansible inventory와 호환될 뿐, ansible-core는 의존성에 포함하지 않는다.
"""

from pydantic import BaseModel, Field


class HostSpec(BaseModel):
  """단일 호스트의 SSH 접속 정보. 모든 ansible_* 필드는 옵션이며,
  미지정 시 SSH 클라이언트 / ~/.ssh/config 기본값에 위임한다."""

  id: str  # inventory hostname, cluster 내 unique
  ansible_host: str | None = None  # 미지정 시 id를 ssh hostname으로 사용
  ansible_user: str | None = None
  ansible_port: int | None = None
  ansible_ssh_private_key_file: str | None = None
  ansible_ssh_common_args: str | None = None  # jump host 등 raw ssh args

  def ssh_hostname(self) -> str:
    """실제 ssh 접속에 사용할 hostname. ansible_host > id."""
    return self.ansible_host or self.id


class ClusterSpec(BaseModel):
  """Cluster 입력 — inventory를 정규화한 결과."""

  cluster_id: str
  api_version: str = "ariadne/v1alpha1"
  hosts: dict[str, HostSpec] = Field(default_factory=dict)  # host_id → HostSpec
  groups: dict[str, list[str]] = Field(default_factory=dict)  # group_name → [host_id]

  def host_ids(self) -> list[str]:
    return list(self.hosts.keys())

  def group_members(self, group_name: str) -> list[HostSpec]:
    """그룹 이름으로 멤버 HostSpec 목록 조회. 그룹 미존재 시 빈 리스트."""
    return [self.hosts[h] for h in self.groups.get(group_name, []) if h in self.hosts]
