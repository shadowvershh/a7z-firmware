#!/usr/bin/env python3
"""Make the A7Z USB-C connector a host port (try-power-role = "source").

The stock board.dts marks the USB-C connector ``try-power-role = "sink"``.
TCPM then advertises Rd (device role) on CC and therefore never detects a sink
such as a USB-C hub, so the C port stays dead even though the ET7304 TCPC is
present.  This board is used as a host, so flip the preference to "source"
before the DTB is compiled.
"""
from __future__ import annotations

import argparse
from pathlib import Path

OLD = 'try-power-role = "sink";'
NEW = 'try-power-role = "source";'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dts", type=Path)
    dts = ap.parse_args().dts.resolve()
    text = dts.read_text(encoding="utf-8")
    if OLD not in text:
        if NEW in text:
            print("already patched")
            return
        raise SystemExit('no try-power-role = "sink" node found')
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"expected exactly one try-power-role node, found {count}")
    dts.write_text(text.replace(OLD, NEW, 1), encoding="utf-8", newline="\n")
    print(f"USB-C try-power-role -> source in {dts}")


if __name__ == "__main__":
    main()