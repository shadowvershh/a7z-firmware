#!/usr/bin/env bash
# Mount the freshly built rootfs ext4 and apply the extra A7Z overlay
# (AIC WiFi modules + USB firmware + systemd-timesyncd + NTP config + tz).
set -Eeuo pipefail

ROOTFS_EXT4=${1:?usage: apply_extra_overlay.sh ROOTFS.ext4 OVERLAY_DIR}
OVERLAY_DIR=${2:?usage: apply_extra_overlay.sh ROOTFS.ext4 OVERLAY_DIR}
[[ -f "$ROOTFS_EXT4" ]] || { echo "rootfs ext4 not found: $ROOTFS_EXT4" >&2; exit 1; }
[[ -d "$OVERLAY_DIR" ]] || { echo "overlay dir not found: $OVERLAY_DIR" >&2; exit 1; }
[[ "$(id -u)" -eq 0 ]] || { echo "must run as root" >&2; exit 1; }

MNT=$(mktemp -d)
LOOP=""
cleanup() {
    sync || true
    mountpoint -q "$MNT" && umount -l "$MNT" 2>/dev/null || true
    [[ -n "$LOOP" ]] && losetup -d "$LOOP" 2>/dev/null || true
    rmdir "$MNT" 2>/dev/null || true
}
trap cleanup EXIT

LOOP=$(losetup -f --show "$ROOTFS_EXT4")
mount "$LOOP" "$MNT"

# 1) copy overlay payload onto the target rootfs (following /lib -> usr/lib)
rsync -a --chown=0:0 "$OVERLAY_DIR"/ "$MNT"/

# 2) enable systemd-timesyncd (offline enable: plain symlinks)
install -d -m 0755 "$MNT/etc/systemd/system/sysinit.target.wants"
ln -sfn /usr/lib/systemd/system/systemd-timesyncd.service \
        "$MNT/etc/systemd/system/sysinit.target.wants/systemd-timesyncd.service"
ln -sfn /usr/lib/systemd/system/systemd-timesyncd.service \
        "$MNT/etc/systemd/system/dbus-org.freedesktop.timesync1.service"

# 3) timezone = Asia/Shanghai (no RTC on A7Z; NTP corrects the clock at boot)
ln -sfn /usr/share/zoneinfo/Asia/Shanghai "$MNT/etc/localtime"
printf 'Asia/Shanghai\n' > "$MNT/etc/timezone"

# 4) regenerate module dependency map so the AIC modules can be autoloaded
if [[ -x "$MNT/usr/sbin/depmod" ]] || [[ -x "$MNT/sbin/depmod" ]]; then
    chroot "$MNT" depmod -a 6.6.98 || depmod -b "$MNT" 6.6.98
else
    depmod -b "$MNT" 6.6.98
fi

echo "extra overlay applied to $ROOTFS_EXT4"
