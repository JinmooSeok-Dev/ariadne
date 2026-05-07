"""SMBIOS / dmidecode 기반 시스템·보드 식별.

DGX/HGX/일반 서버 보드 모델, 제조사, BIOS 정보를 수집한다. 정보는 inter-host
구분이나 LLM serving 인프라 식별 등에 활용 가능.

`dmidecode`는 root 권한이 필요하다. 권한 없거나 도구 미설치 시 빈 SystemIdentity 반환.
"""

import re
import subprocess
from collections.abc import Callable

from pydantic import BaseModel


class SystemIdentity(BaseModel):
  system_manufacturer: str = ""    # SMBIOS Type 1 (System Information)
  system_product_name: str = ""
  system_uuid: str = ""
  system_serial: str = ""
  baseboard_manufacturer: str = ""  # SMBIOS Type 2 (Baseboard) — DGX/HGX 식별 핵심
  baseboard_product_name: str = ""
  baseboard_serial: str = ""
  bios_vendor: str = ""             # SMBIOS Type 0
  bios_version: str = ""
  bios_release_date: str = ""


def _default_dmidecode_runner() -> str:
  """`dmidecode` 실행 결과. root 아니거나 실패 시 빈 문자열."""
  try:
    r = subprocess.run(
      ["dmidecode"],
      capture_output=True, text=True, timeout=5,
    )
    if r.returncode == 0:
      return r.stdout
  except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
    pass
  return ""


def collect_system_identity(
  dmidecode_runner: Callable[[], str] = _default_dmidecode_runner,
) -> SystemIdentity:
  text = dmidecode_runner()
  if not text:
    return SystemIdentity()

  return SystemIdentity(
    system_manufacturer=_extract(text, "System Information", "Manufacturer"),
    system_product_name=_extract(text, "System Information", "Product Name"),
    system_uuid=_extract(text, "System Information", "UUID"),
    system_serial=_extract(text, "System Information", "Serial Number"),
    baseboard_manufacturer=_extract(text, "Base Board Information", "Manufacturer"),
    baseboard_product_name=_extract(text, "Base Board Information", "Product Name"),
    baseboard_serial=_extract(text, "Base Board Information", "Serial Number"),
    bios_vendor=_extract(text, "BIOS Information", "Vendor"),
    bios_version=_extract(text, "BIOS Information", "Version"),
    bios_release_date=_extract(text, "BIOS Information", "Release Date"),
  )


def _extract(text: str, section: str, field: str) -> str:
  """dmidecode 출력의 `<section>` 블록에서 `<field>: value` 라인 추출.

  dmidecode 출력 형식:
    System Information
            Manufacturer: NVIDIA
            Product Name: HGX H100
  """
  # 섹션 헤더부터 다음 빈 줄 또는 다음 섹션까지의 본문
  pattern = re.compile(
    rf"^{re.escape(section)}\s*$(?P<body>(?:\n[ \t]+\S.*)+)",
    re.MULTILINE,
  )
  m = pattern.search(text)
  if not m:
    return ""
  body = m.group("body")
  field_pat = re.compile(rf"^[ \t]+{re.escape(field)}:\s*(.+?)\s*$", re.MULTILINE)
  fm = field_pat.search(body)
  return fm.group(1).strip() if fm else ""
