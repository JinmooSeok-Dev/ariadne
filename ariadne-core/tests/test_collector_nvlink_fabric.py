"""Fabric Manager 로그 파서 테스트."""

import tempfile
from pathlib import Path

from ariadne.collector.nvlink_fabric import (
  FabricInventory,
  parse_fabricmanager_log,
)


def _write_log(content: str) -> Path:
  f = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8")
  f.write(content)
  f.close()
  return Path(f.name)


def test_no_log_file_returns_empty():
  inv = parse_fabricmanager_log(Path("/nonexistent"))
  assert inv.fm_running is False
  assert inv.nvswitches == []
  assert inv.gpus == []


def test_basic_dgx_h100_log():
  log = """\
[INFO] [tid 25] Connected to driver
[INFO] [tid 25] NVSwitch 0: pci_dev: 0000:1c:00.0 deviceuuid:1ff8e91d-1234-5678-9abc-aaabbbccc111
[INFO] [tid 25] NVSwitch 1: pci_dev: 0000:1d:00.0 deviceuuid:2ff8e91d-1234-5678-9abc-aaabbbccc222
[INFO] [tid 25] NVSwitch 2: pci_dev: 0000:1e:00.0 deviceuuid:3ff8e91d-1234-5678-9abc-aaabbbccc333
[INFO] [tid 25] NVSwitch 3: pci_dev: 0000:1f:00.0 deviceuuid:4ff8e91d-1234-5678-9abc-aaabbbccc444
[INFO] [tid 25] GPU pci_dev: 0000:01:00.0 UUID: GPU-aaaa1111-2222-3333-4444-555555555555
[INFO] [tid 25] GPU pci_dev: 0000:25:00.0 UUID: GPU-bbbb1111-2222-3333-4444-555555555555
[INFO] [tid 25] Successfully configured all the available GPUs and NVSwitches to route NVLink traffic.
"""
  path = _write_log(log)
  try:
    inv = parse_fabricmanager_log(path)
    assert inv.fm_running is True
    assert len(inv.nvswitches) == 4
    assert inv.nvswitches[0].index == 0
    assert inv.nvswitches[0].pci_bdf == "0000:1c:00.0"
    assert inv.nvswitches[0].uuid.startswith("1ff8")
    assert len(inv.gpus) == 2
    assert inv.gpus[0].pci_bdf == "0000:01:00.0"
    assert inv.gpus[0].uuid.startswith("GPU-aaaa")
  finally:
    path.unlink(missing_ok=True)


def test_8digit_domain_normalized():
  log = """\
[INFO] NVSwitch 0: pci_dev: 00010000:1c:00.0 deviceuuid:abcdef12-1234-5678-9abc-deadbeef0000
"""
  path = _write_log(log)
  try:
    inv = parse_fabricmanager_log(path)
    assert inv.nvswitches[0].pci_bdf == "0000:1c:00.0"
  finally:
    path.unlink(missing_ok=True)


def test_duplicate_entries_deduplicated():
  log = """\
[INFO] NVSwitch 0: pci_dev: 0000:1c:00.0 deviceuuid:abcdef12-0000-0000-0000-000000000000
[INFO] NVSwitch 0: pci_dev: 0000:1c:00.0 deviceuuid:abcdef12-0000-0000-0000-000000000000
[INFO] GPU pci_dev: 0000:01:00.0 UUID: GPU-1111aaaa-0000-0000-0000-000000000000
[INFO] GPU pci_dev: 0000:01:00.0 UUID: GPU-1111aaaa-0000-0000-0000-000000000000
"""
  path = _write_log(log)
  try:
    inv = parse_fabricmanager_log(path)
    assert len(inv.nvswitches) == 1
    assert len(inv.gpus) == 1
  finally:
    path.unlink(missing_ok=True)


def test_fm_running_only_when_success_message():
  log = "[INFO] starting up..."
  path = _write_log(log)
  try:
    inv = parse_fabricmanager_log(path)
    assert inv.fm_running is False
  finally:
    path.unlink(missing_ok=True)
