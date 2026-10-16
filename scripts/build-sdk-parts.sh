#!/usr/bin/env bash
# Rebuild the SDK-derived firmware pieces from a synced Tina SDK:
#   boot/boot_package_uart1.fex   (SCP with UART1 logging, repacked)
#   dtb/sunxi-uart1.dtb           (arisc S-UART1 = PM4/PM5; USB-C try-power-role=source)
#   overlay/usr/lib/modules/6.6.98/aic8800_{bsp,fdrv,btusb}.ko
#   overlay/usr/lib/modules/6.6.98/tcpci_et7304.ko  (ET7304 USB-C TCPC driver)
#   overlay/usr/local/lib/*.so      (VE hardware video engine + PowerVR OpenCL/Vulkan)
#
# Usage: build-sdk-parts.sh /path/to/tina-sdk
set -Eeuo pipefail

SDK=${1:?usage: build-sdk-parts.sh /path/to/tina-sdk}
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
WORK=${WORK_DIR:-$PWD/sdk-parts-work}

ARISC_SRC="$SDK/brandy/arisc/ar100s"
KSRC="$SDK/kernel/linux-6.6"
KBUILD="$SDK/out/a733/kernel/build"
BOARD="$SDK/device/config/chips/a733/configs/cubie_a7z"
TC="$SDK/out/toolchain/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-"

for p in "$ARISC_SRC" "$KSRC" "$BOARD" "$KBUILD/Module.symvers" "${TC}gcc"; do
    [[ -e "$p" ]] || { echo "ERROR: missing input: $p"; exit 1; }
done
[[ -f "$KBUILD/.config" ]] || { echo "ERROR: kernel build tree not configured ($KBUILD/.config)"; exit 1; }

# 大文件包里的 O= 内核构建树烘焙了打包机的绝对路径（mkmakefile 生成的 wrapper 等），
# 还原后统一改写为当前机器的 SDK 路径，否则 M= 模块编译找不到内核源码树。
grep -rIl '/Desktop/radxa_a7z/tina-sdk' "$KBUILD" 2>/dev/null | while read -r f; do
    sed -i "s|/home/[^/\"']*Desktop/radxa_a7z/tina-sdk|$SDK|g" "$f"
done

mkdir -p "$WORK" "$REPO/boot" "$REPO/dtb" "$REPO/overlay/usr/lib/modules/6.6.98"

# ---------------------------------------------------------------- 1) ARISC/SCP
echo "==> [1/6] ARISC/SCP (UART1)"
mkdir -p "$WORK/arisc/brandy/arisc" "$WORK/arisc/device/config/chips/a733/configs"
rm -rf "$WORK/arisc/brandy/arisc/ar100s" "$WORK/arisc/device/config/chips/a733/configs/cubie_a7z"
cp -a "$ARISC_SRC" "$WORK/arisc/brandy/arisc/"
cp -a "$BOARD"     "$WORK/arisc/device/config/chips/a733/configs/"
python3 "$REPO/scripts/patch_a7z_e902_uart1_staging.py" "$WORK/arisc"
(
  cd "$WORK/arisc/brandy/arisc/ar100s"
  make clean >/dev/null
  make cubie_a7z_s_uart1_defconfig >/dev/null
  make -j"$(nproc)" >/dev/null
)
SCP_BIN="$WORK/arisc/brandy/arisc/ar100s/scp.bin"
strings -a "$SCP_BIN" | grep -q 'E902_S_UART1_READY baud=115200' \
  || { echo "ERROR: SCP marker missing"; exit 1; }
echo "    scp.bin: $(stat -c %s "$SCP_BIN") bytes"

# ------------------------------------------------------- 2) boot package repack
echo "==> [2/6] repack boot package"
PACK_TOOLS="$WORK/orangepi-build/external/packages/pack-uboot"
if [[ ! -d "$PACK_TOOLS" ]]; then
    rm -rf "$WORK/orangepi-build"
    git init -q "$WORK/orangepi-build"
    git -C "$WORK/orangepi-build" remote add origin https://github.com/orangepi-xunlong/orangepi-build.git
    git -C "$WORK/orangepi-build" config core.sparseCheckout true
    echo "external/packages/pack-uboot/*" > "$WORK/orangepi-build/.git/info/sparse-checkout"
    git -C "$WORK/orangepi-build" fetch -q --depth 1 origin 7f776a209b72b92e8c6a06abc83b1e7597eef5af
    git -C "$WORK/orangepi-build" checkout -q --detach FETCH_HEAD
fi
BASELINE_PKG=${BASELINE_BOOT_PACKAGE:-}
if [[ -z "$BASELINE_PKG" ]]; then
    BASELINE_PKG="$SDK/bsp/pack/boot_package.fex"           # fallback; prefer BASELINE_BOOT_PACKAGE
fi
[[ -f "$BASELINE_PKG" ]] || { echo "ERROR: baseline boot package not found (set BASELINE_BOOT_PACKAGE)"; exit 1; }
rm -rf "$WORK/package"
python3 "$REPO/scripts/build_a7z_uart1_boot_package.py" \
    "$BASELINE_PKG" "$PACK_TOOLS" "$SCP_BIN" "$WORK/package"
cp -f "$WORK/package/boot_package_uart1.fex" "$REPO/boot/boot_package_uart1.fex"
echo "    boot package: $(stat -c %s "$REPO/boot/boot_package_uart1.fex") bytes"

# ------------------------------------------------------------------- 3) DTB
echo "==> [3/6] DTB (S-UART1 pins)"
DTS_DIR="$WORK/dts"
rm -rf "$DTS_DIR"; mkdir -p "$DTS_DIR"
cp -a "$BOARD/linux-6.6/board.dts" "$DTS_DIR/board.dts"
python3 "$REPO/scripts/patch_a7z_uart1_dts.py" "$DTS_DIR/board.dts"
# v1.5.0 + gitee BSP 的 linux-6.6 board.dts 没有 USB-C connector 节点
# (try-power-role 只在 gitee 的 5.15 版) -> 回退到仓库提交的、板上验证过的 sunxi-uart1.dtb
BUILD_DTB=1
if ! python3 "$REPO/scripts/patch_a7z_typec_role.py" "$DTS_DIR/board.dts"; then
    BUILD_DTB=0
fi
if [[ "$BUILD_DTB" == "1" ]]; then
    cpp -nostdinc -I"$DTS_DIR" -I"$KSRC/bsp/configs/linux-6.6" -I"$KSRC/bsp/include"         -I"$KSRC/include" -undef -D__DTS__ -x assembler-with-cpp         "$DTS_DIR/board.dts" > "$DTS_DIR/board.pp.dts"
    ORIG_SZ=$(mktemp -d)  # reference size comes from the baseline image, see docs
    dtc -@ -W no-unit_address_vs_reg -I dts -O dtb -o "$DTS_DIR/sunxi.dtb" "$DTS_DIR/board.pp.dts"
    python3 - "$DTS_DIR/sunxi.dtb" <<'PY'
import struct, sys
p = sys.argv[1]
b = open(p, "rb").read()
total = struct.unpack(">I", b[4:8])[0]
print(f"    dtb {len(b)} bytes (totalsize {total})")
if total > 24 * 8192:
    raise SystemExit("ERROR: DTB exceeds the p2 24-cluster chain")
PY
else
    echo "  (source DTS lacks connector node -> using committed verified DTB)"
    cp -f "$REPO/dtb/sunxi-uart1.dtb" "$DTS_DIR/sunxi.dtb"
fi
cp -f "$DTS_DIR/sunxi.dtb" "$REPO/dtb/sunxi-uart1.dtb"
# u-boot actually boots the p2 FAT copy (patch_image_boot.py writes it);
# keep the rootfs /boot copy in sync through the overlay as well.
mkdir -p "$REPO/overlay/boot"
cp -f "$DTS_DIR/sunxi.dtb" "$REPO/overlay/boot/sunxi.dtb"

# ------------------------------------------------------- 4) AIC WiFi modules
echo "==> [4/6] AIC8800 USB kernel modules"
AIC="$WORK/aic8800"
rm -rf "$AIC"; mkdir -p "$AIC"
# GitLab v1.5.0 内核仓库不含 bsp/，vendor 驱动（aic8800 等）在顶层 lichee/bsp 仓库
AIC_SRC="$SDK/bsp/drivers/net/wireless/aic8800"
[[ -d "$AIC_SRC" ]] || AIC_SRC="$KSRC/bsp/drivers/net/wireless/aic8800"   # 本地 v1.4.6 布局回退
cp -a "$AIC_SRC" "$AIC/"
export ARCH=arm64 CROSS_COMPILE="$TC"
make -C "$KBUILD" M="$AIC/aic8800/aic8800_bsp" \
     CONFIG_AIC_WLAN_SUPPORT=y CONFIG_AIC_INTF_USB=y CONFIG_AIC_INTF_SDIO=n \
     CONFIG_AIC_INTF_PCIE=n CONFIG_USB_MSG_EP=y CONFIG_AIC_BSP_CTRL=y modules >/dev/null
make -C "$KBUILD" M="$AIC/aic8800/aic8800_fdrv" \
     KBUILD_EXTRA_SYMBOLS="$AIC/aic8800/aic8800_bsp/Module.symvers" \
     CONFIG_AIC_WLAN_SUPPORT=y CONFIG_AIC_INTF_USB=y CONFIG_AIC_INTF_SDIO=n \
     CONFIG_AIC_INTF_PCIE=n CONFIG_AIC8800_WLAN_SUPPORT=m CONFIG_USB_MSG_EP=y \
     CONFIG_AIC_BSP_CTRL=y modules >/dev/null
make -C "$KBUILD" M="$AIC/aic8800/aic8800_btusb" \
     KBUILD_EXTRA_SYMBOLS="$AIC/aic8800/aic8800_bsp/Module.symvers" \
     CONFIG_AIC_INTF_USB=y CONFIG_AIC8800_BTUSB_SUPPORT=m modules >/dev/null
for m in bsp fdrv btusb; do
    cp -f "$AIC/aic8800/aic8800_$m/aic8800_$m.ko" "$REPO/overlay/usr/lib/modules/6.6.98/"
done
echo "    modules: $(ls "$REPO/overlay/usr/lib/modules/6.6.98/" | tr '\n' ' ')"

# ------------------------------------------------- 5) ET7304 USB-C TCPC
echo "==> [5/6] ET7304 USB-C TCPC module"
ET="$WORK/et7304"
rm -rf "$ET"; mkdir -p "$ET"
cp "$REPO/drivers/tcpci_et7304.c" "$ET/"
printf 'obj-m := tcpci_et7304.o\n' > "$ET/Makefile"
make -C "$KBUILD" ARCH=arm64 CROSS_COMPILE="$TC" M="$ET" modules >/dev/null
cp -f "$ET/tcpci_et7304.ko" "$REPO/overlay/usr/lib/modules/6.6.98/"
echo "    tcpci_et7304.ko: $(stat -c %s "$REPO/overlay/usr/lib/modules/6.6.98/tcpci_et7304.ko") bytes"

# -------------------------------------------- 6) VE / OpenCL / GPU userspace
echo "==> [6/6] VE (cedarc) + PowerVR OpenCL/Vulkan libraries"
"$REPO/scripts/install_media_libs.sh" "$SDK" "$REPO"

echo "==> done. Update these repo files and commit:"
echo "    boot/boot_package_uart1.fex"
echo "    dtb/sunxi-uart1.dtb"
echo "    overlay/boot/sunxi.dtb"
echo "    overlay/usr/lib/modules/6.6.98/aic8800_*.ko"
echo "    overlay/usr/lib/modules/6.6.98/tcpci_et7304.ko"
echo "    overlay/usr/local/lib  (generated, git-ignored)"
