# Ariadne — 데이터 모델 및 측정 전략

## 목적

Ariadne가 다루는 E2E 데이터 흐름의 전체 경로를 top-down으로 정의하고,
각 레이어에서 "무엇이 존재하는지 → S/W로 무엇을 측정할 수 있는지 → Ariadne가 어떻게 다루는지"를
체계적으로 정리한다.

## E2E 데이터 흐름 전체 구조

하나의 데이터가 source에서 destination까지 이동하는 전체 경로:

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1. 시스템 토폴로지                                        │
│   Multi-Socket, NUMA Domains                                    │
│                                                                 │
│  ┌──────────────────────┐    ┌──────────────────────┐           │
│  │ Layer 2. CPU/메모리   │    │ Layer 2. CPU/메모리   │           │
│  │  Cores, Cache, MC    │    │  Cores, Cache, MC    │           │
│  │        │             │    │        │             │           │
│  │  ┌─────▼──────┐      │    │  ┌─────▼──────┐      │           │
│  │  │ Layer 3.   │      │    │  │ Layer 3.   │      │           │
│  │  │ Interconn. │◄─────┼────┼──► Interconn. │      │           │
│  │  │ UPI / IF   │      │    │  │ UPI / IF   │      │           │
│  │  └─────┬──────┘      │    │  └─────┬──────┘      │           │
│  │        │             │    │        │             │           │
│  │  ┌─────▼──────┐      │    │  ┌─────▼──────┐      │           │
│  │  │ Layer 4.   │      │    │  │ Layer 4.   │      │           │
│  │  │ PCIe       │      │    │  │ PCIe       │      │           │
│  │  │ RC→SW→EP   │      │    │  │ RC→SW→EP   │      │           │
│  │  └─────┬──────┘      │    │  └─────┬──────┘      │           │
│  └────────┼─────────────┘    └────────┼─────────────┘           │
│           │                           │                         │
│     ┌─────▼──────┐              ┌─────▼──────┐                  │
│     │ Layer 5.   │              │ Layer 5.   │                  │
│     │ IOMMU      │              │ IOMMU      │                  │
│     └─────┬──────┘              └─────┬──────┘                  │
│           │                           │                         │
│     ┌─────▼──────┐              ┌─────▼──────┐                  │
│     │ Layer 6.   │              │ Layer 6.   │                  │
│     │ Device     │              │ Device     │                  │
│     │ GPU/NIC/   │              │ GPU/NIC/   │                  │
│     │ NVMe       │              │ NVMe       │                  │
│     └────────────┘              └────────────┘                  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐       │
│  │ Layer 7. 가상화 오버레이                               │       │
│  │   VM ↔ Host 매핑 (vCPU, VFIO, virtio)                │       │
│  └──────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

## 레이어별 상세

각 레이어마다 다음 3가지를 정리한다:
- **A. 존재하는 것**: 이 레이어에 어떤 HW/SW 구성요소가 있는가
- **B. S/W 측정 가능 여부**: 무엇을 읽을 수 있고 무엇을 읽을 수 없는가
- **C. Ariadne 전략**: 입력값 / 모델 파라미터 / Out of Scope 분류

---

### Layer 1. 시스템 토폴로지 (System Topology)

**A. 존재하는 것**

- Socket 수, Socket 간 연결 (UPI/Infinity Fabric)
- NUMA domain 구성
- NUMA distance matrix (상대적 접근 비용)

**B. S/W 측정**

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| Socket 수 / 구성 | ✅ | `/sys/devices/system/node/`, `/proc/cpuinfo` |
| NUMA node 수 / CPU 매핑 | ✅ | `/sys/devices/system/node/nodeN/cpulist`, `numactl --hardware` |
| NUMA distance matrix | ✅ | `/sys/devices/system/node/nodeN/distance` |
| Socket 간 link 수/BW | ⚠️ | 벤더 종속 (Intel: `uncore_upi`, AMD: `amd_df`) |
| Socket 간 실측 latency | ⚠️ | `mlc --latency_matrix` 또는 벤치마크 |

**C. Ariadne 전략**

| 용도 | 데이터 | 분류 |
|------|--------|------|
| NUMA 도메인 구성 | socket/node 매핑 | **입력값** (sysfs 수집) |
| NUMA hop 비용 | distance matrix | **입력값** (sysfs 수집) |
| 실제 cross-socket BW/latency | UPI/IF 실측 | **검증 데이터** (mlc 벤치마크) |
| Socket 내부 mesh 구조 | — | **Out of Scope** (마이크로아키텍처) |

---

### Layer 2. CPU / 메모리 (CPU & Memory Subsystem)

**A. 존재하는 것**

- CPU 코어, 하이퍼스레딩 (SMT)
- Cache 계층 (L1/L2/L3), Cache line size
- Memory Controller → DRAM 채널
- Memory BW (채널 수 × DDR 속도)

**B. S/W 측정**

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| 코어 수, SMT 구조 | ✅ | `/proc/cpuinfo`, `/sys/devices/system/cpu/` |
| Cache 계층/크기/공유 관계 | ✅ | sysfs `/sys/devices/system/cpu/cpu*/cache/` |
| Cache line size | ✅ | sysfs `coherency_line_size` |
| Memory 총량 / NUMA별 용량 | ✅ | `/proc/meminfo`, sysfs `meminfo` |
| DRAM 속도/채널 수 | ✅ | `dmidecode`, `lshw` |
| 이론 Memory BW | ✅ | 채널 수 × DDR 속도 × 8B (계산) |
| 실측 Memory BW | ⚠️ | `mlc --bandwidth_matrix`, `stream` |
| LLC miss rate | ✅ | `perf stat` (cache-misses) |
| Memory controller 큐 깊이 | ❌ | HW 내부 |

**C. Ariadne 전략**

| 용도 | 데이터 | 분류 |
|------|--------|------|
| CPU 토폴로지 (core/thread/cache) | sysfs, procfs | **입력값** |
| Memory BW 상한 | DDR spec에서 계산 | **입력값** |
| Memory BW 효율 | 실측/이론 비율 | **모델 파라미터** (`mem_efficiency`, 기본 0.7~0.85) |
| LLC miss에 의한 메모리 압력 | perf counter | **검증 데이터** (향후) |
| DRAM 내부 bank conflict | — | **Out of Scope** |

---

### Layer 3. 프로세서 간 Interconnect (UPI / Infinity Fabric)

**A. 존재하는 것**

- **Intel**: UPI (Ultra Path Interconnect), 이전 QPI
- **AMD**: Infinity Fabric (IF, xGMI)
- Socket 간 데이터 이동의 물리적 경로
- cross-NUMA 메모리 접근, PCIe peer-to-peer의 경유 경로

**B. S/W 측정**

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| UPI link 수 | ⚠️ | Intel uncore PMU (`uncore_upi`), `lscpu` 간접 |
| UPI link BW (이론) | ⚠️ | CPU spec sheet에서 유추 (10.4 GT/s × 2B 등) |
| UPI 실측 BW | ✅ | `perf stat -e uncore_upi/event=.../` (Intel) |
| IF link BW (이론) | ⚠️ | AMD spec, `amd_df` PMU |
| IF 실측 BW | ✅ | `perf stat -e amd_df/event=.../` (AMD EPYC) |
| Cross-socket latency | ⚠️ | `mlc`, `numactl` 벤치마크 |
| Link 토폴로지 (mesh/ring) | ❌ | die 내부 구조, S/W 미노출 |

**C. Ariadne 전략**

| 용도 | 데이터 | 분류 |
|------|--------|------|
| Cross-NUMA hop BW 상한 | UPI/IF 이론 BW | **모델 파라미터** (CPU SKU별 테이블) |
| Cross-NUMA latency 추가분 | NUMA distance + 벤치마크 | **모델 파라미터** (`numa_remote_latency_ns`) |
| Interconnect 경합 | UPI/IF PMU 실측 | **검증 데이터** |
| Die 내부 mesh/ring 구조 | — | **Out of Scope** |

---

### Layer 4. PCIe 서브시스템

**A. 존재하는 것**

```
Root Complex ─┬─ Root Port ─── Endpoint (직결)
              ├─ Root Port ─── Switch ─┬─ Downstream Port ─── EP
              │                        └─ Downstream Port ─── EP
              └─ Root Port ─── Bridge ─── Legacy Device
```

- PCIe 트리 (RC → Switch → Endpoint)
- 각 link: speed (Gen1~5), width (x1~x16)
- 각 device: BAR, capability, MPS/MRRS
- 프로토콜 3계층: Physical → Data Link → Transaction

**B. S/W 측정**

#### PCIe 토폴로지 & 설정

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| 트리 구조 (BDF, parent-child) | ✅ | sysfs `/sys/bus/pci/devices/`, lspci -t |
| Device vendor/device ID | ✅ | sysfs, lspci |
| Link Speed (current/capable) | ✅ | sysfs `current_link_speed`, lspci -vv |
| Link Width (current/capable) | ✅ | sysfs `current_link_width`, lspci -vv |
| BAR 주소/크기 | ✅ | sysfs `resource`, lspci -vv |
| MPS / MRRS | ✅ | config space `DevCtl`, lspci -vv |
| SR-IOV VF/PF 관계 | ✅ | sysfs `physfn`, `virtfn*` |

#### PCIe Capability (경로/성능 결정)

| 항목 | 측정? | 접근 방법 | 비고 |
|------|:-----:|-----------|------|
| ACS 지원/활성, 개별 비트 | ✅ | lspci -vv (Extended Cap) | P2P Redirect, Source Validation 등 |
| ACS override 적용 여부 | ✅ | 커널 cmdline (`pcie_acs_override`), IOMMU 그룹 결과 | 가상 ACS → 그룹 분리 |
| ACS redirect 비활성화 대상 | ✅ | 커널 cmdline (`pci=disable_acs_redir=`) | 특정 디바이스 P2P 허용 |
| ARI 지원/활성 | ✅ | lspci -vv (ARI Cap) | SR-IOV VF 8+ 전제 |
| ATS 지원/활성 | ✅ | lspci -vv (ATS Cap) | 디바이스 측 IOTLB |
| PASID 지원 | ✅ | lspci -vv (PASID Cap) | SVM/SVA 전제 |
| PRI 지원 | ✅ | lspci -vv (PRI Cap) | demand paging |
| FLR 지원 | ✅ | lspci -vv (Device Cap) | VFIO reset |
| Resizable BAR 지원/활성 | ✅ | lspci -vv (Resizable BAR Cap) | GPU VRAM 전체 매핑 |
| LTR 지원 | ✅ | lspci -vv (LTR Cap) | ASPM 정책 영향 |

#### PCIe 프로토콜 계층 (Physical → Data Link → Transaction)

| 항목 | 측정? | 접근 방법 | 비고 |
|------|:-----:|-----------|------|
| 인코딩 overhead | — | speed에서 결정론적 유추 | Gen1/2: 20%, Gen3+: ~1.5% |
| LTSSM 상태 | ⚠️ | 벤더 종속 | 표준화 안 됨 |
| Lane Margining | ⚠️ | Gen4+, 커널 5.18+ | 일부 지원 |
| 시그널 품질 | ❌ | — | 장비 필요 |
| AER 에러 카운터 (replay, bad TLP/DLLP) | ✅ | AER Extended Capability | 링크 건강 지표 |
| Flow Control Credit 현재값 | ❌ | — | HW 내부 상태 |
| Credit stall | ⚠️ | 벤더 PMU (Intel, NVIDIA) | 표준화 안 됨 |
| ACK/NAK latency | ❌ | — | HW 내부 타이밍 |
| TLP throughput (bytes/sec) | ✅ | PCIe PMU | 커널 6.0+ |
| TLP count (Posted/Non-Posted/Cpl) | ✅ | PCIe PMU | 커널 6.0+ |
| Completion latency | ⚠️ | 벤더 PMU, eBPF | 간접 측정 |
| Ordering rule 내부 | ❌ | — | HW 강제 |

#### PCIe PMU 소스

| PMU | 측정 가능 항목 | 플랫폼 |
|-----|---------------|--------|
| Intel Uncore IIO PMU | BW (read/write), TLP count | Xeon Skylake+ |
| AMD DF PMU | Data Fabric BW (NUMA hop 포함) | EPYC Rome+ |
| NVIDIA GPU PMU | PCIe TX/RX bytes | `nvidia-smi dmon` |
| 커널 PCIe PMU (`pcieport`) | BW, TLP count | 커널 6.0+ (제한적) |

**C. Ariadne 전략**

| 용도 | 데이터 | 분류 |
|------|--------|------|
| 이론 BW 계산 | speed × width - 인코딩 overhead | **입력값** |
| PCIe 트리 모델링 | BDF, parent-child 관계 | **입력값** (sysfs) |
| TLP 분할 overhead | MPS, MRRS | **입력값** (config space) |
| 링크 건강 상태 | AER replay/error count | **입력값** (AER) |
| ACS 상태/P2P 경로 결정 | ACS capability + override/redirect 설정 | **입력값** → **경로 계산** (핵심 분석 대상) |
| ARI/SR-IOV VF 수 | ARI capability → VF 최대 수 결정 | **입력값** |
| ATS 활성 여부 | ATS capability | **입력값** → `iommu_latency_ns` 보정에 반영 |
| FLR/Resizable BAR | capability 유무 | **입력값** (표시용) |
| 프로토콜 효율 (credit stall 등) | — | **모델 파라미터** (`pcie_efficiency`, Gen3: 0.85, Gen4: 0.90) |
| 실측 BW 비교 | PCIe PMU | **검증 데이터** (calibration) |
| Credit flow, TLP ordering | — | **Out of Scope** (Level 3 시뮬레이션) |
| 시그널 품질, LTSSM 상세 | — | **Out of Scope** (물리 계층) |

---

### Layer 5. IOMMU / DMA Remapping

**A. 존재하는 것**

- **Intel**: VT-d (Virtualization Technology for Directed I/O)
- **AMD**: AMD-Vi
- IOMMU 그룹: 격리 단위
- IOTLB: IOMMU Translation Lookaside Buffer
- ACS (Access Control Services): peer-to-peer 격리
- ATS (Address Translation Services): device-side translation cache

**B. S/W 측정**

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| IOMMU 그룹 구성 | ✅ | `/sys/kernel/iommu_groups/*/devices/` |
| IOMMU 활성 여부 | ✅ | `dmesg \| grep -i iommu`, sysfs |
| IOMMU 모드 (passthrough/translate) | ✅ | 커널 cmdline `iommu=pt`, dmesg |
| ACS 지원/활성 | ✅ | lspci -vv (PCIe Extended Capability) |
| ATS 지원/활성 | ✅ | lspci -vv (PCIe Extended Capability) |
| IOTLB hit/miss rate | ⚠️ | Intel VT-d PMU, 커널 5.15+ | AMD 미지원 |
| IOMMU translation latency | ⚠️ | 간접 벤치마크만 가능 | 직접 카운터 없음 |
| IOMMU page table 깊이 | ⚠️ | 커널 소스/dmesg에서 유추 | 보통 4-level |
| DMA remapping 에러 | ✅ | dmesg, DMAR 에러 로그 |

**C. Ariadne 전략**

| 용도 | 데이터 | 분류 |
|------|--------|------|
| IOMMU 그룹 시각화 | 그룹-디바이스 매핑 | **입력값** (sysfs) |
| ACS/ATS 상태 표시 | capability 읽기 | **입력값** (lspci) |
| IOMMU translation latency | — | **모델 파라미터** (`iommu_latency_ns`, 기본 100~500ns) |
| IOTLB miss penalty | hit/miss rate | **모델 파라미터** (Intel은 PMU로 calibrate 가능) |
| `iommu=pt` 모드의 overhead 차이 | — | **모델 파라미터** (pt 모드: ~0ns, translate 모드: 100~500ns) |
| Page table walk 내부 | — | **Out of Scope** |

---

### Layer 6. 디바이스 (Endpoint Devices)

**A. 존재하는 것**

- **GPU**: NVIDIA (A100, H100, B200) — VRAM, DMA engine, P2P, GPUDirect RDMA/Storage, NVLink/NVSwitch
- **NIC/HCA**: Mellanox ConnectX-6/7, Broadcom BCM57508 — RDMA (RoCEv2/IB), SR-IOV, GPUDirect
- **DPU**: NVIDIA BlueField-3 — DPU + NIC + ARM cores, SR-IOV, RDMA offload
- **NVMe**: Samsung PM9A3, Micron 9400 — GPUDirect Storage 지원 여부, NVMe-oF
- **기타**: FPGA, 캡처 카드 등

**B. S/W 측정**

공통:

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| Device identity (vendor, class, subsystem) | ✅ | lspci, sysfs |
| PCIe capability (speed/width/MPS/MRRS) | ✅ | lspci -vv |
| BAR 크기/매핑 | ✅ | sysfs `resource` |
| SR-IOV VF 수 | ✅ | sysfs `sriov_numvfs`, `sriov_totalvfs` |

GPU:

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| PCIe BW 실측 | ✅ | `nvidia-smi dmon -s t` |
| VRAM 용량/사용량 | ✅ | `nvidia-smi` |
| GPUDirect RDMA 지원 여부 | ✅ | `nvidia-smi topo -m` (Legend: GDR 표시) |
| GPUDirect Storage 지원 | ✅ | `gdscheck` (NVIDIA GDS utils) |
| P2P 가능 여부 (GPU 간) | ✅ | `nvidia-smi topo -p2p` |

NVLink/NVSwitch:

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| GPU 간 NVLink 연결 토폴로지 | ✅ | `nvidia-smi topo -m` (NV# = NVLink 수) |
| NVLink 버전/link 수 | ✅ | `nvidia-smi nvlink -s` |
| NVLink 이론 BW | ✅ | 버전별 spec (NVL3: 25GB/s/link, NVL4: 25GB/s/link, NVL5: 50GB/s/link) |
| NVLink 실측 throughput | ✅ | `nvidia-smi nvlink -gt d` (TX/RX counters) |
| NVLink 에러 카운터 | ✅ | `nvidia-smi nvlink -e` |
| NVSwitch 유무/토폴로지 | ✅ | `nvidia-smi topo -m` (Legend에 NVS 표시) |
| NVLink 경유 P2P BW/latency 실측 | ⚠️ | `p2pBandwidthLatencyTest` (CUDA samples) |
| NVLink 내부 프로토콜 상태 | ❌ | HW 내부 |
| NVSwitch 내부 라우팅 | ❌ | HW 내부 |

NIC/HCA (Mellanox/Broadcom):

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| Link speed/type (Ethernet/IB) | ✅ | `ethtool`, `ibstat` |
| RDMA capability (RoCEv2/IB) | ✅ | `rdma link`, `ibstat` |
| GID table (RoCE) | ✅ | `rdma resource show` |
| Port state (Active/Down) | ✅ | `ibstat`, `ethtool` |
| 링 버퍼 크기 | ✅ | `ethtool -g` |
| Coalesce 설정 | ✅ | `ethtool -c` |
| SR-IOV VF 구성 | ✅ | sysfs, `mlxconfig` (Mellanox) |
| GPUDirect RDMA 지원 | ✅ | `mlxconfig q` (`PROG_PARSE_GRAPH` 등), `ibdev2netdev` |
| PFC/ECN 설정 (RoCE) | ✅ | `mlnx_qos`, `ethtool --show-pause` |
| HW offload 상태 | ✅ | `ethtool -k` |
| RDMA 실측 BW/latency | ⚠️ | `ib_read_bw`, `ib_write_lat` (perftest 벤치마크) |

NVMe:

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| 큐 깊이/크기 | ✅ | `nvme list`, sysfs |
| Namespace 구성 | ✅ | `nvme id-ns` |
| GPUDirect Storage 지원 | ✅ | `gdscheck`, 커널 모듈 `nvfs` 확인 |
| IO scheduler | ✅ | sysfs `queue/scheduler` |
| 실측 IOPS/BW | ⚠️ | `fio` 벤치마크 |

**C. Ariadne 전략**

| 용도 | 데이터 | 분류 |
|------|--------|------|
| 디바이스 식별 및 분류 | vendor/device/class | **입력값** |
| PCIe 연결 속성 | speed, width, BAR | **입력값** |
| SR-IOV 구성 | VF 수, PF 관계 | **입력값** |
| RDMA 능력 (RoCEv2/IB, GDR 지원) | rdma link, ibstat, mlxconfig | **입력값** |
| GPUDirect 지원 여부 | nvidia-smi topo, gdscheck | **입력값** |
| NIC link speed/type | ethtool, ibstat | **입력값** |
| P2P 경로 유효성 (ACS, Switch 공유 여부) | 토폴로지 분석 | **분석 대상** (핵심 기능) |
| NVLink 토폴로지 (GPU 간 연결 관계) | nvidia-smi topo -m | **입력값** |
| NVLink BW (link 수 × link 속도) | nvidia-smi nvlink -s | **입력값** |
| NVSwitch 토폴로지 | nvidia-smi topo -m | **입력값** |
| GPU-to-GPU 경로 자동 선택 (NVLink vs PCIe) | 토폴로지 분석 | **분석 대상** (핵심 기능) |
| RDMA latency overhead | — | **모델 파라미터** (`rdma_overhead_ns`, kernel bypass 시 ~1~2μs) |
| GPUDirect P2P 효율 | — | **모델 파라미터** (`p2p_efficiency`, 기본 0.90~0.95) |
| NVLink 효율 | — | **모델 파라미터** (`nvlink_efficiency`, 기본 0.92~0.97) |
| Device 내부 BW (VRAM 등) | — | **Out of Scope** (디바이스 내부) |
| NVLink 내부 프로토콜 / NVSwitch 내부 라우팅 | — | **Out of Scope** (HW 내부) |
| RDMA/NVMe/NVLink 실측 throughput | perftest, fio, p2pBandwidthLatencyTest | **검증 데이터** |

---

### Layer 7. 가상화 오버레이 (Virtualization Overlay)

**A. 존재하는 것**

- **QEMU/KVM**: vCPU ↔ pCPU 매핑, 메모리 매핑, virtio/VFIO 디바이스
- **libvirt**: XML 기반 VM 정의 (NUMA topology, CPU pinning, device assignment)
- **KubeVirt**: Kubernetes CRD 기반 VMI spec
- **VFIO**: host device → VM passthrough (IOMMU 그룹 기반)

**B. S/W 측정**

| 항목 | 측정? | 접근 방법 |
|------|:-----:|-----------|
| QEMU process cmdline | ✅ | `/proc/<pid>/cmdline` |
| vCPU ↔ pCPU pinning | ✅ | QEMU cmdline, `virsh vcpuinfo` |
| vCPU NUMA topology (guest) | ✅ | QEMU cmdline `-numa`, libvirt XML |
| VFIO assigned devices | ✅ | QEMU cmdline `-device vfio-pci`, libvirt XML |
| Memory backing (hugepages) | ✅ | QEMU cmdline, libvirt XML |
| virtio device 구성 | ✅ | QEMU cmdline |
| VM의 guest-side 토폴로지 | ⚠️ | guest 내부에서 hwloc/lspci (접근 필요) |
| libvirt XML | ✅ | `virsh dumpxml <domain>` |
| KubeVirt VMI spec | ✅ | `kubectl get vmi -o yaml` |
| VM live migration 상태 | ✅ | `virsh domjobinfo` |
| Emulated vs passthrough 구분 | ✅ | QEMU cmdline 파싱 |

**C. Ariadne 전략**

| 용도 | 데이터 | 분류 |
|------|--------|------|
| vCPU → pCPU 매핑 오버레이 | QEMU cmdline / libvirt XML | **입력값** |
| VFIO device → host PCI device 매핑 | QEMU cmdline / libvirt XML | **입력값** |
| VM NUMA 토폴로지 | guest NUMA config | **입력값** |
| Host-Guest NUMA 정합성 분석 | vCPU pin + VFIO device NUMA 비교 | **분석 대상** (핵심 기능) |
| virtio 경로 모델링 | — | **모델 파라미터** (virtio overhead 추정) |
| Guest 내부 토폴로지 | — | **Out of Scope** (guest 접근 필요) |
| Live migration 분석 | — | **Out of Scope** |

---

## 전체 구현 범위 요약

### 분류 체계

모든 데이터를 4가지로 분류한다:

| 분류 | 의미 | 처리 방식 |
|------|------|-----------|
| **입력값** | S/W에서 직접 수집 가능, 시뮬레이션의 기본 입력 | Collector가 자동 수집 |
| **모델 파라미터** | 직접 측정 불가, 추상화된 보정 계수 | 기본값 제공 + calibration 가능 |
| **검증 데이터** | 실측 가능, 시뮬레이션 결과와 비교용 | PMU/벤치마크로 수집 |
| **Out of Scope** | Ariadne가 다루지 않는 영역 | 문서에 명시적으로 제외 |

### 레이어별 요약

| Layer | 입력값 (✅) | 모델 파라미터 (⚙️) | 검증 데이터 (📊) | Out of Scope (❌) |
|-------|-----------|-------------------|-----------------|------------------|
| 1. 시스템 | Socket/NUMA 구성, distance matrix | — | cross-socket BW (mlc) | die 내부 mesh |
| 2. CPU/메모리 | core/cache/SMT, DDR spec | `mem_efficiency` | Memory BW (stream) | DRAM bank conflict |
| 3. Interconnect | NUMA distance | `numa_remote_latency_ns`, cross-socket BW | UPI/IF PMU | die 내부 ring/mesh |
| 4. PCIe | 트리, speed/width, MPS/MRRS, AER | `pcie_efficiency` | PCIe PMU BW | credit flow, ordering, 시그널 |
| 5. IOMMU | 그룹, ACS/ATS | `iommu_latency_ns` | IOTLB PMU (Intel) | page table walk |
| 6. 디바이스 | identity, PCIe link, SR-IOV, RDMA cap, GDR/GDS, NVLink topo | `rdma_overhead_ns`, `p2p_efficiency`, `nvlink_efficiency` | RDMA/GPU/NVMe/NVLink throughput | 내부 BW, NVLink/NVSwitch 내부 |
| 7. 가상화 | vCPU pin, VFIO, NUMA config | `virtio_overhead` | — | guest 내부, migration |

### 모델 파라미터 일람

S/W에서 직접 측정할 수 없어 추상화하는 항목들:

| 파라미터 | Layer | 의미 | 기본값 | calibration 방법 |
|----------|-------|------|--------|------------------|
| `mem_efficiency` | 2 | DRAM 이론 BW 대비 실효 비율 | 0.70~0.85 | `stream` / `mlc` 벤치마크 |
| `numa_remote_latency_ns` | 3 | cross-NUMA 추가 latency | distance 기반 | `mlc --latency_matrix` |
| `numa_remote_bw_factor` | 3 | remote NUMA BW 감소 비율 | 0.5~0.7 | `mlc --bandwidth_matrix` |
| `pcie_efficiency` | 4 | PCIe 프로토콜 overhead (credit, encoding 등) | Gen3: 0.85, Gen4: 0.90 | 실측 BW / 이론 BW |
| `replay_penalty` | 4 | AER replay에 의한 BW 손실 | AER count 기반 | AER 카운터 |
| `iommu_latency_ns` | 5 | IOMMU translation latency | 100~500ns | IOTLB PMU 또는 벤치마크 |
| `rdma_overhead_ns` | 6 | RDMA 전송 overhead (kernel bypass) | 1~2μs | `ib_write_lat` / `ib_read_lat` |
| `p2p_efficiency` | 6 | PCIe P2P (GPUDirect) 전송 효율 | 0.90~0.95 | `p2pBandwidthLatencyTest` (CUDA samples) |
| `nvlink_efficiency` | 6 | NVLink 전송 효율 | 0.92~0.97 | `p2pBandwidthLatencyTest` (NVLink 경로) |
| `virtio_overhead_ns` | 7 | virtio emulation 추가 latency | 5~20μs | 벤치마크 |

### 시뮬레이션 레벨 결정 근거

```
Level 1 — 정적 경로 분석
  입력: 입력값만 사용 (speed/width, NUMA distance, MPS/MRRS)
  출력: 이론 BW, 최소 latency, 경로 시각화
  → S/W 측정 데이터만으로 100% 구현 가능 ✅

Level 2 — 트래픽 시뮬레이션 (Ariadne 목표)
  입력: Level 1 + 트래픽 패턴 + 모델 파라미터
  출력: 경합 시 BW, latency 분포, 병목 식별, what-if 비교
  → S/W 측정 + 모델 파라미터로 실용적 정확도 달성 가능 ✅
  → PMU/벤치마크 실측으로 calibration 가능 ✅

Level 3 — 프로토콜 수준 시뮬레이션 (Out of Scope)
  입력: TLP 시퀀스, credit 초기값, ordering rule
  출력: cycle-accurate latency, credit utilization
  → S/W에서 credit/ordering 내부가 안 보이므로 입력이 불완전 ❌
  → SimBricks, cocotbext-pcie의 영역
```

**결론**: S/W에서 측정 가능한 데이터의 경계가 곧 Ariadne 시뮬레이션의 자연스러운 경계다.
측정할 수 없는 것은 모델 파라미터로 추상화하고, 측정할 수 있는 것으로 calibrate하여
실용적 정확도를 달성한다.
