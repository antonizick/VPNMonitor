#!/usr/bin/env bash
# Remove everything scripts/install.sh added (idempotent). Logs and config are left alone; the
# bindings.lua backup (bindings.lua.bak.vpn-monitor) is left in place on purpose.
#
#   scripts/uninstall.sh
set -euo pipefail

bin_dir="${XDG_BIN_HOME:-$HOME/.local/bin}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
unit="$config_home/systemd/user/vpn-monitor.service"
bindings="$config_home/hypr/bindings.lua"
backup="$bindings.bak.vpn-monitor"
begin_mark="-- >>> vpn-monitor"
end_mark="-- <<< vpn-monitor"

say() { printf 'uninstall: %s\n' "$*"; }

# 1. service
if systemctl --user list-unit-files vpn-monitor.service >/dev/null 2>&1 || [[ -e "$unit" ]]; then
  systemctl --user disable --now vpn-monitor.service >/dev/null 2>&1 || true
fi
if [[ -e "$unit" ]]; then
  rm -f "$unit"
  say "removed $unit"
fi
systemctl --user daemon-reload || true
systemctl --user reset-failed vpn-monitor.service >/dev/null 2>&1 || true

# 2. command (only if it is our symlink)
link="$bin_dir/vpn-monitor"
if [[ -L "$link" && "$(readlink "$link")" == */scripts/vpn-monitor ]]; then
  rm -f "$link"
  say "removed $link"
elif [[ -e "$link" ]]; then
  say "left $link alone (not the VPN Monitor symlink)"
fi

# 3. keybinding
if [[ -f "$bindings" ]] && grep -qF -- "$begin_mark" "$bindings"; then
  python3 - "$bindings" "$begin_mark" "$end_mark" <<'PY'
import re
import sys

path, begin, end = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
text = re.sub(r"\n" + re.escape(begin) + r"[^\n]*\n.*?" + re.escape(end) + r"\n", "", text, flags=re.S)
open(path, "w", encoding="utf-8").write(text)
PY
  say "removed the vpn-monitor block from $bindings"
  hyprctl reload >/dev/null 2>&1 || say "hyprctl reload failed; the key goes away at the next login"
fi
if [[ -f "$backup" && -f "$bindings" ]]; then
  if diff -q "$backup" "$bindings" >/dev/null; then
    say "bindings.lua is identical to the backup $backup"
  else
    say "bindings.lua differs from the backup (your own later edits); see: diff $backup $bindings"
  fi
fi
say "done. State and logs remain in ~/.local/state/vpn-monitor (delete by hand if you want)."
