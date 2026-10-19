#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Build the existing MWM MangoApp source against Ubuntu's own host libraries.
set -Eeuo pipefail
(( $# == 3 )) || { echo 'Usage: build-ubuntu-mangoapp.sh APP_HOME STATE SOURCE_ROOT' >&2; exit 2; }
[[ $EUID -ne 0 ]] || { echo 'Run as the desktop user, not root.' >&2; exit 1; }
source /etc/os-release
[[ "${ID:-}" == ubuntu && "$(uname -m)" == x86_64 ]] || exit 2
APP_HOME=$1
STATE=$2
SOURCE_ROOT=$3
readonly SOURCE_SHA='f0369405be31eadb0f10abfc120ddd7c0f7eabfcee8da999de40f5402c277693'
readonly SOURCE_URL='https://raw.githubusercontent.com/relorah/mltd-waydroid-manager/f387c602a27234d9dfd245a36c55ae70bb72d479/mwm/vendor/mangoapp/MangoHud-0.8.4-mwm-source.tar.gz'
readonly RECIPE='ubuntu-mangoapp-sdk-v2'
prefix="$APP_HOME/.runtime/bin"
manifest="$APP_HOME/.runtime/mangoapp-build.id"
build_id="$SOURCE_SHA/$RECIPE/$(getconf GNU_LIBC_VERSION)"
loadable() {
  local output
  [[ -x "$1" ]] || return 1
  output="$(env -u LD_LIBRARY_PATH LC_ALL=C ldd "$1" 2>&1)" || return 1
  [[ "$output" != *'not found'* ]]
}
if [[ "$(cat "$manifest" 2>/dev/null || true)" == "$build_id" ]] &&
   loadable "$prefix/mangoapp" && loadable "$prefix/mangohudctl"; then
  echo 'MWM MangoApp: compatible Ubuntu build already installed'
  exit 0
fi
sdk_log="$STATE/mangoapp-sdk.log"
mkdir -p "$STATE"
sdk="$(python3 "$SOURCE_ROOT/packaging/ubuntu-build-sdk.py" "$APP_HOME/.runtime/build-sdk" 2>"$sdk_log")"
export PATH="$sdk/usr/bin:$PATH"
export PYTHONPATH="$sdk/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export PKG_CONFIG_PATH="$sdk/usr/lib/x86_64-linux-gnu/pkgconfig:$sdk/usr/share/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR="$sdk"
export LD_LIBRARY_PATH="$sdk/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$STATE" "$prefix"
archive="$STATE/MangoHud-mwm-source.tar.gz"
bundled="$SOURCE_ROOT/mwm/vendor/mangoapp/MangoHud-0.8.4-mwm-source.tar.gz"
if [[ -f "$bundled" ]]; then
  cp -- "$bundled" "$archive"
else
  curl --proto '=https' --tlsv1.2 -fL --retry 3 "$SOURCE_URL" -o "$archive.part"
  mv -- "$archive.part" "$archive"
fi
printf '%s  %s\n' "$SOURCE_SHA" "$archive" | sha256sum -c -
buildroot="$(mktemp -d "$STATE/mangoapp-build.XXXXXX")"
# Preserve failed build output for diagnosis; never run a broad recursive clean.
echo "MWM MangoApp build directory: $buildroot"
tar -xzf "$archive" -C "$buildroot" --no-same-owner
# Wrap downloads are version/hash pinned by the corresponding source archive.
# Link a private static spdlog/fmt rather than the newer CachyOS shared ABI.
meson setup "$buildroot/build" "$buildroot/MangoHud" \
  -Dmangoapp=true -Dmangohudctl=true -Dwith_xnvctrl=disabled -Dwith_nvml=disabled \
  -Dmangoplot=disabled -Dtests=disabled -Duse_system_spdlog=disabled -Dbuildtype=release
meson compile -C "$buildroot/build" -j 2 mangoapp mangohudctl
loadable "$buildroot/build/src/mangoapp"
loadable "$buildroot/build/src/mangohudctl"
# Preserve only the extra GLFW runtime privately, and remove SDK build paths.
# The source and copyright remain recorded beside the per-host build.
mkdir -p "$APP_HOME/.runtime/lib" "$APP_HOME/.runtime/licenses"
if [[ -f "$sdk/usr/lib/x86_64-linux-gnu/libglfw.so.3" ]]; then
  install -m 0644 "$(readlink -f "$sdk/usr/lib/x86_64-linux-gnu/libglfw.so.3")" "$APP_HOME/.runtime/lib/.libglfw.so.3.new"
  mv -- "$APP_HOME/.runtime/lib/.libglfw.so.3.new" "$APP_HOME/.runtime/lib/libglfw.so.3"
  cp -- "$sdk/usr/share/doc/libglfw3/copyright" "$APP_HOME/.runtime/licenses/libglfw3-copyright"
fi
cp -- "${sdk%/root}/packages.json" "$APP_HOME/.runtime/mangoapp-build-packages.json"
install -m 0755 "$buildroot/build/src/mangoapp" "$prefix/.mangoapp.new"
install -m 0755 "$buildroot/build/src/mangohudctl" "$prefix/.mangohudctl.new"
patchelf --set-rpath '$ORIGIN/../lib' "$prefix/.mangoapp.new"
patchelf --set-rpath '$ORIGIN/../lib' "$prefix/.mangohudctl.new"
loadable "$prefix/.mangoapp.new"
loadable "$prefix/.mangohudctl.new"
mv -- "$prefix/.mangoapp.new" "$prefix/mangoapp"
mv -- "$prefix/.mangohudctl.new" "$prefix/mangohudctl"
printf '%s\n' "$build_id" > "$manifest"
echo 'MWM MangoApp: Ubuntu build installed (system MangoApp unchanged)'
