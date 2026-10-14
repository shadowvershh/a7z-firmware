#!/usr/bin/env bash
# Run this ONCE on a machine that already has the synced Tina SDK.
# It produces the ~1 GB "large files" bundle that GitHub Actions needs,
# so the CI never has to touch MEGA.
#
#   ./scripts/make-large-files-bundle.sh /path/to/tina-sdk out/tina-a7z-large-files.tar.zst
#
# Then upload it to the Release named "inputs":
#   gh release upload inputs out/tina-a7z-large-files.tar.zst
set -Eeuo pipefail

SDK=${1:?usage: make-large-files-bundle.sh /path/to/tina-sdk [out.tar.zst]}
OUT=${2:-$PWD/tina-a7z-large-files.tar.zst}

[[ -d "$SDK" ]] || { echo "ERROR: SDK not found: $SDK"; exit 1; }
command -v zstd >/dev/null || { echo "ERROR: zstd not installed"; exit 1; }

# Only the three projects the A7Z firmware build actually needs.
PROJECTS=(
  "brandy/arisc"                              # RISC-V toolchain -> SCP firmware
  "prebuilt/kernelbuilt/aarch64"              # AArch64 toolchain -> kernel modules
  "brandy/brandy-2.0/tools"                   # boot0/boot-package pack tools
)

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
STAGE="$TMP/tina-a7z-large-files"
mkdir -p "$STAGE"

missing=0
for p in "${PROJECTS[@]}"; do
    if [[ -d "$SDK/$p" ]]; then
        echo "==> staging $p ($(du -sh "$SDK/$p" | cut -f1))"
        mkdir -p "$STAGE/$p"
        # keep vendor binaries but drop VCS metadata
        rsync -a --exclude '.git' "$SDK/$p/" "$STAGE/$p/"
    else
        echo "!! missing: $SDK/$p"
        missing=1
    fi
done
[[ "$missing" -eq 0 ]] || { echo "ERROR: SDK incomplete; sync it first"; exit 1; }

mkdir -p "$(dirname "$OUT")"
echo "==> compressing -> $OUT"
tar --zstd -cf "$OUT" -C "$TMP" "$(basename "$STAGE")"

echo "==> done"
ls -lh "$OUT"
sha256sum "$OUT" | tee "$OUT.sha256"
echo
echo "next:"
echo "  gh release upload inputs $OUT"
