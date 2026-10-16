#!/usr/bin/env bash
set -euo pipefail

rootfs=${1:?usage: configure_radxa_account.sh ROOTFS}
[[ -d "$rootfs/etc" && -x "$rootfs/usr/sbin/adduser" ]] || { echo "ERROR: target Ubuntu rootfs is incomplete" >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || { echo "ERROR: run as root; only the target rootfs is changed" >&2; exit 1; }
if chroot "$rootfs" /usr/bin/getent passwd radxa >/dev/null; then
    echo "ERROR: refusing to overwrite an existing radxa account" >&2
    exit 1
fi
chroot "$rootfs" /usr/sbin/adduser --disabled-password --gecos Radxa radxa
chroot "$rootfs" /usr/sbin/usermod --append --groups sudo,video,render radxa
# Explicit user-requested default. Change before exposing SSH to an untrusted network.
printf '%s:%s\n' radxa radxa | chroot "$rootfs" /usr/sbin/chpasswd
echo "Configured the default radxa sudo account."
