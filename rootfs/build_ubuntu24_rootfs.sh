#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
build_ubuntu24_rootfs.sh --work-dir DIR --base-tarball FILE --base-sha256 SHA256 \
  --vendor-root READ_ONLY_MOUNT --out-ext4 FILE --size-bytes BYTES

Builds an Ubuntu 24.04 ARM64 headless rootfs. Run as root on the isolated Linux
builder with qemu-aarch64 binfmt enabled and the candidate p3 mounted read-only.
No host packages are installed. Only packages inside the target root are changed.
EOF
}
fail() { echo "ERROR: $*" >&2; exit 1; }

WORK_DIR=""
BASE_TARBALL=""
BASE_SHA256=""
VENDOR_ROOT=""
OUT_EXT4=""
SIZE_BYTES=""
while (($#)); do
    case "$1" in
        --work-dir) WORK_DIR=${2:?missing value}; shift 2 ;;
        --base-tarball) BASE_TARBALL=${2:?missing value}; shift 2 ;;
        --base-sha256) BASE_SHA256=${2:?missing value}; shift 2 ;;
        --vendor-root) VENDOR_ROOT=${2:?missing value}; shift 2 ;;
        --out-ext4) OUT_EXT4=${2:?missing value}; shift 2 ;;
        --size-bytes) SIZE_BYTES=${2:?missing value}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; fail "unknown argument: $1" ;;
    esac
done

[[ -n "$WORK_DIR" && -n "$BASE_TARBALL" && -n "$BASE_SHA256" && -n "$VENDOR_ROOT" && -n "$OUT_EXT4" && -n "$SIZE_BYTES" ]] || { usage >&2; fail "all arguments are required"; }
OUT_TMP="${OUT_EXT4}.tmp"
[[ ! -e "$OUT_EXT4" && ! -L "$OUT_EXT4" && ! -e "$OUT_TMP" && ! -L "$OUT_TMP" ]] || fail "refusing to overwrite existing output: $OUT_EXT4"
[[ "$SIZE_BYTES" =~ ^[0-9]+$ && "$SIZE_BYTES" == "3946823168" ]] || fail "p3 ext4 size must be exactly 3946823168 bytes for the 4 GiB SD image"
[[ "$BASE_SHA256" =~ ^[[:xdigit:]]{64}$ ]] || fail "base archive SHA-256 must be 64 hexadecimal characters"
[[ -f "$BASE_TARBALL" ]] || fail "Ubuntu Base tarball does not exist: $BASE_TARBALL"
[[ ! -e "$WORK_DIR" && ! -L "$WORK_DIR" ]] || fail "refusing to reuse existing work directory: $WORK_DIR"
[[ -d "$VENDOR_ROOT" ]] || fail "vendor root is not mounted: $VENDOR_ROOT"
actual_sha=$(sha256sum -- "$BASE_TARBALL" | awk '{print toupper($1)}')
[[ "$actual_sha" == "${BASE_SHA256^^}" ]] || fail "Ubuntu Base archive SHA-256 mismatch"
[[ "$EUID" -eq 0 ]] || fail "run this build script as root on the Linux builder"
mount_options=$(findmnt -n -o OPTIONS --target "$VENDOR_ROOT" 2>/dev/null || true)
[[ ",$mount_options," == *,ro,* ]] || fail "vendor root must be mounted read-only (ro)"
[[ -f "$VENDOR_ROOT/etc/os-release" ]] || fail "vendor root lacks /etc/os-release"
[[ -f "$VENDOR_ROOT/boot/bImage" && -f "$VENDOR_ROOT/boot/sunxi.dtb" ]] || fail "vendor root lacks the A7Z kernel/DTB boot files"
[[ -d "$VENDOR_ROOT/lib/modules/6.6.98" ]] || fail "vendor root lacks matching Linux 6.6.98 modules"
[[ -f "$VENDOR_ROOT/lib/modules/6.6.98/pvrsrvkm.ko" ]] || fail "vendor root lacks the PowerVR kernel module"
[[ -f "$VENDOR_ROOT/lib/modules/6.6.98/modules.builtin" ]] || fail "vendor root lacks built-in module metadata"
[[ -f /proc/sys/fs/binfmt_misc/qemu-aarch64 ]] || fail "qemu-aarch64 binfmt is not registered on the build host"
grep -q '^enabled' /proc/sys/fs/binfmt_misc/qemu-aarch64 || fail "qemu-aarch64 binfmt is disabled"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
PACKAGE_FILE="$SCRIPT_DIR/packages-noble-arm64.txt"
MANIFEST="$SCRIPT_DIR/vendor-runtime-manifest.txt"
OVERLAY="$SCRIPT_DIR/overlay"
[[ -f "$PACKAGE_FILE" && -f "$MANIFEST" && -d "$OVERLAY" && -f "$SCRIPT_DIR/configure_radxa_account.sh" && -f "$SCRIPT_DIR/configure_ubuntu_apt_sources.sh" ]] || fail "package list, vendor manifest, account configurator, apt source helper or headless overlay is missing"
PACKAGES=()
declare -A SEEN_PACKAGES=()
while IFS= read -r raw || [[ -n "$raw" ]]; do
    package=${raw%%#*}
    package=${package//[[:space:]]/}
    [[ -z "$package" ]] && continue
    [[ "$package" =~ ^[a-z0-9][a-z0-9+.-]*$ ]] || fail "invalid package name in manifest: $raw"
    [[ -z "${SEEN_PACKAGES[$package]+x}" ]] || fail "duplicate package name: $package"
    case "$package" in ubuntu-desktop|ubuntu-desktop-minimal|gnome-shell|kde-plasma-desktop|plasma-desktop|xorg|xserver-xorg|gdm3|lightdm|sddm) fail "desktop package is forbidden: $package" ;; esac
    SEEN_PACKAGES[$package]=1
    PACKAGES+=("$package")
done < "$PACKAGE_FILE"
((${#PACKAGES[@]} > 0)) || fail "package manifest is empty"

mkdir -p -- "$(dirname -- "$WORK_DIR")" "$(dirname -- "$OUT_EXT4")"
mkdir -- "$WORK_DIR"
ROOTFS="$WORK_DIR/rootfs"
mkdir -- "$ROOTFS"
PROC_MOUNTED=0
POLICY_FILE="$ROOTFS/usr/sbin/policy-rc.d"
cleanup() {
    if (( PROC_MOUNTED )); then umount "$ROOTFS/proc" 2>/dev/null || true; fi
}
trap cleanup EXIT

tar --extract --gzip --file "$BASE_TARBALL" --directory "$ROOTFS" --numeric-owner --same-owner
[[ -f "$ROOTFS/etc/os-release" ]] || fail "Ubuntu Base archive did not produce /etc/os-release"
grep -qx 'ID=ubuntu' "$ROOTFS/etc/os-release" || fail "base archive ID is not Ubuntu"
grep -Eq '^VERSION_ID="?24\.04"?$' "$ROOTFS/etc/os-release" || fail "base archive is not Ubuntu 24.04"

mkdir -p "$ROOTFS/etc/apt/sources.list.d" "$ROOTFS/var/lib/dpkg" "$ROOTFS/dev" "$ROOTFS/proc"
rm -f "$ROOTFS/etc/apt/sources.list"
find "$ROOTFS/etc/apt/sources.list.d" -maxdepth 1 -type f \
    \( -name '*.list' -o -name '*.sources' \) -delete
bash "$SCRIPT_DIR/configure_ubuntu_apt_sources.sh" "$ROOTFS" bootstrap
for node in null zero random urandom tty; do
    [[ -e "$ROOTFS/dev/$node" ]] || cp -a -- "/dev/$node" "$ROOTFS/dev/$node"
done
if [[ -f /run/systemd/resolve/resolv.conf ]]; then
    rm -f "$ROOTFS/etc/resolv.conf"
    cp -L /run/systemd/resolve/resolv.conf "$ROOTFS/etc/resolv.conf"
fi
cat > "$POLICY_FILE" <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod 0755 "$POLICY_FILE"
mount -t proc proc "$ROOTFS/proc"
PROC_MOUNTED=1
chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none /usr/bin/apt-get update
chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none /usr/bin/apt-get install --yes --no-install-recommends ca-certificates
bash "$SCRIPT_DIR/configure_ubuntu_apt_sources.sh" "$ROOTFS" final
chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none /usr/bin/apt-get update
chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none /usr/bin/apt-get install --yes --no-install-recommends "${PACKAGES[@]}"
chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive /usr/bin/apt-get clean
umount "$ROOTFS/proc"
PROC_MOUNTED=0
rm -f "$POLICY_FILE"

# Keep the candidate kernel/DTB and all modules tied to that exact kernel.
mkdir -p "$ROOTFS/boot" "$ROOTFS/lib/modules" "$ROOTFS/lib/firmware"
cp -a "$VENDOR_ROOT/boot/." "$ROOTFS/boot/"
[[ ! -e "$ROOTFS/lib/modules/6.6.98" ]] || fail "Ubuntu base unexpectedly already contains Linux 6.6.98 modules"
cp -a "$VENDOR_ROOT/lib/modules/6.6.98" "$ROOTFS/lib/modules/"

# The manifest pins every imported regular vendor file to the read-only base.
while IFS=$'\t' read -r digest source_rel dest_rel || [[ -n "${digest:-}${source_rel:-}${dest_rel:-}" ]]; do
    [[ -n "${digest:-}" && "$digest" != \#* ]] || continue
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "invalid SHA-256 in vendor manifest"
    case "$source_rel" in /*|../*|*/../*|*'/..') fail "unsafe vendor source path: $source_rel" ;; esac
    case "$dest_rel" in /*|../*|*/../*|*'/..') fail "unsafe vendor destination path: $dest_rel" ;; esac
    source_file="$VENDOR_ROOT/$source_rel"
    destination="$ROOTFS/$dest_rel"
    # manifest 基于 SD 基底生成；UFS 基底的 vendor 根内容略有差异（如缺 libNBGlinker.so）。
    # 缺失条目跳过并警告；存在的内容仍由下方 SHA-256 校验兜底。
    if [[ ! -f "$source_file" ]]; then
        echo "  WARNING: vendor source missing in this base, skipping: $source_rel" >&2
        continue
    fi
    source_sha=$(sha256sum -- "$source_file" | awk '{print $1}')
    [[ "$source_sha" == "$digest" ]] || fail "vendor source SHA-256 mismatch: $source_rel"
    if [[ -e "$destination" && ! -L "$destination" ]]; then
        destination_sha=$(sha256sum -- "$destination" | awk '{print $1}')
        [[ "$destination_sha" == "$digest" ]] || fail "pre-copied vendor file SHA-256 mismatch: $dest_rel"
    else
        [[ ! -L "$destination" ]] || fail "vendor destination is a symlink: $dest_rel"
        mkdir -p -- "$(dirname -- "$destination")"
        cp -a -- "$source_file" "$destination"
        destination_sha=$(sha256sum -- "$destination" | awk '{print $1}')
        [[ "$destination_sha" == "$digest" ]] || fail "vendor copy SHA-256 mismatch: $dest_rel"
    fi
done < "$MANIFEST"

copy_link() {
    local source_rel=$1 dest_rel=$2 expected_target=$3
    local source="$VENDOR_ROOT/$source_rel" destination="$ROOTFS/$dest_rel" actual_target
    [[ -L "$source" ]] || fail "expected vendor symlink is missing: $source_rel"
    actual_target=$(readlink -- "$source")
    [[ "$actual_target" == "$expected_target" ]] || fail "vendor symlink target differs: $source_rel -> $actual_target"
    [[ ! -e "$destination" && ! -L "$destination" ]] || fail "symlink destination already exists: $dest_rel"
    mkdir -p -- "$(dirname -- "$destination")"
    ln -s -- "$expected_target" "$destination"
}

# Recreate the vendor SONAME chains without replacing Ubuntu's system libraries.
for stem in libGLESv1_CM_PVR_MESA libGLESv2_PVR_MESA libglslcompiler libpvr_dri_support libsrv_um libusc; do
    version=$(basename "$(find "$VENDOR_ROOT/usr/lib" -maxdepth 1 -type f -name "$stem.so.*" -print -quit)" 2>/dev/null || true)
    [[ -n "$version" ]] || fail "versioned PVR library missing: $stem"
    copy_link "usr/lib/$stem.so" "usr/lib/$stem.so" "$version"
done
copy_link usr/local/lib/libEGL.so usr/local/lib/libEGL.so libEGL.so.1
copy_link usr/local/lib/libEGL.so.1 usr/local/lib/libEGL.so.1 libEGL.so.1.0.0
copy_link usr/local/lib/libGLESv1_CM.so usr/local/lib/libGLESv1_CM.so libGLESv1_CM.so.1
copy_link usr/local/lib/libGLESv1_CM.so.1 usr/local/lib/libGLESv1_CM.so.1 libGLESv1_CM.so.1.1.0
copy_link usr/local/lib/libGLESv2.so usr/local/lib/libGLESv2.so libGLESv2.so.2
copy_link usr/local/lib/libGLESv2.so.2 usr/local/lib/libGLESv2.so.2 libGLESv2.so.2.0.0
copy_link usr/local/lib/libgbm.so usr/local/lib/libgbm.so libgbm.so.1
copy_link usr/local/lib/libgbm.so.1 usr/local/lib/libgbm.so.1 libgbm.so.1.0.0
copy_link usr/local/lib/libglapi.so usr/local/lib/libglapi.so libglapi.so.0
copy_link usr/local/lib/libglapi.so.0 usr/local/lib/libglapi.so.0 libglapi.so.0.0.0
copy_link usr/local/lib/libwayland-egl.so usr/local/lib/libwayland-egl.so libwayland-egl.so.1
copy_link usr/local/lib/libwayland-egl.so.1 usr/local/lib/libwayland-egl.so.1 libwayland-egl.so.1.22.0
for stem in libopencv_core libopencv_imgcodecs libopencv_imgproc; do
    real_name="${stem}.so.4.7.0"
    [[ -f "$VENDOR_ROOT/usr/lib/$real_name" ]] || fail "versioned OpenCV library missing: $real_name"
    source_link="$VENDOR_ROOT/usr/lib/${stem}.so.407"
    [[ -L "$source_link" && "$(readlink -- "$source_link")" == "$real_name" ]] || fail "OpenCV SONAME symlink differs: ${stem}.so.407"
    ln -s -- "$real_name" "$ROOTFS/opt/a7z-npu/lib/${stem}.so.407"
    ln -s -- "${stem}.so.407" "$ROOTFS/opt/a7z-npu/lib/${stem}.so"
done

install -d -m 0755 "$ROOTFS/etc/modules-load.d" "$ROOTFS/etc/ld.so.conf.d" "$ROOTFS/etc/profile.d"
printf 'pvrsrvkm\n' > "$ROOTFS/etc/modules-load.d/a7z-pvr.conf"
printf '/usr/local/lib\n' > "$ROOTFS/etc/ld.so.conf.d/00-a7z-pvr.conf"
printf '/opt/a7z-npu/lib\n' > "$ROOTFS/etc/ld.so.conf.d/50-a7z-npu.conf"
printf 'export LIBGL_DRIVERS_PATH=/usr/local/lib/dri\n' > "$ROOTFS/etc/profile.d/a7z-pvr.sh"

# Board identity, SD-root identity, first-boot setup, and headless systemd policy.
printf 'cubie-a7z\n' > "$ROOTFS/etc/hostname"
cat > "$ROOTFS/etc/hosts" <<'HOSTS'
127.0.0.1 localhost
127.0.1.1 cubie-a7z
::1 localhost ip6-localhost ip6-loopback
HOSTS
cat > "$ROOTFS/etc/fstab" <<'FSTAB'
PARTUUID=1a2b3c4d-0000-4000-8000-000000000003 / ext4 defaults,noatime,errors=remount-ro 0 1
FSTAB
install -d -m 0755 \
    "$ROOTFS/etc/NetworkManager/system-connections" \
    "$ROOTFS/etc/systemd/system/ssh.service.d" \
    "$ROOTFS/etc/systemd/system/serial-getty@ttyAS0.service.d" \
    "$ROOTFS/etc/ssh/sshd_config.d"
cp -a "$OVERLAY/etc/NetworkManager/NetworkManager.conf" "$ROOTFS/etc/NetworkManager/"
install -m 0600 "$OVERLAY/etc/NetworkManager/system-connections/a7z-wired-dhcp.nmconnection" "$ROOTFS/etc/NetworkManager/system-connections/"
cp -a "$OVERLAY/etc/systemd/system/ssh.service.d/10-generate-hostkeys.conf" "$ROOTFS/etc/systemd/system/ssh.service.d/"
cp -a "$OVERLAY/etc/systemd/system/serial-getty@ttyAS0.service.d/10-autologin.conf" "$ROOTFS/etc/systemd/system/serial-getty@ttyAS0.service.d/"
cp -a "$OVERLAY/etc/ssh/sshd_config.d/10-a7z-hardening.conf" "$ROOTFS/etc/ssh/sshd_config.d/"
bash "$SCRIPT_DIR/configure_radxa_account.sh" "$ROOTFS"
rm -f "$ROOTFS/etc/ssh/ssh_host_"*_key "$ROOTFS/etc/ssh/ssh_host_"*_key.pub
[[ ! -e "$ROOTFS/etc/machine-id" ]] || : > "$ROOTFS/etc/machine-id"
ln -sfn /run/systemd/resolve/stub-resolv.conf "$ROOTFS/etc/resolv.conf"
systemctl --root="$ROOTFS" set-default multi-user.target
systemctl --root="$ROOTFS" disable systemd-networkd.service >/dev/null 2>&1 || true
systemctl --root="$ROOTFS" enable serial-getty@ttyAS0.service NetworkManager.service systemd-resolved.service ssh.service
systemctl --root="$ROOTFS" disable weston.service >/dev/null 2>&1 || true

# Buildroot's older OpenCV/NPU SONAMEs are private to this runtime path.
chroot "$ROOTFS" /sbin/ldconfig
for executable in /etc/npu/vpm_run/vpm_run /etc/npu/yolov5/yolov5; do
    if ! loader_output=$(chroot "$ROOTFS" /lib/ld-linux-aarch64.so.1 --list "$executable" 2>&1); then
        printf '%s\n' "$loader_output" >&2
        fail "dynamic loader could not resolve $executable"
    fi
    if grep -q 'not found' <<<"$loader_output"; then
        printf '%s\n' "$loader_output" >&2
        fail "vendor runtime dependency is missing for $executable"
    fi
done
bash "$SCRIPT_DIR/verify_rootfs.sh" "$ROOTFS"

blocks=$((SIZE_BYTES / 4096))
(( blocks > 0 )) || fail "rootfs block count is invalid"
truncate -s "$SIZE_BYTES" "$OUT_TMP"
mke2fs -q -F -t ext4 -b 4096 -L ubuntu-root -d "$ROOTFS" "$OUT_TMP" "$blocks"
[[ $(stat -c %s "$OUT_TMP") == "$SIZE_BYTES" ]] || fail "ext4 output size mismatch"
e2fsck -fn "$OUT_TMP"
bash "$SCRIPT_DIR/verify_rootfs.sh" "$ROOTFS"
[[ ! -e "$OUT_EXT4" && ! -L "$OUT_EXT4" ]] || fail "output appeared during build; refusing publication"
mv -- "$OUT_TMP" "$OUT_EXT4"
sha256sum -- "$OUT_EXT4"
echo "PASS: Ubuntu 24.04 ARM64 rootfs ext4 built at $OUT_EXT4"
