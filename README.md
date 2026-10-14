# A7Z 固件（Radxa Cubie A7Z / Allwinner A733）— GitHub 全自动编译

**全程在 GitHub Actions 上编译。** 你只要 clone 这个仓库、往 Release 传一个文件，点一下按钮，就能下载到烤好的固件。

产物：Ubuntu 24.04 headless SD 镜像（4 GiB，xz 约 230 MB），包含

- RISC-V **E902/SCP UART1 直出日志**（S-UART1：排针 37/33 脚，115200 8N1）
- **AIC8800D80 USB WiFi** 驱动 + USB 专用固件
- **systemd-timesyncd** + 中国 NTP + `Asia/Shanghai` 时区
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
  build-sdk-parts.sh           编 SCP / DTB / AIC 模块
  patch_a7z_e902_uart1_staging.py   ARISC UART1 后端改动
  patch_a7z_uart1_dts.py            DTS 引脚改 PM4/PM5
  build_a7z_uart1_boot_package.py   重打启动包
  roundtrip_a7z_boot_package.py     启动包往返自检
  patch_image_boot.py               写启动包槽 + 替换 p2 DTB
  apply_extra_overlay.sh            往 rootfs 灌 WiFi/NTP/时区
  verify-radxa-img.py               Radxa GPT 校验
rootfs/          Ubuntu 24.04 rootfs 构建器 + overlay + 清单 + 单测
overlay/         AIC WiFi 模块 + USB 固件 + systemd-timesyncd + NTP
boot/            boot_package_uart1.fex（含 UART1 SCP）
dtb/             sunxi-uart1.dtb
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

## 六、安全边界

- 只操作 SD 镜像，**不碰 UFS**。
- 生成的镜像保留 SD GPT 布局与 PARTUUID，`p1`/`boot0`/启动包槽以外的引导区不被改动。
- 默认账号 `radxa/radxa`（弱口令），连公网前请先改密码。
