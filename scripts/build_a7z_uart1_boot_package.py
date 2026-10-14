#!/usr/bin/env python3
"""Repack the pinned A7Z boot package, replacing only the SCP payload."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from roundtrip_a7z_boot_package import EXPECTED_SHA256, parse_items, sha256

SLOT_SIZE = 4 * 1024 * 1024
MARKER = b"E902_S_UART1_READY baud=115200"


def build_package(baseline: Path, pack_tools: Path, scp: Path, out_dir: Path) -> dict[str, object]:
    baseline_blob = baseline.read_bytes()
    baseline_hash = sha256(baseline_blob)
    if baseline_hash != EXPECTED_SHA256:
        raise ValueError(f"baseline A7Z boot-package SHA mismatch: {baseline_hash}")
    if not scp.is_file() or scp.stat().st_size == 0:
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
        (work / f"{name}.fex").write_bytes(payload)
    (work / "scp.fex").write_bytes(scp_blob)

    cfg = (pack_tools / "sun60iw2/bin/boot_package.cfg").read_text(encoding="ascii")
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
    new_items = parse_items(package_blob)
    new_payloads = {
        name: package_blob[offset : offset + size]
        for name, offset, size in new_items
    }
    if new_payloads.get("u-boot") != old_payloads.get("u-boot"):
        raise ValueError("U-Boot payload changed during repack")
    if new_payloads.get("monitor") != old_payloads.get("monitor"):
        raise ValueError("BL31/monitor payload changed during repack")
    if new_payloads.get("scp") != scp_blob:
        raise ValueError("repacked SCP payload differs from the built E902 binary")

    final_path = out_dir / "boot_package_uart1.fex"
    shutil.copyfile(package_path, final_path)
    report = {
        "baseline_package_sha256": baseline_hash,
        "baseline_package_size": len(baseline_blob),
        "new_package_sha256": sha256(package_blob),
        "new_package_size": len(package_blob),
        "slot_size": SLOT_SIZE,
        "scp_sha256": sha256(scp_blob),
        "scp_size": len(scp_blob),
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
        "uart1_package_verified": True,
    }
    (out_dir / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("pack_tools", type=Path)
    parser.add_argument("scp", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_package(args.baseline, args.pack_tools, args.scp, args.out_dir), indent=2))


if __name__ == "__main__":
    main()
