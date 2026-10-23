#!/usr/bin/env python3
"""Repack the pinned A7Z boot package, replacing (or dropping) the SCP payload.

Two modes:

  default        replace the scp item with the freshly built E902 binary that
                 carries the UART1 logging marker.
  --drop-scp     remove the scp item entirely, so boot0 has nothing to hand to
                 the RISC-V core and never de-asserts its reset.  This is the
                 "RISC-V core off" variant (no S-UART1 log on the header).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from roundtrip_a7z_boot_package import EXPECTED_SHA256, parse_items, sha256

SLOT_SIZE = 4 * 1024 * 1024
MARKER = b"E902_S_UART1_READY baud=115200"
SCP_LINE = re.compile(r"^\s*item\s*=\s*scp\b.*$", re.IGNORECASE)


def build_package(
    baseline: Path,
    pack_tools: Path,
    scp: Path | None,
    out_dir: Path,
    drop_scp: bool = False,
) -> dict[str, object]:
    baseline_blob = baseline.read_bytes()
    baseline_hash = sha256(baseline_blob)
    if baseline_hash != EXPECTED_SHA256:
        raise ValueError(f"baseline A7Z boot-package SHA mismatch: {baseline_hash}")

    scp_blob = b""
    if not drop_scp:
        if scp is None or not scp.is_file() or scp.stat().st_size == 0:
            raise ValueError("new E902 scp.bin is missing or empty")
        scp_blob = scp.read_bytes()
        if MARKER not in scp_blob:
            raise ValueError("new SCP binary does not contain the unique E902 UART1 marker")

    if out_dir.exists():
        raise FileExistsError(f"refusing to overwrite boot-package output directory: {out_dir}")
    out_dir.mkdir(parents=True)
    work = out_dir / "work"
    work.mkdir()

    old_items = parse_items(baseline_blob)
    old_payloads = {}
    for name, offset, size in old_items:
        payload = baseline_blob[offset : offset + size]
        old_payloads[name] = payload
        if drop_scp and name == "scp":
            continue
        (work / f"{name}.fex").write_bytes(payload)
    if not drop_scp:
        (work / "scp.fex").write_bytes(scp_blob)

    cfg = (pack_tools / "sun60iw2/bin/boot_package.cfg").read_text(encoding="ascii")
    if drop_scp:
        kept = [line for line in cfg.splitlines() if not SCP_LINE.match(line)]
        if len(kept) == len(cfg.splitlines()):
            raise ValueError("boot_package.cfg has no scp item to drop")
        cfg = "\n".join(kept) + "\n"
    (work / "boot_package.cfg").write_bytes(cfg.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))

    tool = pack_tools / "tools/dragonsecboot"
    result = subprocess.run([str(tool), "-pack", "boot_package.cfg"], cwd=work, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"dragonsecboot failed ({result.returncode}): {result.stdout}{result.stderr}")
    package_path = work / "boot_package.fex"
    if not package_path.is_file():
        raise RuntimeError("dragonsecboot did not produce boot_package.fex")
    package_blob = package_path.read_bytes()
    if not 0 < len(package_blob) <= SLOT_SIZE:
        raise ValueError(f"rebuilt boot package does not fit the A7Z slot: {len(package_blob)} bytes")
    new_items = parse_items(package_blob, expected=None)
    new_payloads = {
        name: package_blob[offset : offset + size]
        for name, offset, size in new_items
    }
    if new_payloads.get("u-boot") != old_payloads.get("u-boot"):
        raise ValueError("U-Boot payload changed during repack")
    if new_payloads.get("monitor") != old_payloads.get("monitor"):
        raise ValueError("BL31/monitor payload changed during repack")
    if drop_scp:
        if "scp" in new_payloads:
            raise ValueError("scp payload is still present after --drop-scp")
    else:
        if new_payloads.get("scp") != scp_blob:
            raise ValueError("repacked SCP payload differs from the built E902 binary")
    # Nothing may silently disappear from the package apart from the dropped scp.
    expected = {name for name, _, _ in old_items} - ({"scp"} if drop_scp else set())
    if set(new_payloads) != expected:
        raise ValueError(f"repacked item set changed: {sorted(new_payloads)} != {sorted(expected)}")

    final_path = out_dir / ("boot_package_noscp.fex" if drop_scp else "boot_package_uart1.fex")
    shutil.copyfile(package_path, final_path)
    report = {
        "baseline_package_sha256": baseline_hash,
        "baseline_package_size": len(baseline_blob),
        "new_package_sha256": sha256(package_blob),
        "new_package_size": len(package_blob),
        "slot_size": SLOT_SIZE,
        "scp_dropped": drop_scp,
        "scp_sha256": None if drop_scp else sha256(scp_blob),
        "scp_size": 0 if drop_scp else len(scp_blob),
        "items": [
            {
                "name": name,
                "offset": offset,
                "size": size,
                "sha256": sha256(package_blob[offset : offset + size]),
                "same_as_baseline": name != "scp" and package_blob[offset : offset + size] == old_payloads[name],
            }
            for name, offset, size in new_items
        ],
        "roundtrip_pack_tool_stdout": result.stdout.strip(),
        "roundtrip_pack_tool_stderr": result.stderr.strip(),
        "uart1_package_verified": not drop_scp,
    }
    (out_dir / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("pack_tools", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--scp", type=Path, default=None, help="new scp.bin to pack (uart1 mode)")
    parser.add_argument("--drop-scp", action="store_true", help="remove the scp item so the RISC-V core stays in reset")
    args = parser.parse_args()
    if not args.drop_scp and args.scp is None:
        parser.error("--scp is required unless --drop-scp is given")
    print(json.dumps(build_package(args.baseline, args.pack_tools, args.scp, args.out_dir, args.drop_scp), indent=2))


if __name__ == "__main__":
    main()
