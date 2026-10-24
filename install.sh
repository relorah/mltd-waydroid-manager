#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -Eeuo pipefail
IFS=$'\n\t'

APP_ID="com.bandainamcoent.imas_millionlive_theaterdays"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/mwm/config/versions.env"
BOOTSTRAP_PYTHON="$(command -v python3 || command -v python || true)"
[[ -n "$BOOTSTRAP_PYTHON" ]] || { echo 'Python 3 is required.' >&2; exit 1; }
APP_VERSION="$("$BOOTSTRAP_PYTHON" -c 'import runpy,sys; print(runpy.run_path(sys.argv[1])["__version__"])' "$SCRIPT_DIR/mwm/version.py")"
PACKAGING="$SCRIPT_DIR/packaging"
PAYLOAD="$PACKAGING/payload"
WD="/var/lib/waydroid"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/mwm-setup"
APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/mwm"
LOCAL_BIN="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

GRAPHICS_ARCHIVES=(
  "$PAYLOAD/graphics/mesa-runtime-overlay.tar.zst"
  "$PAYLOAD/graphics/libdrm-overlay.tar.zst"
  "$PAYLOAD/graphics/llvm21-overlay.tar.zst"
  "$PAYLOAD/graphics/gbm-gralloc-overlay.tar.zst"
  "$PAYLOAD/graphics/mesa-rtscale-overlay.tar.zst"
)
RTS_CONF="$PAYLOAD/config/gles_rtscale.conf"
NO_GUI=0
UPDATE_APP=0

say(){ printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok(){ printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
die(){ printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --update-app) UPDATE_APP=1; shift ;;
    --no-gui) NO_GUI=1; shift ;;
    -h|--help) echo "Usage: ./install.sh [--no-gui] [--update-app]"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ $EUID -ne 0 ]] || die "通常ユーザーで実行してください。"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || die 'Linux x86_64 is required.'
source /etc/os-release
case "${ID:-}" in
  arch|cachyos) HOST_FAMILY=arch ;;
  ubuntu)
    HOST_FAMILY=ubuntu
    BOOTSTRAP_PYTHON=/usr/bin/python3
    dpkg --compare-versions "${VERSION_ID:-0}" ge 24.04 || die 'Ubuntu 24.04以降が必要です。'
    export PATH="/usr/games:$PATH"
    source "$PACKAGING/ubuntu-host.sh"
    ;;
  *) die 'CachyOS/ArchまたはUbuntuが必要です。' ;;
esac
[[ "${XDG_SESSION_TYPE:-}" == wayland ]] || die 'Waylandセッションで実行してください。'
mkdir -p "$STATE"
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}"
exec 7>"${XDG_CONFIG_HOME:-$HOME/.config}/mwm-config.lock"
flock -n 7 || die "MWMの設定反映・保存中です。完了してから更新してください。"
"$BOOTSTRAP_PYTHON" - "$APP_HOME" <<'PY'
import os, sys
from pathlib import Path
targets={str(Path(sys.argv[1])/n) for n in ('mwm.py','MWM.py')}
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit(): continue
    try:
        if entry.stat().st_uid != os.getuid(): continue
        args=entry.joinpath('cmdline').read_bytes().split(b'\0')
        if any(os.fsdecode(a) in targets for a in args):
            sys.exit('MWM画面を閉じてから更新してください。')
    except (OSError, PermissionError): pass
PY

say "Checking administrator access"
# Reuse already-authorized noninteractive access; otherwise authenticate as before.
sudo -n true 2>/dev/null || sudo -v

# Keep the normal sudo timestamp alive during setup instead of granting broad
# temporary NOPASSWD access to tools such as python3 or tar.
(
  while sudo -n true 2>/dev/null; do
    sleep 45
  done
) 7>&- &
SUDO_KEEPALIVE_PID=$!
cleanup_installer_privilege() {
  kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
  wait "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
}
trap cleanup_installer_privilege EXIT

verify_payload() {
  say "Checking bundled graphics payload"
  local archive
  for archive in "${GRAPHICS_ARCHIVES[@]}"; do
    [[ -f "$archive" ]] || die "Missing $archive"
  done
  [[ -f "$RTS_CONF" ]] || die "Missing $RTS_CONF"
  [[ -f "$PAYLOAD/SHA256SUMS" ]] || die "Missing $PAYLOAD/SHA256SUMS"
  (cd "$PAYLOAD" && sha256sum -c SHA256SUMS) >/dev/null || die "Payload checksum verification failed"
  ok "Graphics payload verified"
}

install_packages() {
  say "Installing MWM host dependencies"
  if [[ "$HOST_FAMILY" == ubuntu ]]; then
    install_ubuntu_packages
  else
    sudo pacman -S --needed \
      python pyside6 gtk3 gtk-layer-shell python-gobject python-cairo polkit \
      zstd rsync gamescope qt6-tools
  fi

  python - "$PYSIDE6_MIN_VERSION" <<'PY'
import re, sys
try:
    import PySide6
except ImportError:
    sys.exit("PySide6 is unavailable after package installation")
def parts(value):
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])
if parts(PySide6.__version__) < parts(sys.argv[1]):
    sys.exit(f"PySide6 {PySide6.__version__} is older than required {sys.argv[1]}")
PY

  if [[ "$HOST_FAMILY" == arch && "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]] && ! command -v kdotool >/dev/null 2>&1; then
    say "Installing optional KDE Wayland window helper (kdotool)"
    if command -v paru >/dev/null 2>&1; then
      paru -S --needed --noconfirm kdotool || warn "kdotool install failed; optional window verification requires kdotool."
    elif command -v yay >/dev/null 2>&1; then
      yay -S --needed --noconfirm kdotool || warn "kdotool install failed; optional window verification requires kdotool."
    else
      warn "paru/yay not found; optional window verification can use kdotool."
    fi
  fi

}

wait_boot() {
  for _ in $(seq 1 90); do
    [[ "$(sudo waydroid shell -- getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]] && return 0
    sleep 1
  done
  return 1
}

start_existing_waydroid() {
  sudo systemctl start waydroid-container.service >/dev/null 2>&1 || die "Waydroid container could not be started"
  (waydroid session start >"$STATE/session.log" 2>&1 7>&- &) || true
  wait_boot || die "Waydroid boot timeout. See $STATE/session.log"
}

check_existing_environment() {
  say "Checking existing Waydroid + Mirishita environment"
  command -v waydroid >/dev/null 2>&1 || die "Waydroid is required before installing MWM"
  [[ -f "$WD/waydroid.cfg" ]] || die "An initialized Waydroid environment is required before installing MWM"

  start_existing_waydroid

  local rel nb app
  rel="$(sudo waydroid shell -- getprop ro.build.version.release 2>/dev/null | tr -d '\r')"
  nb="$(sudo waydroid shell -- getprop ro.dalvik.vm.native.bridge 2>/dev/null | tr -d '\r')"
  app="$(sudo waydroid shell -- pm path "$APP_ID" 2>/dev/null | tr -d '\r' || true)"

  [[ "$rel" == 11* ]] || die "This build is verified for Android 11 Waydroid; detected Android ${rel:-unknown}"
  [[ "$app" == package:* ]] || die "Mirishita must already be installed and launchable in Waydroid before installing MWM"
  [[ -n "$nb" && "$nb" != "0" ]] || warn "Native Bridge property is empty. Confirm the existing ARM translation environment if Mirishita cannot launch."

  ok "Waydroid Android $rel detected"
  ok "Mirishita package detected"
  [[ -n "$nb" && "$nb" != "0" ]] && ok "Native Bridge detected: $nb"
}

backup_waydroid() {
  say "Backing up MWM modification targets before changes"
  local backup_rc=0 answer
  sudo python "$PACKAGING/mwm-waydroid-backup.py" status >/dev/null || backup_rc=$?
  if (( backup_rc != 0 && backup_rc != 3 )); then
    die "Existing backup could not be verified. Installation aborted; backup retained."
  fi
  if (( backup_rc == 3 )) && { [[ -f "$APP_HOME/version.py" ]] || [[ -f "$APP_HOME/VERSION" ]]; }; then
    warn "No original backup was found for this existing MWM installation."
    warn "A new backup will preserve the CURRENT Waydroid settings and MWM-modified graphics, not the original pre-install state."
    [[ -t 0 ]] || die "Run setup interactively to confirm backup of the current environment."
    printf 'Back up the current environment and continue? [yes/No] '
    IFS= read -r answer || die "Backup confirmation was cancelled."
    [[ "$answer" == yes || "$answer" == Yes || "$answer" == YES ]] || die "Installation cancelled; no graphics changes made."
  fi
  # create validates and retains an existing baseline without starting or
  # stopping Android. New snapshots manage their user session internally.
  sudo python "$PACKAGING/mwm-waydroid-backup.py" create "${XDG_DATA_HOME:-$HOME/.local/share}/waydroid" "$APP_HOME" || die "Backup failed; installation aborted before graphics changes"
}

apply_graphics_stack() {
  say "Applying split Mesa / libdrm / LLVM / gralloc graphics payload"
  waydroid session stop >/dev/null 2>&1 || true
  sudo systemctl stop waydroid-container.service >/dev/null 2>&1 || true
  sudo mkdir -p "$WD/overlay"
  # The donor combined filename bypasses MWM's split adapters.
  if [[ -f "$WD/overlay/vendor/lib64/egl/libGLES_mesa.so" ]]; then
    sudo mkdir -p "$STATE/iso-driver-backup"
    sudo mv "$WD/overlay/vendor/lib64/egl/libGLES_mesa.so" "$STATE/iso-driver-backup/libGLES_mesa.so.$(date +%s)"
  fi

  # Keep obsolete ISO-private dependencies out of the independent stack.
  if grep -Fq 'independent reconstruction' "$PAYLOAD/manifests/graphics-stack.lock"; then
    local obsolete
    for obsolete in vendor/lib64/egl/libEGL_mwm_iso.so vendor/lib64/libLLVM21.so; do
      if [[ -f "$WD/overlay/$obsolete" ]]; then
        sudo mkdir -p "$STATE/iso-driver-backup"
        sudo mv "$WD/overlay/$obsolete" "$STATE/iso-driver-backup/$(basename "$obsolete").$(date +%s)"
      fi
    done
  fi

  local archive
  for archive in "${GRAPHICS_ARCHIVES[@]}"; do
    say "Applying $(basename "$archive")"
    zstd -dc "$archive" | sudo tar --xattrs --acls --numeric-owner -xf - -C "$WD/overlay"
  done

  (cd "$WD/overlay" && sha256sum -c "$PAYLOAD/manifests/overlay-SHA256SUMS") || die "Installed graphics payload does not match this release"
  ok "Rebuilt graphics payload installed and verified"
}

install_root_helper() {
  say "Installing MWM passwordless helper"
  local helper_src="$PACKAGING/mwm-root-helper"
  local helper_dst="/usr/local/libexec/mwm-root-helper"
  local sudoers="/etc/sudoers.d/mwm-${USER}"

  [[ -f "$helper_src" ]] || die "Missing $helper_src"
  sudo install -d -m 0755 /usr/local/libexec
  sudo install -o root -g root -m 0755 "$helper_src" "$helper_dst"
  sudo install -o root -g root -m 0755 "$PACKAGING/mwm-waydroid-backup.py" /usr/local/libexec/mwm-waydroid-backup.py
  sudo install -o root -g root -m 0644 "$PACKAGING/mwm_targeted_backup.py" /usr/local/libexec/mwm_targeted_backup.py
  printf '%s ALL=(root) NOPASSWD: %s *\n' "$USER" "$helper_dst" | sudo tee "$sudoers" >/dev/null
  sudo chmod 0440 "$sudoers"
  sudo visudo -cf "$sudoers" >/dev/null || {
    sudo rm -f "$sudoers"
    die "sudoers validation failed"
  }
  ok "MWM root helper installed"
}

reset_mwm_state() {
  say "Resetting MWM settings to v$APP_VERSION defaults"
  local cfg="${XDG_CONFIG_HOME:-$HOME/.config}/mwm"
  local state="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"

  # Stop only helper processes that belong to a previous MWM install.
  if [[ -f "$state/gamescope.pid" ]]; then
    old_pid="$(cat "$state/gamescope.pid" 2>/dev/null || true)"
    if [[ "$old_pid" =~ ^[0-9]+$ && -r "/proc/$old_pid/cmdline" ]] &&
       tr '\0' ' ' < "/proc/$old_pid/cmdline" | grep -Fq gamescope-supervisor.sh; then
      kill -TERM -- "-$old_pid" 2>/dev/null || kill -TERM "$old_pid" 2>/dev/null || true
    fi
  fi
  if [[ -f "$state/touch-mapper.pid" ]]; then
    old_pid="$(cat "$state/touch-mapper.pid" 2>/dev/null || true)"
    if [[ "$old_pid" =~ ^[0-9]+$ && -r "/proc/$old_pid/cmdline" ]] &&
       tr '\0' ' ' < "/proc/$old_pid/cmdline" | grep -Fq touch_mapper.py; then
      kill "$old_pid" 2>/dev/null || true
    fi
  fi
  if [[ -f "$state/gamescope-metrics.pid" ]]; then
    old_pid="$(cat "$state/gamescope-metrics.pid" 2>/dev/null || true)"
    if [[ "$old_pid" =~ ^[0-9]+$ && -r "/proc/$old_pid/cmdline" ]] &&
       tr '\0' ' ' < "/proc/$old_pid/cmdline" | grep -Fq gamescope-metrics-monitor.py; then
      kill "$old_pid" 2>/dev/null || true
    fi
  fi
  pkill -f "$APP_HOME/fps_overlay.py" >/dev/null 2>&1 || true
  pkill -f "$APP_HOME/scripts/gamescope-metrics-monitor.py" >/dev/null 2>&1 || true

  rm -rf "$cfg" "$state"
  mkdir -p "$cfg" "$state"
  printf 'gamescope\n' > "$cfg/display-backend"
  printf 'fsr\n' > "$cfg/gamescope-render-mode"
  printf 'off\n' > "$cfg/gamescope-fsr-enabled"
  printf 'auto\n' > "$cfg/aspect-ratio"
  printf 'off\n' > "$cfg/kwin-rtscale"
  printf 'on\n' > "$cfg/rtscale-zoom-fix"
  printf '0\n' > "$cfg/rtscale-msaa-samples"
  printf '16:9\n' > "$cfg/custom-aspect"
  printf '10\n' > "$cfg/gamescope-sharpness"
  printf '125\n' > "$cfg/gamescope-fsr-scale"
  printf 'on\n' > "$cfg/mouse-as-touch"
  printf 'on\n' > "$cfg/auto-start-mirishita"
  printf 'on\n' > "$cfg/verify-waydroid-startup"
  printf 'off\n' > "$cfg/performance-overlay-mode"
  # Window placement and KWin-specific startup rules are not part of this UI.
  ok "MWM settings reset (Waydroid/Mirishita app data preserved)"
}

install_mwm_launcher() {
  say "Installing MWM desktop application"
  local cfg="${XDG_CONFIG_HOME:-$HOME/.config}/mwm" migrated_scale
  if [[ -f "$cfg/kwin-rtscale" ]] && [[ "$(tr -d '[:space:]' < "$cfg/kwin-rtscale")" =~ ^(9|10)$ ]]; then
    migrated_scale="$(mktemp "$cfg/.kwin-rtscale.XXXXXX")"
    printf '8\n' > "$migrated_scale"
    mv -f -- "$migrated_scale" "$cfg/kwin-rtscale"
    ok "Previous RTScale x9/x10 setting adjusted to x8"
  fi
  if [[ -f "$APP_HOME/scripts/kwin-fullscreen.py" ]]; then
    python "$APP_HOME/scripts/kwin-fullscreen.py" stop || die "Could not stop previous fullscreen monitor"
  fi
  pkill -f "$APP_HOME/fps_overlay.py" >/dev/null 2>&1 || true
  mkdir -p "$APP_HOME" "$LOCAL_BIN" "$DESKTOP_DIR"
  # Force content comparison when upgrading from archives whose files all
  # carry normalized timestamps. This prevents a stale script surviving an
  # update merely because size and mtime happen to match.
  rsync -a --delete --checksum --exclude=/.runtime/ --exclude=/logs/ --exclude=/.git/ --exclude=/.codex/ --exclude=/.agents/ --exclude=/.aws/ "$SCRIPT_DIR/mwm/" "$APP_HOME/"
  chmod +x "$APP_HOME/mwm.py" "$APP_HOME/fps_overlay.py" "$APP_HOME/scripts/"*.sh "$APP_HOME/scripts/"*.py
  chmod +x "$APP_HOME/scripts/mangoapp-bin/mangoapp"
  if [[ -f "$APP_HOME/scripts/mangoapp-native/mangoapp" ]]; then
    chmod +x "$APP_HOME/scripts/mangoapp-native/mangoapp"
  fi

  cat > "$LOCAL_BIN/mwm" <<EOF2
#!/usr/bin/env bash
export PATH="$APP_HOME/.runtime/venv/bin:$APP_HOME/.runtime/bin:/usr/games:\$PATH"
exec python "$APP_HOME/mwm.py" "\$@"
EOF2
  chmod +x "$LOCAL_BIN/mwm"


  cat > "$LOCAL_BIN/mwm-mirishita" <<EOF2
#!/usr/bin/env bash
export PATH="$APP_HOME/.runtime/venv/bin:$APP_HOME/.runtime/bin:/usr/games:\$PATH"
exec bash "$APP_HOME/scripts/launch-mirishita.sh" "\$@"
EOF2
  chmod +x "$LOCAL_BIN/mwm-mirishita"
  cat > "$DESKTOP_DIR/mwm-mirishita.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=Mirishita (MWM)
Name[ja]=ミリシタ（MWM）
Comment=Launch Mirishita through MWM and Gamescope
Exec=$LOCAL_BIN/mwm-mirishita
Icon=applications-games
Terminal=false
Categories=Game;
StartupNotify=false
StartupWMClass=gamescope
EOF2

  cat > "$DESKTOP_DIR/mwm.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=MLTD Waydroid Manager
GenericName=MWM
Comment=Manage an existing Mirishita Waydroid environment
Exec=$LOCAL_BIN/mwm
Icon=applications-games
Terminal=false
Categories=Game;Utility;
StartupNotify=true
EOF2
  chmod 0644 "$DESKTOP_DIR/mwm.desktop"
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
  ok "MWM installed: KDE app menu + $LOCAL_BIN/mwm"
}

final_verify() {
  say "Final verification"
  sudo systemctl start waydroid-container.service >/dev/null 2>&1 || true
  (waydroid session start >"$STATE/session.log" 2>&1 7>&- &) || true
  wait_boot || die "Waydroid boot timeout during final verification"

  sudo waydroid shell -- wm size reset >/dev/null 2>&1 || true
  waydroid prop set persist.waydroid.multi_windows false >/dev/null 2>&1 || true
  waydroid prop set persist.waydroid.fake_touch "$APP_ID" >/dev/null 2>&1 || true
  waydroid prop set persist.waydroid.uevent false >/dev/null 2>&1 || true

  # Use the same profile application as Refresh. In particular RTScale uses
  # a 1080-high display and 720-high render-target base, not the legacy 1316.
  local default_scale display_mode cfg
  cfg="${XDG_CONFIG_HOME:-$HOME/.config}/mwm"
  display_mode="$(cat "$cfg/aspect-ratio" 2>/dev/null || echo auto)"
  default_scale="$(cat "$cfg/kwin-rtscale" 2>/dev/null || echo off)"
  "$APP_HOME/scripts/set-aspect-ratio.sh" "$display_mode" || die "Display profile verification failed"
  "$APP_HOME/scripts/set-rtscale.sh" "$default_scale" || die "RTScale profile verification failed"

  # Audio normalization is an internal always-on policy in v0.5.52. The host
  # stream may not exist until the game outputs audio, so installer verification
  # uses a non-blocking host check and runtime Refresh retries automatically.
  sudo -n /usr/local/libexec/mwm-root-helper set-media-volume >/dev/null 2>&1 || true
  "$SCRIPT_DIR/mwm/scripts/set-audio-levels.sh" --nowait >/dev/null 2>&1 || true

  sudo waydroid shell -- pm path "$APP_ID" 2>/dev/null | tr -d '\r' | grep -q '^package:' || die "Mirishita package check failed"
  "$SCRIPT_DIR/mwm/scripts/rtscale-debug.sh" event install-verified >/dev/null 2>&1 || true
  ok "Existing Waydroid + Mirishita environment is ready for MWM"
}

launch_gui() {
  # All installation writes have completed. Release the parent's lock before
  # the GUI performs its settings recovery/validation.
  flock -u 7 || die "Installation lock could not be released"
  exec 7>&-
  if (( ! NO_GUI )); then
    say "Launching MWM v$APP_VERSION"
    "$LOCAL_BIN/mwm" 7>&-
  fi
}

if (( UPDATE_APP )); then
  [[ -x /usr/local/libexec/mwm-root-helper ]] || die "MWM is not installed; run install.sh without --update-app first."
  if [[ "$HOST_FAMILY" == ubuntu ]]; then
    install_packages
    install_ubuntu_mangoapp
  fi
  command -v rsync >/dev/null || die "rsync is required"
  if [[ "$HOST_FAMILY" == arch ]] && ! command -v qdbus6 >/dev/null 2>&1; then
    sudo pacman -S --needed qt6-tools
  fi
  backup_waydroid
  install_root_helper
  install_mwm_launcher
  ok "MWM application updated; saved settings and graphics payload preserved. Close older MWM windows and open the updated launcher."
  launch_gui
  exit 0
fi

verify_payload
install_packages
if [[ "$HOST_FAMILY" == ubuntu ]]; then install_ubuntu_mangoapp; fi
if [[ "$HOST_FAMILY" == arch ]] && ! command -v mangoapp >/dev/null 2>&1; then
  sudo pacman -S --needed --noconfirm mangohud || warn "MangoApp installation failed; MWM HUD fallback remains available"
fi
check_existing_environment
backup_waydroid
apply_graphics_stack
install_root_helper
if [[ -d "${XDG_CONFIG_HOME:-$HOME/.config}/mwm" ]]; then
  ok "Existing MWM settings preserved"
else
  reset_mwm_state
fi
install_mwm_launcher
final_verify
launch_gui
