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
readonly RECIPE='ubuntu-mangoapp-v1'
prefix="$APP_HOME/.runtime/bin"
manifest="$APP_HOME/.runtime/mangoapp-build.id"
build_id="$SOURCE_SHA/$RECIPE/$(getconf GNU_LIBC_VERSION)"
loadable() {
  local output
  [[ -x "$1" ]] || return 1
  output="$(LC_ALL=C ldd "$1" 2>&1)" || return 1
  [[ "$output" != *'not found'* ]]
}
if [[ "$(cat "$manifest" 2>/dev/null || true)" == "$build_id" ]] &&
   loadable "$prefix/mangoapp" && loadable "$prefix/mangohudctl"; then
  echo 'MWM MangoApp: compatible Ubuntu build already installed'
  exit 0
fi
sudo apt-get install -y build-essential meson ninja-build pkg-config python3-mako git \
  libgl-dev libegl-dev libglfw3-dev libx11-dev libwayland-dev libxkbcommon-dev libdbus-1-dev libdrm-dev
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
env PATH="/usr/bin:/bin:$PATH" /usr/bin/meson setup "$buildroot/build" "$buildroot/MangoHud" \
  -Dmangoapp=true -Dmangohudctl=true -Dwith_xnvctrl=disabled -Dwith_nvml=disabled \
  -Dmangoplot=disabled -Dtests=disabled -Duse_system_spdlog=disabled -Dbuildtype=release
/usr/bin/meson compile -C "$buildroot/build" -j 2 mangoapp mangohudctl
loadable "$buildroot/build/src/mangoapp"
loadable "$buildroot/build/src/mangohudctl"
# Only complete, loadable builds replace the user-local renderer/control pair.
install -m 0755 "$buildroot/build/src/mangoapp" "$prefix/.mangoapp.new"
install -m 0755 "$buildroot/build/src/mangohudctl" "$prefix/.mangohudctl.new"
mv -- "$prefix/.mangoapp.new" "$prefix/mangoapp"
mv -- "$prefix/.mangohudctl.new" "$prefix/mangohudctl"
printf '%s\n' "$build_id" > "$manifest"
echo 'MWM MangoApp: Ubuntu build installed (system MangoApp unchanged)'
