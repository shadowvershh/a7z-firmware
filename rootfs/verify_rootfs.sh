#!/usr/bin/env bash
set -euo pipefail

root=${1:?usage: verify_rootfs.sh ROOT_DIR}
root=$(readlink -f -- "$root")
fail() { echo "FAIL: $*" >&2; exit 1; }
need_file() { [[ -f "$root/$1" ]] || fail "missing $1"; }
need_link() { [[ -L "$root/$1" ]] || fail "missing enabled unit link $1"; }

[[ -d "$root/etc" && -d "$root/var/lib/dpkg" ]] || fail "not a root filesystem tree"
need_file etc/os-release
grep -qx 'ID=ubuntu' "$root/etc/os-release" || fail "OS ID is not Ubuntu"
grep -Eq '^VERSION_ID="?24\.04"?$' "$root/etc/os-release" || fail "OS is not Ubuntu 24.04"
need_file var/lib/dpkg/status
if [[ -f "$root/var/lib/dpkg/arch" ]] && ! grep -qx 'arm64' "$root/var/lib/dpkg/arch"; then fail "dpkg architecture is not arm64"; fi

is_installed() {
    local wanted=$1
    awk -v wanted="$wanted" 'BEGIN { RS=""; FS="\n" }
        { package=""; status=""; architecture="";
          for (i=1; i<=NF; i++) {
            if ($i ~ /^Package: /) { package=substr($i,10) }
            else if ($i ~ /^Status: /) { status=substr($i,9) }
            else if ($i ~ /^Architecture: /) { architecture=substr($i,15) }
          }
          if (package==wanted && status=="install ok installed" && (architecture=="arm64" || architecture=="all")) found=1
        }
        END { exit !found }' "$root/var/lib/dpkg/status"
}
for package in systemd systemd-sysv systemd-resolved udev adduser passwd sudo openssh-server kmod iproute2 network-manager wpasupplicant glmark2-es2-wayland weston; do
    is_installed "$package" || fail "required package missing/not installed for arm64: $package"
done

need_file etc/apt/sources.list.d/ubuntu.sources
apt_sources="$root/etc/apt/sources.list.d/ubuntu.sources"
grep -Fqx 'URIs: https://mirrors.ustc.edu.cn/ubuntu-ports/' "$apt_sources" || fail "APT source URI is not the approved USTC mirror"
grep -Fqx 'Suites: noble noble-updates noble-security' "$apt_sources" || fail "APT source suites are not the approved Noble suites"
grep -Fqx 'Components: main universe' "$apt_sources" || fail "APT source components differ from the approved set"
grep -Fqx 'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg' "$apt_sources" || fail "APT source does not use the Ubuntu archive signing keyring"
grep -Fqx 'Architectures: arm64' "$apt_sources" || fail "APT source is not restricted to arm64"
if grep -Eqi '(^|[[:space:]])trusted[[:space:]]*=[[:space:]]*yes([[:space:]]|$)' "$apt_sources"; then fail "APT source must not bypass signature verification"; fi
for source_file in "$root/etc/apt/sources.list" "$root"/etc/apt/sources.list.d/*.list "$root"/etc/apt/sources.list.d/*.sources; do
    [[ -e "$source_file" ]] || continue
    [[ "$source_file" == "$apt_sources" ]] || fail "unexpected APT source file: ${source_file#"$root"/}"
done
[[ -x "$root/usr/bin/nmtui" ]] || fail "nmtui executable is missing"
need_file etc/NetworkManager/NetworkManager.conf
grep -Eq '^plugins[[:space:]]*=[[:space:]]*keyfile$' "$root/etc/NetworkManager/NetworkManager.conf" || fail "NetworkManager keyfile plugin is not configured"
grep -Eq '^dns[[:space:]]*=[[:space:]]*systemd-resolved$' "$root/etc/NetworkManager/NetworkManager.conf" || fail "NetworkManager DNS is not integrated with systemd-resolved"
wired_profile="$root/etc/NetworkManager/system-connections/a7z-wired-dhcp.nmconnection"
[[ -f "$wired_profile" ]] || fail "NetworkManager wired DHCP profile is missing"
wired_mode=$(stat -c '%a' "$wired_profile" 2>/dev/null || true)
[[ "$wired_mode" == "600" ]] || fail "NetworkManager wired DHCP profile permissions must be 0600"
awk '
    /^\[/ { section=$0; next }
    section=="[connection]" && $0=="id=A7Z wired DHCP" { id=1 }
    section=="[connection]" && $0=="type=ethernet" { type=1 }
    section=="[connection]" && $0=="autoconnect=true" { autoconnect=1 }
    section=="[ipv4]" && $0=="method=auto" { ipv4=1 }
    section=="[ipv6]" && $0=="method=auto" { ipv6=1 }
    END { exit !(id && type && autoconnect && ipv4 && ipv6) }
' "$wired_profile" || fail "NetworkManager wired DHCP profile must autoconnect over ethernet using automatic IPv4 and IPv6"
[[ -L "$root/etc/resolv.conf" ]] || fail "/etc/resolv.conf is not linked to systemd-resolved"
resolved_conf=$(readlink "$root/etc/resolv.conf" 2>/dev/null || true)
[[ "$resolved_conf" == "/run/systemd/resolve/stub-resolv.conf" ]] || fail "/etc/resolv.conf does not use the systemd-resolved stub"

if awk 'BEGIN { RS=""; FS="\n" }
    { p=""; s=""; for (i=1;i<=NF;i++) { if ($i~/^Package: /) p=substr($i,10); if ($i~/^Status: /) s=substr($i,9) }
      if (s=="install ok installed" && p ~ /^(ubuntu-desktop|ubuntu-desktop-minimal|gnome-shell|kde-plasma-desktop|plasma-desktop|xorg|xserver-xorg|gdm3|lightdm|sddm)$/) bad=p }
    END { if (bad!="") { print bad; exit 0 } exit 1 }' "$root/var/lib/dpkg/status" | grep -q .; then
    fail "desktop/display-manager package is installed"
fi

default_target=$(readlink "$root/etc/systemd/system/default.target" 2>/dev/null || true)
[[ "$default_target" == *multi-user.target ]] || fail "default systemd target is not multi-user.target"
need_link etc/systemd/system/getty.target.wants/serial-getty@ttyAS0.service
need_link etc/systemd/system/multi-user.target.wants/NetworkManager.service
networkd_link=$(find "$root/etc/systemd/system" -type l -name 'systemd-networkd*' -print -quit 2>/dev/null || true)
[[ -z "$networkd_link" ]] || fail "systemd-networkd unit/socket is enabled: ${networkd_link#"$root"/}"
networkd_profile=$(find "$root/etc/systemd/network" \
    \( -type f -o -type l \) \
    \( -name '*.network' -o -name '*.netdev' \) -print -quit 2>/dev/null || true)
[[ -z "$networkd_profile" ]] || fail "stale systemd-networkd profile remains: ${networkd_profile#"$root"/}"
need_link etc/systemd/system/sysinit.target.wants/systemd-resolved.service
need_link etc/systemd/system/multi-user.target.wants/ssh.service
if [[ -L "$root/etc/systemd/system/multi-user.target.wants/weston.service" || -L "$root/etc/systemd/system/graphical.target.wants/weston.service" ]]; then fail "Weston is enabled persistently"; fi
need_file etc/systemd/system/serial-getty@ttyAS0.service.d/10-autologin.conf
grep -Eq 'agetty .*--autologin[[:space:]]+radxa([[:space:]]|$)' "$root/etc/systemd/system/serial-getty@ttyAS0.service.d/10-autologin.conf" || fail "serial console is not configured to autologin radxa"
need_file etc/systemd/system/ssh.service.d/10-generate-hostkeys.conf
grep -q 'ssh-keygen -A' "$root/etc/systemd/system/ssh.service.d/10-generate-hostkeys.conf" || fail "SSH host keys are not generated at runtime"
if [[ -e "$root/etc/systemd/system/a7z-firstboot-account.service" || -e "$root/usr/local/sbin/a7z-firstboot-account" || -L "$root/etc/systemd/system/multi-user.target.wants/a7z-firstboot-account.service" ]]; then fail "obsolete firstboot account prompt remains in rootfs"; fi

need_file etc/ssh/sshd_config.d/10-a7z-hardening.conf
grep -Eq '^PermitRootLogin[[:space:]]+no$' "$root/etc/ssh/sshd_config.d/10-a7z-hardening.conf" || fail "root SSH login is not disabled"
grep -Eq '^PasswordAuthentication[[:space:]]+yes$' "$root/etc/ssh/sshd_config.d/10-a7z-hardening.conf" || fail "SSH password authentication is not enabled"
grep -Eq '^PubkeyAuthentication[[:space:]]+yes$' "$root/etc/ssh/sshd_config.d/10-a7z-hardening.conf" || fail "SSH public-key authentication is not enabled"
grep -Eq '^AllowUsers[[:space:]]+radxa$' "$root/etc/ssh/sshd_config.d/10-a7z-hardening.conf" || fail "SSH password account is not restricted to radxa"
if compgen -G "$root/etc/ssh/ssh_host_*_key" >/dev/null; then fail "SSH private host key was baked into the image"; fi
if compgen -G "$root/home/*/.ssh/authorized_keys" >/dev/null; then fail "an SSH authorized key was baked into the image"; fi
need_file etc/passwd
need_file etc/group
need_file etc/shadow
need_file etc/sudoers
awk -F: '$1=="radxa" && $3!=0 && $6=="/home/radxa" && $7=="/bin/bash" { ok=1 } END { exit !ok }' "$root/etc/passwd" || fail "radxa account is missing or is not an ordinary shell user"
awk -F: '$1=="sudo" { n=split($4, members, ","); for (i=1;i<=n;i++) if (members[i]=="radxa") ok=1 } END { exit !ok }' "$root/etc/group" || fail "radxa is not a member of sudo"
for required_group in video render; do
    awk -F: -v group="$required_group" -v user=radxa '$1==group { n=split($4, members, ","); for (i=1;i<=n;i++) if (members[i]==user) ok=1 } END { exit !ok }' "$root/etc/group" || fail "radxa is not a member of $required_group"
done
awk -F: '$1=="radxa" && $2!="" && $2 !~ /^[!*]/ { ok=1 } END { exit !ok }' "$root/etc/shadow" || fail "radxa password is missing or locked"
awk -F: '$1=="root" && $2 !~ /^[!*]/ { bad=1 } END { exit bad }' "$root/etc/shadow" || fail "root account is not locked"
for sudo_file in "$root/etc/sudoers" "$root/etc/sudoers.d"/*; do
    [[ -f "$sudo_file" ]] || continue
    if grep -Eq 'NOPASSWD:' "$sudo_file"; then fail "sudo must remain password-protected"; fi
done
need_file etc/fstab
grep -Eq '^PARTUUID=1a2b3c4d-0000-4000-8000-000000000003[[:space:]]+/[[:space:]]+ext4([[:space:]]|$)' "$root/etc/fstab" || fail "fstab root does not use the approved p3 PARTUUID"

need_file boot/bImage
need_file boot/sunxi.dtb
need_file boot/extlinux/extlinux.conf
grep -q 'root=PARTUUID=1a2b3c4d-0000-4000-8000-000000000003' "$root/boot/extlinux/extlinux.conf" || fail "extlinux does not root on SD p3 PARTUUID"
need_file lib/modules/6.6.98/pvrsrvkm.ko
need_file lib/modules/6.6.98/modules.builtin
grep -q 'vipcore.ko' "$root/lib/modules/6.6.98/modules.builtin" || fail "NPU vipcore builtin metadata is missing"
need_file lib/firmware/rgx.fw.36.56.104.183
need_file lib/firmware/rgx.sh.36.56.104.183
need_file usr/lib/libGLESv2_PVR_MESA.so.24.2.6603887
need_link usr/lib/libGLESv2_PVR_MESA.so
need_file usr/lib/libpvr_dri_support.so.24.2.6603887
need_link usr/lib/libpvr_dri_support.so
need_link usr/lib/libglslcompiler.so
need_link usr/lib/libusc.so
need_link usr/lib/libsrv_um.so
need_file usr/lib/libsrv_um.so.24.2.6603887
need_file usr/local/lib/dri/pvr_dri.so
need_file usr/local/lib/libEGL.so.1.0.0
need_link usr/local/lib/libEGL.so.1
need_file usr/local/lib/libGLESv1_CM.so.1.1.0
need_link usr/local/lib/libGLESv1_CM.so.1
need_file usr/local/lib/libGLESv2.so.2.0.0
need_link usr/local/lib/libGLESv2.so.2
need_file usr/local/lib/libgbm.so.1.0.0
need_link usr/local/lib/libgbm.so.1
need_file usr/local/lib/libglapi.so.0.0.0
need_link usr/local/lib/libglapi.so.0
need_file opt/a7z-npu/lib/libNBGlinker.so
need_file opt/a7z-npu/lib/libVIPhal.so
need_file opt/a7z-npu/lib/libopencv_core.so.4.7.0
need_link opt/a7z-npu/lib/libopencv_core.so.407
need_file opt/a7z-npu/lib/libopencv_imgcodecs.so.4.7.0
need_link opt/a7z-npu/lib/libopencv_imgcodecs.so.407
need_file opt/a7z-npu/lib/libopencv_imgproc.so.4.7.0
need_link opt/a7z-npu/lib/libopencv_imgproc.so.407
need_file etc/npu/vpm_run/vpm_run
need_file etc/npu/vpm_run/network_binary.nb
need_file etc/npu/yolov5/yolov5
need_file etc/npu/yolov5/model/yolov5.nb
need_file etc/ld.so.conf.d/50-a7z-npu.conf
need_file etc/ld.so.conf.d/00-a7z-pvr.conf

echo "PASS: Ubuntu 24.04 ARM64 headless rootfs structure and board runtime files verified"



