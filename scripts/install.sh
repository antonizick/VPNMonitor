#!/usr/bin/env bash
# Install VPN Monitor for the current user (idempotent; run it again after moving the repo).
#
#   scripts/install.sh [--no-keybinding] [--no-start]
#
# What it changes (undo everything with scripts/uninstall.sh):
#   1. ~/.local/bin/vpn-monitor           symlink to scripts/vpn-monitor in this repository
#   2. ~/.config/systemd/user/vpn-monitor.service   the user unit; enabled and started
#   3. ~/.config/hypr/bindings.lua        one marked block with the pause/resume key
#                                         (backup: bindings.lua.bak.vpn-monitor, made once)
# It never touches /usr/share/omarchy/ or anything outside $HOME.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin_dir="${XDG_BIN_HOME:-$HOME/.local/bin}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
unit_dir="$config_home/systemd/user"
bindings="$config_home/hypr/bindings.lua"
backup="$bindings.bak.vpn-monitor"
key_mods="SUPER + ALT + SHIFT"
key_name="V"
key_modmask=73 # SUPER 64 + ALT 8 + SHIFT 1
begin_mark="-- >>> vpn-monitor (managed by scripts/install.sh; remove with scripts/uninstall.sh)"
end_mark="-- <<< vpn-monitor"

want_key=1
want_start=1
for arg in "$@"; do
  case "$arg" in
    --no-keybinding) want_key=0 ;;
    --no-start) want_start=0 ;;
    -h | --help)
      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "install.sh: unknown option $arg" >&2
      exit 2
      ;;
  esac
done

say() { printf 'install: %s\n' "$*"; }
die() {
  printf 'install: %s\n' "$*" >&2
  exit 1
}

# -- 0. checks (nothing is changed until all of them pass) -------------------------------------
if [[ -z "${VPM_SKIP_CHECKS:-}" ]]; then
  /usr/bin/python3 -c 'import gi' 2>/dev/null ||
    die "the system python cannot import PyGObject: pacman -S python-gobject gtk4"
  [[ -e /usr/lib/libgtk4-layer-shell.so ]] ||
    die "gtk4-layer-shell is missing: pacman -S gtk4-layer-shell"
fi
[[ -x "$repo/scripts/vpn-monitor" ]] || die "$repo/scripts/vpn-monitor is missing or not executable"
[[ -f "$repo/packaging/systemd/vpn-monitor.service" ]] || die "the unit file is missing"
if [[ -e "$bin_dir/vpn-monitor" && ! -L "$bin_dir/vpn-monitor" ]]; then
  die "$bin_dir/vpn-monitor exists and is not a symlink; move it away first"
fi

if ((want_key)); then
  [[ -f "$bindings" ]] || die "$bindings not found (use --no-keybinding to skip the key)"
  # The key must be free: anything on it that is not our own binding stops the install.
  taken="$(hyprctl binds -j 2>/dev/null | python3 -c '
import json, sys
mask, key = int(sys.argv[1]), sys.argv[2].upper()
try:
    binds = json.load(sys.stdin)
except ValueError:
    sys.exit(0)  # Hyprland not answering: cannot check, do not block
for b in binds:
    if b.get("modmask") == mask and str(b.get("key", "")).upper() == key:
        if not str(b.get("description", "")).startswith("VPN Monitor"):
            print(b.get("description") or "another binding")
            break
' "$key_modmask" "$key_name")" || taken=""
  [[ -z "$taken" ]] ||
    die "$key_mods + $key_name is already bound ($taken); free it or use --no-keybinding"
fi

# -- 1. command ---------------------------------------------------------------------------------
mkdir -p "$bin_dir"
ln -sfn "$repo/scripts/vpn-monitor" "$bin_dir/vpn-monitor"
say "linked $bin_dir/vpn-monitor -> $repo/scripts/vpn-monitor"

# -- 2. user unit -------------------------------------------------------------------------------
mkdir -p "$unit_dir"
install -m 0644 "$repo/packaging/systemd/vpn-monitor.service" "$unit_dir/vpn-monitor.service"
systemctl --user daemon-reload
say "installed $unit_dir/vpn-monitor.service"

# -- 3. keybinding ------------------------------------------------------------------------------
if ((want_key)); then
  [[ -e "$backup" ]] || {
    cp -p "$bindings" "$backup"
    say "backed up $bindings to $backup"
  }
  python3 - "$bindings" "$begin_mark" "$end_mark" "$key_mods" "$key_name" <<'PY'
import re
import sys

path, begin, end, mods, key = sys.argv[1:6]
text = open(path, encoding="utf-8").read()
text = re.sub(r"\n" + re.escape(begin) + r"\n.*?" + re.escape(end) + r"\n", "", text, flags=re.S)
if text and not text.endswith("\n"):
    text += "\n"
block = (
    f"\n{begin}\n"
    "-- Pause or resume the VPN Monitor bar (hides it and stops probing until pressed again).\n"
    f'o.bind("{mods} + {key}", "VPN Monitor: pause/resume", "vpn-monitor toggle")\n'
    f"{end}\n"
)
open(path, "w", encoding="utf-8").write(text + block)
PY
  say "added $key_mods + $key_name to $bindings"
  hyprctl reload >/dev/null 2>&1 || say "hyprctl reload failed (is Hyprland running?); log out and in to pick up the key"
fi

# -- 4. enable and start ------------------------------------------------------------------------
if ((want_start)); then
  systemctl --user enable vpn-monitor.service >/dev/null 2>&1 || die "could not enable the unit"
  systemctl --user restart vpn-monitor.service || die "the unit did not start (journalctl --user -u vpn-monitor)"
  say "enabled and (re)started vpn-monitor.service"
else
  systemctl --user enable vpn-monitor.service >/dev/null 2>&1 || die "could not enable the unit"
  say "enabled vpn-monitor.service (not started: --no-start)"
fi
say "done. Try: vpn-monitor status"
