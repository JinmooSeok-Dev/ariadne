"""dmidecode 시스템/보드 식별 테스트."""

from ariadne.collector.system import collect_system_identity


_DMI_DGX_H100 = """\
# dmidecode 3.3
Getting SMBIOS data from sysfs.

Handle 0x0000, DMI type 0, 26 bytes
BIOS Information
\tVendor: AMI
\tVersion: 1.4.5
\tRelease Date: 03/15/2025
\tAddress: 0xF0000

Handle 0x0001, DMI type 1, 27 bytes
System Information
\tManufacturer: NVIDIA
\tProduct Name: HGX H100 8-GPU
\tVersion: Not Specified
\tSerial Number: 1234567890
\tUUID: aabbccdd-eeff-0011-2233-445566778899
\tWake-up Type: Power Switch

Handle 0x0002, DMI type 2, 17 bytes
Base Board Information
\tManufacturer: NVIDIA
\tProduct Name: P3786
\tVersion: PG520_E
\tSerial Number: SN-BASEBOARD-001
"""


def test_dmidecode_dgx_h100_parsing():
  result = collect_system_identity(dmidecode_runner=lambda: _DMI_DGX_H100)
  assert result.system_manufacturer == "NVIDIA"
  assert result.system_product_name == "HGX H100 8-GPU"
  assert result.system_uuid == "aabbccdd-eeff-0011-2233-445566778899"
  assert result.system_serial == "1234567890"
  assert result.baseboard_manufacturer == "NVIDIA"
  assert result.baseboard_product_name == "P3786"
  assert result.bios_vendor == "AMI"
  assert result.bios_version == "1.4.5"
  assert result.bios_release_date == "03/15/2025"


def test_dmidecode_unavailable_returns_empty():
  result = collect_system_identity(dmidecode_runner=lambda: "")
  assert result.system_manufacturer == ""
  assert result.baseboard_product_name == ""


def test_dmidecode_partial_sections():
  """일부 섹션만 있어도 정상 동작."""
  partial = """\
System Information
\tManufacturer: Supermicro
\tProduct Name: SYS-821GE-TNHR
"""
  result = collect_system_identity(dmidecode_runner=lambda: partial)
  assert result.system_manufacturer == "Supermicro"
  assert result.system_product_name == "SYS-821GE-TNHR"
  assert result.bios_vendor == ""
  assert result.baseboard_manufacturer == ""
