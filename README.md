# A7Z 固件（Radxa Cubie A7Z / Allwinner A733）— GitHub 全自动编译

**全程在 GitHub Actions 上编译。** 你只要 clone 这个仓库、往 Release 传一个文件，点一下按钮，就能下载到烤好的固件。

产物：Ubuntu 24.04 headless SD 镜像（4 GiB，xz 约 230 MB），包含

- RISC-V **E902/SCP UART1 直出日志**（S-UART1：排针 37/33 脚，115200 8N1）
- **AIC8800D80 USB WiFi** 驱动 + USB 专用固件
- **VE 硬件视频引擎 + PowerVR OpenCL/Vulkan**（`libvdecoder`/`libVE`/`libPVROCL`/`libVK_IMG`）
- **USB-C 口完整可用**：ET7304 TCPC 驱动 + `try-power-role=source`（USB hub / UVC 摄像头 / HDMI 转接器）
- **NTP 服务端 ntpd（ntpsec）+ `ntpq`/`ntpdate`**，中国 NTP 源，`Asia/Shanghai` 时区（`systemd-timesyncd` 保留为兜底，仅 ntpsec 缺失时启用）
- **`net-tools`**：`ifconfig` / `route` / `netstat`（与 `iproute2` 并存）
- PowerVR GPU / NPU 运行时、`nmtui`、USTC APT 源、串口免密登录（`radxa/radxa`）

---

## 一、三步开跑

### 1) clone / fork 本仓库

```bash
git clone https://github.com/<你>/a7z-firmware.git
cd a7z-firmware
```

### 2) 往 Release 传一个基础镜像

构建需要一份 **2 GB 基础 SD 镜像**（含 A7Z 的 boot0 / U-Boot / BL31 / GPT 布局）。
把它 xz 压缩后作为 Release 资产上传，标签必须是 `inputs`：

```bash
gh release create inputs --title "pinned build inputs" --notes "A7Z base SD image"
gh release upload inputs base-sd512-a7z.img.xz
```

`base-sd512-a7z.img.xz` ≈ 104 MB，解压后 SHA-256 必须是
`977EDDFE9F9895D1DD9FFE991C0A9568BCD3B0FAB69F6B509ADE370DA6995EFF`。

> 想连这步都省掉？把它也放进仓库（104 MB 超出 GitHub 单文件 100 MB 限制，得走 Release 或 LFS），
> 或者把 `cache/base.img.xz` 提交进仓库并改成从本地取。

### 3) 点 Run

Actions → **Build A7Z firmware** → *Run workflow*。

CI 会自动：

1. `repo sync` Tina SDK（GitLab 公开清单，tag `aiot-linux-v1.5.0`）
2. 拉 3 个大文件包（约 1 GB）—— 优先用本仓库 Release 的 `tina-a7z-large-files.tar.zst`，没有就从 MEGA 下
3. 编译 **SCP 固件**（ARISC/E902，含 UART1 日志）、**设备树 DTB**、**AIC8800 WiFi 内核模块**
4. 构建 **Ubuntu 24.04 rootfs**（qemu-arm64 + apt）
5. 合成 4 GiB 镜像 → 打引导区补丁 → 校验（Radxa GPT + e2fsck）→ xz 压缩
6. 上传 Artifact

产物在 **Actions 页面 → 该次运行 → Artifacts** 下载，或：

```bash
gh run download --name a7z-firmware-<run_number>
```

---

## 二、把 MEGA 也省掉（可选但推荐）

CI 里从 MEGA 下 1 GB 不太稳。在你**已有完整 SDK 的机器**上跑一次：

```bash
./scripts/make-large-files-bundle.sh /path/to/tina-sdk out/tina-a7z-large-files.tar.zst
gh release upload inputs out/tina-a7z-large-files.tar.zst
```

之后 CI 就直接从你自己的 Release 取（workflow 里 `source_of_large_files=auto` 会自动优先用它）。

---

## 三、源码来源（全部公开）

| 组件 | 地址 |
|---|---|
| Tina SDK（A733，98 个仓库） | `https://gitlab.com/tina5.0_aiot/manifest.git`，`repo` 同步，tag `aiot-linux-v1.5.0` |
| SDK 大文件（仅需 3 个包，~1 GB） | 见 `.repo/manifests/README.md` 的 MEGA 链接 |
| A7Z 板级补丁 | `https://gitee.com/juping_zheng1/radxa-cubie-a7z-tina-bsp.git` |
| OrangePi `dragonsecboot` 打包工具 | `https://github.com/orangepi-xunlong/orangepi-build`（commit `7f776a20…`） |
| Ubuntu base rootfs | `https://cdimage.ubuntu.com/ubuntu-base/releases/24.04.5/release/` |

---

## 四、仓库结构

```
.github/workflows/build.yml          全程云端编译（主）
.github/workflows/build-selfhosted.yml  用自有构建机（备选，快）
scripts/
  fetch-sdk.sh                 repo init/sync + A7Z 板级补丁
  restore-large-files.sh       按 manifest 还原大文件
  make-large-files-bundle.sh   打 ~1 GB 大文件包（本地跑一次）
  build-sdk-parts.sh           编 SCP / DTB / AIC + ET7304 模块
  patch_a7z_e902_uart1_staging.py   ARISC UART1 后端改动
  patch_a7z_uart1_dts.py            DTS 引脚改 PM4/PM5
  patch_a7z_typec_role.py           DTS：USB-C try-power-role sink→source
  install_media_libs.sh             从 SDK 提取 VE/OpenCL/Vulkan 库到 overlay
  build_a7z_uart1_boot_package.py   重打启动包
  roundtrip_a7z_boot_package.py     启动包往返自检
  patch_image_boot.py               写启动包槽 + 替换 p2 DTB
  apply_extra_overlay.sh            往 rootfs 灌 WiFi/NTP/时区（ntpsec 优先，timesyncd 兜底）
  verify-radxa-img.py               Radxa GPT 校验
drivers/         tcpci_et7304.c（ET7304 USB-C TCPC 驱动源码）
rootfs/          Ubuntu 24.04 rootfs 构建器 + overlay + 清单 + 单测
overlay/         AIC WiFi/ET7304 模块 + USB 固件 + systemd-timesyncd + NTP
overlay/boot/    sunxi.dtb（rootfs /boot 同步用；真正启动的是 p2 那份）
boot/            boot_package_uart1.fex（含 UART1 SCP）
dtb/             sunxi-uart1.dtb（UART1 引脚 + USB-C 角色修正）
inputs/          systemd-timesyncd deb + Release 说明
```

`boot/`、`dtb/`、`overlay/usr/lib/modules/6.6.98/*.ko` 是 SDK 派生件，已预编译提交。
CI 每次会用 `scripts/build-sdk-parts.sh` **重新从源码编译覆盖它们**，所以仓库里那份只是兜底。

---

## 五、本地复现

```bash
./scripts/fetch-sdk.sh tina-sdk
./scripts/restore-large-files.sh tina-sdk /path/to/large-files
sudo ./scripts/build-sdk-parts.sh "$PWD/tina-sdk"
# 之后按 .github/workflows/build.yml 里的步骤走
```

---

## 六、USB-C 口与存储

### USB-C（ET7304）
板子的 USB-C 口由 **ET7304 TCPC** 管，但 SDK 内核里**没有它的驱动**，且 vendor 的
board.dts 把 connector 标成了 `try-power-role = "sink"`（TCPM 会呈现 Rd，永远发现不了同为
sink 的 hub）。本仓库补了两处：

1. `drivers/tcpci_et7304.c` → `overlay/usr/lib/modules/6.6.98/tcpci_et7304.ko`
   （自动加载：`overlay/etc/modules-load.d/et7304.conf`），负责外部 VBUS 稳压器
   （`usb2-vbus` = GPIO PL2）和 `et7304,intr_gpio`（PL3）中断；
2. `scripts/patch_a7z_typec_role.py` 把 `try-power-role` 改成 `source`，
   随 `dtb/sunxi-uart1.dtb` 一起写进 **p2 `/sunxi.dtb`**（u-boot 实际加载的那份）。

实测：hub（USB2.1 + USB3.1 双口）、UVC 摄像头（4K MJPG，`uvcvideo`）、
HDMI 转接器（DP alt mode）均可枚举，摄像头可出图。

### SD 卡热插拔
SD 槽是 `4020000.sdmmc`，DTS 带 `cd-gpios`，驱动进 `detmode:gpio irq`（带消抖），
支持热插拔。**前提是系统不是从这张 SD 启动的**——把固件刷进 UFS 后，SD 就是纯数据槽：
插卡自动出现 `/dev/mmcblk1` 及分区，拔卡设备消失。

---

## 七、多媒体 / GPU 运行时（VE + OpenCL + Vulkan）

A733 的 VE（硬件视频引擎）和 PowerVR OpenCL/Vulkan 用户态**都在 SDK 里**，
但标准 Ubuntu rootfs 不含它们 —— 板子开箱既没有 OpenCL 也没有硬解。
`scripts/install_media_libs.sh` 会在构建时把它们从 SDK 提取到 `overlay/usr/local/lib`，
再由 `apply_extra_overlay.sh` 装进 rootfs（这些 vendor blob 约 59 MB，已 git-ignore）。

| 组件 | 库 | 说明 |
|---|---|---|
| VE 硬解 | `libvdecoder` `libVE` `libMemAdapter` `libcdc_base` `libfbm` `libsbm` `libvideoengine` + 32 个 `libaw*` 插件 | `/dev/cedar_dev`；`/etc/cedarx.conf`、`/etc/cedarc.conf` |
| OpenCL | `libPVROCL.so.24.2.6603887` → `libOpenCL.so{.1}` + `/etc/OpenCL/vendors/pvr.icd` | PowerVR BXM-4-64，OpenCL 3.0（实现了 ICD 接口，走标准 loader） |
| Vulkan | `libVK_IMG.so.24.2.6603887`（依赖 `libufwriter`） | |
| GPU 附加 | `libPVRScopeServices` `libsutu_display` | |

实测：`clGetPlatformIDs` 返回 1 个平台 `PowerVR / OpenCL 3.0`，设备 `PowerVR B-Series BXM-4-64`。
GPU 调频 `/sys/class/devfreq/1800000.gpu`：400 / 600 / 800 / **1008 MHz**。

---

## 七、安全边界

- 只操作 SD 镜像，**不碰 UFS**。
- 生成的镜像保留 SD GPT 布局与 PARTUUID，`p1`/`boot0`/启动包槽以外的引导区不被改动。
- 默认账号 `radxa/radxa`（弱口令），连公网前请先改密码。

---

## 五、SD / UFS 双介质

workflow 以 matrix 同时产出两个固件（Artifacts 里分别带 `sd512` / `ufs4096` 后缀）：

| | SD 版 | UFS 版 |
|---|---|---|
| 基底（Release `inputs`） | `base-sd512-a7z.img.xz`（2 GiB，512 B 扇区） | `base-ufs4096-v2.img.xz`（10 GiB，4096 B 扇区，板上已验证） |
| 引导处理 | 重打 `boot_package_uart1.fex` + p2 DTB 补丁 | **保留基底引导不动**（boot0_ufs 串口静默，boot blob @ 字节 1056768） |
| rootfs | 新构建 Ubuntu 24.04，扩到 4 GiB | 同一份新构建 rootfs，dd 进 p3 后 `resize2fs` 扩满 |
| 刷写 | xz -dc \| dd of=/dev/sdX | xz -dc \| dd of=/dev/sdX bs=4M（UFS 容量按需 `growpart` + `resize2fs`） |

UFS 版 rootfs 内容与 SD 版完全一致（同一份 overlay 与校验流程）。
