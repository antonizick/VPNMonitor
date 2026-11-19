"""Real layer-shell surfaces on the live Wayland session (skipped in CI and without Wayland).

The overlay runs in a subprocess because gtk4-layer-shell must be preloaded at process start. It
flashes a bar on one monitor for about half a second.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

from vpn_monitor.overlay import find_layer_shell_lib

pytestmark = [pytest.mark.gi, pytest.mark.wayland]

PROBE = textwrap.dedent(
    """
    import json
    from gi.repository import GLib
    from vpn_monitor.config import AppearanceConfig
    from vpn_monitor.model import Decision, Indicator
    from vpn_monitor.overlay import NAMESPACE, GlowOverlay, GtkBackend

    backend = GtkBackend()
    LS = backend._ls
    monitor = sorted(backend.monitors())[0]
    overlay = GlowOverlay(AppearanceConfig(fade_ms=100), backend=backend)
    loop = GLib.MainLoop()
    out = {"monitor": monitor}

    def shown():
        bar = overlay.bars[monitor]
        win = bar._surface.window
        out.update(
            layer_window=LS.is_layer_window(win),
            layer=int(LS.get_layer(win)),
            overlay_layer=int(LS.Layer.OVERLAY),
            namespace=LS.get_namespace(win),
            anchors={e: LS.get_anchor(win, getattr(LS.Edge, e)) for e in
                     ("TOP", "BOTTOM", "LEFT", "RIGHT")},
            exclusive_zone=LS.get_exclusive_zone(win),
            keyboard_mode=int(LS.get_keyboard_mode(win)),
            keyboard_none=int(LS.KeyboardMode.NONE),
            monitor_name=LS.get_monitor(win).get_connector(),
            input_region_empty=bar._surface.input_region.is_empty(),
            visible=win.get_visible(),
            height=win.get_height(),
            draws=bar.draws,
            settled=not bar.ticking,
        )
        overlay.apply(Decision(Indicator.HIDDEN, "", "test"))
        GLib.timeout_add(500, hidden)
        return False

    def hidden():
        bar = overlay.bars[monitor]
        out.update(hidden_visible=bar._surface.window.get_visible(), hidden_settled=not bar.ticking,
                   draws_after=bar.draws)
        GLib.timeout_add(300, idle)
        return False

    def idle():
        out["draws_idle"] = overlay.bars[monitor].draws
        loop.quit()
        return False

    overlay.apply(Decision(Indicator.RED, monitor, "test"))
    GLib.timeout_add(700, shown)
    GLib.timeout_add(5000, loop.quit)
    loop.run()
    overlay.close()
    print(json.dumps(out))
    """
)


def test_layer_surface_properties() -> None:
    lib = find_layer_shell_lib()
    if lib is None:
        pytest.skip("libgtk4-layer-shell.so not installed")
    env = dict(os.environ, LD_PRELOAD=lib)
    result = subprocess.run(
        [sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["layer_window"] is True
    assert out["layer"] == out["overlay_layer"]
    assert out["namespace"] == "vpn-monitor"
    assert out["anchors"] == {"TOP": False, "BOTTOM": True, "LEFT": True, "RIGHT": True}
    assert out["exclusive_zone"] == 0
    assert out["keyboard_mode"] == out["keyboard_none"]
    assert out["monitor_name"] == out["monitor"]
    assert out["input_region_empty"] is True  # click-through (S4)
    assert out["visible"] is True
    assert out["height"] == 12  # 2 px core + 10 px glow
    assert out["settled"] is True
    assert out["draws"] > 0
    assert out["hidden_visible"] is False  # unmapped after the fade-out
    assert out["hidden_settled"] is True
    assert out["draws_idle"] == out["draws_after"]  # no redraws while idle (R13)
