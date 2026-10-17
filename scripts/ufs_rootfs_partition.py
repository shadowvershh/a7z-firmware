#!/usr/bin/env python3
"""Print "OFFSET SIZE" (bytes) of partition 3 (rootfs) from a UFS-style image.

The UFS base image uses 4096-byte logical sectors; `losetup --partscan` does not
create partition nodes for it on CI runners, so we parse the GPT ourselves and
expose p3 with losetup -o/--sizelimit instead.
"""
import struct, sys

img, sector_size = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4096
with open(img, "rb") as f:
    f.seek(sector_size)
    hdr = f.read(512)
    if hdr[0:8] != b"EFI PART":
        sys.exit("ERROR: not a GPT image")
    part_lba = struct.unpack("<Q", hdr[72:80])[0]
    num = struct.unpack("<I", hdr[80:84])[0]
    esz = struct.unpack("<I", hdr[84:88])[0]
    f.seek(part_lba * sector_size)
    entries = f.read(num * esz)
for i in range(num):
    e = entries[i*esz:(i+1)*esz]
    if e[0:16] == bytes(16):
        continue
    first = struct.unpack("<Q", e[32:40])[0]
    last = struct.unpack("<Q", e[40:48])[0]
    if i == 2:  # partition number 3
        print(first * sector_size, (last - first + 1) * sector_size)
        break
