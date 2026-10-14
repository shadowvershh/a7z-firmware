#!/usr/bin/env python3
"""Read-only audit of the pinned A7Z SD image and its boot-critical ranges."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from uuid import UUID

BASE_SHA256 = "977EDDFE9F9895D1DD9FFE991C0A9568BCD3B0FAB69F6B509ADE370DA6995EFF"
EXPECTED_SIZE = 2_147_483_648
EXPECTED_ROOT_PARTUUID = "1a2b3c4d-0000-4000-8000-000000000003"
LINUX_GUID = "0fc63daf-8483-4772-8e79-3d69d8477de4"
ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
EXPECTED_PARTITIONS = (
    ("config", 32_768, 65_535, "0fc63daf-8483-4772-8e79-3d69d8477de4"),
    ("efi", 65_536, 679_935, "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"),
    ("rootfs", 679_936, 4_194_270, "0fc63daf-8483-4772-8e79-3d69d8477de4"),
)
BOOT_RANGES = ((256 * 512, 256 * 512 + 1_496_101), (24_576 * 512, 32_768 * 512))
CHUNK_SIZE = 8 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_at(stream, offset: int, size: int) -> bytes:
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"truncated image at byte {offset}")
    return data


def _detect_sector_size(stream) -> int:
    for sector_size in (512, 4096):
        if _read_at(stream, sector_size, 8) == b"EFI PART":
            return sector_size
    raise ValueError("no GPT header at LBA 1 for 512- or 4096-byte sectors")


def _parse_header(raw: bytes, label: str) -> dict[str, int | bytes]:
    if len(raw) < 92 or raw[:8] != b"EFI PART":
        raise ValueError(f"{label} GPT header signature is invalid")
    revision, header_size, stored_crc, _reserved, my_lba, alt_lba, first, last = struct.unpack_from(
        "<IIIIQQQQ", raw, 8
    )
    if revision != 0x00010000 or not 92 <= header_size <= len(raw):
        raise ValueError(f"{label} GPT header revision/size is invalid")
    zeroed = bytearray(raw[:header_size])
    struct.pack_into("<I", zeroed, 16, 0)
    actual_crc = zlib.crc32(zeroed) & 0xFFFFFFFF
    if actual_crc != stored_crc:
        raise ValueError(f"{label} GPT header CRC mismatch")
    entries_lba, count, entry_size, entries_crc = struct.unpack_from("<QIII", raw, 72)
    disk_guid = bytes(raw[56:72])
    return {
        "my_lba": my_lba,
        "alt_lba": alt_lba,
        "first_usable": first,
        "last_usable": last,
        "entries_lba": entries_lba,
        "entry_count": count,
        "entry_size": entry_size,
        "entries_crc": entries_crc,
        "disk_guid": disk_guid,
    }


def _parse_partitions(entries: bytes, count: int, entry_size: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index in range(count):
        entry = entries[index * entry_size:(index + 1) * entry_size]
        if entry[:16] == bytes(16):
            continue
        if entry_size < 128:
            raise ValueError("GPT partition entry is shorter than 128 bytes")
        type_guid = str(UUID(bytes_le=entry[:16]))
        partuuid = str(UUID(bytes_le=entry[16:32]))
        first, last, attrs = struct.unpack_from("<QQQ", entry, 32)
        try:
            name = entry[56:128].decode("utf-16le").split("\0", 1)[0]
        except UnicodeDecodeError as exc:
            raise ValueError(f"partition {index + 1} name is not valid UTF-16LE") from exc
        if first > last:
            raise ValueError(f"partition {index + 1} has reversed LBA bounds")
        result.append({
            "number": index + 1,
            "name": name,
            "type_guid": type_guid,
            "partuuid": partuuid,
            "first_lba": first,
            "last_lba": last,
            "attrs": attrs,
        })
    return result


def inspect_image(path: Path, expected_sha256: str = BASE_SHA256) -> dict[str, object]:
    """Validate the GPT structure and A7Z root identity, returning auditable metadata."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"base image does not exist: {path}")
    image_size = path.stat().st_size
    if image_size % 512:
        raise ValueError("image size is not aligned to a 512-byte sector")
    digest = sha256_file(path)
    if expected_sha256 and digest.upper() != expected_sha256.upper():
        raise ValueError("base image SHA-256 mismatch")

    with path.open("rb") as stream:
        sector_size = _detect_sector_size(stream)
        if sector_size != 512:
            raise ValueError("A7Z SD image must use 512-byte sectors")
        if image_size % sector_size:
            raise ValueError("image size is not aligned to its GPT sector size")
        sectors = image_size // sector_size
        mbr = _read_at(stream, 0, 512)
        if mbr[510:512] != b"\x55\xaa" or mbr[450] != 0xEE:
            raise ValueError("protective MBR is invalid")

        primary = _parse_header(_read_at(stream, sector_size, sector_size), "primary")
        if primary["my_lba"] != 1 or primary["alt_lba"] != sectors - 1:
            raise ValueError("primary GPT does not point to the image's final sector")
        count = int(primary["entry_count"])
        entry_size = int(primary["entry_size"])
        if count != 128 or entry_size != 128:
            raise ValueError("GPT entry geometry must be 128 x 128 bytes")
        table_bytes = count * entry_size
        primary_entries = _read_at(stream, int(primary["entries_lba"]) * sector_size, table_bytes)
        if zlib.crc32(primary_entries) & 0xFFFFFFFF != primary["entries_crc"]:
            raise ValueError("primary GPT entry-array CRC mismatch")

        backup = _parse_header(_read_at(stream, (sectors - 1) * sector_size, sector_size), "backup")
        if backup["my_lba"] != sectors - 1 or backup["alt_lba"] != 1:
            raise ValueError("backup GPT is not at the final sector")
        if backup["disk_guid"] != primary["disk_guid"]:
            raise ValueError("primary and backup GPT disk GUIDs differ")
        if backup["entry_count"] != count or backup["entry_size"] != entry_size:
            raise ValueError("primary and backup GPT entry geometry differs")
        if backup["entries_crc"] != primary["entries_crc"]:
            raise ValueError("primary and backup GPT entry CRC fields differ")
        backup_entries = _read_at(stream, int(backup["entries_lba"]) * sector_size, table_bytes)
        if backup_entries != primary_entries:
            raise ValueError("primary and backup GPT entry arrays differ")
        if zlib.crc32(backup_entries) & 0xFFFFFFFF != backup["entries_crc"]:
            raise ValueError("backup GPT entry-array CRC mismatch")

        partitions = _parse_partitions(primary_entries, count, entry_size)
        if len(partitions) < 3:
            raise ValueError("expected at least three GPT partitions")
        ordered = sorted(partitions, key=lambda part: int(part["first_lba"]))
        for part in ordered:
            if int(part["first_lba"]) < int(primary["first_usable"]) or int(part["last_lba"]) > int(primary["last_usable"]):
                raise ValueError(f"partition {part['number']} is outside GPT usable bounds")
        for left, right in zip(ordered, ordered[1:]):
            if int(left["last_lba"]) >= int(right["first_lba"]):
                raise ValueError("GPT partitions overlap")
        p3 = next((part for part in partitions if part["number"] == 3), None)
        if p3 is None or p3["partuuid"].lower() != EXPECTED_ROOT_PARTUUID:
            raise ValueError("root p3 PARTUUID does not match the approved A7Z value")
        if p3["type_guid"].lower() != LINUX_GUID:
            raise ValueError("root p3 type GUID is not Linux filesystem")

        range_hashes = []
        for start, end in BOOT_RANGES:
            if not (0 <= start < end <= image_size):
                raise ValueError("A7Z boot range exceeds image bounds")
            digest_range = hashlib.sha256()
            stream.seek(start)
            remaining = end - start
            while remaining:
                chunk = stream.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError("truncated A7Z boot range")
                digest_range.update(chunk)
                remaining -= len(chunk)
            range_hashes.append(digest_range.hexdigest().upper())
        if _read_at(stream, BOOT_RANGES[0][0] + 4, 8) != b"eGON.BT0":
            raise ValueError("A7Z boot0 eGON signature is missing at LBA 256")
        if not any(_read_at(stream, BOOT_RANGES[1][0], BOOT_RANGES[1][1] - BOOT_RANGES[1][0])):
            raise ValueError("A7Z boot-package slot is empty")

        lba16 = _read_at(stream, 16 * sector_size, 32)
        if any(lba16):
            raise ValueError("Radxa-compatible LBA 16 reserved bytes are not zero")

    return {
        "path": str(path),
        "image_size": image_size,
        "sha256": digest,
        "sector_size": sector_size,
        "disk_guid": str(UUID(bytes_le=bytes(primary["disk_guid"]))),
        "partitions": partitions,
        "p3_start_byte": int(p3["first_lba"]) * sector_size,
        "boot_ranges": [{"start": start, "end": end} for start, end in BOOT_RANGES],
        "boot_range_sha256": range_hashes,
    }


def validate_pinned_candidate(report: dict[str, object]) -> None:
    if report["image_size"] != EXPECTED_SIZE:
        raise ValueError("pinned A7Z candidate must be exactly 2 GiB")
    partitions = report["partitions"]
    assert isinstance(partitions, list)
    if len(partitions) != 3:
        raise ValueError("pinned A7Z candidate must contain exactly three partitions")
    actual = tuple(
        (str(part["name"]), int(part["first_lba"]), int(part["last_lba"]), str(part["type_guid"]))
        for part in partitions
    )
    if actual != EXPECTED_PARTITIONS:
        raise ValueError(f"pinned candidate partition geometry differs: {actual!r}")
    if report["sha256"] != BASE_SHA256:
        raise ValueError("pinned candidate SHA-256 changed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path, help="write the audit report here")
    args = parser.parse_args(argv)
    try:
        report = inspect_image(args.image)
        validate_pinned_candidate(report)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

