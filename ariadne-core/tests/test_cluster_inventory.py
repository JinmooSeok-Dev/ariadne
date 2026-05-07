"""Ansible inventory 파서 단위 테스트."""

import tempfile
from pathlib import Path

import pytest

from ariadne.cluster.inventory import parse_inventory, parse_inventory_dict
from ariadne.cluster.spec import ClusterSpec


def _write_yaml(content: str) -> Path:
  tmp = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8")
  tmp.write(content)
  tmp.close()
  return Path(tmp.name)


def test_minimal_hosts_only():
  """가장 단순한 inventory — hosts만 있고 vars 없음 (~/.ssh/config에 의존하는 경우)."""
  raw = {
    "all": {
      "hosts": {
        "gpu-01": None,  # ansible은 빈 host에 None을 쓸 수 있음
        "gpu-02": {},
      }
    }
  }
  spec = parse_inventory_dict(raw, cluster_id="test")
  assert spec.cluster_id == "test"
  assert set(spec.hosts.keys()) == {"gpu-01", "gpu-02"}
  assert spec.hosts["gpu-01"].ssh_hostname() == "gpu-01"  # ansible_host 없으면 id 사용
  assert spec.hosts["gpu-01"].ansible_user is None
  assert spec.groups == {}


def test_host_vars():
  raw = {
    "all": {
      "hosts": {
        "gpu-01": {
          "ansible_host": "10.0.0.11",
          "ansible_user": "root",
          "ansible_port": 2222,
        },
      }
    }
  }
  spec = parse_inventory_dict(raw, cluster_id="c1")
  h = spec.hosts["gpu-01"]
  assert h.ansible_host == "10.0.0.11"
  assert h.ansible_user == "root"
  assert h.ansible_port == 2222
  assert h.ssh_hostname() == "10.0.0.11"


def test_var_inheritance_host_overrides_group_overrides_all():
  """host vars > group vars > all vars 우선순위."""
  raw = {
    "all": {
      "vars": {"ansible_user": "default", "ansible_port": 22},
      "hosts": {"gpu-01": {}, "gpu-02": {}, "head-01": {}},
      "children": {
        "gpu_workers": {
          "vars": {"ansible_user": "gpuadmin"},
          "hosts": {
            "gpu-01": {"ansible_user": "rootoverride"},
            "gpu-02": {},
          },
        },
        "head_nodes": {
          "hosts": {"head-01": {}},
        },
      },
    }
  }
  spec = parse_inventory_dict(raw, cluster_id="c")
  assert spec.hosts["gpu-01"].ansible_user == "rootoverride"  # host 우선
  assert spec.hosts["gpu-02"].ansible_user == "gpuadmin"      # group 우선
  assert spec.hosts["head-01"].ansible_user == "default"     # all로 fallback
  # all vars는 모두에게 적용
  assert spec.hosts["gpu-01"].ansible_port == 22
  assert spec.hosts["head-01"].ansible_port == 22


def test_groups_membership():
  raw = {
    "all": {
      "hosts": {"gpu-01": {}, "gpu-02": {}, "head-01": {}},
      "children": {
        "gpu_workers": {"hosts": {"gpu-01": {}, "gpu-02": {}}},
        "head_nodes": {"hosts": {"head-01": {}}},
      },
    }
  }
  spec = parse_inventory_dict(raw, cluster_id="c")
  assert spec.groups == {
    "gpu_workers": ["gpu-01", "gpu-02"],
    "head_nodes": ["head-01"],
  }
  members = spec.group_members("gpu_workers")
  assert {h.id for h in members} == {"gpu-01", "gpu-02"}
  assert spec.group_members("nonexistent") == []


def test_host_defined_only_in_group():
  """all.hosts에 안 적고 그룹 안에서 처음 등장하는 호스트도 등록되어야 한다."""
  raw = {
    "all": {
      "children": {
        "gpu_workers": {
          "hosts": {
            "gpu-01": {"ansible_host": "10.0.0.11"},
          },
        },
      },
    }
  }
  spec = parse_inventory_dict(raw, cluster_id="c")
  assert "gpu-01" in spec.hosts
  assert spec.hosts["gpu-01"].ansible_host == "10.0.0.11"
  assert spec.groups["gpu_workers"] == ["gpu-01"]


def test_unknown_vars_are_ignored():
  """ansible_* 외의 키는 무시된다 (ansible 일반 vars와 충돌 방지)."""
  raw = {
    "all": {
      "hosts": {
        "gpu-01": {
          "ansible_host": "10.0.0.11",
          "some_random_var": "ignored",
          "another_var": 42,
        },
      },
    }
  }
  spec = parse_inventory_dict(raw, cluster_id="c")
  assert spec.hosts["gpu-01"].ansible_host == "10.0.0.11"
  # 알 수 없는 키는 HostSpec 생성에 포함되지 않아야 한다 (Pydantic ValidationError 방지)


def test_nested_children_unsupported():
  raw = {
    "all": {
      "children": {
        "outer": {
          "children": {"inner": {"hosts": {"gpu-01": {}}}},
        },
      },
    }
  }
  with pytest.raises(ValueError, match="중첩 children"):
    parse_inventory_dict(raw, cluster_id="c")


def test_missing_all_section():
  with pytest.raises(ValueError, match="'all' 키"):
    parse_inventory_dict({"hosts": {"gpu-01": {}}}, cluster_id="c")


def test_parse_from_file_uses_filename_as_default_cluster_id():
  yaml_content = """
all:
  hosts:
    gpu-01:
      ansible_host: 10.0.0.11
"""
  path = _write_yaml(yaml_content)
  try:
    spec = parse_inventory(path)
    assert spec.cluster_id == path.stem  # 파일명에서 추출
    assert spec.hosts["gpu-01"].ansible_host == "10.0.0.11"
  finally:
    path.unlink()


def test_parse_from_file_explicit_cluster_id():
  yaml_content = """
all:
  hosts:
    gpu-01: {}
"""
  path = _write_yaml(yaml_content)
  try:
    spec = parse_inventory(path, cluster_id="prod-a")
    assert spec.cluster_id == "prod-a"
  finally:
    path.unlink()


def test_full_realistic_inventory():
  """README/CLAUDE.md에 적은 예시 형태의 inventory 통합 테스트."""
  raw = {
    "all": {
      "hosts": {
        "gpu-01": {"ansible_host": "10.0.0.11", "ansible_user": "root"},
        "gpu-02": {
          "ansible_host": "10.0.0.12",
          "ansible_user": "ubuntu",
          "ansible_port": 2222,
        },
        "head-01": {"ansible_host": "head.lab"},
      },
      "children": {
        "gpu_workers": {"hosts": {"gpu-01": {}, "gpu-02": {}}},
        "head_nodes": {"hosts": {"head-01": {}}},
      },
    }
  }
  spec = parse_inventory_dict(raw, cluster_id="lmtune-prod-a")
  assert isinstance(spec, ClusterSpec)
  assert len(spec.hosts) == 3
  assert spec.hosts["gpu-02"].ansible_port == 2222
  assert spec.groups["gpu_workers"] == ["gpu-01", "gpu-02"]
  # JSON-serializable 확인 (소비자가 model_dump_json으로 받을 수 있어야 함)
  json_str = spec.model_dump_json()
  assert "lmtune-prod-a" in json_str
  assert "gpu-01" in json_str
