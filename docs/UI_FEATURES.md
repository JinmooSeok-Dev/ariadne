# Ariadne Web UI — 현재 구현 기능 목록

현재까지 구현된 모든 UI 기능을 디테일하게 정리한다. 리팩토링의 기준 문서.

## Overview (시스템 토폴로지 뷰)

### 노드 표시

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| 계층 트리 렌더링 | 모든 디바이스를 가로(LR) 트리로 표시. CSS flexbox 기반 | `buildNode()` |
| 노드 색상 | 타입별 배경색 (GPU=녹, NVMe=주황, NIC=보라 등) | `COLORS` 객체 |
| 노드 아이콘 | 타입별 작은 색상 dot | `.htree-dot` |
| 뱃지 표시 | PCIe Gen/Width, IOMMU 그룹, SR-IOV VF 수, BAR 크기, 메모리 용량, CPU 수 | `buildNode()` 내 badges |
| 모든 디바이스 기본 표시 | 칩셋 직결(USB, SATA 등) 포함 전부 표시. 숨기지 않음 | server.py graph API |

### 노드 정렬

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| depth별 수직 정렬 | 같은 depth의 노드가 같은 X 위치 (min-width 고정) | `--node-min-w` CSS 변수 |
| 자식 들여쓰기 | 부모 대비 60px 들여쓰기 | `--child-indent` CSS 변수 |

### Edge 표시

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| SVG 꺾인 직선 | 부모 오른쪽 → 중간점 → 자식 왼쪽으로 elbow path | `drawEdges()` |
| 독립 edge | 각 edge가 별도 SVG `<g>` 그룹. 개별 하이라이트/클릭 가능 | `drawEdges()` |
| PCIe/internal 구분 | PCIe = 파란 실선, internal = 회색 점선 | `.edge-line.pcie`, `.edge-line.internal` |
| BW 라벨 | hover 시에만 표시. 배경 박스 포함 | `.edge-bw`, `.edge-bg` |
| Edge 히트 영역 | 투명 16px path로 hover/click 용이 | hitPath `pointer-events: stroke` |
| Edge hover | 가까이 가면 edge 굵게 + 흰색 | `.edge-line:hover` |
| Edge 클릭 | sidebar Info 탭에 edge 상세 표시 (타입, BW, latency, speed, width) | `showEdgeDetail()` |
| Edge 데이터 모델 | `edgeMap[eId]`에 메타데이터 관리 (source, target, type, BW, latency, path 좌표) | `edgeMap` 객체 |

### 접기/펼치기

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| 토글 버튼 | 자식 있는 노드에 ▼/▶ 표시 | `buildNode()` 내 `.htree-toggle` |
| 접으면 숨김 | 하위 트리 전체 숨김 | `.htree-children.folded` |
| 카운트 뱃지 | 접힌 상태에서 하위 디바이스 총 수 표시 (빨간 뱃지) | `.htree-count` |

### 줌

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| +/− 버튼 | 10% 단위 줌 인/아웃 (20%~200%) | `zoomIn()`, `zoomOut()` |
| Fit 버튼 | 트리를 화면에 맞게 자동 줌 | `zoomFit()` |
| 마우스 휠 | Ctrl+스크롤로 줌 | `wheel` 이벤트 |
| 줌 레벨 표시 | 현재 % 표시 | `#zoom-level` |
| CSS transform | `scale()` 기반, `transform-origin: 0 0` | `setZoom()` |

### 검색

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| 검색 입력 | header에 검색창 | `#search` |
| 매칭 노드 강조 | 이름/BDF 매칭 → glow + brightness | `.search-hl` |
| 비매칭 dim | 나머지 opacity 0.3 | `.search-dim` |

## Trace (경로 추적)

### 입력 방식

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| 클릭 선택 | traceable 노드 클릭 → src(첫) → dst(둘째) → trace 실행 | `pickNode()` |
| 재선택 | trace 완료 후 클릭 → 새 src로 교체 (ESC 불필요) | `pickNode()` 3번째 분기 |
| 우클릭 메뉴 | HTML 컨텍스트 메뉴: Set as Source/Dest, Trace to Memory, Swap, Info | `showCtx()`, `ctxDo()` |
| ESC 초기화 | ESC 키 → 전체 선택/하이라이트 초기화 | `clearSel()` |
| Clear 버튼 | header에 Clear(ESC) 버튼 | `#bclear` |
| Traceable 제한 | GPU, NPU, NVMe, NIC, Memory Controller, PCIe Endpoint만 trace 가능 | `TRACEABLE` Set |
| 상단 selection bar | 현재 src → dst 표시 (녹색 src, 주황 dst) | `updSel()` |

### 결과 표시

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| Summary 카드 | BW (GB/s), Latency (ns), NUMA (same/cross) | `renderTrace()` 카드 영역 |
| Bottleneck 경고 | ⚠ 표시 + 빨간색 | `renderTrace()` bottleneck 영역 |
| Path 다이어그램 | src → 중간 노드 → dst 세로 리스트. 각 구간에 번호/타입/latency/BW | `renderTrace()` Path 영역 |
| Breakdown 테이블 | #, Segment, Theo BW, Eff BW, Latency. Bottleneck 행 빨간색 | `renderTrace()` 테이블 |
| E2E 요약 행 | 테이블 마지막 행에 전체 BW/Latency | `renderTrace()` |

### 트리 하이라이트

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| Source 노드 | 녹색 테두리 + glow | `.src-sel` |
| Destination 노드 | 주황 테두리 + glow | `.dst-sel` |
| 경유 노드 | 빨강 테두리 | `.on-path` |
| 경로 edge | 빨강 + glow (drop-shadow) | `.trace-hl` |

### 양방향 연동

| 방향 | 동작 | 구현 위치 |
|------|------|----------|
| Sidebar → 트리 | Breakdown 행/Path 항목 hover → 해당 edge 흰색 + 노드 강조 | `hlSeg()` |
| Sidebar → 트리 | Breakdown 행/Path 항목 클릭 → 해당 노드로 스크롤 | `scrollToSeg()` |
| 트리 → Sidebar | 트리 edge hover → Breakdown 행 + Path 항목 시안 강조 | `hlSegFromEdge()` |
| Sidebar 강조 색상 | 시안(`#06b6d4`) 배경/텍스트 (흰색 텍스트와 구분) | `.hl` 클래스 |

## History

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| 자동 저장 | trace 완료 시 자동 추가 (최대 10개) | `doTrace()` 내 `hist.unshift()` |
| 리스트 표시 | src → dst, BW, Latency 요약 | `showHistory()` |
| 클릭 복원 | 이전 trace 클릭 → 트리 하이라이트 복원 + sidebar 결과 표시 | `replay()` |

## Info

| 기능 | 설명 | 구현 위치 |
|------|------|----------|
| 노드 정보 | 노드 클릭 → 모든 속성 표시 (타입, BDF, BW, IOMMU 등) | `showInfo()` |
| Edge 정보 | edge 클릭 → src/dst, 타입, BW, latency, speed, width 표시 | `showEdgeDetail()` |

## Sidebar 탭

| 탭 | 내용 |
|----|------|
| **Trace** | trace 결과 (Summary + Path + Breakdown) |
| **Info** | 선택한 노드/edge 상세 정보 |
| **History** | 이전 trace 리스트 |

## API

| Endpoint | 설명 |
|----------|------|
| `GET /` | Web UI HTML |
| `GET /api/topology` | 전체 토폴로지 JSON |
| `GET /api/topology/graph` | 노드/edge 트리 (Cytoscape 형식) |
| `GET /api/trace?source=&destination=` | E2E 경로 추적 결과 |
| `POST /api/topology/reload` | 토폴로지 재수집 |
