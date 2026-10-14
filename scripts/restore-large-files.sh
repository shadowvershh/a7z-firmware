#!/usr/bin/env bash
# Restore the Tina "large files" (omitted from Git) into a synced SDK checkout.
#
#   restore-large-files.sh <sdk-dir> <large-files-tree>
#
# <large-files-tree> is the directory that contains
#   tina5.0_aiot/<project-path>/aiot-linux-v1.5.0-large-files.tar.zst
#
# The manifest maps project names (e.g. lichee/arisc) to checkout paths
# (e.g. brandy/arisc), so we parse the manifest instead of guessing.
set -Eeuo pipefail

SDK=${1:?usage: restore-large-files.sh <sdk-dir> <large-files-tree>}
LF=${2:?usage: restore-large-files.sh <sdk-dir> <large-files-tree>}

[[ -d "$SDK" ]] || { echo "ERROR: SDK not found: $SDK"; exit 1; }
[[ -d "$LF"  ]] || { echo "ERROR: large-files tree not found: $LF"; exit 1; }

MANIFEST=$(find "$SDK/.repo/manifests" -name 'tina5.0_aiot-linux-v1.5.0.xml' | head -1)
if [[ -z "$MANIFEST" ]]; then
    MANIFEST=$(find "$SDK/.repo/manifests" -name '*.xml' | head -1)
fi
[[ -n "$MANIFEST" ]] || { echo "ERROR: no manifest under $SDK/.repo/manifests"; exit 1; }
echo "==> manifest: $MANIFEST"

MAP=$(mktemp)
trap 'rm -f "$MAP"' EXIT
python3 - "$MANIFEST" > "$MAP" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
for project in root.iter("project"):
    name = project.get("name")
    if not name:
        continue
    path = project.get("path") or name
    print("%s\t%s" % (name, path))
PY

restored=0
while IFS=$'\t' read -r name path; do
    [[ -n "$name" ]] || continue
    archive="$LF/tina5.0_aiot/$name/aiot-linux-v1.5.0-large-files.tar.zst"
    [[ -f "$archive" ]] || continue
    dest="$SDK/$path"
    if [[ ! -d "$dest" ]]; then
        echo "  skip $name (not synced: $dest)"
        continue
    fi
    echo "  restore $name -> $path  ($(du -h "$archive" | cut -f1))"
    tar --zstd -xf "$archive" -C "$dest"
    restored=$((restored + 1))
done < "$MAP"

echo "==> restored $restored large-file package(s)"
if [[ "$restored" -eq 0 ]]; then
    echo "WARNING: nothing restored - check the large-files tree layout" >&2
fi
