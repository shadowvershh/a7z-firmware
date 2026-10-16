from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE_LIST = ROOT / "packages-noble-arm64.txt"
BUILDER = ROOT / "build_ubuntu24_rootfs.sh"
VERIFIER = ROOT / "verify_rootfs.sh"
VENDOR_MANIFEST = ROOT / "vendor-runtime-manifest.txt"


class RootfsBuilderTests(unittest.TestCase):
    def require_file(self, path: Path) -> None:
        self.assertTrue(path.is_file(), f"required rootfs build file is missing: {path}")

    def make_legacy_valid_rootfs(self, root: Path) -> None:
        (root / "etc").mkdir(parents=True)
        (root / "etc/os-release").write_text(
            'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n',
            encoding="utf-8",
        )
        (root / "var/lib/dpkg").mkdir(parents=True)
        required = ["systemd", "systemd-sysv", "systemd-resolved", "udev", "adduser", "passwd", "sudo", "openssh-server", "kmod", "iproute2", "glmark2-es2-wayland", "weston"]
        status = "\n\n".join(f"Package: {name}\nStatus: install ok installed\nArchitecture: {'all' if name == 'adduser' else 'arm64'}" for name in required)
        (root / "var/lib/dpkg/status").write_text(status + "\n", encoding="utf-8")
        (root / "etc/systemd/system").mkdir(parents=True)
        (root / "etc/systemd/system/default.target").symlink_to("/lib/systemd/system/multi-user.target")
        wants = root / "etc/systemd/system/multi-user.target.wants"
        wants.mkdir(parents=True)
        for name in ("systemd-networkd.service", "ssh.service"):
            (wants / name).symlink_to(f"/lib/systemd/system/{name}")
        getty_wants = root / "etc/systemd/system/getty.target.wants"
        getty_wants.mkdir()
        (getty_wants / "serial-getty@ttyAS0.service").symlink_to("/lib/systemd/system/serial-getty@.service")
        sysinit_wants = root / "etc/systemd/system/sysinit.target.wants"
        sysinit_wants.mkdir()
        (sysinit_wants / "systemd-resolved.service").symlink_to("/usr/lib/systemd/system/systemd-resolved.service")
        serial_dropin = root / "etc/systemd/system/serial-getty@ttyAS0.service.d"
        serial_dropin.mkdir(parents=True)
        (serial_dropin / "10-autologin.conf").write_text(
            "[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin radxa --keep-baud 115200,38400,9600 %I $TERM\n", encoding="utf-8"
        )
        (root / "etc/systemd/system/ssh.service.d").mkdir(parents=True)
        (root / "etc/systemd/system/ssh.service.d/10-generate-hostkeys.conf").write_text(
            "[Service]\nExecStartPre=/usr/bin/ssh-keygen -A\n", encoding="utf-8"
        )
        (root / "etc/systemd/network").mkdir(parents=True)
        (root / "etc/systemd/network/20-ethernet.network").write_text("[Match]\nName=en* eth* end*\n[Network]\nDHCP=yes\n", encoding="utf-8")
        (root / "etc/ssh/sshd_config.d").mkdir(parents=True)
        (root / "etc/ssh/sshd_config.d/10-a7z-hardening.conf").write_text(
            "PermitRootLogin no\nPasswordAuthentication yes\nKbdInteractiveAuthentication no\nPubkeyAuthentication yes\nAllowUsers radxa\n", encoding="utf-8"
        )
        (root / "etc/fstab").write_text(
            "PARTUUID=1a2b3c4d-0000-4000-8000-000000000003 / ext4 defaults,noatime 0 1\n", encoding="utf-8"
        )
        (root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/bash\nradxa:x:1000:1000:Radxa:/home/radxa:/bin/bash\n", encoding="utf-8")
        (root / "etc/group").write_text("root:x:0:\nsudo:x:27:radxa\nvideo:x:44:radxa\nrender:x:994:radxa\n", encoding="utf-8")
        (root / "etc/shadow").write_text("root:!:1:0:99999:7:::\nradxa:$6$rounds=5000$salt$hash:1:0:99999:7:::\n", encoding="utf-8")
        (root / "etc/sudoers").write_text("%sudo ALL=(ALL:ALL) ALL\n", encoding="utf-8")
        (root / "home/radxa").mkdir(parents=True)
        (root / "lib/modules/6.6.98").mkdir(parents=True)
        (root / "lib/modules/6.6.98/pvrsrvkm.ko").write_bytes(b"ELF-MODULE")
        (root / "lib/modules/6.6.98/modules.builtin").write_text("kernel/bsp/drivers/npu/aw_nna_vip/vip2/vipcore.ko\n", encoding="utf-8")
        (root / "lib/firmware").mkdir(parents=True)
        (root / "lib/firmware/rgx.fw.36.56.104.183").write_bytes(b"firmware")
        (root / "lib/firmware/rgx.sh.36.56.104.183").write_bytes(b"shader")
        (root / "etc/npu/vpm_run").mkdir(parents=True)
        (root / "etc/npu/vpm_run/vpm_run").write_bytes(b"npu-vpm")
        (root / "etc/npu/vpm_run/network_binary.nb").write_bytes(b"nb")
        (root / "etc/npu/yolov5/model").mkdir(parents=True)
        (root / "etc/npu/yolov5/yolov5").write_bytes(b"npu-yolo")
        (root / "etc/npu/yolov5/model/yolov5.nb").write_bytes(b"model")
        (root / "opt/a7z-npu/lib").mkdir(parents=True)
        (root / "opt/a7z-npu/lib/libNBGlinker.so").write_bytes(b"linker")
        (root / "opt/a7z-npu/lib/libVIPhal.so").write_bytes(b"hal")
        for stem in ("libopencv_core", "libopencv_imgcodecs", "libopencv_imgproc"):
            target = root / "opt/a7z-npu/lib" / f"{stem}.so.4.7.0"
            target.write_bytes(stem.encode())
            (root / "opt/a7z-npu/lib" / f"{stem}.so.407").symlink_to(f"{stem}.so.4.7.0")
        (root / "usr/lib").mkdir(parents=True)
        for stem in ("libGLESv2_PVR_MESA", "libpvr_dri_support", "libsrv_um", "libglslcompiler", "libusc"):
            target_name = f"{stem}.so.24.2.6603887"
            (root / "usr/lib" / target_name).write_bytes(target_name.encode())
            (root / "usr/lib" / f"{stem}.so").symlink_to(target_name)
        (root / "usr/local/lib/dri").mkdir(parents=True)
        (root / "usr/local/lib/dri/pvr_dri.so").write_bytes(b"pvr-dri")
        for stem, soname, versioned in (("libEGL", "1", "1.0.0"), ("libGLESv1_CM", "1", "1.1.0"), ("libGLESv2", "2", "2.0.0"), ("libgbm", "1", "1.0.0"), ("libglapi", "0", "0.0.0")):
            target_name = f"{stem}.so.{versioned}"
            (root / "usr/local/lib" / target_name).write_bytes(target_name.encode())
            (root / "usr/local/lib" / f"{stem}.so.{soname}").symlink_to(target_name)
            (root / "usr/local/lib" / f"{stem}.so").symlink_to(f"{stem}.so.{soname}")
        (root / "boot").mkdir()
        (root / "boot/bImage").write_bytes(b"kernel")
        (root / "boot/sunxi.dtb").write_bytes(b"dtb")
        (root / "boot/extlinux").mkdir()
        (root / "boot/extlinux/extlinux.conf").write_text("root=PARTUUID=1a2b3c4d-0000-4000-8000-000000000003\n", encoding="utf-8")
        (root / "etc/ld.so.conf.d").mkdir(parents=True)
        (root / "etc/ld.so.conf.d/50-a7z-npu.conf").write_text("/opt/a7z-npu/lib\n", encoding="utf-8")
        (root / "etc/ld.so.conf.d/00-a7z-pvr.conf").write_text("/usr/local/lib\n", encoding="utf-8")


    def make_valid_networkmanager_rootfs(self, root: Path) -> None:
        self.make_legacy_valid_rootfs(root)
        status = root / "var/lib/dpkg/status"
        status.write_text(
            status.read_text(encoding="utf-8").rstrip()
            + "\n\nPackage: network-manager\nStatus: install ok installed\nArchitecture: arm64"
            + "\n\nPackage: wpasupplicant\nStatus: install ok installed\nArchitecture: arm64\n",
            encoding="utf-8",
        )
        wants = root / "etc/systemd/system/multi-user.target.wants"
        (wants / "systemd-networkd.service").unlink()
        (wants / "NetworkManager.service").symlink_to("/lib/systemd/system/NetworkManager.service")
        (root / "etc/systemd/network/20-ethernet.network").unlink()
        apt_sources = root / "etc/apt/sources.list.d"
        apt_sources.mkdir(parents=True)
        (apt_sources / "ubuntu.sources").write_text(
            "Types: deb\nURIs: https://mirrors.ustc.edu.cn/ubuntu-ports/\nSuites: noble noble-updates noble-security\nComponents: main universe\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\nArchitectures: arm64\n",
            encoding="utf-8",
        )
        (root / "etc/NetworkManager").mkdir(parents=True)
        (root / "etc/NetworkManager/NetworkManager.conf").write_text(
            "[main]\nplugins=keyfile\ndns=systemd-resolved\n", encoding="utf-8"
        )
        connection_dir = root / "etc/NetworkManager/system-connections"
        connection_dir.mkdir(parents=True)
        wired_profile = connection_dir / "a7z-wired-dhcp.nmconnection"
        wired_profile.write_text(
            "[connection]\nid=A7Z wired DHCP\nuuid=ef617f55-4f37-4260-91ea-f3375d7b6b44\ntype=ethernet\nautoconnect=true\n\n"
            "[ethernet]\n\n[ipv4]\nmethod=auto\n\n[ipv6]\naddr-gen-mode=default\nmethod=auto\n\n[proxy]\n",
            encoding="utf-8",
        )
        wired_profile.chmod(0o600)
        (root / "usr/bin").mkdir(parents=True)
        nmtui = root / "usr/bin/nmtui"
        nmtui.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        nmtui.chmod(0o755)
        (root / "etc/resolv.conf").symlink_to("/run/systemd/resolve/stub-resolv.conf")

    def make_valid_rootfs(self, root: Path) -> None:
        self.make_valid_networkmanager_rootfs(root)

    def add_legacy_networkd_conflict(self, root: Path) -> None:
        wants = root / "etc/systemd/system/multi-user.target.wants"
        networkd = wants / "systemd-networkd.service"
        if not networkd.exists():
            networkd.symlink_to("/lib/systemd/system/systemd-networkd.service")
        network_dir = root / "etc/systemd/network"
        network_dir.mkdir(parents=True, exist_ok=True)
        (network_dir / "20-ethernet.network").write_text(
            "[Match]\nName=en* eth* end*\n[Network]\nDHCP=yes\n", encoding="utf-8"
        )

    def test_package_manifest_contains_minimal_runtime_without_desktop_meta_packages(self) -> None:
        self.require_file(PACKAGE_LIST)
        packages = {
            line.strip().split()[0]
            for line in PACKAGE_LIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for required in ("systemd", "openssh-server", "sudo", "iproute2", "network-manager", "wpasupplicant", "libdrm2", "libwayland-client0", "glmark2-es2-wayland", "weston"):
            self.assertIn(required, packages)
        for forbidden in ("ubuntu-desktop", "gnome-shell", "kde-plasma-desktop", "xorg", "gdm3", "lightdm", "sddm"):
            self.assertNotIn(forbidden, packages)

    def test_vendor_manifest_pins_all_selected_files_without_path_escape(self) -> None:
        self.require_file(VENDOR_MANIFEST)
        rows = []
        for line in VENDOR_MANIFEST.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            self.assertEqual(len(fields), 3, line)
            digest, source, destination = fields
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            for relative in (source, destination):
                self.assertFalse(relative.startswith("/"), relative)
                self.assertNotIn("..", Path(relative).parts, relative)
            rows.append((source, destination))
        source_paths = {source for source, _ in rows}
        for required in ("etc/npu/vpm_run/vpm_run", "etc/npu/yolov5/yolov5", "lib/modules/6.6.98/pvrsrvkm.ko", "lib/firmware/rgx.fw.36.56.104.183", "usr/lib/libNBGlinker.so"):
            self.assertIn(required, source_paths)

    @unittest.skipIf(os.name == "nt", "run apt-source shell validation on the Linux build host")
    def test_apt_source_writer_bootstraps_ca_over_signed_ustc_http_then_persists_https(self) -> None:
        helper = ROOT / "configure_ubuntu_apt_sources.sh"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            root.mkdir()
            source = root / "etc/apt/sources.list.d/ubuntu.sources"
            for phase, uri in (
                ("bootstrap", "http://mirrors.ustc.edu.cn/ubuntu-ports/"),
                ("final", "https://mirrors.ustc.edu.cn/ubuntu-ports/"),
            ):
                result = subprocess.run(["bash", str(helper), str(root), phase], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertEqual(result.returncode, 0, result.stdout)
                text = source.read_text(encoding="utf-8")
                for required_line in (
                    "Types: deb",
                    f"URIs: {uri}",
                    "Suites: noble noble-updates noble-security",
                    "Components: main universe",
                    "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg",
                    "Architectures: arm64",
                ):
                    self.assertIn(required_line, text)
                self.assertNotIn("trusted=yes", text.lower())
            before = source.read_text(encoding="utf-8")
            invalid = subprocess.run(["bash", str(helper), str(root), "other"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertEqual(source.read_text(encoding="utf-8"), before)

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_accepts_complete_ubuntu_headless_fixture(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 0, result.stdout)

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_rejects_untrusted_or_incomplete_ubuntu_apt_sources(self) -> None:
        self.require_file(VERIFIER)
        mutations = (
            ("wrong URI", "https://mirrors.ustc.edu.cn/ubuntu-ports/", "http://ports.ubuntu.com/ubuntu-ports"),
            ("missing security suite", "noble noble-updates noble-security", "noble noble-updates"),
            ("missing universe", "Components: main universe", "Components: main"),
            ("wrong signing key", "/usr/share/keyrings/ubuntu-archive-keyring.gpg", "/etc/apt/untrusted.gpg"),
            ("wrong architecture", "Architectures: arm64", "Architectures: amd64"),
        )
        for label, original, changed in mutations:
            with self.subTest(mutation=label), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "root"
                self.make_valid_rootfs(root)
                self.add_legacy_networkd_conflict(root)
                source = root / "etc/apt/sources.list.d/ubuntu.sources"
                text = source.read_text(encoding="utf-8")
                self.assertIn(original, text)
                source.write_text(text.replace(original, changed, 1), encoding="utf-8")
                result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("apt source", result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_rejects_an_additional_active_apt_source(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            self.add_legacy_networkd_conflict(root)
            extra = root / "etc/apt/sources.list.d/extra.sources"
            extra.write_text("Types: deb\nURIs: http://ports.ubuntu.com/ubuntu-ports\nSuites: noble\nComponents: main\n", encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected apt source", result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_requires_networkmanager_and_wpasupplicant(self) -> None:
        self.require_file(VERIFIER)
        for missing_package in ("network-manager", "wpasupplicant"):
            with self.subTest(missing_package=missing_package), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "root"
                self.make_valid_rootfs(root)
                self.add_legacy_networkd_conflict(root)
                status = root / "var/lib/dpkg/status"
                stanzas = [block for block in status.read_text(encoding="utf-8").split("\n\n") if not block.startswith(f"Package: {missing_package}\n")]
                status.write_text("\n\n".join(stanzas), encoding="utf-8")
                result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing_package, result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_requires_nmtui_and_resolved_backed_networkmanager(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            self.add_legacy_networkd_conflict(root)
            (root / "usr/bin/nmtui").unlink()
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nmtui", result.stdout.lower())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            self.add_legacy_networkd_conflict(root)
            config = root / "etc/NetworkManager/NetworkManager.conf"
            config.write_text("[main]\nplugins=keyfile\ndns=default\n", encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("systemd-resolved", result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_requires_private_autoconnect_wired_dhcp_profile(self) -> None:
        self.require_file(VERIFIER)
        profile_rel = Path("etc/NetworkManager/system-connections/a7z-wired-dhcp.nmconnection")
        mutations = (
            ("missing profile", None, None),
            ("manual IPv4", "[ipv4]\nmethod=auto", "[ipv4]\nmethod=manual"),
            ("manual IPv6", "[ipv6]\naddr-gen-mode=default\nmethod=auto", "[ipv6]\naddr-gen-mode=default\nmethod=manual"),
            ("autoconnect disabled", "autoconnect=true", "autoconnect=false"),
        )
        for label, original, changed in mutations:
            with self.subTest(mutation=label), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "root"
                self.make_valid_rootfs(root)
                profile = root / profile_rel
                if original is None:
                    profile.unlink()
                else:
                    text = profile.read_text(encoding="utf-8")
                    self.assertIn(original, text)
                    profile.write_text(text.replace(original, changed, 1), encoding="utf-8")
                result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue("wired dhcp" in result.stdout.lower() or "profile" in result.stdout.lower(), result.stdout)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            (root / profile_rel).chmod(0o644)
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("permissions", result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_requires_networkmanager_and_rejects_networkd(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            self.add_legacy_networkd_conflict(root)
            (root / "etc/systemd/system/multi-user.target.wants/NetworkManager.service").unlink()
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NetworkManager", result.stdout)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            self.add_legacy_networkd_conflict(root)
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("networkd", result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_rejects_networkd_socket_in_other_target_and_any_networkd_profile(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            wants = root / "etc/systemd/system/graphical.target.wants"
            wants.mkdir(parents=True)
            (wants / "systemd-networkd.socket").symlink_to("/lib/systemd/system/systemd-networkd.socket")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("networkd", result.stdout.lower())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            extra_profile = root / "etc/systemd/network/90-custom.network"
            extra_profile.write_text("[Match]\nName=eth*\n[Network]\nDHCP=yes\n", encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("networkd", result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_rejects_non_ubuntu_and_missing_hardware_runtime(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            release = root / "etc/os-release"
            release.write_text('ID=buildroot\nVERSION_ID="2022.05"\n', encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("OS ID is not Ubuntu", result.stdout)
            release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
            (root / "lib/modules/6.6.98/pvrsrvkm.ko").unlink()
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pvrsrvkm.ko", result.stdout)

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_rejects_desktop_packages_unlocked_root_and_baked_host_keys(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            status = root / "var/lib/dpkg/status"
            status.write_text(status.read_text(encoding="utf-8") + "\n\nPackage: gnome-shell\nStatus: install ok installed\nArchitecture: arm64\n", encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("desktop/display-manager", result.stdout)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            (root / "etc/ssh/ssh_host_ed25519_key").write_text("private", encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("host key", result.stdout)

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_requires_radxa_autologin_password_account_and_passworded_sudo(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 0, result.stdout)
            sudoers = root / "etc/sudoers"
            sudoers.write_text("radxa ALL=(ALL) NOPASSWD:ALL\n", encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("password", result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_rejects_missing_radxa_account_or_passwordless_sudo(self) -> None:
        self.require_file(VERIFIER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            passwd = root / "etc/passwd"
            passwd.write_text(passwd.read_text(encoding="utf-8").replace("radxa:x:1000:1000:Radxa:/home/radxa:/bin/bash\n", ""), encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("radxa account", result.stdout)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            self.make_valid_rootfs(root)
            (root / "etc/sudoers.d").mkdir()
            (root / "etc/sudoers.d/90-radxa").write_text("radxa ALL=(ALL) NOPASSWD:ALL\n", encoding="utf-8")
            result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sudo", result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run rootfs shell validation on the Linux build host")
    def test_verifier_requires_video_and_render_groups_for_radxa(self) -> None:
        self.require_file(VERIFIER)
        for missing_group in ("video", "render"):
            with self.subTest(missing_group=missing_group), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "root"
                self.make_valid_rootfs(root)
                group_file = root / "etc/group"
                updated_lines = []
                for line in group_file.read_text(encoding="utf-8").splitlines():
                    fields = line.split(":")
                    if fields[0] == missing_group:
                        fields[3] = ",".join(member for member in fields[3].split(",") if member != "radxa")
                        line = ":".join(fields)
                    updated_lines.append(line)
                group_file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
                result = subprocess.run(["bash", str(VERIFIER), str(root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing_group, result.stdout.lower())

    @unittest.skipIf(os.name == "nt", "run shell builder validation on the Linux build host")
    def test_builder_rejects_wrong_archive_hash_before_creating_work_or_output(self) -> None:
        self.require_file(BUILDER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "base.tar.gz"
            archive.write_bytes(b"not an ubuntu archive")
            work = root / "work"
            output = root / "rootfs.ext4"
            result = subprocess.run(
                ["bash", str(BUILDER), "--work-dir", str(work), "--base-tarball", str(archive),
                 "--base-sha256", "0" * 64, "--vendor-root", str(root), "--out-ext4", str(output),
                 "--size-bytes", "3946823168"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SHA-256", result.stdout)
            self.assertFalse(work.exists())
            self.assertFalse(output.exists())

    @unittest.skipIf(os.name == "nt", "run shell builder validation on the Linux build host")
    def test_builder_refuses_output_collision(self) -> None:
        self.require_file(BUILDER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "base.tar.gz"
            archive.write_bytes(b"unused")
            output = root / "rootfs.ext4"
            output.write_bytes(b"preserve")
            result = subprocess.run(
                ["bash", str(BUILDER), "--work-dir", str(root / "work"), "--base-tarball", str(archive),
                 "--base-sha256", "0" * 64, "--vendor-root", str(root), "--out-ext4", str(output),
                 "--size-bytes", "1048576"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite", result.stdout.lower())
            self.assertEqual(output.read_bytes(), b"preserve")
            self.assertFalse((root / "work").exists())


if __name__ == "__main__":
    unittest.main()

