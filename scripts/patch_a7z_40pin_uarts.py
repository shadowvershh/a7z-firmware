#!/usr/bin/env python3
"""Expose every UART that the A7Z 40-pin header actually carries.

Pins and TX/RX direction follow the official Cubie A7Z 40-pin table
(docs.radxa.com/en/cubie/a7z/hardware-use/pin-gpio):

  uart0   TX PB9(8)  RX PB10(10)   already the boot console, left alone
  uart2   TX PB0(7)  RX PB1(11)    2-wire, so PB2/PB3 keep JTAG
  uart3   TX PJ22(5) RX PJ23(3)    2-wire
  uart4   TX PJ24(16) RX PJ25(18)  2-wire
  s_uart0 -> node uart7  TX PL6(13) RX PL7(15)   R-domain
  s_uart1 -> node uart8  TX PM4(37) RX PM5(32)   R-domain

uart1/uart5/uart6 are NOT touched: the official table does not list them on
the header, and none of their pins (PG6-PG9 / PF,PG,PH,PI,PJ16-19 / PE,PI,PK)
reach it.

The script appends `&label { ... };` overrides to the vendor board.dts, which
dtc merges (later value wins).  Labels for the R-domain UARTs are probed in
the kernel tree when --kernel is given; unknown ones are skipped rather than
breaking the dtc run.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

MARKER = "/* ==== A7Z 40-pin UARTs (generated) ==== */"

# 2-wire groups for the PIO-domain UARTs whose nodes already exist in board.dts.
# TX/RX direction per the official Cubie A7Z 40-pin table (docs.radxa.com).
PIO_UARTS = [
    ("uart2", "PB0", "PB1", "TX=脚7 RX=脚11"),
    ("uart3", "PJ22", "PJ23", "TX=脚5 RX=脚3"),
    ("uart4", "PJ24", "PJ25", "TX=脚16 RX=脚18"),
]

# R-domain UARTs.  Verified against the pinned SDK (bsp/configs/linux-6.6/
# sun60iw2p1.dtsi): the nodes are labelled uart7 (0x7080000 = R_UART0) and
# uart8 (0x7081000 = R_UART1); "s_uart0"/"s_uart1" are the *pinctrl function*
# names, not the node labels.  TX/RX per the official 40-pin table.
#   uart7: TX PL6 (脚13) RX PL7 (脚15)
#   uart8: TX PM4 (脚37) RX PM5 (脚32)   [PM3 also works as RX]
R_UARTS = [
    ("uart7", "s_uart0", "PL6", "PL7", "TX=脚13 RX=脚15"),
    ("uart8", "s_uart1", "PM4", "PM5", "TX=脚37 RX=脚32"),
]


def label_defined(kernel: Path | None, label: str) -> bool:
    if kernel is None or not kernel.is_dir():
        return False
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:", re.MULTILINE)
    for path in kernel.rglob("*"):
        if path.suffix not in (".dts", ".dtsi"):
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def pick(kernel, candidates):
    for cand in candidates:
        if label_defined(kernel, cand):
            return cand
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dts", type=Path)
    ap.add_argument("--kernel", type=Path, default=None,
                    help="kernel source tree; used to check the R-domain labels")
    ap.add_argument("--keep-jtag", action="store_true",
                    help="do not touch PB0-PB3 (JTAG stays muxed, uart2 stays off)")
    args = ap.parse_args()

    dts = args.dts.resolve()
    text = dts.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"40-pin UART mux already applied to {dts}")
        return

    out = [MARKER, "", "&pio {"]
    for idx, (name, tx, rx, _) in enumerate(PIO_UARTS):
        if args.keep_jtag and name == "uart2":
            continue
        out += [
            f"\t{name}_pins_2w: {name}_2w@{idx} {{",
            f'\t\tpins = "{tx}", "{rx}";',
            f'\t\tfunction = "{name}";',
            "\t\tdrive-strength = <10>;",
            "\t};",
        ]
    out += ["};", ""]

    emitted = ["uart0(PB9,PB10) -> 脚 8/10  保持为开机调试控制台"]
    for name, tx, rx, where in PIO_UARTS:
        if args.keep_jtag and name == "uart2":
            continue
        out += [
            f"&{name} {{",
            '\tpinctrl-names = "default";',
            f"\tpinctrl-0 = <&{name}_pins_2w>;",
            '\tstatus = "okay";',
            "};",
        ]
        emitted.append(f"{name}({tx},{rx}) -> {where}")

    # R-domain UARTs: node labels (uart7/uart8) come from the SoC dtsi, the
    # pinctrl *function* names are s_uart0/s_uart1.
    r_pins = []
    r_nodes = []
    skipped = []
    if args.keep_jtag:
        skipped.append("uart2 (PB0/PB1) 跳过：保留 JTAG")
    for node, func, tx, rx, where in R_UARTS:
        # Node labels are verified against the pinned SDK; if a future SDK
        # drops them, dtc will fail loudly instead of us silently skipping.
        if args.kernel is not None and not label_defined(args.kernel, node):
            skipped.append(f"WARNING: {node} 未在 kernel 源码中找到，仍会生成（dtc 会报错）")
        r_pins += [
            f"\t{func}_pins: {func}@0 {{",
            f'\t\tpins = "{tx}", "{rx}";',
            f'\t\tfunction = "{func}";',
            "\t\tdrive-strength = <10>;",
            "\t};",
        ]
        r_nodes += [
            f"&{node} {{",
            '\tpinctrl-names = "default";',
            f"\tpinctrl-0 = <&{func}_pins>;",
            '\tstatus = "okay";',
            "};",
        ]
        emitted.append(f"{node}/{func}({tx},{rx}) -> {where}")

    if r_pins:
        out += ["&r_pio {"] + r_pins + ["};", ""]
    out += r_nodes
    out += [
        "/* uart1(PG6-9) / uart5 / uart6 的引脚不在排针上，未启用 */",
        "",
    ]

    dts.write_text(text.rstrip("\n") + "\n\n" + "\n".join(out), encoding="utf-8", newline="\n")
    print(f"40-pin UART mux applied to {dts}")
    for line in emitted:
        print(f"  + {line}")
    for line in skipped:
        print(f"  - {line}")


if __name__ == "__main__":
    main()
