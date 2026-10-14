from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

try:
    from compose_a7z_ubuntu_image import ImageLayout, compose_image
except ImportError:
    ImageLayout = None
    compose_image = None


SECTOR = 512
BASE_SIZE = 24 * 1024 * 1024
OUTPUT_SIZE = 40 * 1024 * 1024
P1_FIRST, P1_LAST = 32768, 34815
P2_FIRST, P2_LAST = 34816, 36863
P3_FIRST = 36864
ROOT_PARTUUID = "1a2b3c4d-0000-4000-8000-000000000003"
LINUX_GUID = "0fc63daf-8483-4772-8e79-3d69d8477de4"
ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


def gpt_guid(value: str) -> bytes:
    a, b, c, tail = value.split("-", 3)
    return struct.pack("<IHH", int(a, 16), int(b, 16), int(c, 16)) + bytes.fromhex(tail.replace("-", ""))


def make_entry(type_guid: str, partuuid: str, first: int, last: int, attrs: int, name: str) -> bytes:
    encoded = name.encode("utf-16le")
    return gpt_guid(type_guid) + gpt_guid(partuuid) + struct.pack("<QQQ", first, last, attrs) + encoded + bytes(128 - 56 - len(encoded))


def make_header(ss: int, my_lba: int, alt_lba: int, entry_lba: int, entry_crc: int) -> bytes:
    header = bytearray(ss)
    header[:8] = b"EFI PART"
    struct.pack_into("<I", header, 8, 0x10000)
    struct.pack_into("<I", header, 12, 92)
    struct.pack_into("<Q", header, 24, my_lba)
    struct.pack_into("<Q", header, 32, alt_lba)
    struct.pack_into("<Q", header, 40, 34)
    struct.pack_into("<Q", header, 48, max(my_lba, alt_lba) - 33)
    header[56:72] = bytes(range(0x30, 0x40))
    struct.pack_into("<Q", header, 72, entry_lba)
    struct.pack_into("<I", header, 80, 128)
    struct.pack_into("<I", header, 84, 128)
    struct.pack_into("<I", header, 88, entry_crc)
    struct.pack_into("<I", header, 16, zlib.crc32(header[:92]) & 0xFFFFFFFF)
    return bytes(header)


def make_base(path: Path, *, sector_size: int = 512, root_partuuid: str = ROOT_PARTUUID, corrupt_gpt: bool = False) -> None:
    sectors = BASE_SIZE // sector_size
    if sector_size == 512:
        p1s, p1e = P1_FIRST, P1_LAST
        p2s, p2e = P2_FIRST, P2_LAST
        p3s = P3_FIRST
    else:
        p1s, p1e = 4096, 4351
        p2s, p2e = 4352, 4607
        p3s = 4608
    p3e = sectors - 34
    entries = bytearray(128 * 128)
    for index, row in enumerate((
        make_entry(LINUX_GUID, "1a2b3c4d-0000-4000-8000-000000000001", p1s, p1e, 0, "config"),
        make_entry(ESP_GUID, "1a2b3c4d-0000-4000-8000-000000000002", p2s, p2e, 4, "efi"),
        make_entry(LINUX_GUID, root_partuuid, p3s, p3e, 4, "rootfs"),
    )):
        entries[index * 128:(index + 1) * 128] = row
    entry_crc = zlib.crc32(entries) & 0xFFFFFFFF
    alt = sectors - 1
    with path.open("w+b") as stream:
        stream.truncate(BASE_SIZE)
        mbr = bytearray(sector_size)
        mbr[450] = 0xEE
        struct.pack_into("<I", mbr, 454, 1)
        struct.pack_into("<I", mbr, 458, min(alt, 0xFFFFFFFF))
        mbr[510:512] = b"\x55\xaa"
        stream.seek(0)
        stream.write(mbr)
        stream.seek(sector_size)
        primary = bytearray(make_header(sector_size, 1, alt, 2, entry_crc))
        if corrupt_gpt:
            primary[16] ^= 0x01
        stream.write(primary)
        stream.seek(2 * sector_size)
        stream.write(entries)
        backup_lba = alt - 32
        stream.seek(backup_lba * sector_size)
        stream.write(entries)
        stream.seek(alt * sector_size)
        stream.write(make_header(sector_size, alt, 1, backup_lba, entry_crc))
        stream.seek(256 * 512 + 4)
        stream.write(b"eGON.BT0")
        stream.seek(24576 * 512 + 123)
        stream.write(b"A7Z-PACKAGE-SLOT")
        stream.seek(p1s * sector_size + 1024)
        stream.write(b"P1-preserve-me")
        stream.seek(p2s * sector_size + 2048)
        stream.write(b"P2-preserve-me")


def make_ext4_fixture(path: Path, size: int) -> None:
    with path.open("w+b") as stream:
        stream.truncate(size)
        stream.seek(1024 + 56)
        stream.write(b"\x53\xef")
        stream.seek(1024 * 1024)
        stream.write(b"rootfs-payload")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class ComposeA7zImageTests(unittest.TestCase):
    def require_composer(self):
        self.assertIsNotNone(compose_image, "compose_a7z_ubuntu_image.compose_image must be implemented")
        self.assertIsNotNone(ImageLayout, "compose_a7z_ubuntu_image.ImageLayout must be implemented")
        return compose_image

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base.img"
        self.rootfs = self.root / "rootfs.ext4"
        self.output = self.root / "ubuntu.img"
        make_base(self.base)
        p3_last = OUTPUT_SIZE // SECTOR - 1 - 33
        rootfs_size = (p3_last - P3_FIRST + 1) * SECTOR
        make_ext4_fixture(self.rootfs, rootfs_size)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def layout(self):
        composer = self.require_composer()
        del composer
        return ImageLayout(
            sector_size=SECTOR,
            base_size=BASE_SIZE,
            p1_first=P1_FIRST,
            p1_last=P1_LAST,
            p2_first=P2_FIRST,
            p2_last=P2_LAST,
            p3_first=P3_FIRST,
            root_partuuid=ROOT_PARTUUID,
            boot_ranges=((256 * 512, 256 * 512 + 1_496_101), (24576 * 512, 32768 * 512)),
        )

    def test_composes_gpt_and_rootfs_while_preserving_boot_and_p1_p2(self) -> None:
        before = sha256_file(self.base)
        result = self.require_composer()(
            self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
            expected_base_sha256=before, layout=self.layout(),
        )
        self.assertEqual(result["image_size"], OUTPUT_SIZE)
        self.assertEqual(result["root_partuuid"], ROOT_PARTUUID)
        self.assertEqual(result["verified_unchanged_boot_ranges"], "YES")
        self.assertEqual(sha256_file(self.base), before)
        with self.base.open("rb") as original, self.output.open("rb") as output:
            for first, last in ((P1_FIRST, P1_LAST), (P2_FIRST, P2_LAST)):
                offset, length = first * SECTOR, (last - first + 1) * SECTOR
                original.seek(offset)
                output.seek(offset)
                self.assertEqual(original.read(length), output.read(length))
            output.seek(P3_FIRST * SECTOR + 1024 + 56)
            self.assertEqual(output.read(2), b"\x53\xef")
        self.assertFalse(Path(str(self.output) + ".tmp").exists())

    def test_rejects_wrong_base_sha_without_publishing(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.require_composer()(
                self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
                expected_base_sha256="0" * 64, layout=self.layout(),
            )
        self.assertFalse(self.output.exists())
        self.assertFalse(Path(str(self.output) + ".tmp").exists())

    def test_rejects_wrong_root_partuuid(self) -> None:
        make_base(self.base, root_partuuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        with self.assertRaisesRegex(ValueError, "PARTUUID"):
            self.require_composer()(
                self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
                expected_base_sha256=sha256_file(self.base), layout=self.layout(),
            )
        self.assertFalse(self.output.exists())

    def test_rejects_corrupt_gpt_and_4096_sector_source(self) -> None:
        make_base(self.base, corrupt_gpt=True)
        with self.assertRaisesRegex(ValueError, "CRC"):
            self.require_composer()(
                self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
                expected_base_sha256=sha256_file(self.base), layout=self.layout(),
            )
        make_base(self.base, sector_size=4096)
        with self.assertRaisesRegex(ValueError, "512"):
            self.require_composer()(
                self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
                expected_base_sha256=sha256_file(self.base), layout=self.layout(),
            )
        self.assertFalse(self.output.exists())

    def test_rejects_wrong_ext4_or_wrong_p3_capacity(self) -> None:
        self.rootfs.write_bytes(b"not ext4")
        with self.assertRaisesRegex(ValueError, "ext4"):
            self.require_composer()(
                self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
                expected_base_sha256=sha256_file(self.base), layout=self.layout(),
            )
        make_ext4_fixture(self.rootfs, 512)
        with self.assertRaisesRegex(ValueError, "p3 capacity"):
            self.require_composer()(
                self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
                expected_base_sha256=sha256_file(self.base), layout=self.layout(),
            )
        self.assertFalse(self.output.exists())

    def test_refuses_existing_output_and_cleans_temporary_on_write_failure(self) -> None:
        self.output.write_bytes(b"keep")
        with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
            self.require_composer()(
                self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
                expected_base_sha256=sha256_file(self.base), layout=self.layout(),
            )
        self.assertEqual(self.output.read_bytes(), b"keep")
        self.output.unlink()
        with patch("compose_a7z_ubuntu_image._copy_sparse_range", side_effect=OSError("injected write error")):
            with self.assertRaisesRegex(OSError, "injected write error"):
                self.require_composer()(
                    self.base, self.rootfs, self.output, output_size=OUTPUT_SIZE,
                    expected_base_sha256=sha256_file(self.base), layout=self.layout(),
                )
        self.assertFalse(self.output.exists())
        self.assertFalse(Path(str(self.output) + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
