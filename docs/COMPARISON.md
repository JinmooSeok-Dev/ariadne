# Ariadne — 기존 오픈소스 비교 분석

## 비교 대상 도구 목록

| 도구 | 주 목적 | 언어 | 라이선스 |
|------|---------|------|----------|
| **hwloc/lstopo** | HW 토폴로지 시각화 | C | BSD |
| **pcicrawler** | PCIe 디바이스 디버깅 | Python | MIT |
| **numatop** | NUMA 런타임 모니터링 | C | GPL-2.0 |
| **gem5** | 전체 시스템 시뮬레이션 | C++/Python | BSD |
| **SimBricks** | 모듈러 full-system 시뮬레이션 | C/C++/Python | MIT |
| **cocotbext-pcie** | PCIe RTL 검증 | Python | MIT |
| **MuchiSim** | multi-chip manycore 시뮬레이션 | C++ | BSD |

## 도구별 상세 분석

### hwloc / lstopo

**개요**: Open MPI 프로젝트의 일부. CPU, 캐시, NUMA 노드, I/O 디바이스의 계층 토폴로지를 탐지하고 시각화한다.

**강점**:
- 검증된 토폴로지 탐지 엔진 (20년+ 역사)
- 다양한 출력 형식: console, ASCII, SVG, PDF, PNG, XML
- 프로세스 binding 시각화 (어떤 CPU/NUMA에 바인딩되었는지)
- C API + Python binding 제공
- 거의 모든 Linux 배포판에서 패키지 제공

**한계**:
- PCIe link speed/width의 current vs capable 구분 없음
- IOMMU 그룹 정보 미포함
- E2E 데이터 흐름 분석 기능 없음
- bandwidth/latency 예측 불가
- VM overlay (VFIO, vCPU pinning) 미지원
- 정적 토폴로지만 표시 (흐름/경로 개념 없음)

**Ariadne와의 관계**: **참고 대상**. Ariadne는 hwloc에 의존하지 않고 sysfs/procfs 기반으로 직접 구현한다. hwloc의 토폴로지 모델링 방식과 출력 형식을 참고하되, PCIe 상세/IOMMU/NVLink/RDMA 등 hwloc이 커버하지 않는 영역까지 포함한다.

### pcicrawler (Meta/OCP)

**개요**: Meta가 데이터센터 규모의 PCIe 디버깅을 위해 만든 CLI 도구. PCI/PCIe 디바이스 정보를 트리 형태로 출력한다.

**강점**:
- PCIe 상세 정보: link speed/width (current & capable), BAR, VPD
- 트리 형태 출력 + JSON 출력
- 최신 PCI spec 준수
- sysfs 기반으로 별도 드라이버 불필요
- Python 기반, pip 설치 가능

**한계**:
- PCIe 트리만 표시 — CPU/NUMA 토폴로지 미포함
- bandwidth/latency 계산 없음
- E2E 흐름 추적 없음
- IOMMU/ACS/ATS 정보 제한적
- VM/가상화 컨텍스트 미지원

**Ariadne와의 관계**: **PCIe 상세 파싱 로직 참고**. pcicrawler의 sysfs 파싱 패턴을 참고하되, Ariadne는 NUMA 토폴로지와 통합하고 흐름 분석을 추가한다.

### numatop (Intel)

**개요**: Intel 성능 카운터 기반 NUMA 메모리 접근 패턴 실시간 모니터링 도구.

**강점**:
- 런타임 RMA/LMA (Remote/Local Memory Access) 비율 추적
- 프로세스별 NUMA locality 분석
- "hot" 메모리 영역 식별
- 평균 메모리 접근 latency 리포트

**한계**:
- Intel CPU 전용 (AMD 미지원)
- 런타임 모니터링만 — 사전 예측 불가
- PCIe 토폴로지 미포함
- root 권한 필요
- 텍스트 UI만 지원

**Ariadne와의 관계**: **상호보완**. Ariadne는 사전 예측(static analysis), numatop은 런타임 검증(dynamic monitoring). numatop의 측정값으로 Ariadne 모델을 calibrate 할 수 있다.

### gem5

**개요**: 학술 연구용 full-system 시뮬레이터. CPU 마이크로아키텍처, 메모리 시스템, I/O를 cycle-level로 시뮬레이션한다.

**강점**:
- cycle-accurate CPU 시뮬레이션
- 메모리 시스템 상세 모델링 (cache hierarchy, DRAM controller)
- 실제 OS 부팅 가능 (full-system mode)
- 학술 커뮤니티에서 검증됨

**한계**:
- **PCIe 시뮬레이션이 매우 약함**: 동기식 함수 호출 기반, 비동기 PCIe 인터페이스와 비호환
- DMA, SMMU 지원 부족
- 시뮬레이션 속도 매우 느림 (실시간 대비 1000~10000배)
- 설정/사용 복잡도 높음
- 실제 하드웨어 토폴로지 수집 불가 (시뮬레이션 전용)

**Ariadne와의 관계**: **영역이 다름**. gem5는 마이크로아키텍처 연구용 시뮬레이터, Ariadne는 실제 하드웨어 위의 토폴로지 분석 도구. gem5의 latency 모델 데이터를 참고값으로 활용 가능.

### SimBricks

**개요**: MPI-SWS에서 개발한 모듈러 full-system 시뮬레이션 프레임워크. QEMU, gem5, Verilator, ns-3 등 기존 시뮬레이터를 PCIe/Ethernet 인터페이스로 연결한다.

**강점**:
- PCIe transaction layer 수준 시뮬레이션
- 다양한 시뮬레이터 조합 가능 (QEMU + Verilator + ns-3 등)
- 실제 OS/소프트웨어 스택 실행
- link bandwidth/latency 파라미터 설정 가능
- 2025년 4월 완전 재작성 버전 출시

**한계**:
- 시뮬레이션 전용 — 실제 하드웨어 토폴로지 수집 불가
- 설정/실행 복잡도 높음
- 실시간 분석 불가 (시뮬레이션 실행 필요)
- 목적이 "시스템 설계 검증"이지 "운영 최적화"가 아님

**Ariadne와의 관계**: **영역이 다름**. SimBricks는 하드웨어 설계 검증용, Ariadne는 실제 시스템 분석용. SimBricks의 PCIe latency 모델 파라미터를 참고 가능.

### cocotbext-pcie

**개요**: cocotb 기반 PCIe RTL 검증 프레임워크. PCIe Root Complex, Switch, Endpoint를 소프트웨어로 시뮬레이션하여 FPGA PCIe IP를 테스트한다.

**강점**:
- PCIe 프로토콜 상세 구현 (TLP, DLLP, configuration space, BAR allocation)
- Xilinx/Intel FPGA PCIe hard core 지원
- Python 기반 테스트 작성
- DMA, MSI/MSI-X 지원

**한계**:
- FPGA RTL 검증 전용 — 실제 시스템 토폴로지와 무관
- NUMA/CPU 토폴로지 미포함
- 실행에 HDL 시뮬레이터 필요 (Verilator, ModelSim 등)
- 시스템 수준 분석 불가

**Ariadne와의 관계**: **영역이 완전히 다름**. cocotbext-pcie는 하드웨어 설계 검증, Ariadne는 시스템 토폴로지 분석. PCIe 프로토콜 이해 참고용.

### MuchiSim

**개요**: Princeton에서 개발한 multi-chip manycore 아키텍처 시뮬레이터. 수백만 타일 규모의 시스템 설계 탐색용.

**강점**:
- 대규모 시스템 (100만+ 타일) 시뮬레이션
- 2D mesh, folded torus 토폴로지 지원
- 칩렛 간 interconnect 모델링
- 설계 공간 탐색 (DSE)

**한계**:
- 연구 목적 전용 — 실제 시스템 분석 불가
- PCIe 프로토콜 시뮬레이션 아님
- 기존 x86/ARM 시스템과 무관
- 일반 사용자가 활용하기 어려움

**Ariadne와의 관계**: **영역이 완전히 다름**. interconnect topology 모델링 개념만 참고.

## 기능 비교 매트릭스

| 기능 | hwloc | pcicrawler | numatop | gem5 | SimBricks | cocotbext | MuchiSim | **Ariadne** |
|------|:-----:|:----------:|:-------:|:----:|:---------:|:---------:|:--------:|:-----------:|
| **토폴로지 수집** | | | | | | | | |
| CPU/NUMA 토폴로지 | ✅ | ❌ | ⚠️ | ✅¹ | ✅¹ | ❌ | ❌ | ✅ |
| PCIe 트리 | ⚠️ | ✅ | ❌ | ⚠️ | ✅¹ | ✅¹ | ❌ | ✅ |
| PCIe link speed/width | ❌ | ✅ | ❌ | ❌ | ⚠️¹ | ✅¹ | ❌ | ✅ |
| IOMMU 그룹 | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| SR-IOV VF/PF | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 실제 HW에서 수집 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **분석** | | | | | | | | |
| E2E 경로 추적 | ❌ | ❌ | ❌ | ⚠️ | ⚠️ | ❌ | ❌ | ✅ |
| BW/latency 예측 | ❌ | ❌ | ⚠️² | ✅¹ | ✅¹ | ❌ | ✅¹ | ✅ |
| NUMA hop 반영 | ❌ | ❌ | ✅² | ✅¹ | ❌ | ❌ | ❌ | ✅ |
| IOMMU overhead | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 병목 식별 | ❌ | ❌ | ⚠️² | ❌ | ❌ | ❌ | ❌ | ✅ |
| What-if 비교 | ❌ | ❌ | ❌ | ✅¹ | ✅¹ | ❌ | ✅¹ | ✅ |
| **가상화** | | | | | | | | |
| QEMU cmdline 파싱 | ❌ | ❌ | ❌ | N/A | N/A | ❌ | ❌ | ✅ |
| libvirt XML 파싱 | ❌ | ❌ | ❌ | N/A | N/A | ❌ | ❌ | ✅ |
| VFIO overlay | ❌ | ❌ | ❌ | N/A | N/A | ❌ | ❌ | ✅ |
| **고급 interconnect** | | | | | | | | |
| NVLink 토폴로지 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| RDMA/RoCE/IB 모델링 | ❌ | ❌ | ❌ | ❌ | ⚠️¹ | ❌ | ❌ | ✅ |
| GPUDirect (RDMA/Storage) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **시뮬레이션** | | | | | | | | |
| 트래픽 시뮬레이션 (DES) | ❌ | ❌ | ❌ | ✅¹ | ✅¹ | ❌ | ✅¹ | ✅ |
| 다중 흐름 경합 | ❌ | ❌ | ❌ | ✅¹ | ✅¹ | ❌ | ✅¹ | ✅ |
| 큐잉 모델 (tail latency) | ❌ | ❌ | ❌ | ⚠️¹ | ❌ | ❌ | ❌ | ✅ |
| **출력/시각화** | | | | | | | | |
| 터미널 텍스트 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| JSON API | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 그래픽 (SVG/PNG) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Web UI (인터랙티브) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **아키텍처** | | | | | | | | |
| Engine/UI 분리 | ❌ | ❌ | ❌ | ⚠️ | ✅ | ❌ | ❌ | ✅ |
| REST API | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

> ✅ = 지원, ⚠️ = 부분 지원, ❌ = 미지원
>
> ¹ 시뮬레이션 환경에서만 (실제 HW 아님)

## 포지셔닝

```
                  실제 HW 기반 ◄─────────────────────► 가상 환경 전용
                       │                                    │
                       │                                    │
   정적 토폴로지  hwloc ──┐                                 │
        │        pcicrawler┤                                │
        │                  │                                │
        ▼                  ▼                                │
   흐름 분석     ┌─────────────────────┐                    │
        +        │      Ariadne        │                    │
   트래픽        │                     │                    │
   시뮬레이션    │ ┌─────┐  ┌───────┐  │                    │
        +        │ │Core │  │Web UI │  │              gem5, SimBricks
   인터랙티브    │ │Engine│◄►│React  │  │              cocotbext-pcie
   시각화        │ │      │  │D3.js  │  │              MuchiSim
                 │ └─────┘  └───────┘  │                    │
                 └──────────┬──────────┘                    │
                            │                               │
   런타임 모니터링   numatop ◄── calibration                 │
```

### Ariadne의 차별점

1. **Engine/UI 분리**: 계산 엔진은 독립 라이브러리 + REST API, UI는 교체 가능 (CLI, Web, GUI)
2. **통합 뷰**: CPU/NUMA + PCIe + IOMMU를 하나의 그래프로 통합 (기존 도구는 각각 분리)
3. **시뮬레이션**: 정적 경로 분석뿐 아니라 DES 기반 트래픽 시뮬레이션 (경합, 큐잉, 트래픽 패턴)
4. **인터랙티브 시각화**: 웹 기반 토폴로지 탐색, 시뮬레이션 파라미터 조작, 결과 비교
5. **가상화 인식**: QEMU/libvirt/KubeVirt 설정을 파싱하여 VM 관점의 토폴로지 제공
6. **What-if**: 설정 변경 전후 시뮬레이션 비교로 최적 구성 탐색

### 니치(Niche)

기존 도구들 사이의 빈 공간:
- hwloc/pcicrawler는 **"무엇이 있는지"**는 보여주지만 **"데이터가 어떻게 흐르는지"**는 안 보여줌
- numatop은 **"지금 어떤지"**는 보여주지만 **"바꾸면 어떻게 되는지"**는 안 보여줌
- gem5/SimBricks는 **"설계 검증"**은 하지만 **"운영 최적화"**는 안 함
- 어떤 도구도 **실제 HW 토폴로지 + 트래픽 시뮬레이션 + 웹 인터랙티브 시각화**를 결합하지 않음

**Ariadne = 실제 HW 토폴로지 × 트래픽 시뮬레이션 × 인터랙티브 시각화**

## 참고 링크

- [hwloc/lstopo](https://www.open-mpi.org/projects/hwloc/) — Open MPI 프로젝트
- [pcicrawler](https://github.com/opencomputeproject/ocp-diag-pcicrawler) — OCP/Meta
- [numatop](https://github.com/intel/numatop) — Intel
- [gem5](https://www.gem5.org/) — gem5 커뮤니티
- [SimBricks](https://www.simbricks.io/) — MPI-SWS
- [cocotbext-pcie](https://github.com/alexforencich/cocotbext-pcie) — Alex Forencich
- [MuchiSim](https://parallel.princeton.edu/papers/MuchiSim.pdf) — Princeton
