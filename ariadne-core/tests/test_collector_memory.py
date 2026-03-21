"""Memory Collector 테스트."""

from ariadne.collector.memory import _parse_speed, _aggregate_dimms


def test_parse_speed_mt_s():
  assert _parse_speed("5600 MT/s") == 5600


def test_parse_speed_mhz():
  assert _parse_speed("4800 MHz") == 4800


def test_parse_speed_plain():
  assert _parse_speed("3200") == 3200


def test_parse_speed_unknown():
  assert _parse_speed("Unknown") == 0


def test_parse_speed_empty():
  assert _parse_speed("") == 0


def test_aggregate_dimms_ddr5():
  dimms = [
    {"size_mb": 16384, "speed_mhz": 5600, "type": "DDR5", "locator": "DIMM0"},
    {"size_mb": 16384, "speed_mhz": 5600, "type": "DDR5", "locator": "DIMM1"},
  ]
  result = _aggregate_dimms(dimms)
  assert len(result) == 1
  assert result[0].total_mb == 32768
  assert result[0].channels == 2
  assert result[0].speed_mhz == 5600
  assert result[0].type == "DDR5"
  assert result[0].theoretical_bw_gbps == 89.6  # 2 × 5600 × 8 / 1000


def test_aggregate_dimms_empty():
  assert _aggregate_dimms([]) == []


def test_aggregate_dimms_no_module():
  dimms = [{"size_mb": 0}]
  assert _aggregate_dimms(dimms) == []
