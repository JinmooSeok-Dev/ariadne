"""VFIO collector — vfio-pci 디바이스, IOMMU 부팅 옵션, qemu cmdline 파싱."""

from pathlib import Path

from ariadne.collector.vfio import (
  collect_vfio_devices,
  collect_vfio_inventory,
  collect_vms,
  parse_iommu_cmdline,
  parse_qemu_cmdline,
)


def test_collect_vfio_devices_handles_missing_path(tmp_path):
  result = collect_vfio_devices(vfio_path=tmp_path / "nonexistent")
  assert result == []


def test_collect_vfio_devices_reads_bdf_symlinks(tmp_path):
  vfio = tmp_path / "vfio-pci"
  vfio.mkdir()
  pci = tmp_path / "pci_devices"
  pci.mkdir()
  bdf = "0000:01:00.0"
  (pci / bdf).mkdir()
  iommu_groups = tmp_path / "iommu_groups"
  iommu_groups.mkdir()
  (iommu_groups / "42").mkdir()
  (pci / bdf / "iommu_group").symlink_to(iommu_groups / "42")
  (vfio / bdf).symlink_to(pci / bdf)
  # 함정 파일은 무시되어야 함
  (vfio / "module").write_text("vfio_pci")
  (vfio / "bind").write_text("")

  devices = collect_vfio_devices(vfio_path=vfio, pci_devices_path=pci)
  assert len(devices) == 1
  assert devices[0].bdf == bdf
  assert devices[0].iommu_group == 42


def test_parse_iommu_cmdline_intel_passthrough():
  cmdline = "BOOT_IMAGE=/vmlinuz root=UUID=x intel_iommu=on iommu=pt isolcpus=2-5,8 default_hugepagesz=1G hugepages=16"
  s = parse_iommu_cmdline(cmdline)
  assert s.intel_iommu == "on"
  assert s.amd_iommu is None
  assert s.iommu_passthrough is True
  assert s.isolcpus == [2, 3, 4, 5, 8]
  assert s.hugepages_total == 16


def test_parse_iommu_cmdline_amd():
  cmdline = "amd_iommu=on iommu=pt pcie_acs_override=downstream,multifunction"
  s = parse_iommu_cmdline(cmdline)
  assert s.amd_iommu == "on"
  assert s.intel_iommu is None
  assert s.pcie_acs_override == "downstream,multifunction"


def test_parse_qemu_cmdline_extracts_vm_info():
  argv = [
    "/usr/bin/qemu-system-x86_64",
    "-name", "guest=ml-vm,debug-threads=on",
    "-smp", "8,sockets=1,cores=8,threads=1",
    "-m", "32G",
    "-device", "vfio-pci,host=0000:81:00.0,id=hostdev0",
    "-device", "vfio-pci,host=0000:81:00.1",
    "-device", "virtio-net-pci,id=net0",
    "-numa", "node,nodeid=0,cpus=0-3,memdev=ram-node0",
    "-numa", "node,nodeid=1,cpus=4-7,memdev=ram-node1",
  ]
  vm = parse_qemu_cmdline(argv, pid=12345)
  assert vm is not None
  assert vm.name == "ml-vm"
  assert vm.vcpus == 8
  assert vm.memory_mb == 32 * 1024
  assert vm.attached_bdfs == ["0000:81:00.0", "0000:81:00.1"]
  assert vm.numa_nodes == [0, 1]
  assert vm.pid == 12345


def test_parse_qemu_cmdline_returns_none_for_non_qemu():
  argv = ["/usr/bin/python3", "-m", "http.server"]
  assert parse_qemu_cmdline(argv, pid=1) is None


def test_parse_qemu_cmdline_handles_minimal_args():
  argv = ["/usr/bin/qemu-system-aarch64", "-m", "1024"]
  vm = parse_qemu_cmdline(argv, pid=99)
  assert vm is not None
  assert vm.memory_mb == 1024
  assert vm.vcpus == 0
  assert vm.attached_bdfs == []


def test_collect_vms_handles_missing_proc(tmp_path):
  result = collect_vms(proc_path=tmp_path / "no_proc")
  assert result == []


def test_collect_vms_finds_qemu_processes(tmp_path):
  proc = tmp_path
  pid_dir = proc / "9999"
  pid_dir.mkdir()
  argv = [
    "/usr/bin/qemu-system-x86_64",
    "-name", "test-vm",
    "-smp", "4",
    "-m", "8192",
    "-device", "vfio-pci,host=0000:01:00.0",
  ]
  (pid_dir / "cmdline").write_bytes(b"\x00".join(a.encode() for a in argv) + b"\x00")
  # 다른 프로세스
  other = proc / "100"
  other.mkdir()
  (other / "cmdline").write_bytes(b"/bin/bash\x00")
  # 숫자 아닌 디렉토리
  non = proc / "self"
  non.mkdir()

  vms = collect_vms(proc_path=proc)
  assert len(vms) == 1
  assert vms[0].pid == 9999
  assert vms[0].name == "test-vm"
  assert vms[0].attached_bdfs == ["0000:01:00.0"]


def test_collect_vfio_inventory_attaches_vm_name(tmp_path):
  vfio = tmp_path / "vfio-pci"
  vfio.mkdir()
  pci = tmp_path / "pci_devices"
  pci.mkdir()
  bdf = "0000:81:00.0"
  (pci / bdf).mkdir()
  (vfio / bdf).symlink_to(pci / bdf)

  cmdline = tmp_path / "cmdline"
  cmdline.write_text("intel_iommu=on iommu=pt")

  proc = tmp_path / "proc"
  proc.mkdir()
  pid_dir = proc / "1234"
  pid_dir.mkdir()
  argv = [
    "/usr/bin/qemu-system-x86_64",
    "-name", "ml-vm",
    "-device", f"vfio-pci,host={bdf}",
  ]
  (pid_dir / "cmdline").write_bytes(b"\x00".join(a.encode() for a in argv) + b"\x00")

  inv = collect_vfio_inventory(
    vfio_path=vfio, pci_devices_path=pci, cmdline_path=cmdline, proc_path=proc,
  )
  assert len(inv.vfio_devices) == 1
  assert inv.vfio_devices[0].attached_to_vm == "ml-vm"
  assert inv.iommu_settings.intel_iommu == "on"
  assert inv.iommu_settings.iommu_passthrough is True
  assert len(inv.vms) == 1
