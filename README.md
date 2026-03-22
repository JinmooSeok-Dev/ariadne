# Ariadne

시스템 토폴로지(CPU–메모리–PCIe–디바이스) 위에서 E2E 데이터 흐름을 추적하고,
bandwidth/latency를 예측하는 시각화 + 시뮬레이션 도구.

그리스 신화의 아리아드네가 미궁의 실타래로 길을 안내했듯,
복잡한 시스템 토폴로지에서 데이터 흐름의 경로를 추적한다.

## 목표

### 핵심 가치

- **보기 (See)** — 복잡한 시스템의 모든 구성요소를 계층 트리로 한눈에 파악
- **추적 (Trace)** — 임의의 source → destination E2E 경로 + 구간별 BW/latency breakdown
- **시뮬레이션 (Simulate)** — 다중 데이터 흐름의 경합/큐잉/병목 예측 (DES 기반)
- **비교 (Compare)** — BIOS/커널 설정 변경 전후 성능 비교 (What-if)

### 지원 기능 (구현 완료 + 예정)

| 기능 | 상태 |
|------|:----:|
| CPU/NUMA/Cache/Memory 토폴로지 수집 (sysfs/procfs 직접 파싱) | ✅ |
| PCIe 트리 수집 (BDF, speed/width, BAR, IOMMU 그룹, SR-IOV) | ✅ |
| 터미널 토폴로지 출력 (P/E-core 구분, summary 모드) | ✅ |
| E2E 경로 추적 + BW/latency breakdown (CLI fuzzy 선택) | ✅ |
| Web UI: 가로 트리 뷰 + SVG edge + 접기/줌 | ✅ |
| Web UI: Trace 선택 (클릭/우클릭/검색) + sidebar breakdown | ✅ |
| Web UI: 트리 ↔ sidebar 양방향 hover/클릭 연동 | ✅ |
| JSON snapshot 저장/로드 (오프라인 분석, 팀 공유) | ✅ |
| Transfer Mode (RDMA, GPUDirect, P2P, NVLink, UCIe) | 예정 |
| PCIe Capability 분석 (ACS/ARI/ATS → 경로 변화) | 예정 |
| BIOS/커널 설정 영향 시뮬레이션 (iommu, ASPM, hugepage 등) | 예정 |
| VM/VFIO Overlay (QEMU/libvirt/KubeVirt 파싱) | 예정 |
| SR-IOV 안전성 분석 (IOMMU 그룹, reset_method 경고) | 예정 |
| 멀티 VM 시각화 (색상 구분, 공유 BW 경합) | 예정 |
| 다중 흐름 경합 시뮬레이션 (DES) | 예정 |
| Rebellions NPU 지원 (ATOM+ CA22, ATOM-MAX CA25, REBEL CA21) | ✅ |

## 요구사항

- **OS**: Linux (sysfs/procfs 기반 — macOS, Windows 미지원)
- **Python**: 3.10+

## 설치

```bash
cd ariadne-core
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 사용법

### 터미널

```bash
cd ariadne-core
source .venv/bin/activate

# 시스템 토폴로지 보기
ariadne show                       # 전체 트리
ariadne show --summary             # 타입별 요약

# 상세 정보 (sudo 권장)
sudo $(which ariadne) show

# E2E 경로 추적
ariadne trace                      # 인터랙티브 fuzzy 선택
ariadne trace gpu:0 memory         # GPU → Host Memory
ariadne trace gpu:0 nvme:0         # GPU → NVMe
ariadne trace gpu:0 nic:0          # GPU → NIC
ariadne trace 0000:01:00.0 memory  # BDF 직접 지정

# JSON snapshot
sudo $(which ariadne) snapshot my-server.json
ariadne load my-server.json
```

### Web UI

```bash
ariadne serve                      # http://localhost:8000
ariadne serve --port 9000          # 포트 지정
sudo $(which ariadne) serve        # sudo로 상세 정보 포함
```

> **sudo 권장**: PCIe config space, DIMM 상세 등은 root 권한 필요. 기본 CPU/NUMA 정보는 일반 유저로 동작.

## 프로젝트 구성

```
ariadne/
├── ariadne-core/               ← Engine (Python 패키지)
│   ├── ariadne/
│   │   ├── collector/          ← sysfs/procfs 기반 토폴로지 수집
│   │   ├── model/              ← NetworkX 기반 토폴로지 그래프 + Pydantic 타입
│   │   ├── analyzer/           ← E2E 경로 추적 + BW/latency 분석
│   │   ├── api/                ← FastAPI REST 서버
│   │   ├── web/                ← Web UI (HTML/CSS/JS + SVG)
│   │   ├── viz/                ← Rich 터미널 시각화
│   │   └── cli/                ← Typer CLI
│   └── tests/
└── docs/                       ← 설계 문서
```

## 구현 상태

| Phase | 목표 | 상태 |
|-------|------|:----:|
| 1 | CPU/NUMA 토폴로지 수집 + 터미널 출력 | ✅ |
| 2 | PCIe 트리 + IOMMU 그룹 + JSON snapshot | ✅ |
| 3 | E2E 경로 추적 + BW/latency breakdown | ✅ |
| 4 | Web UI | 진행 중 |
| 5 | 다중 흐름 경합 시뮬레이션 (DES) | |
| 6 | VM 오버레이 (QEMU/libvirt/KubeVirt) | |
| 7 | BIOS/커널 설정 변경 What-if | |
| 8 | NVLink, RDMA, GPUDirect, UCIe 경로 | |
| 9 | 멀티 VM 시각화 | |
| 10 | Calibration, 테스트, 패키징 | |

## 기술 스택

| 영역 | 사용 |
|------|------|
| 토폴로지 수집 | sysfs/procfs 직접 파싱 (hwloc 의존 없음) |
| 그래프 모델 | NetworkX, Pydantic |
| 터미널 출력 | Rich, Typer, InquirerPy |
| API 서버 | FastAPI, Uvicorn |
| Web UI | Vanilla JS, SVG edge, Jinja2 템플릿 |
| 시뮬레이션 (예정) | SimPy |

## 문서

| 문서 | 내용 |
|------|------|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 요구사항 — 문제 정의, 용어, 디바이스, PCIe capability, 사용자 시나리오, 기능 범위 |
| [docs/DESIGN.md](docs/DESIGN.md) | 설계 — 아키텍처 (Engine/UI 분리), 입출력 모델, 기술 스택, 패키지 구조 |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | 데이터 모델 — 7개 레이어별 S/W 측정 가능 항목, 모델 파라미터, 시뮬레이션 레벨 |
| [docs/COMPARISON.md](docs/COMPARISON.md) | 비교 분석 — hwloc, pcicrawler, numatop, gem5, SimBricks 등 7개 도구 |
