#!/usr/bin/env bash
set -Eeuo pipefail

usage() { echo "usage: configure_ubuntu_apt_sources.sh ROOTFS bootstrap|final" >&2; }
fail() { echo "ERROR: $*" >&2; exit 1; }
root=${1:-}
phase=${2:-}
[[ -n "$root" && -n "$phase" ]] || { usage; exit 2; }
[[ -d "$root" ]] || fail "target rootfs directory is missing: $root"
case "$phase" in
    bootstrap) uri='http://mirrors.ustc.edu.cn/ubuntu-ports/' ;;
    final) uri='https://mirrors.ustc.edu.cn/ubuntu-ports/' ;;
    *) fail "unsupported APT source phase: $phase" ;;
esac
source_dir="$root/etc/apt/sources.list.d"
install -d -m 0755 "$source_dir"
source_file="$source_dir/ubuntu.sources"
tmp_file="$source_file.tmp"
cleanup() { rm -f -- "$tmp_file"; }
trap cleanup EXIT
cat > "$tmp_file" <<SOURCES
Types: deb
URIs: $uri
Suites: noble noble-updates noble-security
Components: main universe
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
Architectures: arm64
SOURCES
chmod 0644 "$tmp_file"
mv -f -- "$tmp_file" "$source_file"
