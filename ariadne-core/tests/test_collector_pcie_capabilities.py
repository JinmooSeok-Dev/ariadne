"""PCIe Extended Capability 파싱 테스트.

Extended cap list 헤더 구조:
  bits 0-15:  capability ID
  bits 16-19: version
  bits 20-31: next capability offset (0이면 list 끝)
"""

from ariadne.collector.pcie import (
  EXT_CAP_BASE,
  parse_extended_capabilities,
)


def _make_config_with_caps(caps: list[tuple[int, int]], size: int = 4096) -> bytes:
  """[(cap_id, offset), ...] 리스트로부터 가짜 PCI config space 생성.

  caps의 순서대로 linked list 구성 (다음 cap의 offset이 이전 cap의 next 필드).
  """
  buf = bytearray(size)
  for i, (cap_id, offset) in enumerate(caps):
    next_offset = caps[i + 1][1] if i + 1 < len(caps) else 0
    header = (cap_id & 0xFFFF) | ((next_offset & 0xFFF) << 20)
    buf[offset:offset + 4] = header.to_bytes(4, "little")
  return bytes(buf)


def test_parse_acs_ari_ats_chain():
  """일반적인 SR-IOV-capable NIC: ACS(0x0D) → ARI(0x0E) → ATS(0x0F) → SR-IOV(0x10)."""
  config = _make_config_with_caps([
    (0x000D, 0x100),
    (0x000E, 0x140),
    (0x000F, 0x180),
    (0x0010, 0x1C0),
  ])
  caps = parse_extended_capabilities(config)
  assert caps == {"acs": True, "ari": True, "ats": True, "sriov": True}


def test_parse_aer_only():
  """일반 Endpoint는 보통 AER만 있다."""
  config = _make_config_with_caps([(0x0001, 0x100)])
  caps = parse_extended_capabilities(config)
  assert caps == {"aer": True}


def test_parse_ats_pri_pasid():
  """SVM(Shared Virtual Memory) 디바이스."""
  config = _make_config_with_caps([
    (0x000F, 0x100),
    (0x0013, 0x150),
    (0x001B, 0x200),
  ])
  caps = parse_extended_capabilities(config)
  assert caps == {"ats": True, "pri": True, "pasid": True}


def test_parse_unknown_cap_ids_ignored():
  """매핑 안 된 cap ID는 결과에 포함되지 않지만 list 순회는 정상."""
  config = _make_config_with_caps([
    (0x0001, 0x100),  # AER
    (0x0099, 0x150),  # 알 수 없는 cap
    (0x000D, 0x180),  # ACS
  ])
  caps = parse_extended_capabilities(config)
  assert caps == {"aer": True, "acs": True}


def test_parse_short_config():
  """일반 사용자가 256B만 읽은 경우 — extended cap list 접근 불가."""
  config = bytes(256)
  caps = parse_extended_capabilities(config)
  assert caps == {}


def test_parse_uninitialized_config():
  """config 4KB가 모두 0(권한 있지만 device가 OFF) — cap list 종료."""
  config = bytes(4096)
  caps = parse_extended_capabilities(config)
  assert caps == {}


def test_parse_circular_loop_protected():
  """잘못된 config가 순환 참조하면 무한 루프 없이 종료."""
  buf = bytearray(4096)
  # 0x100이 자기 자신을 가리킴
  header = 0x000D | (0x100 << 20)
  buf[0x100:0x104] = header.to_bytes(4, "little")
  caps = parse_extended_capabilities(bytes(buf))
  assert caps == {"acs": True}  # 한 번 등록되고 종료


def test_parse_dpc_ide():
  """최신 cap (DPC, IDE)도 인식."""
  config = _make_config_with_caps([
    (0x0023, 0x100),  # DPC
    (0x002F, 0x150),  # IDE (PCIe 6.0)
  ])
  caps = parse_extended_capabilities(config)
  assert caps == {"dpc": True, "ide": True}


def test_ext_cap_base_constant():
  """Extended cap base는 항상 0x100."""
  assert EXT_CAP_BASE == 0x100
