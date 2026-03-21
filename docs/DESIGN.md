# Ariadne — 설계 문서

## 아키텍처 원칙

### 핵심: Engine / UI 분리

```
┌─────────────────────────────────────────────────────────┐
│                    User Interfaces                       │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ CLI/TUI  │  │  Web UI      │  │  Desktop GUI      │  │
│  │ (Rich)   │  │  (FastAPI +  │  │  (향후 확장)      │  │
│  │          │  │   React/D3)  │  │                   │  │
│  └────┬─────┘  └──────┬───────┘  └────────┬──────────┘  │
│       │               │                   │              │
│       └───────────────┼───────────────────┘              │
│                       ▼                                  │
│              ┌────────────────┐                          │
│              │   REST API     │                          │
│              │  (JSON over    │                          │
│              │   HTTP/WS)     │                          │
│              └────────┬───────┘                          │
└───────────────────────┼──────────────────────────────────┘
                        │
┌───────────────────────┼──────────────────────────────────┐
│                       ▼           Engine (ariadne-core)   │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Python Library API                     │ │
│  │  topology.collect() → model.build() → sim.run()    │ │
│  │                                    → viz.export()   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│  │ Collector  │ │   Model    │ │ Simulator  │           │
│  │ sysfs      │ │ NetworkX   │ │ DES engine │           │
│  │ procfs     │ │ graph      │ │ 경합 모델  │           │
│  │ lspci      │ │ BW/lat     │ │ 큐잉 모델  │           │
│  │ nvidia-smi │ │ NUMA dist  │ │ what-if    │           │
│  │ QEMU/virt  │ │            │ │            │           │
│  └────────────┘ └────────────┘ └────────────┘           │
└──────────────────────────────────────────────────────────┘
```

**원칙**:
1. **Engine은 UI를 모른다**: `ariadne-core`는 순수 Python 라이브러리로, import하여 사용 가능
2. **UI는 교체 가능하다**: CLI, 웹, GUI 중 어떤 것이든 동일한 Engine API를 호출
3. **API 경계는 JSON-serializable**: Engine ↔ UI 사이의 데이터는 모두 JSON으로 직렬화 가능
4. **Engine은 독립 실행 가능**: UI 없이 `python -m ariadne` 또는 라이브러리로 사용

## 입력 모델 (Input Model)

사용자가 Ariadne에 제공하는 입력의 종류와 처리 방식:

### 입력 유형

```
┌────────────────────────────────────────────────────────────┐
│                    Configuration                            │
│                                                            │
│  ┌──────────────────┐   ┌───────────────────────────────┐  │
│  │    Topology       │   │         Scenario              │  │
│  │                  │   │                               │  │
│  │  ┌────────────┐  │   │  ┌─────────────────────────┐  │  │
│  │  │ Base       │  │   │  │ Flow 정의               │  │  │
│  │  │ (수집/로드) │  │   │  │ source, destination,   │  │  │
│  │  └─────┬──────┘  │   │  │ 패턴, 크기             │  │  │
│  │        │         │   │  └─────────────────────────┘  │  │
│  │  ┌─────▼──────┐  │   │  ┌─────────────────────────┐  │  │
│  │  │ Mutations  │  │   │  │ VM Overlay              │  │  │
│  │  │ (추가/변경) │  │   │  │ vCPU pin, VFIO,        │  │  │
│  │  └────────────┘  │   │  │ NUMA config             │  │  │
│  └──────────────────┘   │  └─────────────────────────┘  │  │
│                         └───────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              System Settings                         │  │
│  │  BIOS: ASPM, MPS, SR-IOV, NUMA interleave, ...      │  │
│  │  Kernel: iommu=pt, hugepage, governor, ...           │  │
│  │  Device: ring buffer, coalesce, persistence, ...     │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Model Parameters                        │  │
│  │  pcie_efficiency, iommu_latency_ns, ...              │  │
│  │  (Settings 변경 시 자동으로 파라미터에 반영)            │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

**Settings와 Model Parameters의 관계**: Settings는 사용자가 이해하는 실제 설정 이름(`iommu=pt`, `ASPM=off`)이고, Model Parameters는 시뮬레이션 엔진이 사용하는 내부 수치(`iommu_latency_ns=0`, `aspm_recovery_us=0`). Settings 변경 → Model Parameters에 자동 반영.

### 입력 유형 A: Base Topology (기본 토폴로지)

현재 시스템의 물리 구성을 수집하거나, 저장된 Snapshot을 로드한다.

| 방법 | 설명 | UI 동작 |
|------|------|---------|
| **Live 수집** | 현재 호스트에서 sysfs/procfs/lspci 실행 | "시스템 수집" 버튼 → 자동 완료 |
| **Snapshot 로드** | 이전에 저장한 JSON 파일 로드 | 파일 선택 또는 drag & drop |
| **원격 수집** | 원격 호스트에서 수집 스크립트 실행 → JSON 전송 | SSH 또는 수동 복사 (향후 SSH 직접 지원 가능) |

결과: Topology 그래프 (Component + Link) 생성

### 입력 유형 B: Topology Mutation (토폴로지 변경)

기존 Topology에 가상의 변경을 적용한다. **실제 시스템을 변경하지 않고** 시뮬레이션한다.

| Mutation 종류 | 설명 | UI 동작 |
|-------------|------|---------|
| **Component 추가** | 가상 디바이스를 특정 PCIe slot에 배치 | 디바이스 카탈로그에서 선택 → 위치 지정 |
| **Component 제거** | 기존 디바이스를 Topology에서 제거 | 노드 우클릭 → "제거" |
| **Link 변경** | PCIe speed/width 변경 (업그레이드 시뮬레이션) | Link 클릭 → 속성 편집 |
| **NUMA 재배치** | 디바이스를 다른 NUMA 노드로 이동 | 노드 드래그 또는 속성 편집 |
| **IOMMU 그룹 변경** | 디바이스의 IOMMU 그룹 재배치 | 그룹 편집 UI |

Mutation은 Base Topology 위에 **diff로 관리**되어, 원본과 변경본을 항상 비교 가능.

### 입력 유형 C: VM Overlay (가상화 오버레이)

VM 구성 정보를 Topology 위에 매핑한다. 하나의 Topology에 **여러 VM Overlay**를 겹칠 수 있다.

| 입력 소스 | 파싱 방법 | 추출 정보 |
|----------|----------|----------|
| QEMU cmdline | `/proc/<pid>/cmdline` 또는 직접 입력 | vCPU pin, NUMA, VFIO devices, memory |
| libvirt XML | `virsh dumpxml` 또는 파일 업로드 | 위와 동일 + 더 구조화된 형태 |
| KubeVirt VMI | `kubectl get vmi -o yaml` 또는 파일 업로드 | spec.domain 파싱 |
| 수동 입력 | UI 폼 | vCPU 수, pinning, VFIO device BDF 지정 |

각 VM Overlay에는 **이름과 색상**을 부여하여 시각적 구분.

### 입력 유형 D: Flow 정의

Scenario를 구성하는 개별 데이터 전송 정의.

```
Flow {
  name:        "GPU0 DMA Read"
  source:      Component (GPU0)       # 클릭으로 선택
  destination: Component (Host Mem)   # 클릭으로 선택
  direction:   read | write | bidirectional
  mode:        dma | rdma | gpudirect_rdma | gpudirect_storage | p2p | nvlink_p2p
  pattern:     sustained | burst | periodic
  size:        64KB                   # transfer 단위 크기
  rate:        continuous | <value>   # 발생 빈도
  owner:       VM-A | host            # 어떤 VM(또는 호스트)의 트래픽인지
}
```

**Transfer Mode** — 같은 source-destination이라도 전송 방식에 따라 Path와 성능이 달라짐:

| Mode | Path 특성 | latency 모델 | 비고 |
|------|----------|-------------|------|
| `dma` | Device → PCIe → Host Memory | 표준 PCIe + IOMMU | 기본값 |
| `rdma` | NIC → PCIe → Host Memory (kernel bypass) | PCIe + RDMA overhead (no context switch) | RoCEv2/IB |
| `gpudirect_rdma` | NIC → PCIe P2P → GPU VRAM | PCIe P2P (host memory 경유 안 함) | GDR: NIC-GPU 직접 |
| `gpudirect_storage` | NVMe → PCIe P2P → GPU VRAM | PCIe P2P (bounce buffer 없음) | GDS: Storage-GPU 직접 |
| `p2p` | Device A → PCIe → Device B | ACS에 따라 Switch 직접 or RC 경유 | 일반 PCIe P2P |
| `nvlink_p2p` | GPU → NVLink → GPU | NVLink direct 또는 NVSwitch 경유 | GPU 간 전용, PCIe 안 거침 |

Transfer Mode 선택 시, Ariadne가 자동으로:
1. **경로 유효성 검사**: source와 destination이 해당 mode를 지원하는지 확인 (예: `gpudirect_rdma`는 NIC이 GDR 지원 + GPU가 NVIDIA)
2. **P2P 경로 계산**: 같은 Switch 하위이면 직접 라우팅, 아니면 RC 경유. ACS ON이면 RC 경유 강제
3. **latency 모델 선택**: mode별로 다른 overhead 적용 (RDMA는 kernel bypass, DMA는 kernel 경유)

**Flow 정의 방식**:

| 방식 | 설명 | 적합한 경우 |
|------|------|------------|
| **1:1** | 단일 source → 단일 destination | 특정 디바이스 간 경로 분석 |
| **1:N** | 단일 source → 여러 destination | broadcast, 1-GPU-to-N-NVMe |
| **M:1** | 여러 source → 단일 destination | N-GPU DMA → Host Memory |
| **M:N** (Device Group) | 디바이스 그룹 → 디바이스 그룹 | "모든 GPU" → "모든 NVMe" |
| **Host Memory 경유** | Device → Host Mem → Device | GPU가 읽은 데이터를 NIC로 전송 (mode=dma) |
| **P2P 직접** | Device → Device (host memory 안 거침) | GPUDirect RDMA/Storage (mode=gpudirect_*) |
| **NVLink** | GPU → GPU (NVLink 직접) | GPU 간 고속 통신 (mode=nvlink_p2p) |

**Device Group**: 여러 Component를 묶어서 Flow의 source/destination으로 사용.
예: `GPU Group = {GPU0, GPU1, GPU2, GPU3}`, `NVMe Group = {NVMe0..7}`, `HCA Group = {ConnectX-7 port0, port1}`

### 입력 유형 E: Model Parameters

시뮬레이션 보정 계수. DATA_MODEL.md에서 정의한 파라미터들.

| UI 제공 방식 | 설명 |
|-------------|------|
| **기본값 사용** | 프로젝트에 내장된 기본값 (수정 불필요) |
| **슬라이더/입력 필드** | Web UI에서 개별 파라미터 조정 |
| **프로파일 선택** | "보수적 / 표준 / 낙관적" 프리셋 |
| **Calibration 파일** | PMU/벤치마크 측정 결과 JSON 가져오기 |

### 입력 유형 F: System Settings (시스템 설정)

물리 토폴로지를 바꾸지 않고, **소프트웨어/펌웨어 설정 변경**이 데이터 흐름과 성능에 미치는 영향을 모델링한다. Topology Mutation(물리 배치)과 구분되는 **논리적 설정 변경**.

#### BIOS/펌웨어 설정

| 설정 | 영향받는 모델 속성 | 성능 영향 |
|------|-------------------|----------|
| **NUMA Interleaving** (ON/OFF) | NUMA distance matrix | ON: 모든 NUMA distance 균등화 → remote penalty 사라지지만 locality 이점도 소멸. Memory BW 분산 |
| **PCIe Speed 제한** (Gen3 forced 등) | Link speed | 이론 BW 감소 (Gen4→Gen3: 32→16 GB/s per x16) |
| **Above 4G Decoding** (ON/OFF) | BAR allocation | OFF: 4GB 이상 BAR 불가 → 대형 VRAM GPU 사용 불가, 다수 디바이스 BAR 충돌 |
| **SR-IOV** (enable/disable) | VF 존재 여부 | ON: VF 생성, 각 VF별 독립 Flow 가능. OFF: PF만 사용 |
| **ACS Override** | IOMMU 그룹 구성 | ACS OFF: 같은 switch 하위 디바이스가 하나의 IOMMU 그룹 → VFIO 개별 할당 불가 |
| **PCIe ASPM** (L0s/L1/OFF) | Link latency | L1: 복귀 latency 2~10μs 추가. OFF: latency 최소화, 전력 증가 |
| **PCIe MPS 제한** (128/256/512) | TLP 분할 overhead | MPS 128: 큰 DMA가 많은 TLP로 분할 → overhead 증가. MPS 512: 분할 감소 |
| **PCIe Relaxed Ordering** (ON/OFF) | ordering constraint | ON: 일부 TLP 순서 완화 → latency 감소 가능. 일부 디바이스 비호환 |
| **SMM** (enable/disable) | 주기적 latency spike | ON: SMI 핸들러 실행 시 수십~수백μs stall. VM passthrough 시 영향 |

#### 커널 부트 파라미터 / 런타임 설정

| 설정 | 영향받는 모델 속성 | 성능 영향 |
|------|-------------------|----------|
| `iommu=pt` vs `iommu=on` | `iommu_latency_ns` | pt: IOMMU bypass → translation overhead 0. on: 모든 DMA에 translation |
| `intel_iommu=sm_on` | IOTLB 효율 | Scalable Mode: 더 큰 IOTLB, PASID 지원 → hit rate 향상 |
| `pcie_aspm=off` | Link latency | 커널 수준 ASPM 비활성화 (BIOS 설정과 독립) |
| `pci=noacs` | IOMMU 그룹 구성 | ACS 검사 비활성화 → IOMMU 그룹 병합 (보안 약화, VFIO 유연성 증가) |
| `pcie_acs_override=downstream` | IOMMU 그룹 구성 | 모든 downstream port에 가상 ACS 추가 → 강제 그룹 분리 (VFIO 개별 할당 가능) |
| `pcie_acs_override=multifunction` | IOMMU 그룹 구성 | multifunction 디바이스 내 function 분리 (듀얼포트 NIC 개별 할당) |
| `pci=disable_acs_redir=pci:VVVV:DDDD` | P2P 경로 | 특정 벤더:디바이스의 ACS redirect OFF → P2P 직접 라우팅 (GPUDirect) |
| NUMA balancing (`numa_balancing=0/1`) | NUMA locality | 1: 커널이 자동으로 페이지를 접근 CPU 가까이 이동 → 비결정적 latency |
| Hugepages (`default_hugepagesz=1G`) | `iommu_latency_ns` | 1G hugepage: IOTLB 엔트리 하나로 1GB 커버 → miss rate 대폭 감소 |
| CPU governor (`performance`/`powersave`) | interconnect BW, latency | powersave: 클럭 다운 → UPI/IF BW 감소, C-state 진입 → 복귀 latency |
| IRQ affinity (`irqbalance`, 수동 설정) | interrupt latency | IRQ를 디바이스와 같은 NUMA에 고정 → cross-NUMA interrupt 제거 |

#### 디바이스 수준 설정

| 설정 | 영향받는 모델 속성 | 성능 영향 |
|------|-------------------|----------|
| MPS/MRRS 수동 설정 (`setpci`) | TLP 분할 overhead | 경로 상 모든 디바이스의 MPS 최솟값이 적용됨 |
| NIC ring buffer 크기 | 큐잉 latency | 크면: burst 흡수, latency 증가. 작으면: drop 가능, latency 감소 |
| NIC coalesce 설정 | interrupt latency | coalesce ON: throughput↑, latency↑. OFF: latency↓, CPU 부하↑ |
| GPU persistence mode | 초기 latency | ON: GPU 드라이버 항상 로드 → 첫 접근 latency 제거 |
| NVMe IO scheduler (`none`/`mq-deadline`) | I/O latency | none: 최소 overhead, mq-deadline: 공정성 보장 |

#### Ariadne에서의 모델링 방식

각 설정은 다음 3가지 방식 중 하나로 시뮬레이션에 반영된다:

| 모델링 방식 | 설명 | 예시 |
|------------|------|------|
| **속성 변경** | Topology의 Component/Link 속성을 직접 변경 | PCIe speed 제한 → Link speed 값 변경 |
| **파라미터 변경** | Model Parameter 값을 변경 | `iommu=pt` → `iommu_latency_ns = 0` |
| **구조 변경** | Topology 그래프 구조를 변경 | SR-IOV ON → VF Component 추가, ACS 변경 → IOMMU 그룹 재구성 |

#### UI에서의 Settings 입력

```
┌─────────────────────────────────────────────────┐
│ System Settings                                  │
│                                                 │
│ ▼ BIOS/Firmware                                 │
│   NUMA Interleaving    [ON ▾]  → [OFF ▾]        │
│   PCIe Max Speed       [Auto ▾] → [Gen3 ▾]     │
│   Above 4G Decoding    [ON ▾]                   │
│   SR-IOV               [Enabled ▾]              │
│   ASPM                 [Disabled ▾]             │
│   MPS Limit            [Auto ▾] → [256B ▾]     │
│                                                 │
│ ▼ Kernel Parameters                             │
│   IOMMU Mode           [passthrough ▾]→[on ▾]   │
│   ASPM Override        [off ▾]                  │
│   NUMA Balancing       [off ▾]                  │
│   Hugepage Size        [2MB ▾] → [1GB ▾]       │
│   CPU Governor         [performance ▾]          │
│                                                 │
│ ▼ Device: GPU 0000:41:00.0                      │
│   Persistence Mode     [on ▾]                   │
│                                                 │
│ ▼ Device: NIC 0000:81:00.0                      │
│   Ring Buffer Size     [4096 ▾]                 │
│   Coalesce             [adaptive ▾]             │
│                                                 │
│ 변경점: 3개  [시뮬레이션 실행] [초기화]            │
└─────────────────────────────────────────────────┘
```

- Live 수집 시: 현재 시스템에서 실제 설정값을 자동 감지
- 각 설정 변경 시: 영향받는 모델 속성이 무엇인지 툴팁으로 표시
- 변경 전후 diff 표시 → What-if 시뮬레이션으로 연결

#### Settings 자동 수집 방법

| 설정 범주 | 수집 방법 |
|----------|----------|
| BIOS/펌웨어 | `dmidecode`, ACPI 테이블, 일부는 sysfs (`/sys/firmware/`) |
| 커널 파라미터 | `/proc/cmdline`, sysfs (`/sys/kernel/mm/transparent_hugepage/`) |
| PCIe 설정 | `lspci -vv` (MPS, MRRS, ASPM, ACS), sysfs |
| IOMMU | `/sys/kernel/iommu_groups/`, `dmesg \| grep -i iommu` |
| CPU governor | `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor` |
| 디바이스별 | 벤더 도구 (`nvidia-smi`, `ethtool`, `nvme`) |

### 저장 및 관리

모든 입력은 하나의 **Configuration** 단위로 저장된다.

```
configuration.json
├── topology/
│   ├── base.json          ← Base Topology (수집 결과)
│   └── mutations.json     ← Topology 변경 사항 (diff)
├── settings/
│   ├── detected.json      ← 수집된 현재 시스템 설정
│   └── overrides.json     ← 사용자가 변경한 설정 (diff)
├── overlays/
│   ├── vm-a.json          ← VM-A Overlay
│   ├── vm-b.json          ← VM-B Overlay
│   └── vm-c.json          ← VM-C Overlay
├── scenario/
│   ├── flows.json         ← Flow 정의 목록
│   └── device-groups.json ← Device Group 정의
├── parameters.json        ← Model Parameters
└── metadata.json          ← 이름, 생성일, 설명
```

| 기능 | 설명 |
|------|------|
| **저장** | Configuration 전체를 JSON 파일로 내보내기 |
| **로드** | JSON 파일에서 Configuration 복원 |
| **복제** | 기존 Configuration을 복사하여 변형 (What-if 시작점) |
| **비교** | 두 Configuration의 차이점 표시 + 시뮬레이션 결과 비교 |
| **이력** | Configuration 변경 이력 추적 (undo/redo) |

## 출력 모델 (Output Model)

사용자에게 제공하는 시각화와 분석 결과의 종류:

### 뷰 계층 (View Hierarchy)

```
┌──────────────────────────────────────────────────────┐
│ System View (전체 토폴로지)                            │
│   모든 Component + Link를 보여주는 기본 뷰             │
│                                                      │
│   ┌──────────────────────────────────────────────┐   │
│   │ Flow View (흐름 시각화)                        │   │
│   │   Topology 위에 Flow Path를 오버레이           │   │
│   │                                              │   │
│   │   ┌──────────────────────────────────────┐   │   │
│   │   │ Breakdown View (구간별 상세)           │   │   │
│   │   │   선택된 Flow의 구간별 BW/latency     │   │   │
│   │   └──────────────────────────────────────┘   │   │
│   └──────────────────────────────────────────────┘   │
│                                                      │
│   ┌──────────────────────────────────────────────┐   │
│   │ Simulation View (시뮬레이션 결과)              │   │
│   │   시계열 차트, 히트맵, 병목 분석               │   │
│   └──────────────────────────────────────────────┘   │
│                                                      │
│   ┌──────────────────────────────────────────────┐   │
│   │ Compare View (비교)                           │   │
│   │   Configuration A vs B side-by-side          │   │
│   └──────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

### System View — 전체 토폴로지

| 요소 | 표현 방식 |
|------|----------|
| Component (노드) | 아이콘 + 라벨 (타입별 색상: CPU=파랑, GPU=녹색, NVMe=주황, NIC=보라) |
| Link (에지) | 선 + 굵기(BW 비례) + 라벨(speed/width) |
| NUMA 도메인 | 점선 박스로 그룹핑 |
| IOMMU 그룹 | 토글로 ON/OFF, 반투명 배경으로 그룹 표시 |
| VM Overlay | VM별 색상 테두리 + 반투명 배경 |
| 인터랙션 | 클릭(선택), 호버(상세 팝업), 줌/패닝, 필터 토글 |

### Flow View — 흐름 시각화

**단일 Flow (1:1)**:
- source와 destination 사이 Path를 굵은 색상 선으로 하이라이트
- Path 위의 각 Link에 BW/latency 라벨 표시
- 화살표 방향으로 데이터 흐름 표시

**다중 Flow (Scenario 전체)**:
- 각 Flow를 서로 다른 색상으로 표시
- 공유 Link에서는 여러 Flow의 색상이 겹침 → BW 분배 비율 표시
- 병목 Link는 빨간색/두꺼운 선으로 강조

**멀티 VM 환경**:
```
표시 전략:
1. 기본: 모든 VM의 Flow를 동시에 표시 (VM별 색상 구분)
2. 필터: 특정 VM만 선택하여 해당 VM의 Flow만 하이라이트
3. 집계: 공유 Link에서 "VM-A: 12GB/s | VM-B: 8GB/s | 합계: 20GB/s" 표시
4. 충돌: 공유 Link의 합산 BW > Link 용량이면 경고 표시
```

**Device Group (M:N) Flow**:
- Group 내 개별 디바이스 간 Flow를 개별 표시 (펼침 모드)
- 또는 Group을 하나의 노드로 집계하여 합산 BW 표시 (축소 모드)
- 토글로 펼침/축소 전환

**Host Memory 경유 Flow**:
- Device A → Host Memory → Device B 형태의 2-hop Flow
- 경유점(Host Memory)을 중간 노드로 표시
- 두 구간의 BW 중 더 낮은 쪽이 E2E bottleneck

### Breakdown View — 구간별 상세

선택된 Flow 또는 Path의 구간별 성능 분해:

```
┌─────────────────────────────────────────────────────────┐
│ Flow: GPU0 → Host Memory (DMA Read)                      │
│                                                         │
│ 구간               │ 이론 BW   │ 실효 BW  │ latency     │
│ ────────────────── │ ──────── │ ─────── │ ─────────── │
│ GPU EP → Switch    │ 32 GB/s  │ 28.8    │ 100ns       │
│ Switch → Root Port │ 32 GB/s  │ 28.8    │ 50ns        │
│ Root Port → RC     │ (내부)   │ —       │ 20ns        │
│ RC → Mem Ctrl      │ (내부)   │ —       │ 30ns        │
│ Mem Ctrl → DRAM    │ 204 GB/s │ 153     │ 80ns        │
│ ────────────────── │ ──────── │ ─────── │ ─────────── │
│ E2E               │ —        │ 28.8    │ 280ns       │
│ Bottleneck        │          │ PCIe    │             │
│                                                         │
│ [+IOMMU]  iommu_latency_ns = 200ns → E2E: 480ns        │
│ [+NUMA hop] 이 경로는 same-NUMA ✅ (cross-NUMA 아님)     │
└─────────────────────────────────────────────────────────┘
```

- 각 행을 클릭하면 해당 구간의 상세 속성 표시
- IOMMU/NUMA 영향을 토글로 ON/OFF
- 모델 파라미터 값과 그 근거 표시

### Simulation View — 시뮬레이션 결과

**시계열 차트 (Time Series)**:
- X축: 시뮬레이션 시간
- Y축: BW utilization (%) 또는 절대값 (GB/s)
- Link별 또는 Flow별로 선 표시
- 병목 구간 빨간색 영역으로 표시

**히트맵 (Heatmap)**:
- Topology 그래프 위에 Link별 utilization을 색상으로 표시
- 녹색(여유) → 노랑(높음) → 빨강(포화)
- 시뮬레이션 시간을 슬라이더로 조작하여 시점별 히트맵

**성능 지표 요약 (Metrics Summary)**:
```
┌────────────────────────────────────────────────────┐
│ Scenario: "4-GPU Training Workload"                 │
│                                                    │
│ 전체 Flow 수: 4                                    │
│ 총 요구 BW: 128 GB/s                               │
│ 총 가용 BW: 32 GB/s (PCIe Switch USP)              │
│                                                    │
│ Bottleneck:                                        │
│   1. PCIe Switch 0 USP (utilization: 100%)         │
│   2. Memory Controller 0 (utilization: 62%)        │
│                                                    │
│ Flow별 실효 BW:                                    │
│   GPU0 → Mem:  8.0 GB/s (이론의 25%)               │
│   GPU1 → Mem:  8.0 GB/s (이론의 25%)               │
│   GPU2 → Mem:  8.0 GB/s (이론의 25%)               │
│   GPU3 → Mem:  8.0 GB/s (이론의 25%)               │
│                                                    │
│ Latency 분포:                                      │
│   avg: 450ns  |  p50: 420ns  |  p99: 890ns        │
└────────────────────────────────────────────────────┘
```

### Compare View — 비교

두 Configuration의 시뮬레이션 결과를 나란히 비교:

```
┌─────────── Config A ──────────┐  ┌─────────── Config B ──────────┐
│ GPU 4개 모두 NUMA 0            │  │ GPU 2개 NUMA 0 + 2개 NUMA 1   │
│                               │  │                               │
│ [Topology 그래프]              │  │ [Topology 그래프]              │
│                               │  │                               │
│ Bottleneck: Switch USP (100%) │  │ Bottleneck: MC 0,1 (각 50%)   │
│ GPU당 BW: 8 GB/s              │  │ GPU당 BW: 16 GB/s             │
│ Avg latency: 450ns            │  │ Avg latency: 380ns            │
│                               │  │  (NUMA 1: +40ns cross-NUMA)   │
└───────────────────────────────┘  └───────────────────────────────┘

                     변경점 요약:
                     - GPU2,3을 NUMA 1로 이동
                     - GPU당 BW: 8 → 16 GB/s (+100%)
                     - Bottleneck: Switch → MC로 이동
                     - Latency: 450 → 380ns (-15.5%)
```

- Topology diff: 변경된 Component/Link 하이라이트
- 성능 diff: 수치 변화를 +/- 로 표시 (개선=녹색, 악화=빨강)

## 기술 스택

### Engine (`ariadne-core`)

| 영역 | 선택 | 근거 |
|------|------|------|
| 토폴로지 파싱 | sysfs/procfs 직접 파싱 | 외부 C 라이브러리 의존성 제거, 학습 극대화 |
| 그래프 모델 | NetworkX | 가중치 그래프, 경로 탐색 |
| PCIe 상세 정보 | sysfs 직접 읽기 + lspci 파싱 | config space, capability, AER 등 |
| DES 시뮬레이션 | SimPy 또는 자체 구현 | 이벤트 드리븐 시뮬레이션 |
| API 서버 | FastAPI | async, WebSocket 지원, JSON schema 자동 생성 |
| 데이터 직렬화 | Pydantic | Engine ↔ UI 경계의 데이터 모델 |
| CLI | Typer | FastAPI와 일관된 type hint 기반 |

### UI (`ariadne-web`)

| 영역 | 선택 | 근거 |
|------|------|------|
| 프레임워크 | React (TypeScript) | 컴포넌트 기반, 생태계 |
| 토폴로지 시각화 | D3.js 또는 Cytoscape.js | 그래프 시각화, 인터랙션 |
| 시뮬레이션 차트 | D3.js 또는 Recharts | 시계열, 히트맵 |
| 터미널 출력 | Rich (Python) | 컬러, 트리, 테이블 지원 |
| 정적 내보내기 | Graphviz (pydot) | DOT → SVG/PNG |

## 구현 전략

### 토폴로지: sysfs/procfs 기반 직접 구현

외부 C 라이브러리(hwloc) 의존 없이, Linux sysfs/procfs를 직접 파싱하여 전체 토폴로지를 수집한다.

**수집 소스 → 토폴로지 영역 매핑**:

| 수집 소스 | 토폴로지 영역 |
|----------|-------------|
| `/sys/devices/system/node/` | NUMA 노드, distance matrix |
| `/sys/devices/system/cpu/` | CPU 코어, SMT, cache 계층 |
| `/proc/cpuinfo` | CPU 모델, 클럭, 소켓 매핑 |
| `/sys/bus/pci/devices/` | PCIe 트리 (BDF, parent-child) |
| `lspci -vv` 파싱 | PCIe capability, speed/width, MPS/MRRS, ACS, AER |
| `/sys/kernel/iommu_groups/` | IOMMU 그룹 매핑 |
| `nvidia-smi topo -m`, `nvlink -s` | NVLink 토폴로지, GPU P2P |
| `rdma link`, `ibstat`, `ethtool` | RDMA/IB/RoCE capability |
| `dmidecode` | DRAM 속도/채널 수, BIOS 설정 |
| `/proc/cmdline`, sysfs | 커널 파라미터, CPU governor |
| QEMU cmdline / libvirt XML | VM overlay |

**hwloc 대비 트레이드오프**:
- ✅ 외부 C 라이브러리 의존성 제거 (순수 Python)
- ✅ 수집하는 모든 값의 출처를 코드에서 직접 추적 가능 (학습)
- ✅ PCIe/IOMMU/NVLink/RDMA 등 hwloc이 안 해주는 것까지 통합
- ⚠️ 다양한 플랫폼 edge case는 점진적으로 대응 (타겟: Linux x86_64, EPYC/Xeon)

### 시뮬레이션: DES 기반 트래픽 시뮬레이터

1. **정적 분석** (Phase 1): 토폴로지 그래프에서 경로/BW/latency 계산
2. **DES 시뮬레이션** (Phase 2): 시간축 위에서 다중 흐름 경합/큐잉 시뮬레이션
3. **What-if 엔진**: 토폴로지/설정 변경 → 재시뮬레이션 → 결과 비교

### 패키지 구조

```
ariadne-core/          ← Engine (PyPI 패키지)
  ariadne/
    collector/         ← 토폴로지 수집
    model/             ← 그래프 모델
    simulator/         ← DES 시뮬레이션
    analyzer/          ← 흐름 분석, 병목 식별
    api/               ← FastAPI REST/WebSocket 서버
    cli/               ← Typer CLI

ariadne-web/           ← Web UI (npm 패키지)
  src/
    components/        ← React 컴포넌트
    views/             ← 페이지
    api/               ← Engine API 클라이언트
```
