#!/usr/bin/env python3
"""Extract and byte-verify the A7Z OrangePi boot-package round trip."""
from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

EXPECTED_SHA256 = "ACAA783AA27F862188811DCEDFB85416032FF2FC1BA97B2391D59DDCD6DBBB42"
EXPECTED_ITEMS = ("u-boot", "monitor", "scp")
ITEM_TABLE_OFFSET = 0x3C
ITEM_RECORD_SIZE = 0x170
ITEM_DATA_FIELDS_OFFSET = 0x44


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def parse_items(blob: bytes) -> list[tuple[str, int, int]]:
    if blob[:13] != b"sunxi-package":
        raise ValueError("unexpected Allwinner boot-package magic")
    count = struct.unpack_from("<I", blob, 0x20)[0]
    if count != len(EXPECTED_ITEMS):
        raise ValueError(f"expected 3 package items, found {count}")
    items = []
    for index in range(count):
        record = ITEM_TABLE_OFFSET + index * ITEM_RECORD_SIZE
        raw_name = blob[record : record + 0x40].split(b"\0", 1)[0]
        try:
            _kind, name = raw_name.decode("ascii").split(";", 1)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"invalid package item name at record {index}") from exc
        offset, size = struct.unpack_from("<II", blob, record + ITEM_DATA_FIELDS_OFFSET)
        if not size or offset < ITEM_TABLE_OFFSET + count * ITEM_RECORD_SIZE or offset + size > len(blob):
            raise ValueError(f"invalid bounds for package item {name}")
        items.append((name, offset, size))
    if tuple(item[0] for item in items) != EXPECTED_ITEMS:
        raise ValueError(f"unexpected package items: {items}")
    intervals = sorted((offset, offset + size) for _, offset, size in items)
    if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
        raise ValueError("boot-package item payloads overlap")
    return items


def roundtrip(package: Path, pack_tools: Path, workdir: Path) -> dict[str, object]:
    original = package.read_bytes()
    original_sha = sha256(original)
    if original_sha != EXPECTED_SHA256:
        raise ValueError(f"A7Z package SHA mismatch: {original_sha}")
    items = parse_items(original)
    workdir.mkdir(parents=True, exist_ok=False)
    for name, offset, size in items:
        (workdir / f"{name}.fex").write_bytes(original[offset : offset + size])
    cfg = (pack_tools / "sun60iw2/bin/boot_package.cfg").read_text(encoding="ascii")
    (workdir / "boot_package.cfg").write_bytes(cfg.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))
    tool = pack_tools / "tools/dragonsecboot"
    result = subprocess.run([str(tool), "-pack", "boot_package.cfg"], cwd=workdir, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"dragonsecboot failed ({result.returncode}): {result.stdout}{result.stderr}")
    packed = workdir / "boot_package.fex"
    if not packed.is_file():
        raise RuntimeError("dragonsecboot did not produce boot_package.fex")
    rebuilt = packed.read_bytes()
    rebuilt_sha = sha256(rebuilt)
    if rebuilt != original:
        raise ValueError(f"round-trip package differs: expected {original_sha}, got {rebuilt_sha}")
    return {
        "package_sha256": original_sha,
        "roundtrip_sha256": rebuilt_sha,
        "package_size": len(original),
        "items": [{"name": n, "offset": o, "size": s, "sha256": sha256(original[o:o+s])} for n, o, s in items],
        "roundtrip_byte_identical": True,
        "tool_stdout": result.stdout.strip(),
        "tool_stderr": result.stderr.strip(),
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("pack_tools", type=Path)
    parser.add_argument("workdir", type=Path)
    args = parser.parse_args()
    print(json.dumps(roundtrip(args.package, args.pack_tools, args.workdir), indent=2))


if __name__ == "__main__":
    main()
