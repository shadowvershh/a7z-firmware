#!/usr/bin/env python3
"""Generate docs/40pin-mux.md from a pinctrl dump captured on the board.

Produces, for every one of the 28 GPIO balls on the Cubie A7Z 40-pin header,
the list of SoC functions that pin can be muxed to, plus a peripheral summary.

Capture the dump on the board first (root):

    for f in /sys/kernel/debug/pinctrl/*/pinmux-functions; do
        echo "### FILE $f"; cat "$f"; done > pinctrl-dump.txt

then:  python3 scripts/gen_40pin_doc.py --dump docs/pinctrl-dump-a7z.txt
"""
from __future__ import annotations

import argparse
import re
from collections import OrderedDict, defaultdict

DUMP = "pinctrl_dump.txt"
OUT = "40pin-mux.md"

HEADER = {
    3: "PJ23", 5: "PJ22", 7: "PB0", 8: "PB9", 10: "PB10", 11: "PB1",
    12: "PB5", 13: "PL6", 15: "PL7", 16: "PJ24", 18: "PJ25", 19: "PD12",
    21: "PD13", 22: "PL5", 23: "PD11", 24: "PD10", 26: "PD14", 27: "PD17",
    28: "PD16", 29: "PB2", 31: "PB3", 32: "PM5", 33: "PM3", 35: "PB6",
    36: "PB4", 37: "PM4", 38: "PB8", 40: "PB7",
}
POWER = {1: "3.3V", 2: "5V", 4: "5V", 17: "3.3V"}
GND = {6, 9, 14, 20, 25, 30, 34, 39}
BALL2PIN = {b: p for p, b in HEADER.items()}
HEADER_BALLS = set(HEADER.values())

# serial alias -> (controller address, pinctrl function name). From the live DT:
# /proc/device-tree/aliases/serial0..serial8
UART_ALIASES = [
    ("serial0", "0x2500000", "uart0"),
    ("serial1", "0x2501000", "uart1"),
    ("serial2", "0x2502000", "uart2"),
    ("serial3", "0x2503000", "uart3"),
    ("serial4", "0x2504000", "uart4"),
    ("serial5", "0x2505000", "uart5"),
    ("serial6", "0x2506000", "uart6"),
    ("serial7", "0x7080000", "s_uart0"),
    ("serial8", "0x7081000", "s_uart1"),
]

FUNC_RE = re.compile(r"^function \d+: (\S+), groups = \[ (.*?) \]$")
BORING = {"gpio_in", "gpio_out", "irq", "io_disabled", "test", "trace", "clk", "pll"}

# a bus needs at least this many header pins to be usable
NEEDS = {"uart": 2, "s_uart": 2, "twi": 2, "s_twi": 2, "spi": 4, "s_spi": 4,
         "pwm": 1, "s_pwm": 1, "i2s": 0, "ir": 1, "s_ir": 1}


def parse(path):
    funcs = OrderedDict()
    section = ""
    for raw in open(path, encoding="utf-8", errors="replace"):
        line = raw.rstrip("\n")
        if line.startswith("### FILE"):
            section = "func" if "pinmux-functions" in line else "other"
            continue
        if section == "func":
            m = FUNC_RE.match(line.strip())
            if m:
                funcs.setdefault(m.group(1), []).extend(m.group(2).split())
    return funcs


def kind(name):
    for p in ("uart", "s_uart", "twi", "s_twi", "spi", "s_spi", "pwm", "s_pwm",
              "i2s", "sdc", "csi", "dsi", "lcd", "lvds", "hdmi", "rgmii",
              "ir", "s_ir", "dmic", "owa", "ledc", "jtag", "s_jtag"):
        if name.startswith(p):
            return p
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=DUMP, help="pinctrl dump captured on the board")
    ap.add_argument("--out", default=OUT, help="markdown file to write")
    args = ap.parse_args()
    funcs = parse(args.dump)
    per_ball = defaultdict(list)
    for name, groups in funcs.items():
        if name in BORING:
            continue
        for g in set(groups):
            if g in HEADER_BALLS:
                per_ball[g].append(name)

    lines = []
    add = lines.append
    add("# Cubie A7Z 40-pin 排针功能复用表")
    add("")
    add("由板子实机 `debugfs` 的 `pinmux-functions`（PIO + R_PIO 全量功能表）与官方排针")
    add("pinout 交叉生成，共 28 个 GPIO 脚。改 DTS 前先查这张表。")
    add("")
    add("> 生成方式：`python3 scripts/gen_40pin_doc.py --dump docs/pinctrl-dump-a7z.txt`")
    add("")
    add("## 1. 引脚一览（脚号 → SoC 点位 → 可用功能）")
    add("")
    add("| 排针 | SoC | 可用复用功能 |")
    add("| ---: | --- | --- |")
    for pin in sorted(HEADER):
        ball = HEADER[pin]
        fns = sorted(set(per_ball.get(ball, [])))
        add(f"| {pin} | {ball} | {' / '.join(fns) if fns else '（仅 GPIO）'} |")
    for pin in sorted(POWER):
        add(f"| {pin} | — | 电源 {POWER[pin]} |")
    for pin in sorted(GND):
        add(f"| {pin} | — | GND |")

    add("")
    add("## 2. 能完整引到排针的外设")
    add("")
    full, partial, none_ = [], [], []
    for name, groups in funcs.items():
        if name in BORING or kind(name) in ("other", "i2s"):
            continue
        hit = sorted({g for g in groups if g in HEADER_BALLS}, key=lambda b: BALL2PIN[b])
        need = NEEDS.get(kind(name), 99)
        if hit and len(hit) >= need:
            full.append((name, hit))
        elif hit:
            partial.append((name, hit))
        else:
            none_.append(name)

    add("| 外设 | 排针脚位 |")
    add("| --- | --- |")
    for name, hit in full:
        add(f"| `{name}` | {', '.join(f'{b}(脚{BALL2PIN[b]})' for b in hit)} |")

    add("")
    add("## 3. 只有部分信号在排针上（组不成完整总线）")
    add("")
    add("| 外设 | 排针上的信号 |")
    add("| --- | --- |")
    for name, hit in partial:
        add(f"| `{name}` | {', '.join(f'{b}(脚{BALL2PIN[b]})' for b in hit)} |")

    add("")
    add("## 4. 完全到不了排针的外设")
    add("")
    add("> **`uart1` 名字有歧义，别搞混**：下表里的 `uart1` 指 **PIO 域** `uart@2501000`")
    add("> （内核 `ttyAS1`，PG6–PG9，调试串口）。排针上的 \"UART1\" 是 **R 域 S-UART1**")
    add("> `uart@7081000`（即 `s_uart1`，PM3/PM4/PM5 = 脚 33/37/32），见第 2 节。")
    add("> 两者是**不同的硬件单元**，只有后者引到了排针。")
    add("")
    add("`" + "`, `".join(sorted(none_)) + "`")
    add("")
    add("这些只引到了板载器件或专用接口（SD/eMMC/NAND/SPI-Flash/PCIe/CSI/DSI/GMAC/")
    add("调试串口 UART1 等），从 40pin 拿不到。")
    add("")
    add("## 5. 复用时必须注意的冲突")
    add("")
    add("- **PB 组共享**：PB0/PB1/PB9/PB10 同时是 `uart0`、`uart2`、`twi0`、`twi8`、")
    add("  `spi2` 的候选脚，一次只能选一组用途。")
    add("- **PD10–PD14 / PD16 / PD17 兼作显示**：`lcd0`、`lvds1`、`dsi1`、`eink` 也走这 7 个")
    add("  脚，接屏就全部占用。")
    add("- **脚 32/37（PM5/PM4）**：`s_uart1` 在 `SCP_MODE=uart1` 构建里被 RISC-V E902 的")
    add("  SCP 日志占用（硬件层 mux，Linux 的 pinctrl 看不见，显示为 UNCLAIMED）；")
    add("  `no-riscv-core` 分支关核后才变回普通 GPIO。脚 33（PM3）同为 `s_uart1` 候选，未被占用。")
    add("- **I2S0 全套在排针上**：PB4/PB5/PB6/PB7/PB8 = 脚 36/12/35/40/38")
    add("  （MCLK/BCLK/LRCK/DOUT0/DIN0）。")
    add("")
    add("## 6. UART 对照表（哪个 UART 在排针上）")
    add("")
    add("`serialN` 别名取自实机 `/proc/device-tree/aliases/serial*`。**`uart1` 与 `s_uart1`")
    add("是两个不同控制器**，只有 `s_*` 后缀那个在排针上。")
    add("")
    add("| 别名 | 控制器 | pinctrl 名 | 排针可用脚 |")
    add("| --- | --- | --- | --- |")
    for alias, addr, fname in UART_ALIASES:
        hit = sorted({g for g in funcs.get(fname, []) if g in HEADER_BALLS},
                     key=lambda b: BALL2PIN[b])
        pins = ", ".join(f"{b}(脚{BALL2PIN[b]})" for b in hit) or "❌ 无"
        add(f"| `{alias}` | `{addr}` | `{fname}` | {pins} |")

    add("")
    add("## 7. 结论")
    add("")
    add("**不是所有外设都能塞进 40pin，但常用的都能。** 单看\"能不能引出来\"：UART、I2C、")
    add("SPI、PWM、I2S0 都在排针上有完整脚位；SD/eMMC/NAND/PCIe/CSI/MIPI/GMAC 以及 PIO 域的")
    add("调试串口 `uart1`（PG6–9）没有引出 —— 但**排针上有 UART：R 域的 `s_uart1`（脚")
    add("32/33/37）和 `s_uart0`（脚 13/15/32/33/37）**，见第 6 节。真正限制来自**脚位重叠**：")
    add("28 个脚里 PB 组被 5 个外设共用、PD 组被显示总线共用，实际可同时使用约")
    add("1×UART + 1×I2C + 1×SPI + 1×PWM + 1×I2S（约 15–18 脚）。")
    add("")

    open(args.out, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    print(f"wrote {args.out}: {len(lines)} lines")


if __name__ == "__main__":
    main()
