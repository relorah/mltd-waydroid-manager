#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
APP_ONLY=0
RESTORE_CONFIRMED=0
case "${1:-}" in
  "") ;;
  --app-only-confirmed) APP_ONLY=1 ;;
  --restore-confirmed) RESTORE_CONFIRMED=1 ;;
  -h|--help) echo 'Usage: ./uninstall.sh'; exit 0 ;;
  *) echo 'Unknown uninstall option' >&2; exit 2 ;;
esac
(( $# <= 1 )) || exit 2
[[ $EUID -ne 0 ]] || { echo 'Run as a regular user.' >&2; exit 1; }
APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/mwm"
CFG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications/mwm.desktop"
HELPER=/usr/local/libexec/mwm-root-helper
# Validate every removal target before stopping or changing anything.
python - "$APP_HOME" "$CFG_HOME/mwm" "$STATE_HOME" "$HOME/.local/bin/mwm" "$DESKTOP" <<'PY'
import os,sys
from pathlib import Path
for value in sys.argv[1:]:
 p=Path(value)
 if not p.is_absolute() or p.name not in ('mwm','mwm.desktop') or p.is_symlink():
  sys.exit('Could not verify the removal path: '+value)
 resolved=p.resolve()
 if resolved in (Path('/'),Path.home().resolve()) or not resolved.is_relative_to(Path.home().resolve()):
  sys.exit('Review custom installation paths outside your home directory: '+value)
 if resolved!=p.absolute():sys.exit('Review installation paths containing symbolic links: '+value)
app=Path(sys.argv[1])
for entry in Path('/proc').iterdir():
 if not entry.name.isdigit():continue
 try:
  if entry.stat().st_uid!=os.getuid():continue
  args=entry.joinpath('cmdline').read_bytes().split(b'\0')
  if any(os.fsencode(app/n) in args for n in ('mwm.py','MWM.py')):
   sys.exit('Close the MWM window before uninstalling.')
 except OSError:pass
PY
mkdir -p "$CFG_HOME"
exec 7>"$CFG_HOME/mwm-config.lock"
flock -n 7 || { echo 'Wait for the MWM save or update operation to finish.' >&2; exit 75; }
[[ ! -f "${XDG_STATE_HOME:-$HOME/.local/state}/mwm-lite/restore.json" ]] || {
  echo 'Run mwm-lite --recover before uninstalling.' >&2; exit 78;
}
sudo -v
[[ -x "$HELPER" ]] || { echo 'Update the root helper and try again.' >&2; exit 1; }
backup_rc=0
backup="$(sudo -n "$HELPER" backup-status)" || backup_rc=$?
if (( backup_rc == 3 )); then
  if (( ! APP_ONLY )); then
    printf 'No backup was found. Remove MWM only? [yes/No] '
    read -r answer
    [[ "$answer" == yes ]] || exit 130
    APP_ONLY=1
  fi
elif (( backup_rc != 0 )); then
  echo 'Could not verify the backup. Removal was aborted.' >&2; exit 1
else
  # A backup appearing after GUI confirmation still selects the restore path.
  APP_ONLY=0
  if (( ! RESTORE_CONFIRMED )); then
    printf 'Restore the files and settings modified by MWM, then remove MWM. [yes/No] '
    read -r answer
    [[ "$answer" == yes ]] || exit 130
  fi
fi
python - "$APP_HOME" <<'PY'
import os,signal,subprocess,time,shutil,tempfile,re
from pathlib import Path
app=Path(__import__('sys').argv[1]);targets={str(app/'scripts'/n) for n in ('gamescope-window-fit.py','fps-collector.sh','gamescope-metrics-monitor.py')}
owned=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  if p.stat().st_uid!=os.getuid():continue
  args=[os.fsdecode(a) for a in (p/'cmdline').read_bytes().split(b'\0')]
  if not targets.intersection(args):continue
  stamp=(p/'stat').read_text().rsplit(')',1)[1].split()[19]
  owned.append((p,stamp));os.kill(int(p.name),signal.SIGTERM)
 except (OSError,IndexError):pass
for _ in range(40):
 if all(not p.exists() for p,_ in owned):break
 time.sleep(.1)
for p,stamp in owned:
 try:
  if (p/'stat').read_text().rsplit(')',1)[1].split()[19]==stamp:os.kill(int(p.name),signal.SIGKILL)
 except (OSError,IndexError):pass
# MWM's transient scripts have exact names and are owned by this user.
for p in Path(tempfile.gettempdir()).glob('mwm-window-aspect-*.js'):
 match=re.match(r'(mwm-window-aspect-[0-9]+-[0-9]+)-',p.name)
 if not match or p.is_symlink() or p.stat().st_uid!=os.getuid():continue
 dbus=shutil.which('qdbus6') or shutil.which('qdbus')
 if dbus:subprocess.run([dbus,'org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',match[1]],timeout=4,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 p.unlink(missing_ok=True)
shader=app.parent/'gamescope/reshade/Shaders/MWM_CAS.fx'
if shader.is_file() and not shader.is_symlink() and shader.stat().st_uid==os.getuid():
 if 'MWM_CAS' in shader.read_text(errors='replace'):shader.unlink()
PY
for ctl in performance-overlay.py kwin-fullscreen.py; do
  if [[ -f "$APP_HOME/scripts/$ctl" ]]; then python "$APP_HOME/scripts/$ctl" stop; fi
done
if [[ -f "$APP_HOME/scripts/gamescope-control.sh" ]]; then
  "$APP_HOME/scripts/gamescope-control.sh" stop
fi
if [[ -f "$APP_HOME/scripts/touch-mapper.sh" ]]; then
  "$APP_HOME/scripts/touch-mapper.sh" stop
fi
if (( ! APP_ONLY )); then
  waydroid session stop
  sudo -n "$HELPER" backup-restore || { echo 'Restoration failed. MWM will be retained.' >&2; exit 1; }
fi
sudo -n "$HELPER" backup-cleanup-setup "${XDG_STATE_HOME:-$HOME/.local/state}/mwm-setup"
# Remove only this user's rule. Other MWM users can retain the shared helper.
sudo rm -f -- "/etc/sudoers.d/mwm-$(id -un)"
remaining="$(sudo find /etc/sudoers.d -maxdepth 1 -type f -name 'mwm-*' -print)"
if [[ -z "$remaining" ]]; then sudo rm -f -- "$HELPER" /usr/local/libexec/mwm-waydroid-backup.py /usr/local/libexec/mwm_targeted_backup.py; fi
python - "$APP_HOME" "$CFG_HOME/mwm" "$STATE_HOME" "$HOME/.local/bin/mwm" "$DESKTOP" "$APP_ONLY" <<'PY'
import shutil,sys
from pathlib import Path
app,cfg,state,launcher,desktop=map(Path,sys.argv[1:6]);app_only=sys.argv[6]=='1'
def remove(p):
 if p.is_symlink() or p.is_file():p.unlink()
 elif p.is_dir():shutil.rmtree(p)
for p in (launcher,desktop):remove(p)
for name in ('mwm-lite', 'mwm-lite-settings'):
 remove(launcher.with_name(name))
 remove(desktop.with_name(name+'.desktop'))
if app.is_dir():
 for child in app.iterdir():
  remove(child)
 if not any(app.iterdir()):app.rmdir()
for p in (cfg,state):remove(p)
print('MWM, its launchers, and its permission rules have been removed.')
print('MWM settings and diagnostic logs: removed')
print('Waydroid environment: '+('current state retained' if app_only else 'MWM modification targets restored'))
print('Recovery backups: retained in /var/lib/mwm-backups')
PY
if command -v update-desktop-database >/dev/null; then
 update-desktop-database "$(dirname "$DESKTOP")" >/dev/null 2>&1 || true
fi
