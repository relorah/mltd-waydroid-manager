#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Install only missing dependencies; preserve the host graphics/kernel stack.
mwm_ubuntu_safe_install() {
  local packaging=$1 p status guard_dir plan native_arch
  native_arch="$(dpkg --print-architecture)"
  shift
  local -a missing=()
  for p in "$@"; do
    status="$(dpkg-query -W -f='${Architecture} ${Status}\n' "$p" 2>/dev/null || true)"
    if ! awk -v arch="$native_arch" '($1 == arch || $1 == "all") && $2 == "install" && $3 == "ok" && $4 == "installed" {found=1} END {exit !found}' <<<"$status"; then
      missing+=("$p")
    fi
  done
  ((${#missing[@]})) || return 0
  plan="$(mktemp)"
  if ! LC_ALL=C apt-get --simulate --no-remove --no-upgrade --no-install-recommends install "${missing[@]}" >"$plan" 2>&1; then
    cat "$plan" >&2; rm -f -- "$plan"
    echo 'MWM dependency resolution failed. Check configured Ubuntu repositories; no host changes made.' >&2
    return 1
  fi
  cat "$plan"
  if ! python3 "$packaging/apt_guard.py" --plan <"$plan"; then rm -f -- "$plan"; return 1; fi
  rm -f -- "$plan"
  guard_dir="$(sudo mktemp -d /run/mwm-apt-XXXXXXXX)" || return
  sudo install -m 0755 "$packaging/apt_guard.py" "$guard_dir/guard.py" || return
  local rc=0
  sudo apt-get --assume-yes --no-remove --no-upgrade --no-install-recommends \
    -o "DPkg::Pre-Install-Pkgs::=/usr/bin/python3 $guard_dir/guard.py" \
    install "${missing[@]}" || rc=$?
  sudo rm -f -- "$guard_dir/guard.py"
  sudo rmdir -- "$guard_dir"
  return "$rc"
}
