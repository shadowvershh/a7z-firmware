#!/usr/bin/env python3
"""Verify an image matches the Radxa radxa-a733 published format.

usage: verify-radxa-img.py <image> [sector_size]
Sector size is auto-detected (512 or 4096) when omitted.
"""
import struct, zlib, sys, os

def guid_str(g):
    return "%08x-%04x-%04x-%s-%s" % (
        int.from_bytes(g[0:4], 'little'), int.from_bytes(g[4:6], 'little'),
        int.from_bytes(g[6:8], 'little'), g[8:10].hex(), g[10:16].hex())

def detect_ss(f):
    for ss in (512, 4096):
        f.seek(ss); 
        if f.read(8) == b'EFI PART':
            return ss
    return None

def main(path, ss=None):
    size = os.path.getsize(path)
    f = open(path, 'rb')
    rd = lambda off, n: (f.seek(off), f.read(n))[1]

    if ss is None:
        ss = detect_ss(f)
        if ss is None:
            print("no GPT header found at LBA 1 for ss=512 or 4096")
            return 1
        print("sector size: %d (auto-detected)" % ss)
    else:
        print("sector size: %d" % ss)

    secs = size // ss
    ok = True
    print("image      : %s" % path)
    print("size       : %d bytes = %.2f GiB (%d sectors of %d)" % (size, size/2**30, secs, ss))

    mbr = rd(0, 512)
    good = mbr[510:512] == b'\x55\xaa' and mbr[446+4] == 0xEE
    ok &= good
    print("MBR        : sig=%s p1type=0x%02x %s" % (mbr[510:512].hex(), mbr[446+4],
          "OK (protective)" if good else "BAD"))

    h = rd(ss, ss)
    sig, rev, hsize, hcrc, _r, my, alt, fu, lu = struct.unpack('<8sIIIIQQQQ', h[:56])
    pe_lba, npe, pesz, pecrc = struct.unpack('<QIII', h[72:92])
    print("GPT sig    : %r" % sig)
    print("my_lba=%d alt_lba=%d first_usable=%d last_usable=%d" % (my, alt, fu, lu))

    good = (npe == 128 and pesz == 128)
    ok &= good
    print("entry array: %d x %d = %d bytes (%d sectors of %d) %s"
          % (npe, pesz, npe*pesz, (npe*pesz+ss-1)//ss, ss, "OK (standard)" if good else "NOT STANDARD"))

    full = (size % ss == 0) and (alt == secs - 1)
    if full:
        print("backup GPT : alt_lba=%d, last sector=%d OK (at end)" % (alt, secs-1))
    else:
        print("backup GPT : alt_lba=%d (image sample truncated at sector %d -> cannot check)"
              % (alt, secs-1))

    ents = rd(pe_lba*ss, npe*pesz)
    calc = zlib.crc32(ents) & 0xffffffff
    good = calc == pecrc
    ok &= good
    print("entry CRC  : stored=0x%08x calc=0x%08x %s" % (pecrc, calc, "OK" if good else "MISMATCH"))

    print("--- partitions ---")
    names = []
    for i in range(npe):
        e = ents[i*pesz:(i+1)*pesz]
        if e[:16] == b'\0'*16:
            continue
        fs, ls, attr = struct.unpack('<QQQ', e[32:56])
        nm = e[56:128].decode('utf-16-le').rstrip('\0')
        names.append(nm)
        print("  p%d first=%-8d last=%-8d %5d MiB  attr=0x%x  type=%s"
              % (i+1, fs, ls, ((ls-fs+1)*ss)//2**20, attr, guid_str(e[:16]).upper()))
    print("  names: %s" % ",".join(names))

    lba16 = rd(16*ss, 32)
    good = lba16 == b'\0'*32
    ok &= good
    print("LBA 16     : %s" % ("ALL ZERO -> Radxa layout (no Allwinner boot0 collision)"
                               if good else "NON-ZERO " + lba16.hex()))

    blob = rd(0, min(16*1024*1024, size))
    offs, i = [], 0
    while True:
        i = blob.find(b'eGON', i)
        if i < 0:
            break
        offs.append((i, i//ss)); i += 1
    print("eGON spots : %s" % (offs[:8] if offs else "none"))
    if offs:
        print("           -> first bootloader at sector %d (offset %d = %d KiB)"
              % (offs[0][1], offs[0][0], offs[0][0]//1024))
    f.close()
    print()
    print("RESULT: %s" % ("PASS - matches Radxa radxa-a733 format" if ok else "FAIL"))
    return 0 if ok else 1

if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[0], int(a[1]) if len(a) > 1 else None))
