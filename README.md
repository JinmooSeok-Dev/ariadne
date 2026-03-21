# Ariadne

시스템 토폴로지(CPU–메모리–PCIe–디바이스) 위에서 E2E 데이터 흐름을 추적하고,
bandwidth/latency를 예측하는 시각화 + 시뮬레이션 도구.

그리스 신화의 아리아드네가 미궁의 실타래로 길을 안내했듯,
복잡한 시스템 토폴로지에서 데이터 흐름의 경로를 추적한다.

## 목표

- **보기** — CPU/NUMA/PCIe/IOMMU/NVLink을 하나의 통합 뷰로 시각화
- **추적** — source → destination E2E 경로 + 구간별 BW/latency breakdown
- **시뮬레이션** — 다중 데이터 흐름의 경합/큐잉/병목 예측
- **비교** — BIOS/커널 설정 변경 전후 성능 비교 (What-if)

## 설치

```bash
cd ariadne-core
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 사용법

```bash
# venv 활성화 (세션당 한 번)
cd ariadne-core
source .venv/bin/activate

# 현재 시스템 토폴로지 보기 (일반 유저)
ariadne show

# 상세 정보 포함 (sudo 권장)
sudo $(which ariadne) show

# JSON snapshot 저장/로드 (오프라인 분석, 팀 공유용)
sudo $(which ariadne) snapshot my-server.json
ariadne load my-server.json
```

> **sudo 권장**: 최대한 많은 정보를 수집하려면 sudo로 실행한다.
>
> | 정보 | 일반 유저 | sudo |
> |------|:--------:|:----:|
> | CPU/NUMA 토폴로지 | ✅ | ✅ |
> | Cache 계층 | ✅ | ✅ |
> | 메모리 총 용량 | ✅ | ✅ |
> | DIMM 상세 (DDR 타입, 속도, 채널 수, 이론 BW) | ❌ | ✅ |
> | PCIe config space (속도, BAR, capability) | ❌ | ✅ |
> | IOMMU 그룹 | ✅ | ✅ |

## 프로젝트 구성

```
ariadne/
├── ariadne-core/               ← Engine (Python 패키지)
│   ├── ariadne/
│   │   ├── collector/          ← sysfs/procfs 기반 토폴로지 수집
│   │   ├── model/              ← NetworkX 기반 토폴로지 그래프 + Pydantic 타입
│   │   ├── viz/                ← Rich 터미널 시각화
│   │   └── cli/                ← Typer CLI
│   └── tests/
└── docs/                       ← 설계 문서
    ├── REQUIREMENTS.md
    ├── DESIGN.md
    ├── DATA_MODEL.md
    └── COMPARISON.md
```

## 구현 상태

| Phase | 목표 | 상태 |
|-------|------|:----:|
| 1 | CPU/NUMA 토폴로지 수집 + 터미널 출력 | ✅ |
| 2 | PCIe 트리 + IOMMU 그룹 + JSON snapshot | |
| 3 | E2E 경로 추적 + BW/latency breakdown | |
| 4 | Web UI (FastAPI + React + D3.js) | |
| 5 | 다중 흐름 경합 시뮬레이션 (DES) | |
| 6 | VM 오버레이 (QEMU/libvirt/KubeVirt) | |
| 7 | BIOS/커널 설정 변경 What-if | |
| 8 | NVLink, RDMA, GPUDirect 경로 | |
| 9 | 멀티 VM 시각화 | |
| 10 | Calibration, 테스트, 패키징 | |

## 기술 스택

| 영역 | 현재 | 예정 |
|------|------|------|
| 토폴로지 수집 | sysfs/procfs 직접 파싱 | lspci, nvidia-smi, rdma/ibstat |
| 그래프 모델 | NetworkX, Pydantic | |
| 터미널 출력 | Rich, Typer | |
| 시뮬레이션 | | SimPy |
| API 서버 | | FastAPI |
| Web UI | | React + D3.js/Cytoscape.js |

## 문서

| 문서 | 내용 |
|------|------|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 요구사항 — 문제 정의, 용어, 디바이스, PCIe capability, 사용자 시나리오, 기능 범위 |
| [docs/DESIGN.md](docs/DESIGN.md) | 설계 — 아키텍처 (Engine/UI 분리), 입출력 모델, 기술 스택, 패키지 구조 |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | 데이터 모델 — 7개 레이어별 S/W 측정 가능 항목, 모델 파라미터, 시뮬레이션 레벨 |
| [docs/COMPARISON.md](docs/COMPARISON.md) | 비교 분석 — hwloc, pcicrawler, numatop, gem5, SimBricks 등 7개 도구 |
