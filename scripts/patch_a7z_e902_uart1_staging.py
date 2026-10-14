#!/usr/bin/env python3
"""Apply the A7Z E902 UART1 changes to a disposable Tina SDK staging copy."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise ValueError(f"expected one exact patch anchor in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sdk", type=Path, help="isolated Tina SDK staging root")
    sdk = parser.parse_args().sdk.resolve()
    arisc = sdk / "brandy/arisc/ar100s"
    board = sdk / "device/config/chips/a733/configs/cubie_a7z"
    if not (arisc / "arch/configs/sun60iw2p1_defconfig").is_file():
        raise SystemExit(f"not an A733 AR100S source tree: {arisc}")

    regs = arisc / "arch/riscv/plat-sun60iw2p1/inc/platform_regs.h"
    replace_once(
        regs,
        "#define R_UART_REG_BASE\t\t(0x07080000)\n",
        "#define R_UART_REG_BASE\t\t(0x07080000)\n#define R_UART1_REG_BASE\t(0x07081000)\n",
    )

    uart_i = arisc / "driver/uart/uart_i.h"
    replace_once(uart_i, "#define UART_REG_ADDR   (R_UART_REG_BASE)", "#define UART_REG_ADDR   (uart_reg_base)")

    uart_c = arisc / "driver/uart/uart.c"
    replace_once(
        uart_c,
        "static int s_uart_num;\n",
        "static int s_uart_num;\nstatic u32 uart_reg_base;\n\nextern s32 uart_puts(const char *string);\n",
    )
    replace_once(
        uart_c,
        '''\tret = fdt_get_status(fdt, arisc_uart_node);
\tif (!ret)
\t\treturn -1;

\tcount = fdt_stringlist_count(fdt, arisc_uart_node, "pins");''',
        '''\tret = fdt_get_status(fdt, arisc_uart_node);
\tif (!ret)
\t\treturn -1;

#ifdef CFG_A7Z_S_UART1
\ts_uart_num = 1;
#endif
\ts_uart_prop = fdt_getprop(fdt, arisc_uart_node, "s_uart-num", NULL);
\tif (s_uart_prop) {
\t\ts_uart_num = fdt32_to_cpu(s_uart_prop[0]);
#ifdef CFG_A7Z_S_UART1
\t\tif (s_uart_num != 1)
\t\t\treturn -EINVAL;
#endif
\t}
\tif (s_uart_num > 1)
\t\treturn -EINVAL;
\tif (s_uart_num == 1) {
\t\tuart_reg_base = R_UART1_REG_BASE;
\t\tuart_rate = 115200;
\t} else {
\t\tuart_reg_base = R_UART_REG_BASE;
\t\tuart_rate = UART_BAUDRATE;
\t}

\tcount = fdt_stringlist_count(fdt, arisc_uart_node, "pins");''',
    )
    replace_once(
        uart_c,
        '''\ts_uart_prop = fdt_getprop(fdt, arisc_uart_node, "s_uart-num", NULL);
\tif (s_uart_prop)
\t\ts_uart_num = fdt32_to_cpu(s_uart_prop[0]);

\tuart_pin_not_used = 0;''',
        '''\tuart_pin_not_used = 0;''',
    )
    replace_once(
        uart_c,
        '''\tuart_rate = UART_BAUDRATE;
#ifndef CFG_FDT_INIT_ARISC_UART_USED
\tif (!uart_pin_not_used) {
\t\tpin_set_multi_sel(PIN_GRP_PL, 2, 2);
\t\tpin_set_multi_sel(PIN_GRP_PL, 3, 2);
\t}
#else
\tif (uart_init_from_dts() < 0)
\t\tuart_pin_not_used = 1;
#endif

\tif (uart_pin_not_used)
\t\treturn -EACCES;
''',
        '''#ifndef CFG_FDT_INIT_ARISC_UART_USED
\tif (!uart_pin_not_used) {
\t\tpin_set_multi_sel(PIN_GRP_PL, 2, 2);
\t\tpin_set_multi_sel(PIN_GRP_PL, 3, 2);
\t}
#else
\tif (uart_init_from_dts() < 0)
\t\tuart_pin_not_used = 1;
#endif

\tif (uart_pin_not_used)
\t\treturn -EACCES;
\tif (s_uart_num > 1) {
\t\tuart_pin_not_used = 1;
\t\treturn -EINVAL;
\t}

\tif (s_uart_num == 1) {
\t\tuart_reg_base = R_UART1_REG_BASE;
\t\tuart_rate = 115200;
\t} else {
\t\tuart_reg_base = R_UART_REG_BASE;
\t\tuart_rate = UART_BAUDRATE;
\t}
''',
    )
    replace_once(
        uart_c,
        '''\t/* ensure uart is unlock */
\tuart_lock = 0;

\t/* uart initialize succeeded */''',
        '''\t/* ensure uart is unlock */
\tuart_lock = 0;

\tif (s_uart_num == 1)
\t\tuart_puts("E902_S_UART1_READY baud=115200\\n");

\t/* uart initialize succeeded */''',
    )
    replace_once(
        uart_c,
        '''\tuart_lock = 1;
\tuart_pin_not_used = 1;

\tpin_set_multi_sel(PIN_GRP_PL, 2, 7);
\tpin_set_multi_sel(PIN_GRP_PL, 3, 7);

\t/* set uart clock, open apb0 uart gating. */
\tccu_set_mclk_onoff(CCU_MOD_CLK_R_UART, CCU_CLK_OFF);

\t/* set reset as assert state. */
\tccu_set_mclk_reset(CCU_MOD_CLK_R_UART, CCU_CLK_RESET);
''',
        '''\tuart_lock = 1;
\tuart_pin_not_used = 1;

\tif (s_uart_num == 1) {
\t\tpin_set_multi_sel(PIN_GRP_PM, 4, 7);
\t\tpin_set_multi_sel(PIN_GRP_PM, 5, 7);
\t\tccu_set_mclk_onoff(CCU_MOD_CLK_R_UART1, CCU_CLK_OFF);
\t\tccu_set_mclk_reset(CCU_MOD_CLK_R_UART1, CCU_CLK_RESET);
\t} else {
\t\tpin_set_multi_sel(PIN_GRP_PL, 2, 7);
\t\tpin_set_multi_sel(PIN_GRP_PL, 3, 7);
\t\tccu_set_mclk_onoff(CCU_MOD_CLK_R_UART, CCU_CLK_OFF);
\t\tccu_set_mclk_reset(CCU_MOD_CLK_R_UART, CCU_CLK_RESET);
\t}
''',
    )

    mclk = arisc / "driver/prcm/prcm-sun60iw2p1/mclk.c"
    replace_once(
        mclk,
        '''\tcase CCU_MOD_CLK_R_UART:
\t\t{
\t\t\tvalue = readl(R_UART_BUS_GATE_RST_REG);
\t\t\tvalue &= (~(1 << 0));
\t\t\tvalue |= (onoff << 0);
\t\t\twritel(value, R_UART_BUS_GATE_RST_REG);
\t\t\treturn OK;
\t\t}
''',
        '''\tcase CCU_MOD_CLK_R_UART:
\t\t{
\t\t\tvalue = readl(R_UART_BUS_GATE_RST_REG);
\t\t\tvalue &= (~(1 << 0));
\t\t\tvalue |= (onoff << 0);
\t\t\twritel(value, R_UART_BUS_GATE_RST_REG);
\t\t\treturn OK;
\t\t}
\tcase CCU_MOD_CLK_R_UART1:
\t\t{
\t\t\tvalue = readl(R_UART_BUS_GATE_RST_REG);
\t\t\tvalue &= (~(1 << 1));
\t\t\tvalue |= (onoff << 1);
\t\t\twritel(value, R_UART_BUS_GATE_RST_REG);
\t\t\treturn OK;
\t\t}
''',
    )
    reset = arisc / "driver/prcm/prcm-sun60iw2p1/reset.c"
    replace_once(
        reset,
        '''\tcase CCU_MOD_CLK_R_UART:
\t\t{
\t\t\twritel(((readl(R_UART_BUS_GATE_RST_REG) & (~(1 << 16)))
\t\t\t\t\t| (reset << 16)), R_UART_BUS_GATE_RST_REG);
\t\t\treturn OK;
\t\t}
''',
        '''\tcase CCU_MOD_CLK_R_UART:
\t\t{
\t\t\twritel(((readl(R_UART_BUS_GATE_RST_REG) & (~(1 << 16)))
\t\t\t\t\t| (reset << 16)), R_UART_BUS_GATE_RST_REG);
\t\t\treturn OK;
\t\t}
\tcase CCU_MOD_CLK_R_UART1:
\t\t{
\t\t\twritel(((readl(R_UART_BUS_GATE_RST_REG) & (~(1 << 17)))
\t\t\t\t\t| (reset << 17)), R_UART_BUS_GATE_RST_REG);
\t\t\treturn OK;
\t\t}
''',
    )

    service_kconfig = arisc / "service/Kconfig"
    replace_once(
        service_kconfig,
        '''config FDT_INIT_ARISC_UART_USED
	def_bool n
	depends on FDT_USED
	prompt "init arisc uart from fdt support"
''',
        '''config FDT_INIT_ARISC_UART_USED
	def_bool n
	depends on FDT_USED
	prompt "init arisc uart from fdt support"

config A7Z_S_UART1
	bool "A7Z E902 S-UART1 direct logging"
	depends on FDT_INIT_ARISC_UART_USED
''',
    )

    config_dir = arisc / "arch/configs"
    defconfig = config_dir / "cubie_a7z_s_uart1_defconfig"
    if defconfig.exists():
        raise SystemExit(f"refusing to overwrite {defconfig}")
    shutil.copyfile(config_dir / "sun60iw2p1_defconfig", defconfig)
    with defconfig.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("CFG_FDT_INIT_ARISC_UART_USED=y\nCFG_A7Z_S_UART1=y\n")

    replace_once(
        board / "arisc.config",
        "export LICHEE_ARISC_DEFCONFIG=sun60iw2p1_defconfig\n",
        "export LICHEE_ARISC_DEFCONFIG=cubie_a7z_s_uart1_defconfig\n",
    )
    replace_once(
        board / "linux-6.6/board.dts",
        '''\t\ts_uart_config{
\t\t\tpins = "PL2", "PL3";
\t\t\tfunction = <3>, <3>;
\t\t\tstatus = "disabled";
\t\t};''',
        '''\t\ts_uart_config{
\t\t\tpins = "PM4", "PM5";
\t\t\tfunction = <5>, <5>;
\t\t\tstatus = "okay";
\t\t};''',
    )

    print(f"UART1 staging patch applied under {sdk}")


if __name__ == "__main__":
    main()

