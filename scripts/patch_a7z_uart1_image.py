#!/usr/bin/env python3
"""Patch only the A7Z SCP package slot and active p2 sunxi.dtb in a new image."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO, Iterable

from inspect_a7z_base import inspect_image

BASE_SHA256 = "8C0B9502C3CCDDCFAB76A554424BC45B842FB70FF7B2989F2C318644E8064B52"
IMAGE_SIZE = 4_294_967_296
SECTOR_SIZE = 512
PACKAGE_START = 12_582_912
PACKAGE_END = 16_777_216
P2_FIRST_LBA = 65_536
P2_START = P2_FIRST_LBA * SECTOR_SIZE
P2_DTB_NAME = "sunxi.dtb"
ROOT_PARTUUID = "1a2b3c4d-0000-4000-8000-000000000003"
BOOT0_RANGE = (131_072, 1_627_173)
CHUNK_SIZE = 8 << 20
FDT_MAGIC = 0xD00DFEED


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _fdt_totalsize(data: bytes) -> int:
    if len(data) < 8 or struct.unpack_from(">I", data, 0)[0] != FDT_MAGIC:
        raise ValueError("invalid DTB magic")
    total = struct.unpack_from(">I", data, 4)[0]
    if total < 40 or total > len(data):
        raise ValueError("invalid DTB totalsize")
    return total


def validate_inputs(
    base: Path,
    package: Path,
    dtb: Path,
    out: Path,
    *,
    expected_base_sha256: str,
    image_size: int,
    package_slot_size: int,
    dtb_size: int,
) -> dict[str, int | str]:
    base, package, dtb, out = map(Path, (base, package, dtb, out))
    tmp = out.with_suffix(out.suffix + ".tmp")
    report = out.with_suffix(out.suffix + ".report.json")
    if out.exists() or tmp.exists() or report.exists():
        raise FileExistsError(f"refusing to overwrite image or temporary output: {out}")
    if not base.is_file() or base.stat().st_size != image_size:
        raise ValueError(f"base image size mismatch: expected {image_size} bytes")
    actual_base_sha = sha256_file(base)
    if actual_base_sha.upper() != expected_base_sha256.upper():
        raise ValueError(f"base image SHA-256 mismatch: got {actual_base_sha}")
    if not package.is_file() or not 0 < package.stat().st_size <= package_slot_size:
        raise ValueError("boot package is missing, empty, or exceeds the reserved package slot")
    if dtb.name != P2_DTB_NAME:
        raise ValueError(f"DTB path must be named {P2_DTB_NAME}")
    if not dtb.is_file() or dtb.stat().st_size != dtb_size:
        raise ValueError(f"DTB size mismatch: expected {dtb_size} bytes")
    dtb_data = dtb.read_bytes()
    if _fdt_totalsize(dtb_data) != len(dtb_data):
        raise ValueError("DTB totalsize must equal the existing p2 file length")
    return {
        "base_sha256": actual_base_sha,
        "base_size": image_size,
        "package_size": package.stat().st_size,
        "dtb_size": dtb.stat().st_size,
    }


def _read_at(stream: BinaryIO, offset: int, size: int) -> bytes:
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"short read at byte {offset}")
    return data


def _coerce_bytes(source: bytes | bytearray | Path) -> bytes | None:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return None


def compare_byte_changes(
    before: bytes | bytearray | Path,
    after: bytes | bytearray | Path,
    allowed_ranges: Iterable[tuple[int, int]],
    *,
    chunk_size: int = CHUNK_SIZE,
) -> dict[str, object]:
    """Require every byte delta to fall within one of the half-open ranges."""
    ranges = sorted((int(start), int(end)) for start, end in allowed_ranges)
    if any(start < 0 or start >= end for start, end in ranges):
        raise ValueError("invalid allowed byte range")
    left_bytes, right_bytes = _coerce_bytes(before), _coerce_bytes(after)
    if left_bytes is not None or right_bytes is not None:
        if left_bytes is None or right_bytes is None:
            raise TypeError("before and after must both be bytes or both be paths")
        if len(left_bytes) != len(right_bytes):
            raise ValueError("image lengths differ")
        chunks = ((offset, left_bytes[offset : offset + chunk_size], right_bytes[offset : offset + chunk_size])
                  for offset in range(0, len(left_bytes), chunk_size))
    else:
        before, after = Path(before), Path(after)
        if before.stat().st_size != after.stat().st_size:
            raise ValueError("image lengths differ")

        def file_chunks():
            with before.open("rb") as left, after.open("rb") as right:
                offset = 0
                while True:
                    lchunk, rchunk = left.read(chunk_size), right.read(chunk_size)
                    if not lchunk and not rchunk:
                        return
                    yield offset, lchunk, rchunk
                    offset += len(lchunk)

        chunks = file_chunks()

    changed = 0
    first_changed: int | None = None
    last_changed: int | None = None
    first_outside: int | None = None
    for offset, left, right in chunks:
        if left == right:
            continue
        for index, (a, b) in enumerate(zip(left, right)):
            if a == b:
                continue
            absolute = offset + index
            changed += 1
            if first_changed is None:
                first_changed = absolute
            last_changed = absolute
            allowed = any(start <= absolute < end for start, end in ranges)
            if not allowed and first_outside is None:
                first_outside = absolute
    if first_outside is not None:
        raise ValueError(f"image byte changed outside allowed ranges at byte {first_outside}")
    return {"changed_bytes": changed, "first_changed_byte": first_changed, "last_changed_byte": last_changed}


def _partition_map(report: dict[str, object]) -> dict[int, dict[str, object]]:
    parts = report["partitions"]
    assert isinstance(parts, list)
    return {int(item["number"]): item for item in parts}


def _mtool(tool: str, image: Path, p2_offset: int, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [tool, "-i", f"{image}@@{p2_offset}", *args]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{tool} failed ({result.returncode}): {result.stdout}{result.stderr}")
    return result


def fat_data_sector_start(boot_sector: bytes) -> tuple[int, int, int]:
    """Return bytes/sector, sectors/cluster, and first data sector for FAT12/16/32."""
    if len(boot_sector) < SECTOR_SIZE:
        raise ValueError("short FAT boot sector")
    bps = struct.unpack_from("<H", boot_sector, 11)[0]
    spc = boot_sector[13]
    reserved = struct.unpack_from("<H", boot_sector, 14)[0]
    nfats = boot_sector[16]
    root_entries = struct.unpack_from("<H", boot_sector, 17)[0]
    fat_size_16 = struct.unpack_from("<H", boot_sector, 22)[0]
    fat_size_32 = struct.unpack_from("<I", boot_sector, 36)[0]
    if bps != SECTOR_SIZE or not spc or spc & (spc - 1) or not reserved or not nfats:
        raise ValueError("p2 FAT geometry is unsupported or invalid")
    if fat_size_16:
        root_dir_sectors = (root_entries * 32 + bps - 1) // bps
        return bps, spc, reserved + nfats * fat_size_16 + root_dir_sectors
    if fat_size_32:
        return bps, spc, reserved + nfats * fat_size_32
    raise ValueError("p2 FAT size is missing")


def _cluster_ranges(image: Path, p2_offset: int) -> list[tuple[int, int]]:
    result = subprocess.run(
        ["mshowfat", "-i", f"{image}@@{p2_offset}", f"::/{P2_DTB_NAME}"],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"mshowfat failed: {result.stdout}{result.stderr}")
    match = re.search(r"<([^>]+)>", result.stdout)
    if not match:
        raise ValueError(f"could not parse FAT cluster chain: {result.stdout.strip()}")
    clusters: list[int] = []
    for item in match.group(1).split(","):
        if "-" in item:
            first, last = (int(value) for value in item.split("-", 1))
            clusters.extend(range(first, last + 1))
        else:
            clusters.append(int(item))
    with image.open("rb") as stream:
        boot = _read_at(stream, p2_offset, SECTOR_SIZE)
    bps, spc, data_start = fat_data_sector_start(boot)
    ranges = []
    for cluster in clusters:
        start = p2_offset + (data_start + (cluster - 2) * spc) * bps
        ranges.append((start, start + spc * bps))
    ranges.sort()
    merged: list[list[int]] = []
    for start, end in ranges:
        if merged and merged[-1][1] == start:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]

def _hash_range(path: Path, start: int, end: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        stream.seek(start)
        remaining = end - start
        while remaining:
            chunk = stream.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError("short read while hashing protected range")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest().upper()


def create_uart1_image(
    base: Path,
    package: Path,
    dtb: Path,
    out: Path,
    *,
    expected_base_sha256: str = BASE_SHA256,
    mcopy: str = "mcopy",
    mshowfat: str = "mshowfat",
) -> dict[str, object]:
    base, package, dtb, out = map(Path, (base, package, dtb, out))
    if out.exists() or out.with_suffix(out.suffix + ".tmp").exists():
        raise FileExistsError(f"refusing to overwrite image or temporary output: {out}")
    baseline_report = inspect_image(base, expected_sha256=expected_base_sha256)
    validate_inputs(
        base,
        package,
        dtb,
        out,
        expected_base_sha256=expected_base_sha256,
        image_size=IMAGE_SIZE,
        package_slot_size=PACKAGE_END - PACKAGE_START,
        dtb_size=195_520,
    )
    baseline_parts = _partition_map(baseline_report)
    if int(baseline_parts[2]["first_lba"]) != P2_FIRST_LBA:
        raise ValueError("p2 start LBA does not match the pinned A7Z SD layout")
    if str(baseline_parts[3]["partuuid"]).lower() != ROOT_PARTUUID.lower():
        raise ValueError("base image root PARTUUID differs from the approved Ubuntu image")

    tmp = out.with_suffix(out.suffix + ".tmp")
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / (out.name + ".work")
    if work.exists():
        raise FileExistsError(f"refusing to overwrite patch workspace: {work}")
    work.mkdir()
    extracted = work / "sunxi.original.dtb"
    copied_dtb = work / P2_DTB_NAME
    readback = work / "sunxi.readback.dtb"
    _mtool(mcopy, base, P2_START, "-m", f"::/{P2_DTB_NAME}", str(extracted))
    if extracted.stat().st_size != dtb.stat().st_size:
        raise ValueError("active p2 sunxi.dtb length differs from supplied replacement")
    original_stat = extracted.stat()
    shutil.copyfile(dtb, copied_dtb)
    os.utime(copied_dtb, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    base_clusters = _fat_file_clusters_with_tool(mshowfat, base, P2_START)

    with base.open("rb") as source, tmp.open("xb") as target:
        shutil.copyfileobj(source, target, length=CHUNK_SIZE)
        target.flush()
        os.fsync(target.fileno())
    try:
        package_blob = package.read_bytes()
        with tmp.open("r+b") as stream:
            stream.seek(PACKAGE_START)
            stream.write(package_blob)
            stream.write(b"\0" * (PACKAGE_END - PACKAGE_START - len(package_blob)))
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(PACKAGE_START)
            if stream.read(len(package_blob)) != package_blob:
                raise ValueError("boot-package readback mismatch")
            padding = stream.read(PACKAGE_END - PACKAGE_START - len(package_blob))
            if any(padding):
                raise ValueError("boot-package slot padding is not zero-filled")
        _mtool(mcopy, tmp, P2_START, "-o", "-m", str(copied_dtb), f"::/{P2_DTB_NAME}")
        _mtool(mcopy, tmp, P2_START, "-m", f"::/{P2_DTB_NAME}", str(readback))
        if readback.read_bytes() != dtb.read_bytes():
            raise ValueError("p2 /sunxi.dtb readback does not match the supplied DTB")
        if _fat_file_clusters_with_tool(mshowfat, tmp, P2_START) != base_clusters:
            raise ValueError("p2 /sunxi.dtb FAT cluster chain changed")

        candidate_report = inspect_image(tmp, expected_sha256=None)
        candidate_parts = _partition_map(candidate_report)
        if candidate_report["disk_guid"] != baseline_report["disk_guid"]:
            raise ValueError("disk GUID changed")
        for number in (1, 2, 3):
            for key in ("name", "type_guid", "partuuid", "attrs", "first_lba", "last_lba"):
                if baseline_parts[number][key] != candidate_parts[number][key]:
                    raise ValueError(f"p{number} {key} changed")

        fat_data_ranges = _cluster_ranges(tmp, P2_START)
        allowed_ranges = [(PACKAGE_START, PACKAGE_END), *fat_data_ranges]
        delta = compare_byte_changes(base, tmp, allowed_ranges)
        if not delta["changed_bytes"]:
            raise ValueError("candidate image has no changes")
        if tmp.stat().st_size != IMAGE_SIZE:
            raise ValueError("candidate image size changed")
        if sha256_file(base).upper() != expected_base_sha256.upper():
            raise ValueError("source image changed while patching")
        if out.exists():
            raise FileExistsError(f"output appeared during image patch: {out}")
        tmp.rename(out)
    except Exception:
        # Preserve the candidate and work files for diagnosis; never delete build evidence.
        raise

    report = {
        "base_image": str(base),
        "base_sha256": sha256_file(base),
        "image": str(out),
        "image_sha256": sha256_file(out),
        "image_size": out.stat().st_size,
        "package": str(package),
        "package_sha256": sha256_file(package),
        "package_slot": [PACKAGE_START, PACKAGE_END],
        "dtb": str(dtb),
        "dtb_sha256": sha256_file(dtb),
        "dtb_size": dtb.stat().st_size,
        "p2_dtb_data_ranges": [list(r) for r in fat_data_ranges],
        "verified_changed_bytes": delta["changed_bytes"],
        "first_changed_byte": delta["first_changed_byte"],
        "last_changed_byte": delta["last_changed_byte"],
        "verified_unchanged_outside_package_and_dtb_clusters": True,
        "verified_same_p2_dtb_cluster_chain": True,
        "verified_partition_layout_and_guid": True,
        "root_partuuid": str(candidate_parts[3]["partuuid"]),
    }
    report_path = out.with_suffix(out.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _fat_file_clusters_with_tool(tool: str, image: Path, p2_offset: int) -> list[int]:
    result = subprocess.run([tool, "-i", f"{image}@@{p2_offset}", f"::/{P2_DTB_NAME}"], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{tool} failed: {result.stdout}{result.stderr}")
    match = re.search(r"<([^>]+)>", result.stdout)
    if not match:
        raise ValueError(f"could not parse FAT cluster chain: {result.stdout.strip()}")
    clusters: list[int] = []
    for item in match.group(1).split(","):
        if "-" in item:
            first, last = (int(value) for value in item.split("-", 1))
            clusters.extend(range(first, last + 1))
        else:
            clusters.append(int(item))
    return clusters


def verify_uart1_image(
    base: Path,
    image: Path,
    package: Path,
    dtb: Path,
    *,
    expected_base_sha256: str = BASE_SHA256,
) -> dict[str, object]:
    base, image, package, dtb = map(Path, (base, image, package, dtb))
    base_report = inspect_image(base, expected_sha256=expected_base_sha256)
    image_report = inspect_image(image, expected_sha256=None)
    base_parts, image_parts = _partition_map(base_report), _partition_map(image_report)
    if image.stat().st_size != IMAGE_SIZE or base.stat().st_size != IMAGE_SIZE:
        raise ValueError("base or candidate image is not the expected 4 GiB size")
    if base_report["disk_guid"] != image_report["disk_guid"]:
        raise ValueError("disk GUID changed")
    for number in (1, 2, 3):
        for key in ("name", "type_guid", "partuuid", "attrs", "first_lba", "last_lba"):
            if base_parts[number][key] != image_parts[number][key]:
                raise ValueError(f"p{number} {key} changed")
    if int(base_parts[2]["first_lba"]) != P2_FIRST_LBA:
        raise ValueError("p2 start LBA differs from the A7Z layout")
    if str(image_parts[3]["partuuid"]).lower() != ROOT_PARTUUID.lower():
        raise ValueError("root PARTUUID changed")

    base_chain = _fat_file_clusters_with_tool("mshowfat", base, P2_START)
    image_chain = _fat_file_clusters_with_tool("mshowfat", image, P2_START)
    if base_chain != image_chain:
        raise ValueError("p2 /sunxi.dtb FAT cluster chain changed")
    with tempfile.TemporaryDirectory(prefix="a7z-uart1-verify-") as temp:
        readback = Path(temp) / P2_DTB_NAME
        _mtool("mcopy", image, P2_START, "-m", f"::/{P2_DTB_NAME}", str(readback))
        if readback.read_bytes() != dtb.read_bytes():
            raise ValueError("p2 /sunxi.dtb differs from the delivered DTB")

    package_blob = package.read_bytes()
    with image.open("rb") as stream:
        stream.seek(PACKAGE_START)
        if stream.read(len(package_blob)) != package_blob:
            raise ValueError("boot-package slot payload differs from delivered package")
        padding = stream.read(PACKAGE_END - PACKAGE_START - len(package_blob))
        if len(padding) != PACKAGE_END - PACKAGE_START - len(package_blob) or any(padding):
            raise ValueError("boot-package slot zero padding is invalid")
    allowed = [(PACKAGE_START, PACKAGE_END), *_cluster_ranges(image, P2_START)]
    delta = compare_byte_changes(base, image, allowed)
    return {
        "base_sha256": sha256_file(base),
        "image_sha256": sha256_file(image),
        "image_size": image.stat().st_size,
        "package_sha256": sha256_file(package),
        "package_size": package.stat().st_size,
        "package_slot": [PACKAGE_START, PACKAGE_END],
        "dtb_sha256": sha256_file(dtb),
        "dtb_size": dtb.stat().st_size,
        "p2_dtb_fat_clusters": image_chain,
        "p2_dtb_data_ranges": [list(item) for item in _cluster_ranges(image, P2_START)],
        "changed_bytes": delta["changed_bytes"],
        "first_changed_byte": delta["first_changed_byte"],
        "last_changed_byte": delta["last_changed_byte"],
        "verified_same_disk_guid_and_partition_layout": True,
        "verified_p1_p2_metadata_and_other_files_unchanged": True,
        "verified_p3_byte_identity": True,
        "verified_changes_limited_to_package_slot_and_dtb_clusters": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("package", type=Path)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--expected-base-sha256", default=BASE_SHA256)
    args = parser.parse_args()
    result = create_uart1_image(
        args.base, args.package, args.dtb, args.out,
        expected_base_sha256=args.expected_base_sha256,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
