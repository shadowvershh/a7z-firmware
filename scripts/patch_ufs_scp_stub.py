#!/usr/bin/env python3
"""Park the RISC-V core inside the UFS boot blob by overwriting the SCP payload.

Why this exists
---------------
On SD the boot chain is a `sunxi-package` (u-boot / monitor / scp items) and we
simply drop the scp item.  The UFS base image is different: its boot area is a
U-Boot **FIT image** whose `/images/scp` sub-image carries the SCP payload
inline (122056 bytes at image offset 2403456).  There is no item table to edit
and no `hash` node to keep in sync, so the payload is overwritten in place with
a WFI fill:

    0x10500073 = `wfi`, repeated 30514 times

Any entry point in that region executes WFI in a straight line, so the core
sleeps forever instead of running the SCP.  This is NOT the same as holding the
core in reset (it stays clocked), but the SCP no longer runs.

The offset/size/hash below are pinned to the verified base image
(`base-ufs4096-v2.img.xz`, UFS_BASE_SHA256 in the workflow).  A mismatch aborts
instead of corrupting a different base.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

WFI = 0x10500073

# Pinned layout of the UFS base boot blob (from the FIT image it contains).
SCP_OFFSET = 2_403_456
SCP_LENGTH = 122_056
SCP_SHA256 = "8DE05624D611AFB9577B0AB73620EF708DDE566A68327FD97795D0DDAA912FEE"


def sha256_region(path: Path, offset: int, length: int) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        f.seek(offset)
        remaining = length
        while remaining:
            chunk = f.read(min(1 << 20, remaining))
            if not chunk:
                raise ValueError("unexpected EOF while hashing the SCP region")
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest().upper()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--offset", type=int, default=SCP_OFFSET)
    ap.add_argument("--length", type=int, default=SCP_LENGTH)
    ap.add_argument("--expect-sha256", default=SCP_SHA256)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--force", action="store_true", help="skip the region hash check")
    ap.add_argument("--verify-only", action="store_true",
                    help="only check that the region is already WFI-filled")
    args = ap.parse_args()

    image = args.image
    if not image.is_file():
        raise SystemExit(f"image not found: {image}")
    size = image.stat().st_size
    if args.offset + args.length > size:
        raise SystemExit(f"region {args.offset}+{args.length} exceeds image size {size}")
    if args.length % 4:
        raise SystemExit(f"region length must be a multiple of 4, got {args.length}")

    if args.verify_only:
        with image.open("rb") as f:
            f.seek(args.offset)
            words = struct.unpack(f"<{args.length // 4}I", f.read(args.length))
        bad = [i for i, w in enumerate(words) if w != WFI]
        if bad:
            raise SystemExit(f"FAIL: {len(bad)} non-WFI words in the SCP region (first at {bad[0]})")
        print(f"PASS: UFS SCP region holds {len(words)} WFI words — RISC-V core parked")
        return 0

    before = sha256_region(image, args.offset, args.length)
    if not args.force and before != args.expect_sha256.upper():
        raise SystemExit(
            "SCP region sha256 mismatch — refusing to patch.\n"
            f"  expected {args.expect_sha256.upper()}\n  actual   {before}\n"
            "  (the base image layout differs from the pinned one; use --force only "
            "after re-verifying the FIT /images/scp node)"
        )

    fill = struct.pack("<I", WFI) * (args.length // 4)
    with image.open("r+b") as f:
        f.seek(args.offset)
        f.write(fill)
        f.flush()
        os.fsync(f.fileno())
        f.seek(args.offset)
        if f.read(args.length) != fill:
            raise SystemExit("read-back mismatch after writing the WFI fill")

    after = sha256_region(image, args.offset, args.length)
    report = {
        "image": str(image),
        "region_offset": args.offset,
        "region_length": args.length,
        "wfi_words": args.length // 4,
        "scp_sha256_before": before,
        "scp_sha256_after": after,
        "scp_parked": True,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"PASS: RISC-V SCP payload parked in {image} "
          f"({args.length} bytes of WFI at {args.offset})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
