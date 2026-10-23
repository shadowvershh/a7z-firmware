# Cubie A7Z 40-pin 排针功能复用表

由板子实机 `debugfs` 的 `pinmux-functions`（PIO + R_PIO 全量功能表）与官方排针
pinout 交叉生成，共 28 个 GPIO 脚。改 DTS 前先查这张表。

> 生成方式：`python3 scripts/gen_40pin_doc.py --dump docs/pinctrl-dump-a7z.txt`

## 1. 引脚一览（脚号 → SoC 点位 → 可用功能）

| 排针 | SoC | 可用复用功能 |
| ---: | --- | --- |
| 3 | PJ23 | lcd0 / lcd1 / pwm1_5 / twi11 / twi3 / twi7 / uart2 / uart3 |
| 5 | PJ22 | lcd0 / lcd1 / pwm1_4 / twi11 / twi3 / twi7 / uart2 / uart3 |
| 7 | PB0 | dsi / jtag / lcd0 / spi2 / uart0 / uart2 |
| 8 | PB9 | i2s0_din2 / i2s0_dout2 / lcd0 / pwm1_1 / twi0 / twi8 / uart0 / watchdog |
| 10 | PB10 | i2s0_din3 / i2s0_dout3 / lcd0 / pwm1_2 / twi0 / twi8 / uart0 |
| 11 | PB1 | jtag / lcd0 / spi2 / uart0 / uart2 |
| 12 | PB5 | i2s0_bclk / lcd0 / pwm0_1 / spi2 / twi1 |
| 13 | PL6 | s_ir_rx / s_jtag_do / s_pwm0_4 / s_spi0 / s_uart0 |
| 15 | PL7 | s_jtag_di / s_pwm0_5 / s_spi0 / s_uart0 |
| 16 | PJ24 | lcd1 / pwm1_6 / spi3 / twi4 / uart4 |
| 18 | PJ25 | lcd1 / pwm1_7 / spi3 / twi4 / uart4 |
| 19 | PD12 | dsi1 / eink / lcd0 / lvds1 / pwm1_2 / spi1 |
| 21 | PD13 | dsi1 / eink / lcd0 / lvds1 / pwm1_3 / spi1 |
| 22 | PL5 | s_jtag_ck / s_pwm0_3 / s_spi0 / s_twi2 |
| 23 | PD11 | dsi1 / eink / lcd0 / lvds1 / pwm1_1 / spi1 |
| 24 | PD10 | dsi1 / eink / lcd0 / lvds1 / pwm1_0 / spi1 |
| 26 | PD14 | dsi1 / eink / lcd0 / lvds1 / spi1 / uart3 |
| 27 | PD17 | dsi1 / eink / lcd0 / lvds1 / twi2 / uart3 |
| 28 | PD16 | dsi1 / eink / lcd0 / lvds1 / twi2 / uart3 |
| 29 | PB2 | hdmi / jtag / lcd0 / spi2 / twi0 / uart2 |
| 31 | PB3 | hdmi / jtag / lcd0 / spi2 / twi0 / uart2 |
| 32 | PM5 | s_ir_rx / s_pwm0_1 / s_twi1 / s_twi2 / s_uart0 / s_uart1 |
| 33 | PM3 | s_jtag_di / s_pwm0_5 / s_spi0 / s_uart0 / s_uart1 |
| 35 | PB6 | i2s0_lrck / pwm0_2 / pwm0_8 / spi2 |
| 36 | PB4 | hdmi / i2s0_mclk / lcd0 / pwm0_0 / spi2 / twi1 |
| 37 | PM4 | s_ir_rx / s_pwm0_0 / s_twi1 / s_twi2 / s_uart0 / s_uart1 |
| 38 | PB8 | i2s0_din0 / i2s0_dout1 / owa0 / pwm1_0 / twi1 |
| 40 | PB7 | i2s0_din1 / i2s0_dout0 / owa0 / pwm0_9 / twi1 |
| 1 | — | 电源 3.3V |
| 2 | — | 电源 5V |
| 4 | — | 电源 5V |
| 17 | — | 电源 3.3V |
| 6 | — | GND |
| 9 | — | GND |
| 14 | — | GND |
| 20 | — | GND |
| 25 | — | GND |
| 30 | — | GND |
| 34 | — | GND |
| 39 | — | GND |

## 2. 能完整引到排针的外设

| 外设 | 排针脚位 |
| --- | --- |
| `uart2` | PJ23(脚3), PJ22(脚5), PB0(脚7), PB1(脚11), PB2(脚29), PB3(脚31) |
| `uart0` | PB0(脚7), PB9(脚8), PB10(脚10), PB1(脚11) |
| `spi2` | PB0(脚7), PB1(脚11), PB5(脚12), PB2(脚29), PB3(脚31), PB6(脚35), PB4(脚36) |
| `twi0` | PB9(脚8), PB10(脚10), PB2(脚29), PB3(脚31) |
| `pwm0_0` | PB4(脚36) |
| `twi1` | PB5(脚12), PB4(脚36), PB8(脚38), PB7(脚40) |
| `pwm0_1` | PB5(脚12) |
| `pwm0_2` | PB6(脚35) |
| `pwm0_8` | PB6(脚35) |
| `pwm0_9` | PB7(脚40) |
| `pwm1_0` | PD10(脚24), PB8(脚38) |
| `pwm1_1` | PB9(脚8), PD11(脚23) |
| `twi8` | PB9(脚8), PB10(脚10) |
| `pwm1_2` | PB10(脚10), PD12(脚19) |
| `spi1` | PD12(脚19), PD13(脚21), PD11(脚23), PD10(脚24), PD14(脚26) |
| `pwm1_3` | PD13(脚21) |
| `uart3` | PJ23(脚3), PJ22(脚5), PD14(脚26), PD17(脚27), PD16(脚28) |
| `twi2` | PD17(脚27), PD16(脚28) |
| `uart4` | PJ24(脚16), PJ25(脚18) |
| `pwm1_5` | PJ23(脚3) |
| `twi3` | PJ23(脚3), PJ22(脚5) |
| `pwm1_4` | PJ22(脚5) |
| `twi11` | PJ23(脚3), PJ22(脚5) |
| `twi4` | PJ24(脚16), PJ25(脚18) |
| `pwm1_6` | PJ24(脚16) |
| `pwm1_7` | PJ25(脚18) |
| `twi7` | PJ23(脚3), PJ22(脚5) |
| `s_twi1` | PM5(脚32), PM4(脚37) |
| `s_twi2` | PL5(脚22), PM5(脚32), PM4(脚37) |
| `s_ir_rx` | PL6(脚13), PM5(脚32), PM4(脚37) |
| `s_uart1` | PM5(脚32), PM3(脚33), PM4(脚37) |
| `s_uart0` | PL6(脚13), PL7(脚15), PM5(脚32), PM3(脚33), PM4(脚37) |
| `s_pwm0_0` | PM4(脚37) |
| `s_pwm0_1` | PM5(脚32) |
| `s_spi0` | PL6(脚13), PL7(脚15), PL5(脚22), PM3(脚33) |
| `s_pwm0_3` | PL5(脚22) |
| `s_pwm0_4` | PL6(脚13) |
| `s_pwm0_5` | PL7(脚15), PM3(脚33) |

## 3. 只有部分信号在排针上（组不成完整总线）

| 外设 | 排针上的信号 |
| --- | --- |
| `dsi` | PB0(脚7) |
| `lcd0` | PJ23(脚3), PJ22(脚5), PB0(脚7), PB9(脚8), PB10(脚10), PB1(脚11), PB5(脚12), PD12(脚19), PD13(脚21), PD11(脚23), PD10(脚24), PD14(脚26), PD17(脚27), PD16(脚28), PB2(脚29), PB3(脚31), PB4(脚36) |
| `jtag` | PB0(脚7), PB1(脚11), PB2(脚29), PB3(脚31) |
| `hdmi` | PB2(脚29), PB3(脚31), PB4(脚36) |
| `owa0` | PB8(脚38), PB7(脚40) |
| `lvds1` | PD12(脚19), PD13(脚21), PD11(脚23), PD10(脚24), PD14(脚26), PD17(脚27), PD16(脚28) |
| `dsi1` | PD12(脚19), PD13(脚21), PD11(脚23), PD10(脚24), PD14(脚26), PD17(脚27), PD16(脚28) |
| `spi3` | PJ24(脚16), PJ25(脚18) |
| `lcd1` | PJ23(脚3), PJ22(脚5), PJ24(脚16), PJ25(脚18) |
| `s_jtag_ck` | PL5(脚22) |
| `s_jtag_do` | PL6(脚13) |
| `s_jtag_di` | PL7(脚15), PM3(脚33) |

## 4. 完全到不了排针的外设

> **`uart1` 名字有歧义，别搞混**：下表里的 `uart1` 指 **PIO 域** `uart@2501000`
> （内核 `ttyAS1`，PG6–PG9，调试串口）。排针上的 "UART1" 是 **R 域 S-UART1**
> `uart@7081000`（即 `s_uart1`，PM3/PM4/PM5 = 脚 33/37/32），见第 2 节。
> 两者是**不同的硬件单元**，只有后者引到了排针。

`csi0`, `csi1`, `dmic`, `dsi0`, `ir`, `ledc`, `lvds0`, `lvds2`, `lvds3`, `pwm0_3`, `pwm0_4`, `pwm0_5`, `pwm0_6`, `pwm0_7`, `pwm1_8`, `pwm1_9`, `rgmii0`, `rgmii1`, `s_jtag_ms`, `s_pwm0_2`, `s_pwm0_6`, `s_pwm0_7`, `s_pwm0_8`, `s_pwm0_9`, `s_twi0`, `sdc0`, `sdc1`, `sdc2`, `sdc3`, `spi0`, `spi4`, `spif0`, `twi10`, `twi12`, `twi5`, `twi6`, `twi9`, `uart1`, `uart5`, `uart6`

这些只引到了板载器件或专用接口（SD/eMMC/NAND/SPI-Flash/PCIe/CSI/DSI/GMAC/
调试串口 UART1 等），从 40pin 拿不到。

## 5. 复用时必须注意的冲突

- **PB 组共享**：PB0/PB1/PB9/PB10 同时是 `uart0`、`uart2`、`twi0`、`twi8`、
  `spi2` 的候选脚，一次只能选一组用途。
- **PD10–PD14 / PD16 / PD17 兼作显示**：`lcd0`、`lvds1`、`dsi1`、`eink` 也走这 7 个
  脚，接屏就全部占用。
- **脚 32/37（PM5/PM4）**：`s_uart1` 在 `SCP_MODE=uart1` 构建里被 RISC-V E902 的
  SCP 日志占用（硬件层 mux，Linux 的 pinctrl 看不见，显示为 UNCLAIMED）；
  `no-riscv-core` 分支关核后才变回普通 GPIO。脚 33（PM3）同为 `s_uart1` 候选，未被占用。
- **I2S0 全套在排针上**：PB4/PB5/PB6/PB7/PB8 = 脚 36/12/35/40/38
  （MCLK/BCLK/LRCK/DOUT0/DIN0）。

## 6. UART 对照表（哪个 UART 在排针上）

### 6.1 官方表给出的 TX/RX 方向

来源：<https://docs.radxa.com/en/cubie/a7z/hardware-use/pin-gpio>（40-pin 复用表）。
**官方表里排针上只有这 6 路 UART**，`uart1`/`uart5`/`uart6` 没有引出。

| UART | TX | RX | 其它信号 |
| --- | --- | --- | --- |
| `uart0`（开机控制台） | PB9(脚8) / PB0(脚7) | PB10(脚10) / PB1(脚11) | — |
| `uart2` | PB0(脚7) | PB1(脚11) | RTS=PB2(29)/PJ22(5)，CTS=PB3(31)/PJ23(3) |
| `uart3` | PJ22(脚5) / PD16(脚28) | PJ23(脚3) / PD17(脚27) | RTS=PD14(脚26) |
| `uart4` | PJ24(脚16) | PJ25(脚18) | — |
| `s_uart0` | PL6(脚13) / PM4(脚37) | PL7(脚15) / PM5(32) / PM3(33) | — |
| `s_uart1`（SCP 日志） | PM4(脚37) | PM5(脚32) / PM3(脚33) | — |

> 注意 PB0/PB1 同时是 JTAG-MS/CK：boot0 通过 `sys_config.fex` 的 `[jtag_para]`
> 把 PB0–PB3 复用成 JTAG，一旦把 uart2 放到 PB0/PB1，JTAG 就没了。

### 6.2 控制器 ↔ 别名 ↔ 排针脚（从实机 DT 生成）

`serialN` 别名取自实机 `/proc/device-tree/aliases/serial*`。**`uart1` 与 `s_uart1`
是两个不同控制器**，只有 `s_*` 后缀那个在排针上。

| 别名 | 控制器 | pinctrl 名 | 排针可用脚 |
| --- | --- | --- | --- |
| `serial0` | `0x2500000` | `uart0` | PB0(脚7), PB9(脚8), PB10(脚10), PB1(脚11) |
| `serial1` | `0x2501000` | `uart1` | ❌ 无 |
| `serial2` | `0x2502000` | `uart2` | PJ23(脚3), PJ22(脚5), PB0(脚7), PB1(脚11), PB2(脚29), PB3(脚31) |
| `serial3` | `0x2503000` | `uart3` | PJ23(脚3), PJ22(脚5), PD14(脚26), PD17(脚27), PD16(脚28) |
| `serial4` | `0x2504000` | `uart4` | PJ24(脚16), PJ25(脚18) |
| `serial5` | `0x2505000` | `uart5` | ❌ 无 |
| `serial6` | `0x2506000` | `uart6` | ❌ 无 |
| `serial7` | `0x7080000` | `s_uart0` | PL6(脚13), PL7(脚15), PM5(脚32), PM3(脚33), PM4(脚37) |
| `serial8` | `0x7081000` | `s_uart1` | PM5(脚32), PM3(脚33), PM4(脚37) |

## 7. 结论

**不是所有外设都能塞进 40pin，但常用的都能。** 单看"能不能引出来"：UART、I2C、
SPI、PWM、I2S0 都在排针上有完整脚位；SD/eMMC/NAND/PCIe/CSI/MIPI/GMAC 以及 PIO 域的
调试串口 `uart1`（PG6–9）没有引出 —— 但**排针上有 UART：R 域的 `s_uart1`（脚
32/33/37）和 `s_uart0`（脚 13/15/32/33/37）**，见第 6 节。真正限制来自**脚位重叠**：
28 个脚里 PB 组被 5 个外设共用、PD 组被显示总线共用，实际可同时使用约
1×UART + 1×I2C + 1×SPI + 1×PWM + 1×I2S（约 15–18 脚）。
