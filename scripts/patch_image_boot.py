#!/usr/bin/env python3
"""Patch the A7Z boot-package slot and p2 /sunxi.dtb inside a composed SD image."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

CHUNK = 8 << 20
SECTOR = 512
IMAGE_SIZE = 4_294_967_296
PACKAGE_START = 12_582_912
PACKAGE_END = 16_777_216
P2_OFFSET = 65_536 * SECTOR
DTB_SLACK_CLUSTERS = 24          # p2 /sunxi.dtb keeps its original 24-cluster chain


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest().upper()


def fdt_size(blob: bytes) -> int:
    if len(blob) < 8 or struct.unpack_from(">I", blob, 0)[0] != 0xD00DFEED:
        raise ValueError("not a valid DTB (bad magic)")
    total = struct.unpack_from(">I", blob, 4)[0]
    if not 40 <= total <= len(blob):
        raise ValueError("invalid DTB totalsize")
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--boot-package", required=True, type=Path)
    ap.add_argument("--dtb", required=True, type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    image, package, dtb = args.image, args.boot_package, args.dtb
    if not image.is_file() or image.stat().st_size != IMAGE_SIZE:
        print(f"ERROR: image missing or not {IMAGE_SIZE} bytes", file=sys.stderr)
        return 1
    if package.stat().st_size > PACKAGE_END - PACKAGE_START:
        print("ERROR: boot package exceeds the reserved slot", file=sys.stderr)
        return 1

    package_blob = package.read_bytes()
    dtb_blob = dtb.read_bytes()
    fdt_size(dtb_blob)                       # validates magic/size
    if len(dtb_blob) > DTB_SLACK_CLUSTERS * 8192:
        print("ERROR: DTB larger than the existing 24-cluster chain", file=sys.stderr)
        return 1

    before = sha256_file(image)

    # 1) boot-package slot (SCP / monitor / u-boot payload), zero padded
    with image.open("r+b") as f:
        f.seek(PACKAGE_START)
        f.write(package_blob)
        f.write(b"\0" * (PACKAGE_END - PACKAGE_START - len(package_blob)))
        f.flush()
        os.fsync(f.fileno())
        f.seek(PACKAGE_START)
        if f.read(len(package_blob)) != package_blob:
            print("ERROR: boot-package readback mismatch", file=sys.stderr)
            return 1
        if any(f.read(PACKAGE_END - PACKAGE_START - len(package_blob))):
            print("ERROR: boot-package slot padding is not zero", file=sys.stderr)
            return 1

    # 2) p2 /sunxi.dtb via mcopy (preserves FAT layout when the file still fits)
    staging = image.parent / "dtb-patch-staging"
    staging.mkdir(exist_ok=True)
    padded = staging / "sunxi.dtb"
    shutil.copyfile(dtb, padded)
    # keep the original FAT mtime so only content/size change
    orig_stat = None
    extract = staging / "sunxi.orig.dtb"
    subprocess.run(["mcopy", "-o", "-i", f"{image}@@{P2_OFFSET}", "::/sunxi.dtb", str(extract)], check=True)
    orig_stat = extract.stat()
    os.utime(padded, ns=(orig_stat.st_atime_ns, orig_stat.st_mtime_ns))
    subprocess.run(["mcopy", "-o", "-m", "-i", f"{image}@@{P2_OFFSET}", str(padded), "::/sunxi.dtb"], check=True)

    readback = staging / "sunxi.readback.dtb"
    subprocess.run(["mcopy", "-o", "-i", f"{image}@@{P2_OFFSET}", "::/sunxi.dtb", str(readback)], check=True)
    if readback.read_bytes() != dtb_blob:
        print("ERROR: p2 /sunxi.dtb readback mismatch", file=sys.stderr)
        return 1

    report = {
        "image": str(image),
        "image_sha256_before": before,
        "image_sha256_after": sha256_file(image),
        "boot_package": str(package),
        "boot_package_sha256": hashlib.sha256(package_blob).hexdigest().upper(),
        "dtb": str(dtb),
        "dtb_sha256": hashlib.sha256(dtb_blob).hexdigest().upper(),
        "dtb_size": len(dtb_blob),
        "package_slot": [PACKAGE_START, PACKAGE_END],
        "verified_package_readback": True,
        "verified_dtb_readback": True,
    }
    text = json.dumps(report, indent=2) + "\n"
    (args.report or image.with_suffix(".boot-patch.json")).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
