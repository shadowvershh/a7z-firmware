# A7Z SD 卡热插拔修复

## 问题

Cubie A7Z 的 SD 卡**插卡无法被检测**（拔卡可以）。

- `sunxi_pio_edge` 中断域只在一个边沿方向产生中断（实测：拔卡 +4，插卡 +0）
- 而 vendor 的 `sunxi-mmc` 驱动从不设置 `MMC_CAP_NEEDS_POLL`，
  所以 MMC 核心总是注册 cd-gpios 中断 → 插卡永远检测不到

## 修复（两部分）

### 1. 内核驱动：让驱动支持标准 `broken-cd` 属性

`patches/0001-mmc-honour-broken-cd.patch`（`bsp/drivers/mmc/sunxi-mmc.c`）

```c
if (of_property_read_bool(np, "broken-cd"))
    mmc->caps |= MMC_CAP_NEEDS_POLL;
```

位置：`sunxi_mmc_extra_of_parse()` 内、`mmc_add_host()` 之前。
效果：核心跳过中断注册，改用 `mmc_gpio_get_cd()` 每秒轮询，两个方向都能检测。

**编译时必须传 `LOCALVERSION=`**，否则源码树 dirty 会让版本号变成 `6.6.98+`，
与 `/lib/modules/6.6.98` 不匹配 → WiFi 等模块全部加载失败。

### 2. 设备树：两处修改（`sdmmc@4020000` 节点）

```
cd-gpios   = <0x36 0x05 0x06 0x21>   ; 原 0x20 → 0x21 (加 GPIO_ACTIVE_LOW)
broken-cd  = <1>                      ; 新增，启用轮询
sunxi-power-save-mode                 ; 删除（卡槽保持常供电）
```

用 `fdtput` 直接改二进制，**不要 dtc 反编译再编译**（会丢信息）：

```sh
P=/soc@3000000/sdmmc@4020000
fdtput -t x  sunxi.dtb $P cd-gpios 0x36 0x05 0x06 0x21
fdtput -t bx sunxi.dtb $P broken-cd 1
fdtput -d    sunxi.dtb $P sunxi-power-save-mode
```

## 验证

```
[52.950219] mmc1: new ultra high speed SDR104 SDHC card at address 5048   ← 插卡 ✅
[52.955220]  mmcblk1: p1
[59.526913] mmc1: card 5048 removed                                       ← 拔卡 ✅
[ 2.500364] detmode:gpio polling                                          ← 轮询模式 ✅
/proc/interrupts 中已无 "4020000.sdmmc cd" 行
```

## 注意事项

⚠️ **U-Boot 每次都优先从 SD 卡的 p1 读 `/bImage`**。所以：

- 启动时 SD 卡插着 → 用的是 **SD 卡里的内核**，不是 UFS 里的
- 换内核时 **SD 卡和 UFS 两处都要更新**
- 或者启动时把 SD 卡拔掉

## 实测结论

| 检查 | 结果 |
|---|---|
| 插卡自动识别 | ✅ ≤1 秒 |
| 拔卡自动识别 | ✅ ≤1 秒 |
| 分区识别 | ✅ `mmcblk1: p1` |
| 依赖 CD 中断 | ❌ 不需要（轮询）|
