# Ariadne — UI 구현 원칙 및 스타일 가이드

## UI 구현 원칙

### 핵심: "복잡한 시스템을 한눈에, 원하는 정보를 쉽게"

- **모든 디바이스를 기본 표시** — 임의로 숨기지 않음. 사용자가 접기/필터로 제어
- **계층 구조가 명확해야 함** — 터미널 `ariadne show`와 동일한 트리 구조를 Web UI에 그대로 반영
- **Edge가 독립적이어야 함** — 각 노드 간 연결(edge)은 독립 요소. 개별 하이라이트/클릭/hover 가능
- **인터랙션이 직관적이어야 함** — 클릭/hover 결과가 즉시 시각적으로 보여야 함

### Overview 원칙

- 노드 배치: CSS flexbox로 계층 트리 구성 (가로 LR 방향)
- Edge 렌더링: SVG overlay로 노드 사이 꺾인 직선 (elbow) 독립 렌더링
- 모든 디바이스 표시, 접기/펼치기로 복잡도 관리
- 줌: CSS transform scale + Fit 버튼

### Trace 원칙

- 입력: 클릭 (src → dst), 우클릭 메뉴, 검색
- src 선택 후 다른 src 클릭 → 교체 (리셋 불필요)
- trace 완료 후 다른 노드 클릭 → 새 trace 시작
- 결과: sidebar에 요약 카드 + Path 다이어그램 + Breakdown 테이블
- 양방향 연동: sidebar hover ↔ 트리 edge/노드 동시 하이라이트

## 색상 체계

### 배경

| 요소 | 색상 |
|------|------|
| body 배경 | `#0f0f1a` |
| header/sidebar 배경 | `#1a1a2e` |
| 카드/입력 배경 | `#0f0f1a` |

### 노드 타입별 색상

| 타입 | 색상 | 용도 |
|------|------|------|
| NUMA Node | `#f0c040` | 최상위 도메인 |
| Socket | `#4ecdc4` | CPU 소켓 |
| Memory Controller | `#3b82f6` | 메모리 컨트롤러 |
| Root Complex | `#e94560` | PCIe RC |
| Root Port | `#7c3aed` | PCIe RP (bus) |
| GPU | `#22c55e` | 그래픽 카드 |
| NPU | `#06b6d4` | AI 가속기 (Rebellions 등) |
| NIC | `#a855f7` | 네트워크 (Mellanox, Broadcom 등) |
| NVMe | `#f59e0b` | 스토리지 |
| Endpoint (기타) | `#6b7280` | 기타 PCIe 디바이스 |

### Edge 색상

| 상태 | 색상 | 용도 |
|------|------|------|
| PCIe 기본 | `#4a9eff` (파랑) | PCIe 연결 |
| Internal 기본 | `#666` (점선) | 내부 연결 (NUMA↔Socket 등) |
| Trace 강조 | `#e94560` (빨강) + glow | 선택된 E2E 경로 |
| Segment hover | `#fff` (흰색) | Breakdown 행 hover 시 해당 edge |

### 선택 상태

| 상태 | 색상 | 용도 |
|------|------|------|
| Source 선택 | `#22c55e` (녹색) 테두리 + glow | trace src |
| Destination 선택 | `#f59e0b` (주황) 테두리 + glow | trace dst |
| 경로 경유 노드 | `#e94560` (빨강) 테두리 | trace 중간 노드 |
| Sidebar hover 강조 | `#06b6d4` (시안) 배경/텍스트 | 양방향 연동 |
| 검색 매칭 | glow + brightness | 검색 결과 |
| 검색 비매칭 | `opacity: 0.3` | 나머지 dim |

### 뱃지

| 뱃지 | 색상 |
|------|------|
| BW 라벨 | `#22d3ee` (시안) bold |
| IOMMU 그룹 | `#fbbf24` (노랑) bold |
| 일반 뱃지 (Gen, VF, BAR) | `#ccc` 밝은 회색 |
| Bottleneck 표시 | `#e94560` 빨강 |

## 레이아웃 상수

CSS 변수 (`--`)와 JS `LAYOUT` 객체로 관리. 한곳에서 변경.

```css
:root {
  --child-indent: 60px;    /* 자식 노드 들여쓰기 */
  --child-gap: 2px;        /* 자식 간 세로 간격 */
  --child-pad: 4px;        /* children 컨테이너 패딩 */
  --node-min-w: 160px;     /* 노드 최소 너비 (depth 정렬용) */
}
```

```javascript
const LAYOUT = {
  childIndent: 60,
  childGap: 2,
  childPadding: 4,
  nodeMinWidth: 160,
  edgeWidth: 2,
  edgePcieWidth: 2.5,
  edgeHlWidth: 5,
  bwLabelOffset: 4,
};
```

## 구조

### 레이아웃

```
┌── Header (Ariadne + hostname + 검색 + Clear + Reload) ──────┐
├── Tree Panel ──────────────────────┬── Sidebar ──────────────┤
│                                    │ [Trace] [Info] [History]│
│  [+] [-] 100% [Fit]               │                         │
│                                    │  Summary Cards          │
│  NUMA Node 0 ─── Socket           │  Path Diagram           │
│              ├── MC                │  Breakdown Table        │
│              └── RC ─── RP ─── GPU│                         │
│                     └── RP ─── NIC│                         │
│                     └── USB       │                         │
│  (SVG edge overlay)               │                         │
└────────────────────────────────────┴─────────────────────────┘
```

### 노드 렌더링: HTML/CSS (flexbox)

```html
<div class="htree">
  <div class="htree-node">노드 내용</div>
  <div class="htree-children">
    <div class="htree-child">재귀</div>
  </div>
</div>
```

### Edge 렌더링: SVG overlay

노드 배치 후 `requestAnimationFrame`에서 SVG path를 그림.

```javascript
// 각 edge = 독립 SVG <g> 그룹
<g class="edge-group" data-source="..." data-target="...">
  <path class="edge-line pcie" id="e_src_tgt" d="M... L... L... L..."/>  <!-- 꺾인 직선 -->
  <path stroke="transparent" stroke-width="16"/>  <!-- 히트 영역 -->
  <text class="edge-bw">8</text>                  <!-- BW 라벨 (hover 시 표시) -->
</g>
```

### Edge 데이터 모델

```javascript
edgeMap[eId] = {
  id, source, target, type,
  bandwidth_gbps, latency_ns, speed, width,
  path: { x1, y1, x2, y2, mx },  // SVG 좌표
};
```

## 인터랙션 패턴

### Trace 흐름

```
1. 디바이스 클릭 → Source 선택 (녹색 테두리)
   - 상단 bar: "SRC: NVIDIA GPU → click destination..."
2. 다른 디바이스 클릭 → Destination 선택 (주황 테두리) → Trace 실행
   - 경로 edge 빨강 하이라이트
   - Sidebar에 결과 표시
3. 또 다른 디바이스 클릭 → 새로운 Source로 교체 (리셋 불필요)
4. ESC 또는 Clear → 전체 초기화
```

### 양방향 연동

```
Sidebar hover → 트리:
  Breakdown 행 hover → 해당 edge 흰색 + 해당 노드 강조
  Path 항목 hover → 동일

트리 hover → Sidebar:
  Edge hover → 해당 Breakdown 행 시안색 강조
  Edge hover → BW 라벨 표시

Sidebar 클릭 → 트리:
  Breakdown 행 클릭 → 해당 노드로 스크롤
```

### 우클릭 메뉴

```
🟢 Set as Source
🟡 Set as Destination
📦 Trace to Memory
🔄 Swap Source ↔ Dest
ℹ️ Device Info
```
