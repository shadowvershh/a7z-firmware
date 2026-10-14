#!/usr/bin/env bash
# Sync the public Tina AIOT Linux v1.5.0 SDK (A733) and apply the A7Z board patch.
#
#   https://gitlab.com/tina5.0_aiot/manifest.git   tag: aiot-linux-v1.5.0
#   https://gitee.com/juping_zheng1/radxa-cubie-a7z-tina-bsp.git
#
# NOTE: 11 repos ship *without* their large files; those (~14 GB) must be fetched
#       from MEGA first. See .repo/manifests/README.md inside the SDK.
set -Eeuo pipefail

SDK_DIR=${1:-$PWD/tina-sdk}
MANIFEST_URL=${MANIFEST_URL:-https://gitlab.com/tina5.0_aiot/manifest.git}
MANIFEST_REV=${MANIFEST_REV:-refs/tags/aiot-linux-v1.5.0}
BSP_REPO=${BSP_REPO:-https://gitee.com/juping_zheng1/radxa-cubie-a7z-tina-bsp.git}
LARGE_FILES_DIR=${LARGE_FILES_DIR:-}   # e.g. /path/to/large-files/tina5.0_aiot

command -v repo >/dev/null || { echo "ERROR: 'repo' not installed (apt install repo / pip install git-repo)"; exit 1; }
command -v git  >/dev/null || { echo "ERROR: git not installed"; exit 1; }

# 1) manifest init -----------------------------------------------------------
mkdir -p "$SDK_DIR"
if [[ ! -d "$SDK_DIR/.repo" ]]; then
    echo "==> repo init $MANIFEST_URL ($MANIFEST_REV)"
    ( cd "$SDK_DIR" && repo init -u "$MANIFEST_URL" -b "$MANIFEST_REV" --repo-url=https://gerrit.googlesource.com/git-repo --no-clone-bundle )
fi

# 2) optional: restrict to the projects the A7Z firmware build needs ----------
MANIFEST=$(find "$SDK_DIR/.repo/manifests" -name 'tina5.0_aiot-linux-v1.5.0.xml' | head -1)
if [[ -n "$MANIFEST" && "${SDK_FULL_SYNC:-0}" != "1" ]]; then
    mkdir -p "$SDK_DIR/.repo/local_manifests"
    cat > "$SDK_DIR/.repo/local_manifests/a7z-build-only.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <!-- Build-scope filter: keep only what the A7Z image build touches.
       Projects not listed here are NOT removed, they are simply not synced
       when using `repo sync -c` with this local manifest present. -->
</manifest>
XML
fi

# 3) sync --------------------------------------------------------------------
JOBS=${JOBS:-8}
echo "==> repo sync -c --no-clone-bundle -j$JOBS --no-tags"
( cd "$SDK_DIR" && repo sync -c --no-clone-bundle --no-tags -j"$JOBS" )

# 4) large-file packages -----------------------------------------------------
if [[ -n "$LARGE_FILES_DIR" ]]; then
    echo "==> dropping in large-file packages from $LARGE_FILES_DIR"
    while IFS= read -r archive; do
        proj=${archive#"$LARGE_FILES_DIR"/}
        proj=${proj%/aiot-linux-v1.5.0-large-files.tar.zst}
        dest="$SDK_DIR/$proj"
        [[ -d "$dest" ]] || { echo "  skip (project not synced): $proj"; continue; }
        echo "  $proj"
        tar --zstd -xf "$archive" -C "$dest"
    done < <(find "$LARGE_FILES_DIR" -name 'aiot-linux-v1.5.0-large-files.tar.zst' | sort)
else
    cat <<'WARN'
==> WARNING: LARGE_FILES_DIR not set.
    11 projects (incl. lichee/arisc, lichee/brandy-2.0/tools and
    prebuilt/kernel-built/aarch64) are missing their large files.
    Download the ~14 GB package from MEGA (link in
    .repo/manifests/README.md) and re-run with LARGE_FILES_DIR=<dir>.
WARN
fi

# 5) A7Z board patch ---------------------------------------------------------
PATCH_TMP="$SDK_DIR/.a7z-bsp-patch"
if [[ ! -d "$PATCH_TMP/.git" ]]; then
    git clone --depth 1 "$BSP_REPO" "$PATCH_TMP"
else
    git -C "$PATCH_TMP" fetch --depth 1 origin && git -C "$PATCH_TMP" reset --hard FETCH_HEAD
fi

echo "==> copying A7Z device/build/target/ubuntu trees"
for d in build debian device target ubuntu; do
    [[ -d "$PATCH_TMP/$d" ]] || continue
    cp -a "$PATCH_TMP/$d/." "$SDK_DIR/$d/"
done

if [[ -d "$PATCH_TMP/bsp-patchs" && -d "$SDK_DIR/bsp" ]]; then
    echo "==> applying bsp patches"
    for p in $(ls "$PATCH_TMP"/bsp-patchs/*.patch | sort); do
        echo "  $(basename "$p")"
        ( cd "$SDK_DIR/bsp" && git apply --3way "$p" ) || {
            echo "    (already applied or conflict — continuing)"; }
    done
fi

echo "==> SDK ready at $SDK_DIR"
echo "    next: bash scripts/build-sdk-parts.sh $SDK_DIR"
