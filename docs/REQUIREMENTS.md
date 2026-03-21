# Ariadne — 요구사항 정의서

## 프로젝트 개요

**Ariadne**(아리아드네)는 시스템 토폴로지(CPU–메모리–PCIe–디바이스) 위에서
E2E 데이터 흐름을 추적하고, bandwidth/latency를 예측하는 **시각화 + 시뮬레이션 도구**다.

- **이름 유래**: 그리스 신화의 아리아드네가 미궁의 실타래로 길을 안내했듯,
  복잡한 시스템 토폴로지에서 데이터 흐름의 경로를 추적한다.
- **언어**: Python 3.10+

## 문제 정의

### 해결하려는 문제

VFIO passthrough, SR-IOV, 멀티 GPU, 대규모 NVMe 등 복잡한 I/O 구성에서:

1. **데이터가 어떤 경로로 흐르는지** 파악이 어렵다
   - CPU → QPI/UPI → PCIe Root Complex → Switch → Device
   - NUMA hop, IOMMU 경유 여부, ACS/ATS 영향
2. **병목 지점을 예측하기 어렵다**
   - PCIe link width/speed, NUMA remote access penalty, IOMMU translation overhead
3. **설정 변경의 영향을 사전에 알 수 없다**
   - vCPU pinning 변경, NUMA topology 변경, IOMMU 그룹 재배치

### 대상 사용자

- **인프라/플랫폼 엔지니어**: KubeVirt/libvirt 환경에서 VFIO passthrough 최적화
- **성능 엔지니어**: NUMA-aware workload placement
- **학습자**: PCIe/NUMA 토폴로지 이해를 위한 시각화

## 용어 정의 (Glossary)

Ariadne 전체에서 일관되게 사용하는 핵심 용어:

| 용어 | 정의 | 예시 |
|------|------|------|
| **Topology** | 시스템의 물리적/논리적 구성 요소와 그 연결 관계의 그래프. 노드(Component)와 에지(Link)로 구성 | 2-socket EPYC + GPU 4개 + NVMe 8개의 전체 구성 |
| **Component** | Topology 그래프의 노드. CPU, NUMA 노드, PCIe Root Complex, Switch, Endpoint, Memory Controller 등 | `NUMA Node 0`, `PCIe Switch (USP)`, `GPU 0000:41:00.0` |
| **Link** | 두 Component 사이의 연결. bandwidth, latency 속성을 가짐 | `PCIe Gen4 x16` (이론 ~32GB/s, latency ~100ns) |
| **Flow** | 하나의 source에서 하나의 destination으로 향하는 데이터 전송. 경로(Path)와 트래픽 특성(패턴, 크기)을 가짐 | `GPU0 → Host Memory` (DMA read, 64KB burst) |
| **Path** | Flow가 통과하는 Link의 순서. Topology 위의 경로 | `GPU0 → PCIe Switch → Root Port → Root Complex → Memory Controller → DRAM` |
| **Scenario** | 하나의 Topology 위에 정의된 Flow들의 집합. "이 시스템에서 이런 워크로드가 동시에 돌면 어떤 일이 일어나는가" | "GPU 4개가 동시에 DMA read + NIC가 RDMA write" |
| **Configuration** | Topology + Settings + Model Parameters + Scenario를 합친 전체 시뮬레이션 입력. 저장/로드/비교의 단위 | `config-epyc-4gpu-training.json` |
| **Snapshot** | 특정 시점의 Configuration을 JSON으로 직렬화한 파일. 오프라인 분석/공유 가능 | 원격 서버에서 수집 → 로컬에서 분석 |
| **Bottleneck** | Scenario 실행 시 전체 성능을 제한하는 Link 또는 Component | "PCIe Switch의 upstream port가 x16인데 downstream 4개 합산 트래픽이 초과" |
| **What-if** | Configuration의 일부를 변경하고 재시뮬레이션하여 결과를 비교하는 작업 | "GPU를 NUMA 0에서 NUMA 1로 옮기면?" |
| **Overlay** | 물리 Topology 위에 가상화 매핑(VM, VFIO, vCPU pinning)을 겹쳐 표시하는 레이어 | VM의 vCPU 0~7 → pCPU 0~7 (NUMA 0) 바인딩 시각화 |
| **Settings** | 물리 토폴로지를 바꾸지 않고 성능에 영향을 주는 BIOS/커널/디바이스 설정의 집합. Topology와 독립적으로 변경 가능 | `iommu=pt`, ASPM OFF, MPS 256, hugepage 1G |
| **Transfer Mode** | 데이터 전송 방식. 같은 source-destination 쌍이라도 전송 방식에 따라 Path와 성능이 달라짐 | DMA, RDMA, GPUDirect RDMA, GPUDirect Storage, P2P, NVLink |
| **Device Profile** | 특정 디바이스 모델의 성능 특성 프리셋. 벤더/모델별 BW, latency, 지원 기능 정보 | Mellanox ConnectX-7: 400Gbps, RoCEv2, GPUDirect |

## 대상 디바이스 (Target Devices)

Ariadne가 모델링하는 주요 디바이스 카테고리와 우선 지원 벤더:

### GPU

| 벤더 | 모델 예시 | 핵심 속성 |
|------|----------|----------|
| **NVIDIA** | A100, H100, B200 | PCIe Gen4/5, GPUDirect RDMA, GPUDirect Storage, NVLink (GPU 간 토폴로지/BW), VRAM BW |

### NIC / HCA (Network)

| 벤더 | 모델 예시 | 핵심 속성 |
|------|----------|----------|
| **NVIDIA (Mellanox)** | ConnectX-6/7, BlueField-3 DPU | InfiniBand (HDR/NDR), RoCEv2, GPUDirect RDMA, SR-IOV, PCIe Gen4/5 |
| **Broadcom** | BCM57508 (P2100G), Stingray PS1100R | RoCEv2, SR-IOV, PCIe Gen4, 100/200GbE |

### Storage

| 벤더 | 모델 예시 | 핵심 속성 |
|------|----------|----------|
| **NVMe SSD** | Samsung PM9A3, Micron 9400 | PCIe Gen4/5, NVMe 1.4+, GPUDirect Storage 지원 여부 |
| **NVMe-oF Target** | — | RDMA 기반 원격 스토리지 (fabric 경유, 향후) |

### 특수 데이터 전송 경로 (Transfer Modes)

일반적인 `Device → PCIe → Host Memory` 외에 다음 경로를 모델링:

```
일반 DMA:
  Device ──PCIe──► Host Memory
  경로: EP → Switch → RC → MC → DRAM

RDMA (RoCE / InfiniBand):
  NIC ──PCIe──► Host Memory (RDMA 버퍼, kernel bypass)
  경로: 일반 DMA와 동일하지만 latency 모델이 다름
  특성: kernel bypass → context switch overhead 제거, zero-copy

GPUDirect RDMA (GDR):
  NIC ──PCIe P2P──► GPU VRAM (host memory 경유하지 않음)
  경로: NIC EP → (PCIe Switch or RC) → GPU EP
  조건: NIC과 GPU가 같은 PCIe Switch 하위이거나 RC 경유
  특성: host memory 복사 제거 → latency/BW 개선

GPUDirect Storage (GDS):
  NVMe ──PCIe P2P──► GPU VRAM (host memory 경유하지 않음)
  경로: NVMe EP → (PCIe Switch or RC) → GPU EP
  조건: GDR과 동일한 PCIe P2P 요건
  특성: storage → GPU 직접 전송, bounce buffer 제거

PCIe Peer-to-Peer (P2P):
  Device A ──PCIe──► Device B (host memory 경유 가능/불가능)
  경로: ACS 설정에 따라 달라짐
    ACS OFF: Switch 내 직접 라우팅 (최적)
    ACS ON: RC 경유 강제 (IOMMU 격리를 위해)

NVLink P2P (GPU-to-GPU):
  GPU0 ──NVLink──► GPU1 (PCIe 경유하지 않음)
  경로: GPU EP → NVLink → GPU EP (직접 연결)
  또는: GPU0 → NVLink → NVSwitch → NVLink → GPU5 (NVSwitch 경유)
  특성: PCIe 대비 10~30배 BW (NVLink4: 900GB/s bidirectional per GPU)
  조건: 양쪽 GPU가 NVLink로 연결되어 있어야 함
  Fallback: NVLink 없으면 PCIe P2P로 자동 전환
```

**GPU-to-GPU 경로 자동 선택 로직**:
```
GPU A → GPU B 통신 시:
  1. NVLink 직접 연결 있음? → nvlink_p2p (최적)
  2. NVSwitch 경유 가능?    → nvlink_p2p via NVSwitch
  3. 같은 PCIe Switch 하위? → p2p (PCIe 직접, ACS 의존)
  4. 다른 Root Port?        → p2p via RC (PCIe, host memory 경유 가능)
```

## PCIe Capability 모델링

데이터 흐름의 **경로와 성능을 결정**하는 PCIe capability들을 모델링한다.
이들은 디바이스의 기능이 아니라 **"데이터가 어떤 경로로 흐르는가"**를 바꾸는 요소다.

### 경로 결정 Capability

| Capability | 데이터 흐름에 미치는 영향 | 수집 방법 |
|-----------|----------------------|----------|
| **ACS** (Access Control Services) | P2P TLP을 Switch에서 직접 라우팅할지, RC로 리다이렉트할지 결정. ACS ON = P2P가 IOMMU 경유 (느리지만 격리), ACS OFF = Switch 내 직접 (빠르지만 격리 불가) | `lspci -vv` (ACS capability), sysfs |
| **ARI** (Alternative Routing-ID Interpretation) | BDF function 번호를 3bit(8개) → 8bit(256개)로 확장. SR-IOV에서 VF 8개 이상 생성에 필수. BDF 공간 소비 모델에 영향 | `lspci -vv` (ARI capability) |
| **ATS** (Address Translation Services) | 디바이스가 IOMMU translation을 캐시 (ATC). ATS hit 시 IOMMU page walk 생략 → latency 대폭 감소 | `lspci -vv` (ATS capability) |

### 성능/기능 Capability

| Capability | 영향 | 수집 방법 |
|-----------|------|----------|
| **PASID** (Process Address Space ID) | 디바이스가 프로세스별 주소 공간 사용 (SVM/SVA). 컨테이너 디바이스 공유에 필요 (향후) | `lspci -vv` |
| **PRI** (Page Request Interface) | 디바이스가 OS에 page fault 요청. PASID와 함께 demand paging 지원 | `lspci -vv` |
| **FLR** (Function Level Reset) | 개별 function 리셋. VFIO unbind/재할당 시 clean reset 보장 | `lspci -vv` |
| **Resizable BAR** | 런타임 BAR 크기 변경. GPU 전체 VRAM 매핑 가능 → 성능 최적화 | `lspci -vv`, BIOS 설정 |
| **LTR** (Latency Tolerance Reporting) | 디바이스가 허용 latency를 보고 → ASPM 정책에 영향 | `lspci -vv` |

### ACS 설정과 경로 변화 시각화

```
ACS 비활성화 (또는 disable_acs_redir):
  GPU0 ──► Switch ──► GPU1          (직접 P2P, ~100ns)

ACS 활성화 (P2P Redirect ON):
  GPU0 ──► Switch ──► RC ──► IOMMU ──► RC ──► Switch ──► GPU1  (~400ns)
```

Ariadne는 ACS 설정 변경에 따라 **Flow의 Path가 어떻게 바뀌는지** 시각화하고, BW/latency 변화를 계산한다.

### 커널 파라미터와 시뮬레이션 영향

| 커널 파라미터 | Ariadne 모델 영향 | 사용 시나리오 |
|-------------|------------------|-------------|
| `pcie_acs_override=downstream` | IOMMU 그룹 강제 분리 → VFIO 개별 할당 가능, 단 ACS 없는 HW에서 보안 약화 | 같은 Switch 하위 디바이스를 개별 VM에 할당 |
| `pcie_acs_override=multifunction` | multifunction 디바이스 내 function 분리 → 개별 VFIO 할당 | 듀얼포트 NIC의 각 port를 다른 VM에 할당 |
| `pci=disable_acs_redir=pci:10de:*` | 특정 벤더의 ACS redirect OFF → P2P 직접 라우팅 허용 | GPUDirect RDMA: NVIDIA GPU+NIC 간 P2P |
| `pci=disable_acs_redir=pci:15b3:*` | Mellanox NIC의 ACS redirect OFF | GDR에서 NIC→GPU P2P 활성화 |

### 시나리오별 Capability 교차 영향

| 시나리오 | 필수 Capability | 선택 Capability | 설정 충돌 |
|---------|---------------|---------------|----------|
| **VM + VFIO GPU** | ACS (IOMMU 그룹 분리), FLR | ATS, Resizable BAR | ACS ON ↔ GPUDirect P2P 차단 |
| **VM + SR-IOV VF** | ARI (VF 8+), ACS, FLR | ATS (VF별 IOTLB) | — |
| **GPUDirect RDMA** | ACS redirect OFF (GPU+NIC 모두) | — | ACS OFF → IOMMU 그룹 병합 → 개별 VFIO 불가 |
| **Container + SR-IOV** | ARI, SR-IOV | PASID+PRI (향후 SVM) | — |
| **멀티 VM + GPUDirect** | ACS override + disable_acs_redir 조합 | ATS | IOMMU 격리 vs P2P 성능 트레이드오프 |

Ariadne는 이 교차 영향을 시뮬레이션하여 **"이 설정 조합에서 어떤 것이 가능하고 어떤 것이 불가능한지"**를 사전에 분석한다.

## 가치 제안 (Value Proposition)

Ariadne가 제공하는 핵심 가치:

### 보기 (See)
> "이 시스템의 데이터 경로가 어떻게 생겼는지 한눈에 보여줘"

- 물리 Topology를 통합 그래프로 시각화 (CPU/NUMA + PCIe + IOMMU + Device)
- VM Overlay로 가상화 매핑까지 포함
- 기존 도구(lstopo, lspci)가 각각 보여주는 것을 하나의 뷰로 통합

### 추적하기 (Trace)
> "이 GPU에서 메모리까지 데이터가 실제로 어떤 경로로 가는지 보여줘"

- 임의의 source → destination 사이의 E2E Path를 추적
- 각 구간(Link)별 BW/latency breakdown 제공
- NUMA hop, IOMMU 경유 여부 명시

### 시뮬레이션하기 (Simulate)
> "GPU 4개가 동시에 DMA 하면 어디서 병목이 생기는지 시뮬레이션해줘"

- 다중 Flow를 정의하고 시간축 위에서 경합/큐잉 시뮬레이션
- 구간별 BW utilization, latency 분포, 병목 지점 식별
- 트래픽 패턴(burst, sustained, mixed) 반영

### 비교하기 (Compare)
> "GPU를 NUMA 1으로 옮기면 성능이 얼마나 바뀌는지 비교해줘"

- Configuration을 변경하고 재시뮬레이션
- 변경 전후 결과를 side-by-side로 비교
- 최적 구성 탐색

## 사용자 시나리오 (User Scenarios)

### 시나리오 A: "현재 시스템 파악"

```
사용자: 인프라 엔지니어, 새로 할당받은 베어메탈 서버 분석

1. Ariadne에 접속 → "현재 시스템 수집" 클릭
2. 호스트에서 sysfs/procfs/lspci 자동 수집
3. 전체 Topology가 그래프로 표시됨:
   - 2 Socket, 4 NUMA Node
   - PCIe Switch 2개, GPU 4개, NVMe 8개, NIC 2개
   - 각 Link에 speed/width 표시
4. NUMA Node 0 클릭 → 연결된 디바이스 하이라이트
5. IOMMU 그룹 오버레이 ON → 어떤 디바이스가 같은 그룹인지 표시
6. JSON Snapshot 저장 → 팀에 공유
```

### 시나리오 B: "단일 E2E 흐름 분석"

```
사용자: 성능 엔지니어, GPU DMA 경로 확인

1. Topology 뷰에서 GPU0 (source) 클릭 → Host Memory (destination) 클릭
2. E2E Path가 하이라이트됨:
   GPU0 → PCIe EP → Switch DSP → Switch USP → Root Port → RC → MC → DRAM
3. 각 구간별 breakdown 테이블 표시:
   | 구간              | 이론 BW    | latency  | 비고           |
   |-------------------|-----------|----------|----------------|
   | GPU → Switch      | 32 GB/s   | ~100ns   | Gen4 x16       |
   | Switch → Root Port| 32 GB/s   | ~50ns    | Gen4 x16 (USP) |
   | Root Port → MC    | 내부      | ~50ns    | SoC 내부       |
   | MC → DRAM         | 204 GB/s  | ~80ns    | DDR5-4800 8ch  |
   | **E2E**           | **32 GB/s** | **~280ns** | bottleneck: PCIe |
4. "IOMMU 활성화 시" 토글 → latency에 +200ns 반영된 결과 표시
```

### 시나리오 C: "다중 디바이스 경합 시뮬레이션"

```
사용자: ML 플랫폼 엔지니어, 4-GPU 학습 시 PCIe 병목 확인

1. Scenario 생성:
   - Flow 1: GPU0 → Host Memory (DMA read, 64KB, sustained)
   - Flow 2: GPU1 → Host Memory (DMA read, 64KB, sustained)
   - Flow 3: GPU2 → Host Memory (DMA read, 64KB, sustained)
   - Flow 4: GPU3 → Host Memory (DMA read, 64KB, sustained)
2. "시뮬레이션 실행" 클릭
3. 결과:
   - 4개 GPU가 같은 PCIe Switch USP (x16, 32GB/s)를 공유
   - 개별 GPU당 실효 BW: ~8GB/s (32/4)
   - Switch USP가 병목으로 빨간색 하이라이트
   - 시계열 차트: BW utilization over time
4. What-if: "GPU 2개를 다른 PCIe Root Port로 이동" → 재시뮬레이션
   - 각 그룹 2개씩 → GPU당 ~16GB/s → 비교 뷰 표시
```

### 시나리오 D: "VM VFIO passthrough 최적화"

```
사용자: KubeVirt 관리자, VM에 GPU 4개 + NVMe 8개 할당 최적화

1. 호스트 Topology 수집 완료 상태
2. "VM Overlay 추가" → QEMU cmdline 또는 libvirt XML 입력
3. Topology 위에 VM 오버레이 표시:
   - vCPU 0~31 → pCPU 0~31 (NUMA 0,1)
   - VFIO GPU 0~3 → PCI 0000:41~44:00.0
   - VFIO NVMe 0~7 → PCI 0000:61~68:00.0
4. 문제 발견: GPU 2개는 NUMA 0, 2개는 NUMA 1인데 vCPU가 NUMA 0에만 할당됨
   → "NUMA 불일치" 경고 표시
5. Scenario: 4 GPU DMA + 8 NVMe I/O 동시 실행
6. 시뮬레이션 → NUMA 1의 GPU가 cross-NUMA 접근으로 latency 2배 증가
7. What-if: "vCPU를 NUMA 0,1에 균등 분배" → 재시뮬레이션 → 개선 확인
```

### 시나리오 E: "장비 추가/변경 시뮬레이션 (가상 구성)"

```
사용자: 하드웨어 계획 담당자, 기존 서버에 GPU 추가 시 영향 분석

1. 현재 Topology (GPU 2개) Snapshot 로드
2. "Component 추가" → 가상 GPU 2개를 PCIe Slot 3,4에 배치
   - 사용자가 선택: Gen4 x16, NUMA 1에 연결
3. 기존 Scenario (GPU 2개 DMA) + 추가된 GPU 2개 DMA Flow 정의
4. 시뮬레이션 → 기존 GPU의 성능 영향 분석
5. 비교 뷰: 2-GPU 구성 vs 4-GPU 구성의 BW/latency 차이
```

### 시나리오 F: "멀티 VM 환경 분석"

```
사용자: 클라우드 인프라 담당자, 하나의 호스트에서 VM 3개 운영

1. 호스트 Topology 수집
2. VM Overlay 3개 추가:
   - VM-A: vCPU 0~15, GPU 0~1 (VFIO), NVMe 0~1 (VFIO)
   - VM-B: vCPU 16~31, GPU 2~3 (VFIO), NVMe 2~3 (VFIO)
   - VM-C: vCPU 32~47, NIC 0 (VFIO), NVMe 4~7 (VFIO)
3. 각 VM의 Flow를 색상/패턴으로 구분:
   - VM-A: 파란색 실선
   - VM-B: 초록색 실선
   - VM-C: 주황색 점선
4. Scenario: 3 VM 동시 워크로드
5. 시뮬레이션 → 공유 Link에서 VM 간 BW 경합 시각화
   - PCIe Switch USP를 VM-A와 VM-B가 공유 → 양쪽 모두 BW 감소
   - Memory Controller를 3 VM이 모두 공유 → MC가 전체 병목
6. 각 VM 별 필터링: "VM-A만 보기" → VM-A의 Flow만 하이라이트
```

### 시나리오 G: "커널/BIOS 설정 변경 영향 분석"

```
사용자: 성능 엔지니어, IOMMU 모드와 hugepage 설정 최적화

1. 현재 Topology + 현재 Settings 수집 완료
   - 현재: iommu=on, hugepage=2MB, ASPM=L1
2. Scenario: GPU 4개 DMA + NVMe 8개 I/O 동시 실행
3. 기준 시뮬레이션 실행 → 결과 저장

4. What-if 설정 변경 1: iommu=pt
   → iommu_latency_ns: 300ns → 0ns
   → 재시뮬레이션 → GPU DMA latency 40% 감소

5. What-if 설정 변경 2: hugepage=1G
   → IOTLB miss rate 모델: 5% → 0.1%
   → iommu=on에서도 latency 절반 감소

6. What-if 설정 변경 3: ASPM=off + CPU governor=performance
   → Link latency에서 복귀 지연 제거, interconnect BW 최대화
   → 재시뮬레이션 → tail latency(p99) 대폭 개선

7. 비교 뷰: 4개 Configuration (원본 + 3가지 변경)의 결과 나란히 비교
   → 최적 조합: iommu=pt + hugepage=1G + ASPM=off
```

### 시나리오 H: "SR-IOV VFIO 안전성 사전 분석"

```
사용자: 인프라 엔지니어, Broadcom NIC SR-IOV VF를 VM에 VFIO 할당하려 함

1. 호스트 Topology 수집 → NIC PF + VF 8개 표시
2. IOMMU 그룹 분석:
   ⚠️ 경고: "PF 0000:81:00.0과 VF 0000:81:00.1~8이 같은 IOMMU 그룹 25"
   ⚠️ 경고: "VF를 VFIO로 격리하면 PF까지 격리 범위에 포함됨"
   ⚠️ 경고: "reset_method에 bus_reset 포함 → PF 리셋 → 호스트 NIC 상실 위험"
3. 해결 제안 표시:
   - 옵션 A: pcie_acs_override=downstream,multifunction → PF/VF 그룹 분리
   - 옵션 B: 각 VF의 reset_method에서 bus_reset 제거
4. What-if: ACS override 적용 시 IOMMU 그룹 변화 시뮬레이션
   - 변경 전: 그룹 25 = {PF, VF0, VF1, ..., VF7}
   - 변경 후: 그룹 25 = {PF}, 그룹 26 = {VF0}, ..., 그룹 33 = {VF7}
5. 각 VF의 reset_method 표시:
   - FLR: ❌ (Broadcom 미지원)
   - PM reset: ✅
   - bus_reset: ✅ ← 위험, 제거 권장
```

## 기능 요구사항

### 토폴로지 수집 (Topology Collector)

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| TC-1 | sysfs/procfs 기반 CPU/NUMA/Cache 토폴로지 파싱 (직접 구현) | P0 |
| TC-2 | sysfs 기반 PCIe 토폴로지 수집 (`/sys/bus/pci/devices/`) | P0 |
| TC-3 | lspci 파싱 (vendor/device ID, link speed/width, BAR 정보) | P0 |
| TC-4 | IOMMU 그룹 매핑 (`/sys/kernel/iommu_groups/`) | P0 |
| TC-5 | QEMU command line 파싱 (VM 구성 추출) | P1 |
| TC-6 | libvirt XML 파싱 | P1 |
| TC-7 | KubeVirt VMI spec 파싱 | P2 |
| TC-8 | SR-IOV VF/PF 관계 수집 | P1 |

### 토폴로지 모델 (Topology Model)

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| TM-1 | 계층적 토폴로지 그래프 구축 (NUMA → Socket → PCIe RC → Switch → EP) | P0 |
| TM-2 | 각 edge에 bandwidth/latency 속성 부여 | P0 |
| TM-3 | NUMA distance matrix 반영 | P0 |
| TM-4 | IOMMU/ACS/ATS 속성 모델링 | P1 |
| TM-5 | VM overlay (vCPU-pCPU, VFIO device 매핑) | P1 |

### 흐름 분석 (Flow Analysis)

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FA-1 | source → destination E2E 경로 추적 | P0 |
| FA-2 | 경로 상 bottleneck bandwidth 계산 (min-cut) | P0 |
| FA-3 | 경로 상 누적 latency 계산 | P0 |
| FA-4 | NUMA hop penalty 반영 | P0 |
| FA-5 | IOMMU translation overhead 반영 | P1 |

### 트래픽 시뮬레이션 (Traffic Simulation)

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| TS-1 | Discrete-Event Simulation (DES) 엔진 | P0 |
| TS-2 | 다중 흐름 간 bandwidth 경합 모델링 | P0 |
| TS-3 | 큐잉 모델 기반 latency 분포 예측 (avg + tail) | P1 |
| TS-4 | 트래픽 패턴 프로파일 입력 (burst, sustained, mixed) | P1 |
| TS-5 | "what-if" 시뮬레이션 (설정 변경 전후 비교) | P0 |
| TS-6 | 시뮬레이션 결과 시계열 출력 (BW utilization over time) | P1 |
| TS-7 | 시뮬레이션 스냅샷 저장/비교 | P1 |

**시뮬레이션 범위 정의**:

```
Level 1 — 정적 경로 분석 (FA-1 ~ FA-5)
  토폴로지 그래프에서 경로/BW/latency 계산. 시간축 없음.

Level 2 — 트래픽 시뮬레이션 (TS-1 ~ TS-7)   ← Ariadne 목표
  시간축이 있는 DES. 다중 흐름 경합, 큐잉, 트래픽 패턴 반영.
  예: "GPU 4개가 동시에 64KB DMA read → PCIe switch에서 BW 경합 시뮬레이션"

Level 3 — 프로토콜 수준 시뮬레이션 (Out of Scope)
  PCIe TLP credit flow, ordering, replay 등. → SimBricks/cocotbext-pcie 영역.
```

### 시각화 (Visualization)

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| VZ-1 | Engine: JSON-serializable 토폴로지/시뮬레이션 결과 출력 | P0 |
| VZ-2 | CLI/TUI: 터미널 텍스트 다이어그램 (ASCII/Unicode) | P0 |
| VZ-3 | Web UI: 인터랙티브 토폴로지 시각화 (노드 클릭, 줌, 패닝) | P1 |
| VZ-4 | Web UI: 실시간 시뮬레이션 결과 시각화 (흐름 애니메이션) | P1 |
| VZ-5 | Web UI: 병목 지점 히트맵 / 색상 하이라이트 | P1 |
| VZ-6 | Web UI: What-if 비교 뷰 (설정 A vs B side-by-side) | P1 |
| VZ-7 | Web UI: 시뮬레이션 파라미터 조작 UI (슬라이더, 드롭다운) | P1 |
| VZ-8 | 정적 내보내기: SVG, PNG, Graphviz DOT | P1 |

**시각화 아키텍처 원칙**:
- Engine은 시각화 데이터를 JSON으로만 제공 (VZ-1)
- 모든 UI (CLI, Web, GUI)는 이 JSON을 소비하여 렌더링
- Web UI는 별도 패키지 (`ariadne-web`)로 분리

## 비기능 요구사항

| ID | 요구사항 | 비고 |
|----|----------|------|
| NF-1 | root 권한 없이 기본 기능 동작 | sysfs 읽기는 일반 유저 가능 |
| NF-2 | 단일 호스트에서 < 5초 내 토폴로지 수집 완료 | |
| NF-3 | Engine 패키지는 UI 의존성 없이 설치 가능 | `pip install ariadne-core` |
| NF-4 | 오프라인 모드 지원 (JSON snapshot → 분석/시뮬레이션) | |
| NF-5 | Python 3.10+ 호환 | |
| NF-6 | Engine ↔ UI 통신은 REST API (JSON over HTTP/WebSocket) | |
| NF-7 | 시뮬레이션은 100개 동시 흐름에서 < 10초 내 완료 | |

## 기능 범위

### 포함 (In Scope)

- 호스트 물리 토폴로지 수집 및 모델링
- PCIe 트리 시각화 (link speed/width 포함)
- NVLink 토폴로지 시각화 (GPU 간 연결, NVSwitch)
- NUMA topology 시각화
- IOMMU 그룹 매핑 시각화
- E2E 데이터 흐름 경로 추적 및 bandwidth/latency 예측
- **Transfer Modes**: DMA, RDMA, GPUDirect RDMA/Storage, PCIe P2P, NVLink P2P
- **트래픽 시뮬레이션**: 다중 흐름 경합, 큐잉 모델, 트래픽 패턴
- VM/VFIO overlay (QEMU cmdline, libvirt XML 기반)
- **시스템 설정 변경 시뮬레이션**: BIOS/커널/디바이스 설정의 성능 영향 모델링
- 설정 변경 비교 (what-if)
- **웹 기반 인터랙티브 시각화**: 토폴로지 그래프, 시뮬레이션 결과, 비교 뷰
- **REST API**: Engine 기능을 외부 도구에서 호출 가능

### 미포함 (Out of Scope)

- **RTL/프로토콜 수준 시뮬레이션**: TLP credit flow, ordering, replay 등 cycle-accurate 시뮬레이션 (→ cocotbext-pcie, SimBricks 영역)
- **네트워크 시뮬레이션**: 호스트 간 네트워크는 다루지 않음 (→ ns-3, OMNeT++ 영역)
- **런타임 모니터링**: perf counter 기반 실시간 모니터링은 하지 않음 (→ numatop 영역)
- **NVLink/NVSwitch 내부**: NVLink 프로토콜 시뮬레이션, NVSwitch 내부 라우팅은 다루지 않음 (토폴로지와 BW/latency는 다룸)
- **Windows 지원**: Linux만 지원

## 관련 문서

| 문서 | 내용 |
|------|------|
| [DESIGN.md](DESIGN.md) | 아키텍처 원칙, 입출력 모델, 기술 스택, 패키지 구조 |
| [DATA_MODEL.md](DATA_MODEL.md) | 레이어별 데이터 모델, S/W 측정 전략, 모델 파라미터 |
| [COMPARISON.md](COMPARISON.md) | 기존 오픈소스 도구 비교 분석 |
