#!/usr/bin/env bash
# Screenshot the glow bar (red and blue) for review.
#
#   scripts/preview.sh [MONITOR] [OUTDIR]
#
# MONITOR defaults to Hyprland's focused monitor; OUTDIR to docs/screenshots. The bar is drawn
# over a plain fullscreen backdrop window (`vpn-monitor preview --backdrop`), so the shots contain
# nothing personal and also show the bar above a fullscreen window. The backdrop takes keyboard
# focus for about five seconds. Captures the bottom 60 logical pixels of the monitor with grim.
# Needs: Hyprland (hyprctl), grim, python3, and the project venv or `vpn-monitor` on PATH.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
outdir="${2:-$here/docs/screenshots}"
mkdir -p "$outdir"

if [[ -x "$here/.venv/bin/python" ]]; then
  vpm=("$here/.venv/bin/python" -m vpn_monitor)
else
  vpm=(vpn-monitor)
fi

# Monitor name and its bottom strip in global logical coordinates: "name x y w h".
read -r name x y w h < <(hyprctl monitors -j | python3 -c '
import json, sys
want = sys.argv[1] if len(sys.argv) > 1 else ""
for m in json.load(sys.stdin):
    if (want and m["name"] == want) or (not want and m["focused"]):
        rotated = m.get("transform", 0) % 2 == 1
        pw, ph = (m["height"], m["width"]) if rotated else (m["width"], m["height"])
        lw, lh = round(pw / m["scale"]), round(ph / m["scale"])
        print(m["name"], m["x"], m["y"] + lh - 60, lw, 60)
        break
else:
    sys.exit(f"no monitor {want!r}")
' "${1:-}")
geometry="$x,$y ${w}x$h"
echo "monitor $name, capturing $geometry into $outdir"

# cycle: red at 0 s, blue at 2 s, hidden at 4 s. (The 150 ms cross-fade is shorter than grim
# takes to start, so it is not captured; watch it live with `vpn-monitor preview cycle`.)
"${vpm[@]}" preview cycle --seconds 4.5 --monitor "$name" --backdrop &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
sleep 1.5
grim -g "$geometry" "$outdir/vpm-bar-red.png"
sleep 1.5
grim -g "$geometry" "$outdir/vpm-bar-blue.png"
wait "$pid"
trap - EXIT
ls -l "$outdir"/vpm-bar-*.png
