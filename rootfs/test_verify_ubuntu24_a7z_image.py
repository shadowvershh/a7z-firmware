from __future__ import annotations

import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from uuid import UUID

from compose_a7z_ubuntu_image import ImageLayout, OUTPUT_SIZE as UNUSED_OUTPUT_SIZE, compose_image

try:
    from verify_ubuntu24_a7z_image import verify_image
except ImportError:
    verify_image = None

from test_compose_a7z_ubuntu_image import (
    BASE_SIZE,
    OUTPUT_SIZE,
    P1_FIRST,
    P1_LAST,
    P2_FIRST,
    P2_LAST,
    P3_FIRST,
    ROOT_PARTUUID,
    SECTOR,
    make_base,
    make_ext4_fixture,
    sha256_file,
)


def update_header_crc(header: bytearray) -> None:
    header_size = struct.unpack_from("<I", header, 12)[0]
    struct.pack_into("<I", header, 16, 0)
    struct.pack_into("<I", header, 16, zlib.crc32(header[:header_size]) & 0xFFFFFFFF)


def mutate_root_partuuid(path: Path) -> None:
    with path.open("r+b") as stream:
        sector_size = 512
        entries_offset = 2 * sector_size
        stream.seek(entries_offset)
        entries = bytearray(stream.read(128 * 128))
        entries[2 * 128 + 16:2 * 128 + 32] = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa").bytes_le
        entry_crc = zlib.crc32(entries) & 0xFFFFFFFF
        stream.seek(entries_offset)
        stream.write(entries)
        sector_count = path.stat().st_size // sector_size
        backup_lba = sector_count - 1 - 32
        stream.seek(backup_lba * sector_size)
        stream.write(entries)
        for lba in (1, sector_count - 1):
            stream.seek(lba * sector_size)
            header = bytearray(stream.read(sector_size))
            struct.pack_into("<I", header, 88, entry_crc)
            update_header_crc(header)
            stream.seek(lba * sector_size)
            stream.write(header)


class VerifyUbuntu24ImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base.img"
        self.rootfs = self.root / "rootfs.ext4"
        self.image = self.root / "ubuntu.img"
        self.layout = ImageLayout(
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
        make_base(self.base)
        p3_last = OUTPUT_SIZE // SECTOR - 1 - 33
        make_ext4_fixture(self.rootfs, (p3_last - P3_FIRST + 1) * SECTOR)
        compose_image(
            self.base, self.rootfs, self.image, output_size=OUTPUT_SIZE,
            expected_base_sha256=sha256_file(self.base), layout=self.layout,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def verifier(self):
        self.assertIsNotNone(verify_image, "verify_ubuntu24_a7z_image.verify_image must be implemented")
        return verify_image

    def copy_image(self, name: str) -> Path:
        path = self.root / name
        shutil.copyfile(self.image, path)
        return path

    def verify(self, image: Path):
        return self.verifier()(
            image, self.base, expected_base_sha256=sha256_file(self.base),
            expected_root_partuuid=ROOT_PARTUUID, output_size=OUTPUT_SIZE, layout=self.layout,
        )

    def test_accepts_composed_image_and_reports_partition_and_boot_evidence(self) -> None:
        report = self.verify(self.image)
        self.assertEqual(report["image_size"], OUTPUT_SIZE)
        self.assertEqual(report["root_partuuid"], ROOT_PARTUUID)
        self.assertEqual(report["verified_p1_p2_byte_identity"], "YES")
        self.assertEqual(report["verified_boot_byte_identity"], "YES")

    def test_rejects_corrupt_gpt_and_moved_backup_header(self) -> None:
        bad_crc = self.copy_image("bad-crc.img")
        with bad_crc.open("r+b") as stream:
            stream.seek(SECTOR + 16)
            byte = stream.read(1)
            stream.seek(SECTOR + 16)
            stream.write(bytes([byte[0] ^ 1]))
        with self.assertRaisesRegex(ValueError, "CRC"):
            self.verify(bad_crc)

        moved = self.copy_image("moved-backup.img")
        with moved.open("r+b") as stream:
            stream.seek(SECTOR)
            header = bytearray(stream.read(SECTOR))
            struct.pack_into("<Q", header, 32, OUTPUT_SIZE // SECTOR - 2)
            update_header_crc(header)
            stream.seek(SECTOR)
            stream.write(header)
        with self.assertRaisesRegex(ValueError, "final sector"):
            self.verify(moved)

    def test_rejects_wrong_root_partuuid(self) -> None:
        image = self.copy_image("wrong-root.img")
        mutate_root_partuuid(image)
        with self.assertRaisesRegex(ValueError, "PARTUUID"):
            self.verify(image)

    def test_rejects_boot_package_and_p1_or_p2_mutation(self) -> None:
        for name, offset in (
            ("changed-package.img", 24576 * 512 + 100),
            ("changed-p1.img", P1_FIRST * 512 + 100),
            ("changed-p2.img", P2_FIRST * 512 + 100),
        ):
            image = self.copy_image(name)
            with image.open("r+b") as stream:
                stream.seek(offset)
                byte = stream.read(1)
                stream.seek(offset)
                stream.write(bytes([byte[0] ^ 1]))
            with self.assertRaisesRegex(ValueError, "differ|changed|protected"):
                self.verify(image)

    def test_rejects_wrong_size_and_non_ext4_p3(self) -> None:
        wrong_size = self.copy_image("wrong-size.img")
        with wrong_size.open("r+b") as stream:
            stream.truncate(OUTPUT_SIZE - SECTOR)
        with self.assertRaisesRegex(ValueError, "size|GPT"):
            self.verify(wrong_size)

        bad_fs = self.copy_image("bad-ext4.img")
        with bad_fs.open("r+b") as stream:
            stream.seek(P3_FIRST * SECTOR + 1024 + 56)
            stream.write(b"\x00\x00")
        with self.assertRaisesRegex(ValueError, "ext4"):
            self.verify(bad_fs)

    def test_rejects_wrong_base_hash_before_acceptance(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.verifier()(
                self.image, self.base, expected_base_sha256="0" * 64,
                expected_root_partuuid=ROOT_PARTUUID, output_size=OUTPUT_SIZE, layout=self.layout,
            )


if __name__ == "__main__":
    unittest.main()
