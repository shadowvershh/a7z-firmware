from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

try:
    from inspect_a7z_base import inspect_image
except ImportError:
    inspect_image = None


SECTORS_512 = 512
IMAGE_BYTES = 20 * 1024 * 1024
EXPECTED_ROOT_PARTUUID = "1a2b3c4d-0000-4000-8000-000000000003"
LINUX_GUID = "0fc63daf-8483-4772-8e79-3d69d8477de4"
ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


def gpt_guid(value: str) -> bytes:
    a, b, c, tail = value.split("-", 3)
    return struct.pack("<IHH", int(a, 16), int(b, 16), int(c, 16)) + bytes.fromhex(tail.replace("-", ""))


def partition(type_guid: str, partuuid: str, first: int, last: int, attrs: int, name: str) -> bytes:
    encoded_name = name.encode("utf-16le")
    return (
        gpt_guid(type_guid)
        + gpt_guid(partuuid)
        + struct.pack("<QQQ", first, last, attrs)
        + encoded_name
        + bytes(128 - 56 - len(encoded_name))
    )


def make_header(sector_size: int, my_lba: int, alt_lba: int, entries_lba: int, entries_crc: int) -> bytes:
    header = bytearray(sector_size)
    header[:8] = b"EFI PART"
    struct.pack_into("<I", header, 8, 0x00010000)
    struct.pack_into("<I", header, 12, 92)
    struct.pack_into("<Q", header, 24, my_lba)
    struct.pack_into("<Q", header, 32, alt_lba)
    struct.pack_into("<Q", header, 40, 34)
    struct.pack_into("<Q", header, 48, max(my_lba, alt_lba) - 33)
    header[56:72] = bytes(range(0x30, 0x40))
    struct.pack_into("<Q", header, 72, entries_lba)
    struct.pack_into("<I", header, 80, 128)
    struct.pack_into("<I", header, 84, 128)
    struct.pack_into("<I", header, 88, entries_crc)
    struct.pack_into("<I", header, 16, zlib.crc32(header[:92]) & 0xFFFFFFFF)
    return bytes(header)


def make_fixture(path: Path, *, sector_size: int = 512, root_partuuid: str = EXPECTED_ROOT_PARTUUID, corrupt_backup_crc: bool = False) -> None:
    size = IMAGE_BYTES
    sectors = size // sector_size
    p1s, p1e = 2048, 4095
    p2s, p2e = 4096, 8191
    p3s, p3e = 8192, sectors - 34
    entries = bytearray(128 * 128)
    rows = [
        partition(LINUX_GUID, "1a2b3c4d-0000-4000-8000-000000000001", p1s, p1e, 0, "config"),
        partition(ESP_GUID, "1a2b3c4d-0000-4000-8000-000000000002", p2s, p2e, 4, "efi"),
        partition(LINUX_GUID, root_partuuid, p3s, p3e, 4, "rootfs"),
    ]
    for index, row in enumerate(rows):
        entries[index * 128:(index + 1) * 128] = row
    entries_crc = zlib.crc32(entries) & 0xFFFFFFFF
    alt = sectors - 1
    with path.open("w+b") as stream:
        stream.truncate(size)
        mbr = bytearray(sector_size)
        mbr[446 + 4] = 0xEE
        struct.pack_into("<I", mbr, 446 + 8, 1)
        struct.pack_into("<I", mbr, 446 + 12, min(alt, 0xFFFFFFFF))
        mbr[510:512] = b"\x55\xaa"
        stream.seek(0)
        stream.write(mbr)
        stream.seek(sector_size)
        stream.write(make_header(sector_size, 1, alt, 2, entries_crc))
        stream.seek(2 * sector_size)
        stream.write(entries)
        backup_entries_lba = alt - (len(entries) + sector_size - 1) // sector_size
        stream.seek(backup_entries_lba * sector_size)
        stream.write(entries)
        backup = bytearray(make_header(sector_size, alt, 1, backup_entries_lba, entries_crc))
        if corrupt_backup_crc:
            backup[16] ^= 0x01
        stream.seek(alt * sector_size)
        stream.write(backup)
        stream.seek(256 * SECTORS_512 + 4)
        stream.write(b"eGON.BT0")
        stream.seek(24576 * SECTORS_512 + 128)
        stream.write(b"A7Z-BL31-PACKAGE-MARKER")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class InspectA7zBaseTests(unittest.TestCase):
    def require_inspector(self):
        self.assertIsNotNone(inspect_image, 'inspect_a7z_base.inspect_image must be implemented')
        return inspect_image

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.image = Path(self.temp_dir.name) / "fixture.img"
        make_fixture(self.image)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_inspects_structurally_valid_sd_image_and_boot_ranges(self) -> None:
        report = self.require_inspector()(self.image, expected_sha256=sha256_file(self.image))
        self.assertEqual(report["sector_size"], 512)
        self.assertEqual(report["image_size"], IMAGE_BYTES)
        self.assertEqual(report["p3_start_byte"], 8192 * 512)
        self.assertEqual(report["partitions"][2]["partuuid"], EXPECTED_ROOT_PARTUUID)
        self.assertEqual([part['name'] for part in report['partitions']], ['config', 'efi', 'rootfs'])
        self.assertEqual(len(report["boot_range_sha256"]), 2)

    def test_rejects_base_hash_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.require_inspector()(self.image, expected_sha256="0" * 64)

    def test_rejects_wrong_root_partuuid(self) -> None:
        make_fixture(self.image, root_partuuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        with self.assertRaisesRegex(ValueError, "PARTUUID"):
            self.require_inspector()(self.image, expected_sha256=sha256_file(self.image))

    def test_rejects_bad_backup_gpt_crc(self) -> None:
        make_fixture(self.image, corrupt_backup_crc=True)
        with self.assertRaisesRegex(ValueError, "backup GPT"):
            self.require_inspector()(self.image, expected_sha256=sha256_file(self.image))

    def test_rejects_4096_byte_sector_image(self) -> None:
        make_fixture(self.image, sector_size=4096)
        with self.assertRaisesRegex(ValueError, "512"):
            self.require_inspector()(self.image, expected_sha256=sha256_file(self.image))


if __name__ == "__main__":
    unittest.main()






