"""GTK4 layer-shell glow bar, one per monitor, click-through (spec A1, R8, S4; ADR-0017).

Three layers, so most of it is testable without a Wayland session:

* **Pure helpers**: colour parsing, bar geometry, glow gradient stops, :class:`Fade` (the animator,
  time injected). No ``gi``, no clock.
* :class:`Bar`: the per-monitor state machine (hidden, fading in, shown, cross-fading, fading out).
  It drives a :class:`BarSurface` (map, unmap, queue a draw, start frame ticks) and counts its
  draws, so tests run it with a fake surface and a fake frame clock.
* :class:`GlowOverlay`, the :class:`~vpn_monitor.model.IndicatorSink`, over a :class:`Backend` that
  creates surfaces and reports monitor changes. :class:`GtkBackend` is the real one: one
  ``Gtk.Window`` per monitor on layer ``OVERLAY`` (anchored bottom/left/right, exclusive zone 0,
  keyboard mode NONE, namespace ``vpn-monitor``, empty input region).

Idle cost (R13): when a fade ends the tick callback is removed, so nothing is redrawn until the next
:meth:`GlowOverlay.apply` that changes something; a fully faded-out bar is unmapped.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from vpn_monitor.model import Decision, Indicator

if TYPE_CHECKING:
    from vpn_monitor.config import AppearanceConfig
    from vpn_monitor.eventlog import EventLog

NAMESPACE = "vpn-monitor"
"""Layer-shell namespace (visible in ``hyprctl layers``; usable in Hyprland layer rules)."""

GLOW_ALPHA = 0.55
"""Opacity of the glow where it meets the core line; it falls off to 0 at the top."""

GLOW_FALLOFF = 2.2
"""Exponent of the glow's falloff: alpha = GLOW_ALPHA * (1 - t) ** GLOW_FALLOFF."""

GLOW_STEPS = 10
"""Number of gradient segments; enough for a smooth curve at 128 px of glow."""

DEFAULT_GSK_RENDERER = "cairo"
"""GTK renderer used unless ``$GSK_RENDERER`` is set (ADR-0017)."""

PRELOAD_GUARD = "VPN_MONITOR_PRELOADED"
"""Set in the environment of the re-exec'd process so the re-exec happens at most once."""

LAYER_SHELL_DIRS = (
    "/usr/lib",
    "/usr/lib64",
    "/usr/lib/x86_64-linux-gnu",
    "/usr/lib/aarch64-linux-gnu",
    "/usr/local/lib",
)

Clock = Callable[[], float]
RGBA = tuple[float, float, float, float]

# ---------------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------------


def parse_colour(text: str) -> RGBA:
    """``#RRGGBB`` or ``#RRGGBBAA`` to floats in 0..1. Raises ``ValueError`` otherwise."""
    digits = text[1:] if text.startswith("#") else ""
    bad = ValueError(f"colour must be #RRGGBB or #RRGGBBAA, got {text!r}")
    if len(digits) not in (6, 8) or not all(c in "0123456789abcdefABCDEF" for c in digits):
        raise bad
    values = [int(digits[i : i + 2], 16) / 255 for i in range(0, len(digits), 2)]
    alpha = values[3] if len(values) == 4 else 1.0
    return (values[0], values[1], values[2], alpha)


def bar_height(thickness: int, glow: int) -> int:
    """Height of the layer surface in logical pixels: core line plus glow above it."""
    return thickness + glow


def snap_to_device(logical: float, scale: float) -> float:
    """Round a logical length to whole device pixels (at least one), in logical units.

    At scale 1.6 a 3 px core is 4.8 device pixels; drawing 5 (3.125 logical) keeps its top edge on
    a pixel boundary, so it is crisp. The bottom edge is the monitor edge, always aligned.
    """
    if scale <= 0:
        scale = 1.0
    return max(1, round(logical * scale)) / scale


def glow_stops(steps: int = GLOW_STEPS) -> tuple[tuple[float, float], ...]:
    """Gradient stops ``(offset, alpha)``; offset 0 is the core's top edge, 1 the glow's top."""
    if steps < 1:
        raise ValueError("steps must be >= 1")
    return tuple(
        (i / steps, GLOW_ALPHA * (1 - i / steps) ** GLOW_FALLOFF) for i in range(steps + 1)
    )


def ease(t: float) -> float:
    """Smoothstep easing on 0..1 (clamped)."""
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@dataclass(frozen=True, slots=True)
class Look:
    """What a bar is drawn with, resolved from ``[appearance]``."""

    red: RGBA
    blue: RGBA
    thickness: int
    glow: int
    fade_s: float

    @classmethod
    def from_config(cls, appearance: AppearanceConfig) -> Look:
        return cls(
            red=parse_colour(appearance.red),
            blue=parse_colour(appearance.blue),
            thickness=appearance.thickness,
            glow=appearance.glow,
            fade_s=appearance.fade_ms / 1000,
        )

    @property
    def height(self) -> int:
        return bar_height(self.thickness, self.glow)

    def colour(self, indicator: Indicator) -> RGBA | None:
        """The colour for an indicator; ``None`` for HIDDEN."""
        if indicator is Indicator.RED:
            return self.red
        if indicator is Indicator.BLUE:
            return self.blue
        return None


@dataclass(frozen=True, slots=True)
class Frame:
    """One sampled animation value: colour (with its own alpha) and overall opacity."""

    colour: RGBA
    opacity: float


class Fade:
    """Animates colour and opacity towards a target over ``duration_s`` (pure; time injected).

    A new target taken mid-animation starts from the value currently on screen, so an interrupted
    fade never jumps. Showing a hidden bar does not cross-fade from its old colour: it fades in
    already in the new colour.
    """

    def __init__(self, duration_s: float, colour: RGBA = (0.0, 0.0, 0.0, 0.0)) -> None:
        self.duration_s = max(0.0, duration_s)
        self._from = Frame(colour, 0.0)
        self._to = self._from
        self._t0 = 0.0

    @property
    def target(self) -> Frame:
        return self._to

    def sample(self, now: float) -> Frame:
        """The value to draw at ``now``."""
        t = self._progress(now)
        if t >= 1.0:
            return self._to
        k = ease(t)
        a, b = self._from, self._to
        colour = (
            _lerp(a.colour[0], b.colour[0], k),
            _lerp(a.colour[1], b.colour[1], k),
            _lerp(a.colour[2], b.colour[2], k),
            _lerp(a.colour[3], b.colour[3], k),
        )
        return Frame(colour, _lerp(a.opacity, b.opacity, k))

    def running(self, now: float) -> bool:
        """True until the current animation has reached its target."""
        return self._progress(now) < 1.0

    def retarget(self, colour: RGBA | None, opacity: float, now: float) -> bool:
        """Animate towards ``colour`` (``None`` keeps the current one) at ``opacity``.

        Returns False (and changes nothing) if that is already the target.
        """
        current = self.sample(now)
        if colour is None:
            colour = self._to.colour
        target = Frame(colour, opacity)
        if target == self._to:
            return False
        if current.opacity <= 0.0:
            # Invisible: no cross-fade from a colour nobody can see.
            current = Frame(colour, 0.0)
        self._from, self._to, self._t0 = current, target, now
        return True

    def restart(self, now: float) -> None:
        """Start the current animation over at ``now`` (used when the first frame is late)."""
        self._t0 = now

    def _progress(self, now: float) -> float:
        if self._from == self._to or self.duration_s <= 0:
            return 1.0
        return (now - self._t0) / self.duration_s


# ---------------------------------------------------------------------------------------------
# Drawing (pycairo, any context)
# ---------------------------------------------------------------------------------------------


def paint(cr: Any, width: float, height: float, frame: Frame, look: Look, scale: float) -> None:
    """Draw the bar into the cairo context ``cr`` (logical units; GTK applies the device scale).

    Core line at the bottom edge, snapped to whole device pixels; a vertical gradient glow above it
    fading to transparent.
    """
    import cairo

    r, g, b, a = frame.colour
    alpha = a * frame.opacity
    cr.save()
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    if alpha > 0:
        core = min(height, snap_to_device(look.thickness, scale))
        core_top = height - core
        glow = min(core_top, look.glow)
        if glow > 0:
            gradient = cairo.LinearGradient(0, core_top, 0, core_top - glow)
            for offset, stop_alpha in glow_stops():
                gradient.add_color_stop_rgba(offset, r, g, b, alpha * stop_alpha)
            cr.rectangle(0, core_top - glow, width, glow)
            cr.set_source(gradient)
            cr.fill()
        cr.rectangle(0, core_top, width, core)
        cr.set_source_rgba(r, g, b, alpha)
        cr.fill()
    cr.restore()


# ---------------------------------------------------------------------------------------------
# Per-monitor bar state machine
# ---------------------------------------------------------------------------------------------


class BarSurface(Protocol):
    """What :class:`Bar` needs from a real surface (one layer-shell window)."""

    def map(self) -> None:
        """Make the surface visible (idempotent)."""
        ...

    def unmap(self) -> None:
        """Hide the surface; it costs nothing while unmapped (idempotent)."""
        ...

    def queue_draw(self) -> None:
        """Schedule one redraw; the surface then calls :meth:`Bar.draw`."""
        ...

    def start_ticks(self) -> None:
        """Call :meth:`Bar.tick` once per frame until it returns False (idempotent)."""
        ...

    def destroy(self) -> None:
        """Release the surface. Safe to call twice."""
        ...


class Bar:
    """One monitor's bar. Shows HIDDEN, RED or BLUE, with fades, and counts its draws."""

    def __init__(
        self,
        monitor: str,
        look: Look,
        clock: Clock,
        on_settled: Callable[[Bar], None] | None = None,
    ) -> None:
        self.monitor = monitor
        self.look = look
        self.indicator = Indicator.HIDDEN
        self.fade = Fade(look.fade_s)
        self.draws = 0
        """Total draw calls; one fade costs about ``fade_ms`` x refresh rate of them."""
        self.draws_at_settle = 0
        """``draws`` when the last fade finished; stays equal to ``draws`` while idle."""
        self.ticking = False
        self.mapped = False
        self._clock = clock
        self._on_settled = on_settled
        self._surface: BarSurface | None = None
        self._first_tick_pending = False
        """Just mapped: the fade starts at the first frame, not at the (slow) map request."""
        self._final_draw_pending = False
        """A fade just ended and its last frame is queued; that draw still belongs to the fade."""

    def attach(self, surface: BarSurface) -> None:
        self._surface = surface

    def set_indicator(self, indicator: Indicator) -> bool:
        """Animate towards ``indicator``. Returns True if anything changed (idempotent)."""
        if indicator is self.indicator:
            return False
        self.indicator = indicator
        now = self._clock()
        colour = self.look.colour(indicator)
        if not self.fade.retarget(colour, 0.0 if colour is None else 1.0, now):
            return False
        self._final_draw_pending = False
        surface = self._surface
        if surface is None:
            return True
        if colour is not None and not self.mapped:
            surface.map()
            self.mapped = True
            self._first_tick_pending = True
        if self.fade.running(now):
            self.ticking = True
            surface.start_ticks()
        else:  # fade_ms = 0: jump straight there
            self._settle()
        surface.queue_draw()
        return True

    def tick(self, now: float | None = None) -> bool:
        """Frame-clock callback: redraw, and stop (return False) once the fade has finished."""
        surface = self._surface
        if surface is None:
            self.ticking = False
            return False
        if now is None:
            now = self._clock()
        if self._first_tick_pending:
            self._first_tick_pending = False
            self.fade.restart(now)
        surface.queue_draw()
        if self.fade.running(now):
            return True
        self._settle()
        return False

    def draw(self, cr: Any, width: float, height: float, scale: float) -> None:
        """Draw-function body: paint the current frame."""
        self.draws += 1
        if self._final_draw_pending:
            self._final_draw_pending = False
            self.draws_at_settle = self.draws
        paint(cr, width, height, self.frame(), self.look, scale)

    @property
    def idle_draws(self) -> int:
        """Draws since the last fade ended (its final frame excluded). Must stay 0 (R13)."""
        return self.draws - self.draws_at_settle

    def frame(self) -> Frame:
        return self.fade.sample(self._clock())

    def _settle(self) -> None:
        self.ticking = False
        self._first_tick_pending = False
        self.draws_at_settle = self.draws
        if self.fade.target.opacity <= 0.0 and self.mapped and self._surface is not None:
            self._surface.unmap()
            self.mapped = False
        else:
            self._final_draw_pending = self.mapped
        if self._on_settled is not None:
            self._on_settled(self)

    def destroy(self) -> None:
        if self._surface is not None:
            self._surface.destroy()
            self._surface = None
        self.ticking = False
        self.mapped = False


# ---------------------------------------------------------------------------------------------
# The IndicatorSink
# ---------------------------------------------------------------------------------------------


class Backend(Protocol):
    """Creates surfaces and reports which monitors exist."""

    def monitors(self) -> set[str]:
        """Connector names of the monitors present now."""
        ...

    def create(self, monitor: str, bar: Bar) -> BarSurface | None:
        """A surface for ``bar`` on ``monitor``, or ``None`` if that monitor is not present."""
        ...

    def watch_monitors(self, callback: Callable[[set[str]], None]) -> None:
        """Call ``callback`` with the new set of monitor names whenever it changes."""
        ...

    def close(self) -> None:
        """Stop watching monitors. Safe to call twice."""
        ...


class GlowOverlay:
    """Renders Decisions as a glow bar. Implements the IndicatorSink Protocol.

    Only the monitor a Decision names shows a bar; any other bar fades out. ``apply`` is
    idempotent (the engine repeats an indicator when only the reason changed). A fault in the
    toolkit is logged and swallowed: the overlay must never take the daemon or the desktop down
    (spec S4).
    """

    def __init__(
        self,
        appearance: AppearanceConfig,
        *,
        backend: Backend | None = None,
        log: EventLog | None = None,
        clock: Clock = time.monotonic,
        on_settled: Callable[[Bar], None] | None = None,
    ) -> None:
        self.look = Look.from_config(appearance)
        self._backend: Backend = backend if backend is not None else GtkBackend()
        self._log = log
        self._clock = clock
        self._on_settled = on_settled
        self._bars: dict[str, Bar] = {}
        self._decision: Decision | None = None
        self._closed = False
        self._backend.watch_monitors(self._monitors_changed)

    # -- IndicatorSink ------------------------------------------------------------------------

    def apply(self, decision: Decision) -> None:
        if self._closed:
            return
        self._decision = decision
        self._safely(self._render, decision)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for bar in self._bars.values():
            bar.destroy()
        self._bars.clear()
        self._backend.close()

    # -- introspection (preview, tests, logs) -------------------------------------------------

    @property
    def bars(self) -> dict[str, Bar]:
        return dict(self._bars)

    def stats(self) -> dict[str, int]:
        """Draw counters summed over all bars."""
        bars = self._bars.values()
        return {
            "draws": sum(b.draws for b in bars),
            "idle_draws": sum(b.idle_draws for b in bars if not b.ticking),
            "animating": sum(1 for b in bars if b.ticking),
        }

    # -- internals ----------------------------------------------------------------------------

    def _safely(self, action: Callable[[Decision], None], decision: Decision) -> None:
        try:
            action(decision)
        except Exception as exc:  # a toolkit fault must not reach the daemon (S4)
            self._error("overlay_error", f"{type(exc).__name__}: {exc}")

    def _render(self, decision: Decision) -> None:
        target = decision.monitor if decision.indicator is not Indicator.HIDDEN else ""
        for name, other in self._bars.items():
            if name != target:
                other.set_indicator(Indicator.HIDDEN)
        if not target:
            return
        bar: Bar | None = self._bars.get(target)
        if bar is None:
            bar = self._create(target)
        if bar is None:
            self._error(
                "overlay_monitor_missing",
                f"monitor {target!r} is not known to GTK; no bar shown",
                {"monitor": target, "known": ",".join(sorted(self._backend.monitors()))},
            )
            return
        if bar.set_indicator(decision.indicator):
            self._record(
                "overlay",
                f"{decision.indicator.value} on {target}",
                {"monitor": target, "indicator": decision.indicator.value},
            )

    def _create(self, monitor: str) -> Bar | None:
        bar = Bar(monitor, self.look, self._clock, on_settled=self._settled)
        surface = self._backend.create(monitor, bar)
        if surface is None:
            return None
        bar.attach(surface)
        self._bars[monitor] = bar
        return bar

    def _settled(self, bar: Bar) -> None:
        self._record(
            "overlay_settled",
            f"fade finished: {bar.indicator.value} on {bar.monitor}",
            {"monitor": bar.monitor, "indicator": bar.indicator.value, "draws": str(bar.draws)},
            level=logging.DEBUG,
        )
        if self._on_settled is not None:
            self._on_settled(bar)

    def _monitors_changed(self, present: set[str]) -> None:
        if self._closed:
            return
        for name in [n for n in self._bars if n not in present]:
            self._bars.pop(name).destroy()
            self._record("overlay_monitor", f"monitor {name} removed", {"monitor": name})
        decision = self._decision
        wanted = decision.monitor if decision is not None else ""
        if decision is not None and wanted in present and wanted not in self._bars:
            # The monitor that should show the bar came (back): show it there now.
            self._safely(self._render, decision)

    def _record(
        self, event: str, reason: str, inputs: dict[str, str], level: int = logging.INFO
    ) -> None:
        if self._log is not None:
            self._log.record(event, reason=reason, inputs=inputs, level=level)

    def _error(self, event: str, reason: str, inputs: dict[str, str] | None = None) -> None:
        if self._log is not None:
            self._log.error(event, reason, inputs)


# ---------------------------------------------------------------------------------------------
# LD_PRELOAD re-exec
# ---------------------------------------------------------------------------------------------


def find_layer_shell_lib(dirs: Iterable[str] = LAYER_SHELL_DIRS) -> str | None:
    """Path of ``libgtk4-layer-shell.so``, or ``None``."""
    for directory in dirs:
        path = Path(directory) / "libgtk4-layer-shell.so"
        if path.exists():
            return str(path)
    return None


def preload_command(
    argv: Sequence[str], env: dict[str, str], lib: str | None
) -> tuple[list[str], dict[str, str]] | None:
    """The command and environment to re-exec with ``LD_PRELOAD``, or ``None`` if not needed.

    gtk4-layer-shell must be loaded before libwayland-client; from Python that means
    ``LD_PRELOAD`` (without it ``is_supported()`` is False and the window would be an ordinary
    toplevel, verified in Phase 06). The guard variable makes this happen at most once.
    """
    if lib is None or "libgtk4-layer-shell" in env.get("LD_PRELOAD", "") or env.get(PRELOAD_GUARD):
        return None
    new_env = dict(env)
    new_env["LD_PRELOAD"] = f"{lib} {env.get('LD_PRELOAD', '')}".strip()
    new_env[PRELOAD_GUARD] = "1"
    return [sys.executable, "-m", "vpn_monitor", *argv], new_env


def ensure_layer_shell(argv: Sequence[str]) -> None:  # pragma: no cover - replaces the process
    """Re-exec this command once with ``LD_PRELOAD`` set, if needed. Call before importing Gtk."""
    command = preload_command(argv, dict(os.environ), find_layer_shell_lib())
    if command is not None:
        args, env = command
        os.execve(sys.executable, args, env)  # noqa: S606 - re-exec of ourselves, fixed argv


# ---------------------------------------------------------------------------------------------
# GTK backend
# ---------------------------------------------------------------------------------------------


class GtkSurface:  # pragma: no cover - exercised by the wayland tests
    """One layer-shell window bound to one GDK monitor."""

    def __init__(self, gtk: Any, layer_shell: Any, gdk_monitor: Any, bar: Bar) -> None:
        import cairo

        self._cairo: Any = cairo
        self._bar = bar
        self._tick_id: int | None = None
        ls = layer_shell
        window: Any = gtk.Window()
        window.set_decorated(False)
        window.set_focusable(False)
        window.set_can_target(False)
        window.add_css_class(NAMESPACE)
        ls.init_for_window(window)
        ls.set_namespace(window, NAMESPACE)
        ls.set_layer(window, ls.Layer.OVERLAY)
        ls.set_keyboard_mode(window, ls.KeyboardMode.NONE)
        ls.set_exclusive_zone(window, 0)
        for edge in (ls.Edge.BOTTOM, ls.Edge.LEFT, ls.Edge.RIGHT):
            ls.set_anchor(window, edge, True)
        ls.set_anchor(window, ls.Edge.TOP, False)
        ls.set_monitor(window, gdk_monitor)
        area: Any = gtk.DrawingArea()
        area.set_content_height(bar.look.height)
        area.set_can_target(False)
        area.set_draw_func(self._draw)
        window.set_default_size(1, bar.look.height)
        window.set_child(area)
        window.connect("map", self._on_map)
        self.window: Any = window
        self.area: Any = area

    def _on_map(self, _window: Any) -> None:
        # Empty input region: every click and scroll goes to the window underneath (S4).
        self.input_region: Any = self._cairo.Region()
        self.window.get_native().get_surface().set_input_region(self.input_region)

    def scale(self) -> float:
        surface = self.window.get_native().get_surface() if self.window is not None else None
        return float(surface.get_scale()) if surface is not None else 1.0

    def _draw(self, _area: Any, cr: Any, width: int, height: int) -> None:
        self._bar.draw(cr, width, height, self.scale())

    def _tick(self, _widget: Any, _clock: Any) -> bool:
        tick_id, self._tick_id = self._tick_id, None
        keep = self._bar.tick()
        if keep:
            self._tick_id = tick_id
        return keep

    def map(self) -> None:
        self.window.set_visible(True)

    def unmap(self) -> None:
        self.stop_ticks()
        self.window.set_visible(False)

    def queue_draw(self) -> None:
        self.area.queue_draw()

    def start_ticks(self) -> None:
        if self._tick_id is None:
            self._tick_id = self.area.add_tick_callback(self._tick)

    def stop_ticks(self) -> None:
        if self._tick_id is not None:
            self.area.remove_tick_callback(self._tick_id)
            self._tick_id = None

    def destroy(self) -> None:
        if self.window is None:
            return
        self.stop_ticks()
        self.window.destroy()
        self.window = None


class GtkBackend:  # pragma: no cover - exercised by the wayland tests
    """Layer-shell windows on the default GDK display; monitors from ``Gdk.Display``.

    Needs gtk4-layer-shell preloaded (:func:`ensure_layer_shell`). Raises ``RuntimeError`` if layer
    shell is not active, rather than showing an ordinary window that would steal clicks (S4).
    """

    def __init__(self) -> None:
        # A 15 px bar gains nothing from a GPU renderer; cairo costs ~50 MB less RSS, 5 fewer
        # threads and no idle CPU (measured in Phase 06, ADR-0017). The environment can override.
        os.environ.setdefault("GSK_RENDERER", DEFAULT_GSK_RENDERER)
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gdk, Gtk
        from gi.repository import Gtk4LayerShell as LayerShell

        self._gtk: Any = Gtk
        self._ls: Any = LayerShell
        Gtk.init()
        if not LayerShell.is_supported():
            raise RuntimeError(
                "gtk4-layer-shell is not active (needs LD_PRELOAD=libgtk4-layer-shell.so and a "
                "compositor with wlr-layer-shell)"
            )
        display: Any = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("no Wayland display")
        css: Any = Gtk.CssProvider()
        css.load_from_string(f"window.{NAMESPACE} {{ background: transparent; }}")
        Gtk.StyleContext.add_provider_for_display(
            display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._model: Any = display.get_monitors()
        self._handler: int | None = None
        self._callback: Callable[[set[str]], None] | None = None

    def _gdk_monitors(self) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for i in range(self._model.get_n_items()):
            monitor = self._model.get_item(i)
            connector = monitor.get_connector() if monitor is not None else None
            if connector and monitor.is_valid():
                found[connector] = monitor
        return found

    def monitors(self) -> set[str]:
        return set(self._gdk_monitors())

    def create(self, monitor: str, bar: Bar) -> BarSurface | None:
        gdk_monitor = self._gdk_monitors().get(monitor)
        if gdk_monitor is None:
            return None
        return GtkSurface(self._gtk, self._ls, gdk_monitor, bar)

    def watch_monitors(self, callback: Callable[[set[str]], None]) -> None:
        self._callback = callback
        self._handler = self._model.connect("items-changed", self._items_changed)

    def _items_changed(self, *_args: Any) -> None:
        if self._callback is not None:
            self._callback(self.monitors())

    def close(self) -> None:
        if self._handler is not None:
            self._model.disconnect(self._handler)
            self._handler = None
        self._callback = None
