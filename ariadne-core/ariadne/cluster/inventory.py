"""Ansible inventory (YAML) 파서 — ClusterSpec으로 정규화.

지원 범위 (v1alpha1):
  - all.hosts.<host>          호스트 정의 + host vars
  - all.vars                  cluster 전역 vars
  - all.children.<group>.hosts.<host>  그룹 멤버십 (이미 정의된 호스트 또는 새 호스트)
  - all.children.<group>.vars 그룹 vars

미지원 (의도적):
  - children 중첩 그룹 (group of groups). v1에서는 1단계 그룹만 지원.
  - INI 형식.
  - ansible의 22단계 변수 우선순위. 단순 머지: host > group > all.

호스트가 여러 그룹에 속하고 그룹 vars가 충돌하는 경우, 마지막으로 처리된
그룹의 vars가 우선한다 (Python dict 순서).
"""

from pathlib import Path

import yaml

from ariadne.cluster.spec import ClusterSpec, HostSpec

_HOST_VAR_KEYS = {
  "ansible_host",
  "ansible_user",
  "ansible_port",
  "ansible_ssh_private_key_file",
  "ansible_ssh_common_args",
}


def parse_inventory(path: Path | str, cluster_id: str | None = None) -> ClusterSpec:
  """Ansible inventory YAML 파일을 읽어 ClusterSpec으로 정규화한다.

  cluster_id 미지정 시 파일명(확장자 제외)을 사용한다.
  """
  path = Path(path)
  with path.open("r", encoding="utf-8") as f:
    raw = yaml.safe_load(f) or {}

  cid = cluster_id or path.stem
  return parse_inventory_dict(raw, cluster_id=cid)


def parse_inventory_dict(raw: dict, cluster_id: str) -> ClusterSpec:
  """이미 파싱된 dict로부터 ClusterSpec 생성. 테스트/프로그램적 사용용."""
  if not isinstance(raw, dict) or "all" not in raw:
    raise ValueError("inventory의 최상위에 'all' 키가 필요합니다")

  all_section = raw["all"] or {}
  all_vars = _filter_host_vars(all_section.get("vars") or {})

  # host_id → host vars (raw, 미상속)
  host_vars: dict[str, dict] = {}
  groups: dict[str, list[str]] = {}
  group_vars: dict[str, dict] = {}

  for host_id, vars_dict in (all_section.get("hosts") or {}).items():
    host_vars[host_id] = _filter_host_vars(vars_dict or {})

  children = all_section.get("children") or {}
  for group_name, group_section in children.items():
    if group_section is None:
      group_section = {}
    if "children" in group_section:
      raise ValueError(
        f"그룹 '{group_name}'에 중첩 children이 있습니다. v1alpha1는 1단계 그룹만 지원합니다"
      )

    group_vars[group_name] = _filter_host_vars(group_section.get("vars") or {})
    members: list[str] = []
    for host_id, vars_dict in (group_section.get("hosts") or {}).items():
      members.append(host_id)
      existing = host_vars.get(host_id, {})
      new_vars = _filter_host_vars(vars_dict or {})
      # 같은 호스트가 여러 곳에서 정의되면 더 구체적인 정의(나중 등장)가 우선
      host_vars[host_id] = {**existing, **new_vars}
    groups[group_name] = members

  hosts: dict[str, HostSpec] = {}
  for host_id, hv in host_vars.items():
    merged = dict(all_vars)
    for group_name, members in groups.items():
      if host_id in members:
        merged.update(group_vars.get(group_name, {}))
    merged.update(hv)
    hosts[host_id] = HostSpec(id=host_id, **merged)

  return ClusterSpec(cluster_id=cluster_id, hosts=hosts, groups=groups)


def _filter_host_vars(vars_dict: dict) -> dict:
  """ansible vars 중 우리가 사용하는 ansible_* 키만 추출. 나머지는 무시한다."""
  return {k: v for k, v in vars_dict.items() if k in _HOST_VAR_KEYS}
