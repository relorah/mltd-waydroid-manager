#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Sourced by install.sh; user runtime stays isolated from system Python.
ubuntu_candidate() {
  local candidate
  candidate="$(LC_ALL=C apt-cache policy "$1" | awk '/Candidate:/ {print $2; exit}')"
  [[ -n "$candidate" && "$candidate" != '(none)' ]]
}

install_ubuntu_packages() {
  sudo apt-get update
  # Gamescope is in multiverse; PyGObject and layer-shell are in universe.
  sudo apt-get install -y software-properties-common
  sudo add-apt-repository -y universe
  sudo add-apt-repository -y multiverse
  sudo apt-get update
  local -a packages=(python3 python-is-python3 python3-venv python3-pip
    python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0
    gir1.2-gtklayershell-0.1 libgtk-layer-shell0 polkitd pkexec zstd rsync
    xwayland mesa-vulkan-drivers libvulkan1 libxcb-cursor0 libxkbcommon-x11-0
    libegl1 libgl1 libopengl0 libdbus-1-3 libxcb-icccm4 libxcb-image0
    libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1
    pulseaudio-utils desktop-file-utils curl ca-certificates)
  if ! command -v gamescope >/dev/null; then
    ubuntu_candidate gamescope || die 'GamescopeのAPT候補がありません。Ubuntu 26.04 LTSを使用するか、互換性のあるGamescope 3.16系を先に導入してください。別Ubuntu版のパッケージは混在させないでください。'
    packages+=(gamescope)
  fi
  if [[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]]; then
    packages+=(qt6-tools-dev-tools)
    if ubuntu_candidate qdbus-qt6; then packages+=(qdbus-qt6); fi
    if ubuntu_candidate kdotool; then packages+=(kdotool); fi
  fi
  sudo apt-get install -y "${packages[@]}"
  local help
  help="$(gamescope --help 2>&1)" || true
  for flag in --backend --expose-wayland --keep-alive --force-windows-fullscreen; do
    grep -q -- "$flag" <<<"$help" || die "Gamescope lacks $flag; install a compatible Gamescope 3.16 build."
  done
  # Ubuntu LTS releases do not all package a suitable PySide6. Never pip into
  # externally managed system Python; GI/Cairo come from system packages.
  "$BOOTSTRAP_PYTHON" -m venv --system-site-packages "$APP_HOME/.runtime/venv"
  "$APP_HOME/.runtime/venv/bin/python" -m pip install "PySide6>=$PYSIDE6_MIN_VERSION,<7"
  export PATH="$APP_HOME/.runtime/venv/bin:$APP_HOME/.runtime/bin:$PATH"
}

install_ubuntu_mangoapp() {
  say 'Building MWM MangoApp for Ubuntu'
  if ! bash "$PACKAGING/build-ubuntu-mangoapp.sh" "$APP_HOME" "$STATE" "$SCRIPT_DIR" \
      > >(tee "$STATE/mangoapp-build.log") 2>&1; then
    warn "MangoApp build failed. Use FPS Counter Off; retry install.sh --update-app. Log: $STATE/mangoapp-build.log"
  fi
}
