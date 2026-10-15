#!/usr/bin/env bash
# Stage the A733 multimedia/GPU userspace libraries into the repo overlay so
# `apply_extra_overlay.sh` installs them into the firmware rootfs:
#
#   VE / hardware video engine : libvdecoder, libVE, libMemAdapter,
#                                libcdc_base, libfbm, libsbm, libvideoengine,
#                                codec plugins (libaw*), cedarx/cedarc conf
#   GPU                        : PowerVR OpenCL (libPVROCL), Vulkan (libVK_IMG),
#                                PVRScope/sutu display helpers
#
# The SDK ships all of these (buildroot target + gpu_um_pub); a stock Ubuntu
# rootfs simply does not include them, which is why the board had no OpenCL and
# no hardware decode out of the box.
#
# Usage: install_media_libs.sh /path/to/tina-sdk [repo-root]
set -Eeuo pipefail

SDK=${1:?usage: install_media_libs.sh /path/to/tina-sdk [repo-root]}
REPO=${2:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)}

T="$SDK/out/a733/cubie_a7z/buildroot/buildroot/target"
G=$(find "$SDK/out/a733/cubie_a7z/buildroot/buildroot/build/gpu_um_pub/img-bxm" \
        -maxdepth 1 -type d -name "gcc-*" 2>/dev/null | sort | tail -1)/x11

[[ -d "$T/usr/lib" ]] || { echo "ERROR: buildroot target not found: $T" >&2; exit 1; }
[[ -d "$G/usr/lib" ]] || { echo "ERROR: img-bxm gpu package not found under $G" >&2; exit 1; }

LIB="$REPO/overlay/usr/local/lib"
INC="$REPO/overlay/usr/local/include"
CONF="$REPO/overlay/etc"
ICD="$REPO/overlay/etc/OpenCL/vendors"
mkdir -p "$LIB" "$INC" "$CONF" "$ICD"

# ---------------------------------------------------------------- VE / cedarc
# Resolve the full DT_NEEDED closure of the vdecoder stack so nothing is missed.
python3 - "$T" "$LIB" <<'PY'
import os, shutil, subprocess, sys
target, out = sys.argv[1], sys.argv[2]
roots = [os.path.join(target, "usr/lib"), os.path.join(target, "lib")]
system = {"libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1",
          "libgcc_s.so.1", "libstdc++.so.6", "ld-linux-aarch64.so.1", "libdrm.so.2",
          "libz.so.1", "libion.so.1"}

def find(name):
    for r in roots:
        p = os.path.join(r, name)
        if os.path.exists(p):
            return p
    return None

def needed(path):
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return [l.split("[")[1].split("]")[0] for l in out.splitlines() if "(NEEDED)" in l]

seeds = ["libvdecoder.so", "libMemAdapter.so", "libcdc_base.so", "libcdx_ion.so",
         "libawion.so", "libVE.so", "libvdecVcs.so", "libvencoder.so",
         "libvenc_base.so", "libvenc_codec.so", "libOmxVdec.so", "libOmxVenc.so",
         "libxmetadataretriever.so"]
done, queue, missing = {}, list(seeds), set()
while queue:
    name = queue.pop(0)
    if name in done or name in system:
        continue
    path = find(name)
    if not path:
        missing.add(name)
        continue
    done[name] = path
    queue.extend(n for n in needed(path) if n not in done and n not in system)

for name, path in done.items():
    dst = os.path.join(out, name)
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
print(f"  VE/cedarc: staged {len(done)} libs")
if missing:
    print("  WARNING unresolved:", ", ".join(sorted(missing)))
PY

# codec plugins (libcedarx awplayer) + cedarc config files
plug=0
for f in "$T"/usr/lib/libaw*.so; do
    [[ -e "$f" ]] || continue
    b=$(basename "$f")
    [[ "$b" == "libawion.so" ]] && continue
    cp -a "$f" "$LIB/" && plug=$((plug+1))
done
echo "  codec plugins: $plug"
cp -a "$T"/etc/cedarx.conf "$T"/etc/cedarc.conf "$CONF/" 2>/dev/null || \
    echo "  WARNING: cedarx/cedarc conf missing" >&2

# --------------------------------------------------------------- GPU / OpenCL
for f in libPVROCL libVK_IMG libPVRScopeServices libsutu_display libufwriter; do
    src=$(ls "$G"/usr/lib/${f}.so.24.2.* 2>/dev/null | head -1 || true)
    [[ -n "$src" ]] || { echo "  WARNING: $f missing"; continue; }
    cp -a "$src" "$LIB/"
    ver=$(basename "$src")
    ln -sf "$ver" "$LIB/${f}.so"
done
ln -sf "$(basename "$(ls "$LIB"/libPVROCL.so.24.2.* | head -1)")" "$LIB/libOpenCL.so.1"
cp -a "$G"/include/CL "$INC/" 2>/dev/null || true

echo /usr/local/lib/libPVROCL.so.24.2.6603887 > "$ICD/pvr.icd"

echo "  staged into $REPO/overlay/usr/local/lib ($(ls "$LIB" | wc -l) files)"