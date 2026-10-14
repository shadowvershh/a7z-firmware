#!/usr/bin/env python3
"""Compose the pinned A7Z SD boot area with a new Ubuntu p3 root filesystem."""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from inspect_a7z_base import BASE_SHA256, EXPECTED_ROOT_PARTUUID, inspect_image, validate_pinned_candidate

SECTOR_SIZE = 512
BASE_SIZE = 2_147_483_648
OUTPUT_SIZE = 4_294_967_296
P1_FIRST, P1_LAST = 32_768, 65_535
P2_FIRST, P2_LAST = 65_536, 679_935
P3_FIRST = 679_936
BOOT_RANGES = ((256 * 512, 256 * 512 + 1_496_101), (24_576 * 512, 32_768 * 512))
CHUNK_SIZE = 8 << 20
GPT_ENTRIES = 128
GPT_ENTRY_SIZE = 128
GPT_TABLE_SIZE = GPT_ENTRIES * GPT_ENTRY_SIZE


@dataclass(frozen=True)
class ImageLayout:
    sector_size: int
    base_size: int
    p1_first: int
    p1_last: int
    p2_first: int
    p2_last: int
    p3_first: int
    root_partuuid: str
    boot_ranges: tuple[tuple[int, int], ...]


PRODUCTION_LAYOUT = ImageLayout(
    sector_size=SECTOR_SIZE,
    base_size=BASE_SIZE,
    p1_first=P1_FIRST,
    p1_last=P1_LAST,
    p2_first=P2_FIRST,
    p2_last=P2_LAST,
    p3_first=P3_FIRST,
    root_partuuid=EXPECTED_ROOT_PARTUUID,
    boot_ranges=BOOT_RANGES,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_at(stream: BinaryIO, offset: int, size: int) -> bytes:
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"truncated image data at byte {offset}")
    return data


def _write_at(stream: BinaryIO, offset: int, data: bytes) -> None:
    stream.seek(offset)
    written = stream.write(data)
    if written != len(data):
        raise OSError(f"short write at byte {offset}")


def _update_header_crc(header: bytearray) -> None:
    header_size = struct.unpack_from("<I", header, 12)[0]
    if not 92 <= header_size <= len(header):
        raise ValueError("GPT header size is invalid")
    struct.pack_into("<I", header, 16, 0)
    struct.pack_into("<I", header, 16, zlib.crc32(header[:header_size]) & 0xFFFFFFFF)


def _copy_bytes(source_fd: int, dest_fd: int, source_offset: int, dest_offset: int, length: int) -> None:
    remaining = length
    source_position = source_offset
    dest_position = dest_offset
    with os.fdopen(os.dup(source_fd), "rb") as source, os.fdopen(os.dup(dest_fd), "r+b") as destination:
        while remaining:
            source.seek(source_position)
            chunk = source.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise OSError(f"unexpected EOF while copying at byte {source_position}")
            destination.seek(dest_position)
            view = memoryview(chunk)
            while view:
                count = destination.write(view)
                if count is None or count <= 0:
                    raise OSError(f"short write while copying at byte {dest_position}")
                view = view[count:]
                dest_position += count
            source_position += len(chunk)
            remaining -= len(chunk)
        destination.flush()


def _copy_sparse_range(source_fd: int, dest_fd: int, source_offset: int, dest_offset: int, length: int) -> None:
    """Copy allocated file extents only when SEEK_DATA/SEEK_HOLE is available."""
    if length <= 0:
        return
    if os.name != "posix" or not hasattr(os, "SEEK_DATA") or not hasattr(os, "SEEK_HOLE"):
        _copy_bytes(source_fd, dest_fd, source_offset, dest_offset, length)
        return
    cursor = 0
    while cursor < length:
        try:
            data_offset = os.lseek(source_fd, source_offset + cursor, os.SEEK_DATA)
        except OSError as exc:
            if exc.errno == errno.ENXIO:
                return
            if exc.errno in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS):
                _copy_bytes(source_fd, dest_fd, source_offset + cursor, dest_offset + cursor, length - cursor)
                return
            raise
        if data_offset >= source_offset + length:
            return
        try:
            hole_offset = os.lseek(source_fd, data_offset, os.SEEK_HOLE)
        except OSError as exc:
            if exc.errno in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS):
                _copy_bytes(source_fd, dest_fd, source_offset + cursor, dest_offset + cursor, length - cursor)
                return
            raise
        end_offset = min(hole_offset, source_offset + length)
        if end_offset <= data_offset:
            raise OSError("filesystem returned a non-advancing sparse extent")
        _copy_bytes(source_fd, dest_fd, data_offset, dest_offset + data_offset - source_offset, end_offset - data_offset)
        cursor = end_offset - source_offset


def _validate_layout(report: dict[str, object], layout: ImageLayout, *, check_base_size: bool = True) -> None:
    if report["sector_size"] != layout.sector_size:
        raise ValueError("base image sector size does not match the selected SD layout")
    if check_base_size and report["image_size"] != layout.base_size:
        raise ValueError("base image size does not match the selected A7Z layout")
    partitions = report["partitions"]
    assert isinstance(partitions, list)
    by_number = {int(part["number"]): part for part in partitions}
    for number, first, last in (
        (1, layout.p1_first, layout.p1_last),
        (2, layout.p2_first, layout.p2_last),
        (3, layout.p3_first, int(by_number[3]["last_lba"])),
    ):
        part = by_number.get(number)
        if part is None or int(part["first_lba"]) != first:
            raise ValueError(f"base p{number} start LBA does not match the approved layout")
        if number != 3 and int(part["last_lba"]) != last:
            raise ValueError(f"base p{number} end LBA does not match the approved layout")
    if str(by_number[3]["partuuid"]).lower() != layout.root_partuuid.lower():
        raise ValueError("root p3 PARTUUID does not match the approved value")
    if int(report["p3_start_byte"]) != layout.p3_first * layout.sector_size:
        raise ValueError("root p3 byte start does not match the approved layout")


def _validate_ext4(path: Path, expected_size: int) -> None:
    if not path.is_file():
        raise ValueError(f"rootfs ext4 input does not exist: {path}")
    if path.stat().st_size != expected_size:
        raise ValueError(f"rootfs ext4 size must exactly match p3 capacity ({expected_size} bytes)")
    with path.open("rb") as stream:
        if _read_at(stream, 1024 + 56, 2) != b"\x53\xef":
            raise ValueError("rootfs input does not contain an ext4 superblock signature")


def _compare_ranges(left_path: Path, right_path: Path, ranges: tuple[tuple[int, int], ...]) -> None:
    with left_path.open("rb") as left, right_path.open("rb") as right:
        for start, end in ranges:
            if not (0 <= start <= end <= left_path.stat().st_size and end <= right_path.stat().st_size):
                raise ValueError("comparison range exceeds an input image")
            position = start
            while position < end:
                count = min(CHUNK_SIZE, end - position)
                if _read_at(left, position, count) != _read_at(right, position, count):
                    raise ValueError(f"source bytes changed in a protected range at byte {position}")
                position += count


def _write_gpt(stream: BinaryIO, source_header: bytes, source_entries: bytes, sector_size: int, output_size: int) -> int:
    if output_size % sector_size:
        raise ValueError("output image size must align to the sector size")
    total_sectors = output_size // sector_size
    new_alt_lba = total_sectors - 1
    new_last_usable = new_alt_lba - 33
    backup_entries_lba = new_alt_lba - GPT_TABLE_SIZE // sector_size
    entries = bytearray(source_entries)
    p3_entry_offset = 2 * GPT_ENTRY_SIZE
    p3_first = struct.unpack_from("<Q", entries, p3_entry_offset + 32)[0]
    if p3_first > new_last_usable:
        raise ValueError("output image is too small to hold the p3 start")
    struct.pack_into("<Q", entries, p3_entry_offset + 40, new_last_usable)
    entries_crc = zlib.crc32(entries) & 0xFFFFFFFF

    mbr = bytearray(_read_at(stream, 0, 512))
    if mbr[510:512] != b"\x55\xaa" or mbr[450] != 0xEE:
        raise ValueError("source protective MBR is invalid")
    struct.pack_into("<I", mbr, 458, min(new_alt_lba, 0xFFFFFFFF))
    _write_at(stream, 0, bytes(mbr))

    primary_header = bytearray(source_header)
    struct.pack_into("<Q", primary_header, 32, new_alt_lba)
    struct.pack_into("<Q", primary_header, 48, new_last_usable)
    struct.pack_into("<I", primary_header, 88, entries_crc)
    _update_header_crc(primary_header)
    _write_at(stream, sector_size, bytes(primary_header))
    _write_at(stream, 2 * sector_size, bytes(entries))

    backup_header = bytearray(primary_header)
    struct.pack_into("<Q", backup_header, 24, new_alt_lba)
    struct.pack_into("<Q", backup_header, 32, 1)
    struct.pack_into("<Q", backup_header, 48, new_last_usable)
    struct.pack_into("<Q", backup_header, 72, backup_entries_lba)
    _update_header_crc(backup_header)
    _write_at(stream, backup_entries_lba * sector_size, bytes(entries))
    _write_at(stream, new_alt_lba * sector_size, bytes(backup_header))
    return new_last_usable


def compose_image(
    base: Path,
    rootfs_ext4: Path,
    out: Path,
    *,
    output_size: int = OUTPUT_SIZE,
    expected_base_sha256: str = BASE_SHA256,
    layout: ImageLayout | None = None,
) -> dict[str, object]:
    base, rootfs_ext4, out = Path(base), Path(rootfs_ext4), Path(out)
    layout = layout or PRODUCTION_LAYOUT
    tmp = out.with_name(out.name + ".tmp")
    if out.exists() or out.is_symlink() or tmp.exists() or tmp.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing output or temporary image: {out}")
    if not base.is_file():
        raise ValueError(f"base image does not exist: {base}")
    if output_size <= base.stat().st_size or output_size % layout.sector_size:
        raise ValueError("output size must be larger than the base and sector aligned")
    if output_size // layout.sector_size > 0xFFFFFFFF:
        raise ValueError("output size exceeds the protective-MBR addressable SD size")

    base_report = inspect_image(base, expected_sha256=expected_base_sha256)
    _validate_layout(base_report, layout)
    if layout == PRODUCTION_LAYOUT:
        validate_pinned_candidate(base_report)
    p3_start_byte = layout.p3_first * layout.sector_size
    new_last_usable = output_size // layout.sector_size - 1 - 33
    p3_capacity = (new_last_usable - layout.p3_first + 1) * layout.sector_size
    _validate_ext4(rootfs_ext4, p3_capacity)
    for start, end in layout.boot_ranges:
        if start < 0 or end <= start or end > p3_start_byte:
            raise ValueError("approved boot ranges must fit before the p3 start")

    with base.open("rb") as source:
        source_header = _read_at(source, layout.sector_size, layout.sector_size)
        entries_lba = struct.unpack_from("<Q", source_header, 72)[0]
        entry_count, entry_size = struct.unpack_from("<II", source_header, 80)
        if (entry_count, entry_size) != (GPT_ENTRIES, GPT_ENTRY_SIZE):
            raise ValueError("source GPT entry geometry is not 128 x 128")
        source.seek(entries_lba * layout.sector_size)
        source_entries = source.read(GPT_TABLE_SIZE)
    if len(source_entries) != GPT_TABLE_SIZE:
        raise ValueError("source GPT entry array is truncated")

    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out.parent).free < output_size:
        raise OSError("insufficient free space for the output image")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
    try:
        os.ftruncate(fd, output_size)
        base_fd = os.open(base, os.O_RDONLY)
        root_fd = os.open(rootfs_ext4, os.O_RDONLY)
        try:
            _copy_sparse_range(base_fd, fd, 0, 0, p3_start_byte)
            _copy_sparse_range(root_fd, fd, 0, p3_start_byte, p3_capacity)
        finally:
            os.close(base_fd)
            os.close(root_fd)
        with os.fdopen(os.dup(fd), "r+b", buffering=0) as stream:
            actual_last_usable = _write_gpt(stream, source_header, source_entries, layout.sector_size, output_size)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(fd)
    except Exception:
        os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)

    try:
        output_report = inspect_image(tmp, expected_sha256=None)
        _validate_layout(output_report, layout, check_base_size=False)
        if output_report["image_size"] != output_size:
            raise ValueError("composed image size does not match requested size")
        output_parts = output_report["partitions"]
        assert isinstance(output_parts, list)
        if int(output_parts[2]["last_lba"]) != actual_last_usable:
            raise ValueError("composed p3 does not extend to the final usable GPT LBA")
        protected = list(layout.boot_ranges)
        for number in (1, 2):
            part = output_parts[number - 1]
            protected.append((int(part["first_lba"]) * layout.sector_size, (int(part["last_lba"]) + 1) * layout.sector_size))
        _compare_ranges(base, tmp, tuple(protected))
        if sha256_file(base) != base_report["sha256"]:
            raise ValueError("base image changed during composition")
        if out.exists() or out.is_symlink():
            raise FileExistsError(f"output appeared during composition; refusing publication: {out}")
        os.link(tmp, out)
        tmp.unlink()
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    return {
        "image": str(out),
        "image_size": output_size,
        "sha256": sha256_file(out),
        "root_partuuid": layout.root_partuuid,
        "p3_start_byte": p3_start_byte,
        "p3_capacity_bytes": p3_capacity,
        "p3_last_lba": actual_last_usable,
        "boot_ranges_sha256": output_report["boot_range_sha256"],
        "verified_unchanged_boot_ranges": "YES",
        "verified_unchanged_p1_p2": "YES",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--rootfs-ext4", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--expected-base-sha256", default=BASE_SHA256)
    args = parser.parse_args(argv)
    try:
        result = compose_image(args.base, args.rootfs_ext4, args.out, expected_base_sha256=args.expected_base_sha256)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
