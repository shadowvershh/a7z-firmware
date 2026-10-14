#!/usr/bin/env python3
"""Verify the static A7Z Ubuntu SD image and its allowed byte-level deltas."""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import BinaryIO

from compose_a7z_ubuntu_image import (
    BASE_SIZE,
    BOOT_RANGES,
    CHUNK_SIZE,
    EXPECTED_ROOT_PARTUUID,
    ImageLayout,
    OUTPUT_SIZE,
    PRODUCTION_LAYOUT,
    _read_at,
    sha256_file,
)
from inspect_a7z_base import inspect_image, validate_pinned_candidate

GPT_TABLE_SIZE = 128 * 128


def _partition_map(report: dict[str, object]) -> dict[int, dict[str, object]]:
    partitions = report["partitions"]
    assert isinstance(partitions, list)
    return {int(item["number"]): item for item in partitions}


def _compare_range(left: BinaryIO, right: BinaryIO, start: int, end: int) -> None:
    position = start
    while position < end:
        count = min(CHUNK_SIZE, end - position)
        if _read_at(left, position, count) != _read_at(right, position, count):
            raise ValueError(f"source and output differ in protected prefix at byte {position}")
        position += count


def _compare_prefix_ignoring_metadata(base: Path, image: Path, prefix_end: int, sector_size: int) -> None:
    excluded = sorted((
        (458, 462),
        (sector_size, 2 * sector_size),
        (2 * sector_size, 2 * sector_size + GPT_TABLE_SIZE),
    ))
    with base.open("rb") as left, image.open("rb") as right:
        position = 0
        for start, end in excluded:
            if position < start:
                _compare_range(left, right, position, min(start, prefix_end))
            position = max(position, end)
            if position >= prefix_end:
                break
        if position < prefix_end:
            _compare_range(left, right, position, prefix_end)


def _check_ext4_signature(image: Path, p3_start_byte: int) -> None:
    with image.open("rb") as stream:
        magic = _read_at(stream, p3_start_byte + 1024 + 56, 2)
    if magic != b"\x53\xef":
        raise ValueError("p3 does not contain an ext4 superblock signature")


def verify_image(
    image: Path,
    base: Path,
    *,
    expected_base_sha256: str = "977EDDFE9F9895D1DD9FFE991C0A9568BCD3B0FAB69F6B509ADE370DA6995EFF",
    expected_root_partuuid: str = EXPECTED_ROOT_PARTUUID,
    output_size: int = OUTPUT_SIZE,
    layout: ImageLayout | None = None,
) -> dict[str, object]:
    image, base = Path(image), Path(base)
    layout = layout or PRODUCTION_LAYOUT
    if expected_root_partuuid.lower() != layout.root_partuuid.lower():
        raise ValueError("requested root PARTUUID conflicts with the approved A7Z layout")
    if image.stat().st_size != output_size:
        raise ValueError(f"image size mismatch: expected {output_size} bytes")
    base_report = inspect_image(base, expected_sha256=expected_base_sha256)
    if layout == PRODUCTION_LAYOUT:
        validate_pinned_candidate(base_report)
    image_report = inspect_image(image, expected_sha256=None)
    if image_report["image_size"] != output_size:
        raise ValueError("output image size does not match the requested size")
    if image_report["sector_size"] != layout.sector_size:
        raise ValueError("output sector size does not match the SD layout")
    if image_report["disk_guid"] != base_report["disk_guid"]:
        raise ValueError("disk GUID changed from the approved source image")

    base_parts = _partition_map(base_report)
    image_parts = _partition_map(image_report)
    for number in (1, 2, 3):
        original = base_parts[number]
        produced = image_parts[number]
        for key in ("name", "type_guid", "partuuid", "attrs", "first_lba"):
            if original[key] != produced[key]:
                raise ValueError(f"p{number} {key} changed from the approved source image")
        if number in (1, 2) and original["last_lba"] != produced["last_lba"]:
            raise ValueError(f"p{number} partition end changed")
    if str(image_parts[3]["partuuid"]).lower() != expected_root_partuuid.lower():
        raise ValueError("output root p3 PARTUUID is incorrect")

    new_last_usable = output_size // layout.sector_size - 1 - 33
    if int(image_parts[3]["last_lba"]) != new_last_usable:
        raise ValueError("p3 does not extend to the final usable GPT LBA")
    p3_start_byte = int(image_parts[3]["first_lba"]) * layout.sector_size
    p3_capacity = (new_last_usable - int(image_parts[3]["first_lba"]) + 1) * layout.sector_size
    if p3_start_byte != int(base_report["p3_start_byte"]):
        raise ValueError("p3 start byte changed")
    _check_ext4_signature(image, p3_start_byte)

    protected_ranges = tuple(layout.boot_ranges) + tuple(
        (int(image_parts[number]["first_lba"]) * layout.sector_size,
         (int(image_parts[number]["last_lba"]) + 1) * layout.sector_size)
        for number in (1, 2)
    )
    for start, end in protected_ranges:
        if not (0 <= start < end <= p3_start_byte):
            raise ValueError("protected boot/p1/p2 range is invalid")
    _compare_prefix_ignoring_metadata(base, image, p3_start_byte, layout.sector_size)

    return {
        "image": str(image),
        "base": str(base),
        "image_size": output_size,
        "image_sha256": sha256_file(image),
        "base_sha256": base_report["sha256"],
        "sector_size": layout.sector_size,
        "root_partuuid": str(image_parts[3]["partuuid"]),
        "p3_start_byte": p3_start_byte,
        "p3_capacity_bytes": p3_capacity,
        "p3_last_lba": new_last_usable,
        "verified_p1_p2_byte_identity": "YES",
        "verified_boot_byte_identity": "YES",
        "verified_radxa_gpt": "YES",
        "ext4_signature": "YES",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--expected-root-partuuid", default=EXPECTED_ROOT_PARTUUID)
    parser.add_argument("--expected-base-sha256", default="977EDDFE9F9895D1DD9FFE991C0A9568BCD3B0FAB69F6B509ADE370DA6995EFF")
    args = parser.parse_args(argv)
    try:
        result = verify_image(
            args.image,
            args.base,
            expected_base_sha256=args.expected_base_sha256,
            expected_root_partuuid=args.expected_root_partuuid,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
