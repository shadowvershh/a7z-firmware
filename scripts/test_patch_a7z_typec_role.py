from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
PATCHER = SCRIPTS / "patch_a7z_typec_role.py"
BUILD_PARTS = SCRIPTS / "build-sdk-parts.sh"
DRIVER = REPO / "drivers" / "tcpci_et7304.c"
MODULES_LOAD = REPO / "overlay" / "etc" / "modules-load.d" / "et7304.conf"

# The property line as it appears in the vendor board.dts.
VENDOR_DTS = """\
/ {
\tconnector {
\t\tcompatible = "usb-c-connector";
\t\tlabel = "USB-C";
\t\tdata-role = "dual";
\t\tpower-role = "dual";
\t\ttry-power-role = "sink";
\t\top-sink-microwatt = <1000000>;
\t};
};
"""


def run_patcher(dts: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PATCHER), str(dts)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


class TypecRolePatchTests(unittest.TestCase):
    def test_flips_sink_to_source_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dts = Path(temp) / "board.dts"
            dts.write_text(VENDOR_DTS, encoding="utf-8", newline="\n")
            first = run_patcher(dts)
            self.assertEqual(first.returncode, 0, first.stdout)
            text = dts.read_text(encoding="utf-8")
            self.assertIn('try-power-role = "source";', text)
            self.assertNotIn('try-power-role = "sink";', text)
            # op-sink-microwatt must survive: only the role line may change.
            self.assertIn("op-sink-microwatt", text)
            second = run_patcher(dts)
            self.assertEqual(second.returncode, 0, second.stdout)
            self.assertIn("already patched", second.stdout)
            self.assertEqual(text, dts.read_text(encoding="utf-8"))

    def test_rejects_a_dts_without_the_connector(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dts = Path(temp) / "board.dts"
            dts.write_text("/ {\n};\n", encoding="utf-8", newline="\n")
            result = run_patcher(dts)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no try-power-role", result.stdout)

    def test_scripts_and_driver_use_lf_line_endings(self) -> None:
        for path in (PATCHER, BUILD_PARTS, DRIVER, MODULES_LOAD):
            self.assertTrue(path.is_file(), f"missing repo file: {path}")
            self.assertNotIn(b"\r", path.read_bytes(), f"{path} must use LF line endings")

    def test_driver_matches_the_a7z_hardware_bindings(self) -> None:
        driver = DRIVER.read_text(encoding="utf-8")
        self.assertIn('"etek,et7304"', driver)
        self.assertIn('"vbus"', driver)
        self.assertIn('"et7304,intr_gpio"', driver)
        self.assertIn("tcpci_register_port", driver)
        self.assertIn("MODULE_LICENSE(\"GPL\")", driver)

    def test_build_pipeline_wires_the_typec_fix(self) -> None:
        script = BUILD_PARTS.read_text(encoding="utf-8")
        self.assertIn("patch_a7z_typec_role.py", script)
        self.assertIn("drivers/tcpci_et7304.c", script)
        self.assertIn("overlay/usr/lib/modules/6.6.98/", script)
        self.assertIn("overlay/boot/sunxi.dtb", script)
        self.assertIn("tcpci_et7304", MODULES_LOAD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()