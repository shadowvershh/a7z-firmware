from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OVERLAY = ROOT / "overlay"
ACCOUNT_CONFIG = ROOT / "configure_radxa_account.sh"
SERIAL_AUTOLOGIN = OVERLAY / "etc" / "systemd" / "system" / "serial-getty@ttyAS0.service.d" / "10-autologin.conf"
NETWORK_MANAGER_CONF = OVERLAY / "etc" / "NetworkManager" / "NetworkManager.conf"
WIRED_DHCP_PROFILE = OVERLAY / "etc" / "NetworkManager" / "system-connections" / "a7z-wired-dhcp.nmconnection"
SSHD = OVERLAY / "etc" / "ssh" / "sshd_config.d" / "10-a7z-hardening.conf"
SSH_KEYGEN = OVERLAY / "etc" / "systemd" / "system" / "ssh.service.d" / "10-generate-hostkeys.conf"


def required_text(case: unittest.TestCase, path: Path) -> str:
    case.assertTrue(path.is_file(), f"required configuration is missing: {path}")
    return path.read_text(encoding="utf-8")


class HeadlessOverlayTests(unittest.TestCase):
    def test_networkmanager_has_an_autoconnect_wired_dhcp_profile(self) -> None:
        profile = required_text(self, WIRED_DHCP_PROFILE)
        self.assertRegex(profile, r"(?m)^\[connection\]$")
        self.assertRegex(profile, r"(?m)^id=A7Z wired DHCP$")
        self.assertRegex(profile, r"(?m)^uuid=[0-9a-f-]{36}$")
        self.assertRegex(profile, r"(?m)^type=ethernet$")
        self.assertRegex(profile, r"(?m)^autoconnect=true$")
        self.assertRegex(profile, r"(?m)^\[ipv4\]$")
        self.assertRegex(profile, r"(?m)^method=auto$")
        self.assertRegex(profile, r"(?m)^\[ipv6\][\s\S]*^method=auto$", msg="wired DHCP profile must use automatic IPv6 configuration as well")
        builder = required_text(self, ROOT / "build_ubuntu24_rootfs.sh")
        self.assertIn("install -m 0600", builder)
        self.assertIn("a7z-wired-dhcp.nmconnection", builder)
        self.assertIn("NetworkManager/system-connections", builder)

    def test_serial_getty_autologins_as_non_root_radxa(self) -> None:
        config = required_text(self, SERIAL_AUTOLOGIN)
        self.assertIn("ExecStart=", config)
        self.assertRegex(config, r"(?m)--autologin\s+radxa")
        self.assertNotIn("--autologin root", config)
        self.assertNotIn("password", config.lower())

    def test_builder_does_not_install_a_firstboot_account_prompt(self) -> None:
        builder = required_text(self, ROOT / "build_ubuntu24_rootfs.sh")
        self.assertNotIn("enable a7z-firstboot-account.service", builder)
        self.assertNotIn("a7z-firstboot-account.service", builder)

    def test_networkmanager_uses_resolved_and_replaces_networkd(self) -> None:
        config = required_text(self, NETWORK_MANAGER_CONF)
        self.assertNotIn(b"\r", NETWORK_MANAGER_CONF.read_bytes(), "NetworkManager config must use LF line endings for the rootfs verifier")
        self.assertRegex(config, r"(?m)^\[main\]$")
        self.assertRegex(config, r"(?m)^plugins=keyfile$")
        self.assertRegex(config, r"(?m)^dns=systemd-resolved$")
        builder = required_text(self, ROOT / "build_ubuntu24_rootfs.sh")
        self.assertNotIn("20-ethernet.network", builder)
        self.assertIn('enable serial-getty@ttyAS0.service NetworkManager.service systemd-resolved.service ssh.service', builder)
        self.assertIn('disable systemd-networkd.service', builder)

    def test_sshd_accepts_password_only_for_radxa_but_forbids_root(self) -> None:
        sshd = required_text(self, SSHD)
        self.assertRegex(sshd, r"(?m)^PermitRootLogin\s+no\s*$")
        self.assertRegex(sshd, r"(?m)^PasswordAuthentication\s+yes\s*$")
        self.assertRegex(sshd, r"(?m)^KbdInteractiveAuthentication\s+no\s*$")
        self.assertRegex(sshd, r"(?m)^PubkeyAuthentication\s+yes\s*$")
        self.assertRegex(sshd, r"(?m)^AllowUsers\s+radxa\s*$")
        self.assertNotIn("NOPASSWD", sshd)

    def test_ssh_host_keys_are_generated_at_runtime_not_baked(self) -> None:
        dropin = required_text(self, SSH_KEYGEN)
        self.assertIn("ExecStartPre=/usr/bin/ssh-keygen -A", dropin)
        self.assertFalse(any(OVERLAY.rglob("ssh_host_*")))

    def run_as_root(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        forwarded = [f"{key}={value}" for key, value in env.items() if key == "PATH" or key.startswith("FAKE_")]
        return subprocess.run(["sudo", "-n", "env", *forwarded, "bash", str(ACCOUNT_CONFIG), str(env["FAKE_ROOTFS"])], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def reclaim_temp_permissions(self, directory: Path) -> None:
        subprocess.run(["sudo", "-n", "chown", "-R", f"{os.getuid()}:{os.getgid()}", str(directory)], check=True)

    @unittest.skipIf(os.name == "nt", "run shell account provisioning tests on the Linux build host")
    def test_default_account_script_creates_radxa_with_requested_password_and_sudo_group(self) -> None:
        self.assertTrue(ACCOUNT_CONFIG.is_file(), f"required account configuration is missing: {ACCOUNT_CONFIG}")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fakebin = root / "fakebin"
            fakebin.mkdir()
            calls = root / "calls.log"
            password_input = root / "chpasswd.input"
            fake_chroot = fakebin / "chroot"
            fake_chroot.write_text(
                "\n".join([
                    "#!/bin/sh",
                    "printf 'chroot %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"",
                    "if [ \"${2:-}\" = \"/usr/bin/getent\" ]; then exit 1; fi",
                    "if [ \"${2:-}\" = \"/usr/sbin/chpasswd\" ]; then cat >\"$FAKE_PASSWORD_INPUT\"; fi",
                    "exit 0",
                    "",
                ]),
                encoding="utf-8",
            )
            fake_chroot.chmod(0o755)
            target = root / "target-rootfs"
            (target / "etc").mkdir(parents=True)
            (target / "usr/sbin").mkdir(parents=True)
            (target / "usr/sbin/adduser").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (target / "usr/sbin/adduser").chmod(0o755)
            env = os.environ.copy()
            env.update({
                "PATH": f"{fakebin}:{env.get('PATH', '')}",
                "FAKE_CALL_LOG": str(calls),
                "FAKE_PASSWORD_INPUT": str(password_input),
                "FAKE_ROOTFS": str(target),
            })
            result = self.run_as_root(env)
            self.reclaim_temp_permissions(root)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotIn("radxa:radxa", result.stdout)
            self.assertEqual(calls.read_text(encoding="utf-8").splitlines(), [
                f"chroot {target} /usr/bin/getent passwd radxa",
                f"chroot {target} /usr/sbin/adduser --disabled-password --gecos Radxa radxa",
                f"chroot {target} /usr/sbin/usermod --append --groups sudo,video,render radxa",
                f"chroot {target} /usr/sbin/chpasswd",
            ])
            self.assertEqual(password_input.read_text(encoding="utf-8"), "radxa:radxa\n")


if __name__ == "__main__":
    unittest.main()
