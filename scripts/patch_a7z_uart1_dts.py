#!/usr/bin/env python3
"""Point the A7Z arisc s_uart_config at the header S-UART1 pins (PM4/PM5, func 5)."""
from __future__ import annotations

import argparse
from pathlib import Path

OLD = '''\t\ts_uart_config{
\t\t\tpins = "PL2", "PL3";
\t\t\tfunction = <3>, <3>;
\t\t\tstatus = "disabled";
\t\t};'''
NEW = '''\t\ts_uart_config{
\t\t\tpins = "PM4", "PM5";
\t\t\tfunction = <5>, <5>;
\t\t\tstatus = "okay";
\t\t};'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dts", type=Path)
    dts = ap.parse_args().dts.resolve()
    text = dts.read_text(encoding="utf-8")
    if NEW in text:
        print("already patched")
        return
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"expected exactly one s_uart_config block, found {count}")
    dts.write_text(text.replace(OLD, NEW, 1), encoding="utf-8", newline="\n")
    print(f"UART1 pins applied to {dts}")


if __name__ == "__main__":
    main()
