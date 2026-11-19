"""Overlay: pure helpers, the per-bar state machine with a fake frame clock, the IndicatorSink."""

from __future__ import annotations

import ast
import itertools
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from vpn_monitor import cli, overlay
from vpn_monitor.config import AppearanceConfig, Config, load_config
from vpn_monitor.eventlog import EventLog
from vpn_monitor.model import Decision, Indicator, IndicatorSink
from vpn_monitor.overlay import (
    GLOW_ALPHA,
    PRELOAD_GUARD,
    Bar,
    Fade,
    Frame,
    GlowOverlay,
    Look,
    bar_height,
    ease,
    find_layer_shell_lib,
    glow_stops,
    parse_colour,
    preload_command,
    snap_to_device,
)

RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)


class FakeClock:
    """Monotonic clock the test advances by hand (stands in for the frame clock)."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSurface:
    """Records what the bar asks of its surface; ``frame()`` plays one frame-clock tick."""

    def __init__(self, bar: Bar) -> None:
        self.bar = bar
        self.mapped = False
        self.maps = 0
        self.unmaps = 0
        self.ticking = False
        self.draw_queued = False
        self.destroyed = 0

    def map(self) -> None:
        self.mapped = True
        self.maps += 1

    def unmap(self) -> None:
        self.mapped = False
        self.ticking = False
        self.unmaps += 1

    def queue_draw(self) -> None:
        self.draw_queued = True

    def start_ticks(self) -> None:
        self.ticking = True

    def destroy(self) -> None:
        self.destroyed += 1

    def frame(self) -> None:
        """One frame: run the tick callback if installed, then any queued draw (if mapped)."""
        if self.ticking:
            self.ticking = self.bar.tick()
        if self.draw_queued and self.mapped:
            self.draw_queued = False
            self.bar.draw(_NullCairo(), 1000, 15, 1.6)
        elif not self.mapped:
            self.draw_queued = False


class _NullCairo:
    """Accepts any cairo call (paint() is tested separately against a real image surface)."""

    def __getattr__(self, _name: str) -> Callable[..., None]:
        return lambda *_a, **_k: None


def run_frames(surface: FakeSurface, clock: FakeClock, n: int, dt: float = 1 / 60) -> None:
    for _ in range(n):
        clock.advance(dt)
        surface.frame()


def make_bar(fade_ms: int = 150) -> tuple[Bar, FakeSurface, FakeClock]:
    clock = FakeClock()
    look = Look.from_config(AppearanceConfig(fade_ms=fade_ms))
    bar = Bar("DP-1", look, clock)
    surface = FakeSurface(bar)
    bar.attach(surface)
    return bar, surface, clock


# ---------------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#FF0000", (1.0, 0.0, 0.0, 1.0)),
        ("#00ff00", (0.0, 1.0, 0.0, 1.0)),
        ("#0000FF80", (0.0, 0.0, 1.0, 128 / 255)),
        ("#000000", (0.0, 0.0, 0.0, 1.0)),
    ],
)
def test_parse_colour(text: str, expected: tuple[float, ...]) -> None:
    assert parse_colour(text) == pytest.approx(expected)


def test_parse_default_colours() -> None:
    look = Look.from_config(AppearanceConfig())
    # Approved at the Phase 06 review (ADR-0017): 80 % opacity.
    assert look.red == pytest.approx((1.0, 0x3B / 255, 0x30 / 255, 0xCC / 255))
    assert look.blue == pytest.approx((0x0A / 255, 0x84 / 255, 1.0, 0xCC / 255))
    assert (look.thickness, look.glow, look.height) == (2, 10, 12)


@pytest.mark.parametrize("bad", ["", "FF0000", "#FFF", "#GG0000", "#FF00000", "#ff 000", "red"])
def test_parse_colour_rejects(bad: str) -> None:
    with pytest.raises(ValueError, match="RRGGBB"):
        parse_colour(bad)


def test_bar_height_and_look() -> None:
    assert bar_height(3, 12) == 15
    look = Look.from_config(AppearanceConfig(thickness=4, glow=20, fade_ms=300))
    assert look.height == 24
    assert look.fade_s == pytest.approx(0.3)
    assert look.colour(Indicator.HIDDEN) is None
    assert look.colour(Indicator.RED) == look.red
    assert look.colour(Indicator.BLUE) == look.blue


@pytest.mark.parametrize(
    ("logical", "scale", "expected"),
    [
        (3, 1.0, 3.0),
        (3, 1.6, 5 / 1.6),  # 4.8 device px -> 5
        (3, 2.0, 3.0),
        (3, 1.25, 4 / 1.25),  # 3.75 -> 4
        (1, 0.5, 2.0),  # never less than one device pixel
        (3, 0.0, 3.0),  # nonsense scale -> 1
    ],
)
def test_snap_to_device(logical: float, scale: float, expected: float) -> None:
    assert snap_to_device(logical, scale) == pytest.approx(expected)
    if scale > 0:
        assert (snap_to_device(logical, scale) * scale) == pytest.approx(
            round(snap_to_device(logical, scale) * scale)
        )


def test_glow_stops_fall_off_to_zero() -> None:
    stops = glow_stops()
    assert stops[0] == (0.0, pytest.approx(GLOW_ALPHA))
    assert stops[-1] == (1.0, pytest.approx(0.0))
    offsets = [o for o, _ in stops]
    alphas = [a for _, a in stops]
    assert offsets == sorted(offsets)
    assert all(a > b for a, b in itertools.pairwise(alphas))
    assert all(0.0 <= a <= 1.0 for a in alphas)
    assert len(glow_stops(3)) == 4
    with pytest.raises(ValueError, match="steps"):
        glow_stops(0)


def test_ease() -> None:
    assert ease(-1) == 0.0
    assert ease(0) == 0.0
    assert ease(0.5) == pytest.approx(0.5)
    assert ease(1) == 1.0
    assert ease(2) == 1.0
    samples = [ease(i / 20) for i in range(21)]
    assert samples == sorted(samples)


# ---------------------------------------------------------------------------------------------
# Fade
# ---------------------------------------------------------------------------------------------


def test_fade_in_from_hidden_uses_target_colour() -> None:
    fade = Fade(0.15)
    assert fade.retarget(RED, 1.0, now=0.0)
    mid = fade.sample(0.075)
    assert mid.colour == RED  # no cross-fade from the invisible start colour
    assert mid.opacity == pytest.approx(0.5)
    assert fade.running(0.1)
    assert not fade.running(0.15)
    assert fade.sample(0.2) == Frame(RED, 1.0)


def test_fade_cross_fades_colour_at_full_opacity() -> None:
    fade = Fade(0.1)
    fade.retarget(RED, 1.0, 0.0)
    fade.retarget(BLUE, 1.0, 1.0)
    mid = fade.sample(1.05)
    assert mid.opacity == 1.0
    assert mid.colour == pytest.approx((0.5, 0.0, 0.5, 1.0))


def test_fade_retarget_same_is_noop() -> None:
    fade = Fade(0.1)
    assert fade.retarget(RED, 1.0, 0.0)
    assert not fade.retarget(RED, 1.0, 0.05)
    assert not fade.retarget(None, 1.0, 0.05)


def test_fade_interrupted_starts_from_current_value() -> None:
    fade = Fade(0.1)
    fade.retarget(RED, 1.0, 0.0)
    halfway = fade.sample(0.05)
    fade.retarget(None, 0.0, 0.05)  # hide mid fade-in
    assert fade.sample(0.05) == halfway  # no jump
    assert fade.sample(0.15).opacity == 0.0


def test_fade_zero_duration_is_instant() -> None:
    fade = Fade(0.0)
    fade.retarget(RED, 1.0, 0.0)
    assert not fade.running(0.0)
    assert fade.sample(0.0) == Frame(RED, 1.0)


def test_fade_restart_shifts_start() -> None:
    fade = Fade(0.1)
    fade.retarget(RED, 1.0, 0.0)
    fade.restart(5.0)
    assert fade.sample(5.0).opacity == 0.0
    assert fade.running(5.05)


# ---------------------------------------------------------------------------------------------
# Bar state machine with a fake frame clock
# ---------------------------------------------------------------------------------------------


def test_bar_show_maps_animates_then_stops_ticking() -> None:
    bar, surface, clock = make_bar()
    assert bar.set_indicator(Indicator.RED)
    assert surface.mapped
    assert surface.maps == 1
    assert surface.ticking
    assert bar.ticking
    run_frames(surface, clock, 30)  # 0.5 s, far longer than the 150 ms fade
    assert not surface.ticking
    assert not bar.ticking
    assert bar.frame() == Frame(bar.look.red, 1.0)
    assert 8 <= bar.draws <= 12  # about 150 ms of 60 Hz frames
    assert bar.idle_draws == 0


def test_bar_does_no_redraws_after_fade() -> None:
    bar, surface, clock = make_bar()
    bar.set_indicator(Indicator.BLUE)
    run_frames(surface, clock, 20)
    draws = bar.draws
    run_frames(surface, clock, 600)  # ten idle seconds of frames
    assert bar.draws == draws
    assert bar.idle_draws == 0


def test_bar_fade_starts_at_first_frame_after_slow_map() -> None:
    bar, surface, clock = make_bar()
    bar.set_indicator(Indicator.RED)
    clock.advance(0.5)  # the compositor took 500 ms to map the window
    surface.frame()
    assert bar.frame().opacity == 0.0  # the fade has just begun, not already finished
    run_frames(surface, clock, 30)
    assert bar.draws >= 8


def test_bar_hide_unmaps_after_fade() -> None:
    bar, surface, clock = make_bar()
    bar.set_indicator(Indicator.RED)
    run_frames(surface, clock, 20)
    assert bar.set_indicator(Indicator.HIDDEN)
    assert surface.mapped  # still fading out
    run_frames(surface, clock, 20)
    assert not surface.mapped
    assert surface.unmaps == 1
    assert not bar.mapped
    assert not bar.ticking
    draws = bar.draws
    run_frames(surface, clock, 100)
    assert bar.draws == draws


def test_bar_colour_change_cross_fades_without_remap() -> None:
    bar, surface, clock = make_bar()
    bar.set_indicator(Indicator.RED)
    run_frames(surface, clock, 20)
    bar.set_indicator(Indicator.BLUE)
    assert surface.maps == 1
    run_frames(surface, clock, 4)
    mid = bar.frame()
    assert mid.opacity == 1.0
    assert mid.colour != bar.look.red
    assert mid.colour != bar.look.blue
    run_frames(surface, clock, 20)
    assert bar.frame() == Frame(bar.look.blue, 1.0)
    assert bar.idle_draws == 0


def test_bar_is_idempotent() -> None:
    bar, surface, clock = make_bar()
    assert bar.set_indicator(Indicator.RED)
    run_frames(surface, clock, 20)
    draws = bar.draws
    assert not bar.set_indicator(Indicator.RED)
    assert not surface.ticking
    run_frames(surface, clock, 10)
    assert bar.draws == draws


def test_bar_hidden_when_already_hidden_does_nothing() -> None:
    bar, surface, _clock = make_bar()
    assert not bar.set_indicator(Indicator.HIDDEN)
    assert surface.maps == 0


def test_bar_show_during_fade_out_reverses_without_unmap() -> None:
    bar, surface, clock = make_bar()
    bar.set_indicator(Indicator.RED)
    run_frames(surface, clock, 20)
    bar.set_indicator(Indicator.HIDDEN)
    run_frames(surface, clock, 3)
    bar.set_indicator(Indicator.RED)
    run_frames(surface, clock, 20)
    assert surface.unmaps == 0
    assert surface.mapped
    assert bar.frame() == Frame(bar.look.red, 1.0)


def test_bar_zero_fade_is_instant() -> None:
    bar, surface, clock = make_bar(fade_ms=0)
    bar.set_indicator(Indicator.BLUE)
    assert surface.mapped
    assert not surface.ticking
    run_frames(surface, clock, 1)
    assert bar.draws == 1
    assert bar.idle_draws == 0
    bar.set_indicator(Indicator.HIDDEN)
    assert not surface.mapped


def test_bar_settled_callback_and_detached_bar() -> None:
    clock = FakeClock()
    settled: list[Indicator] = []
    bar = Bar(
        "X", Look.from_config(AppearanceConfig()), clock, lambda b: settled.append(b.indicator)
    )
    assert bar.set_indicator(Indicator.RED)  # no surface yet: state changes, nothing drawn
    assert not bar.tick()
    surface = FakeSurface(bar)
    bar.attach(surface)
    bar.set_indicator(Indicator.BLUE)
    run_frames(surface, clock, 20)
    assert settled == [Indicator.BLUE]
    bar.destroy()
    bar.destroy()
    assert surface.destroyed == 1


# ---------------------------------------------------------------------------------------------
# paint() against a real cairo image surface
# ---------------------------------------------------------------------------------------------


def test_paint_draws_core_and_glow() -> None:
    cairo = pytest.importorskip("cairo")
    look = Look.from_config(AppearanceConfig(red="#FF0000", thickness=3, glow=12))
    image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 15)
    cr = cairo.Context(image)
    overlay.paint(cr, 10, 15, Frame(look.red, 1.0), look, 1.0)
    image.flush()
    data = image.get_data()
    stride = image.get_stride()

    def pixel(y: int) -> tuple[int, int, int, int]:
        b, g, r, a = data[y * stride + 20 : y * stride + 24]
        return r, g, b, a

    for y in (12, 13, 14):  # the 3 px core at the bottom
        assert pixel(y) == (255, 0, 0, 255)
    alphas = [pixel(y)[3] for y in range(12)]
    assert alphas == sorted(alphas)  # glow brighter towards the core
    assert alphas[0] < 10
    assert alphas[11] > 100


def test_paint_hidden_frame_is_transparent() -> None:
    cairo = pytest.importorskip("cairo")
    look = Look.from_config(AppearanceConfig())
    image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 15)
    cr = cairo.Context(image)
    cr.set_source_rgba(1, 1, 1, 1)
    cr.paint()  # paint() must clear what was there before
    overlay.paint(cr, 4, 15, Frame(look.red, 0.0), look, 1.6)
    image.flush()
    assert set(bytes(image.get_data())) == {0}


# ---------------------------------------------------------------------------------------------
# GlowOverlay over a fake backend
# ---------------------------------------------------------------------------------------------


class FakeBackend:
    def __init__(self, monitors: set[str]) -> None:
        self.present = set(monitors)
        self.surfaces: dict[str, FakeSurface] = {}
        self.callback: Callable[[set[str]], None] | None = None
        self.closed = 0
        self.fail_create = False

    def monitors(self) -> set[str]:
        return set(self.present)

    def create(self, monitor: str, bar: Bar) -> FakeSurface | None:
        if self.fail_create:
            raise RuntimeError("toolkit exploded")
        if monitor not in self.present:
            return None
        surface = FakeSurface(bar)
        self.surfaces[monitor] = surface
        return surface

    def watch_monitors(self, callback: Callable[[set[str]], None]) -> None:
        self.callback = callback

    def change(self, monitors: set[str]) -> None:
        self.present = set(monitors)
        assert self.callback is not None
        self.callback(self.monitors())

    def close(self) -> None:
        self.closed += 1

    def frames(self, clock: FakeClock, n: int) -> None:
        for _ in range(n):
            clock.advance(1 / 60)
            for surface in list(self.surfaces.values()):
                surface.frame()


def make_overlay(
    monitors: set[str] | None = None, log: EventLog | None = None
) -> tuple[GlowOverlay, FakeBackend, FakeClock]:
    clock = FakeClock()
    backend = FakeBackend(monitors if monitors is not None else {"DP-1", "HDMI-A-1"})
    return GlowOverlay(AppearanceConfig(), backend=backend, log=log, clock=clock), backend, clock


def show(indicator: Indicator, monitor: str) -> Decision:
    return Decision(indicator, monitor if indicator is not Indicator.HIDDEN else "", "test")


def test_overlay_is_an_indicator_sink() -> None:
    ov, _, _ = make_overlay()
    assert isinstance(ov, IndicatorSink)


def test_overlay_shows_only_on_the_decided_monitor() -> None:
    ov, backend, clock = make_overlay()
    ov.apply(show(Indicator.RED, "DP-1"))
    backend.frames(clock, 20)
    assert set(backend.surfaces) == {"DP-1"}  # no surface at all on the other monitor
    ov.apply(show(Indicator.RED, "HDMI-A-1"))
    backend.frames(clock, 20)
    assert not backend.surfaces["DP-1"].mapped
    assert backend.surfaces["HDMI-A-1"].mapped
    assert ov.bars["HDMI-A-1"].frame() == Frame(ov.look.red, 1.0)
    assert ov.stats() == {"draws": ov.stats()["draws"], "idle_draws": 0, "animating": 0}


def test_overlay_hidden_fades_everything_out() -> None:
    ov, backend, clock = make_overlay()
    ov.apply(show(Indicator.BLUE, "DP-1"))
    backend.frames(clock, 20)
    ov.apply(show(Indicator.HIDDEN, ""))
    backend.frames(clock, 20)
    assert not backend.surfaces["DP-1"].mapped
    draws = ov.stats()["draws"]
    backend.frames(clock, 300)
    assert ov.stats()["draws"] == draws


def test_overlay_apply_is_idempotent() -> None:
    ov, backend, clock = make_overlay()
    ov.apply(show(Indicator.RED, "DP-1"))
    backend.frames(clock, 20)
    draws = ov.stats()["draws"]
    for reason in ("a", "b", "c"):
        ov.apply(Decision(Indicator.RED, "DP-1", reason))
        backend.frames(clock, 10)
    assert ov.stats()["draws"] == draws
    assert backend.surfaces["DP-1"].maps == 1


def test_overlay_unknown_monitor_logs_and_shows_nothing(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    ov, backend, _ = make_overlay({"DP-1"}, log=log)
    ov.apply(show(Indicator.RED, "DP-9"))
    assert backend.surfaces == {}
    log.close()
    events = [json.loads(line) for line in log.events_path.read_text().splitlines()]
    assert events[-1]["event"] == "overlay_monitor_missing"
    assert events[-1]["level"] == "error"
    assert events[-1]["inputs"] == {"monitor": "DP-9", "known": "DP-1"}


def test_overlay_monitor_unplug_and_replug(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    ov, backend, clock = make_overlay(log=log)
    ov.apply(show(Indicator.BLUE, "HDMI-A-1"))
    backend.frames(clock, 20)
    first = backend.surfaces["HDMI-A-1"]
    backend.change({"DP-1"})  # unplugged
    assert first.destroyed == 1
    assert "HDMI-A-1" not in ov.bars
    backend.frames(clock, 20)  # nothing crashes, nothing left to draw
    backend.change({"DP-1", "HDMI-A-1"})  # plugged back in: the bar comes back
    second = backend.surfaces["HDMI-A-1"]
    assert second is not first
    assert second.mapped
    backend.frames(clock, 20)
    assert ov.bars["HDMI-A-1"].frame() == Frame(ov.look.blue, 1.0)
    log.close()
    events = [json.loads(line)["event"] for line in log.events_path.read_text().splitlines()]
    assert "overlay_monitor" in events


def test_overlay_replug_of_other_monitor_does_not_show_bar() -> None:
    ov, backend, _ = make_overlay()
    ov.apply(show(Indicator.HIDDEN, ""))
    backend.change({"DP-1"})
    backend.change({"DP-1", "HDMI-A-1"})
    assert backend.surfaces == {}


def test_overlay_toolkit_fault_is_logged_not_raised(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    ov, backend, _ = make_overlay(log=log)
    backend.fail_create = True
    ov.apply(show(Indicator.RED, "DP-1"))  # must not raise (S4)
    log.close()
    last = json.loads(log.events_path.read_text().splitlines()[-1])
    assert last["event"] == "overlay_error"
    assert "toolkit exploded" in last["reason"]


def test_overlay_logs_changes_and_settles(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    settled: list[str] = []
    clock = FakeClock()
    backend = FakeBackend({"DP-1"})
    ov = GlowOverlay(
        AppearanceConfig(),
        backend=backend,
        log=log,
        clock=clock,
        on_settled=lambda bar: settled.append(bar.indicator.value),
    )
    ov.apply(show(Indicator.RED, "DP-1"))
    backend.frames(clock, 20)
    ov.apply(show(Indicator.RED, "DP-1"))  # repeat: not logged again
    log.close()
    events = [json.loads(line) for line in log.events_path.read_text().splitlines()]
    assert [e["event"] for e in events] == ["overlay", "overlay_settled"]
    assert events[0]["inputs"] == {"monitor": "DP-1", "indicator": "red"}
    assert events[1]["level"] == "debug"
    assert int(events[1]["inputs"]["draws"]) > 0
    assert settled == ["red"]


def test_overlay_close_is_safe_twice_and_ignores_later_input() -> None:
    ov, backend, _clock = make_overlay()
    ov.apply(show(Indicator.RED, "DP-1"))
    ov.close()
    ov.close()
    assert backend.surfaces["DP-1"].destroyed == 1
    assert backend.closed == 1
    ov.apply(show(Indicator.BLUE, "DP-1"))
    backend.change(set())
    assert ov.bars == {}


def test_overlay_default_backend_is_gtk(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[bool] = []

    class StubBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__(set())
            made.append(True)

    monkeypatch.setattr(overlay, "GtkBackend", StubBackend)
    GlowOverlay(AppearanceConfig())
    assert made == [True]


# ---------------------------------------------------------------------------------------------
# LD_PRELOAD re-exec
# ---------------------------------------------------------------------------------------------


def test_preload_command_sets_preload_once() -> None:
    lib = "/usr/lib/libgtk4-layer-shell.so"
    command = preload_command(["preview", "red"], {"PATH": "/bin"}, lib)
    assert command is not None
    args, env = command
    assert args[1:] == ["-m", "vpn_monitor", "preview", "red"]
    assert env["LD_PRELOAD"] == lib
    assert env[PRELOAD_GUARD] == "1"
    assert env["PATH"] == "/bin"
    # Already preloaded, or already re-exec'd once, or no library: no re-exec.
    assert preload_command(["x"], env, lib) is None
    assert preload_command(["x"], {PRELOAD_GUARD: "1"}, lib) is None
    assert preload_command(["x"], {}, None) is None


def test_preload_command_keeps_existing_preload() -> None:
    command = preload_command(
        [], {"LD_PRELOAD": "/opt/other.so"}, "/usr/lib/libgtk4-layer-shell.so"
    )
    assert command is not None
    assert command[1]["LD_PRELOAD"] == "/usr/lib/libgtk4-layer-shell.so /opt/other.so"


def test_find_layer_shell_lib(tmp_path: Path) -> None:
    assert find_layer_shell_lib([str(tmp_path)]) is None
    (tmp_path / "libgtk4-layer-shell.so").write_bytes(b"")
    assert find_layer_shell_lib(["/nonexistent", str(tmp_path)]) == str(
        tmp_path / "libgtk4-layer-shell.so"
    )


# ---------------------------------------------------------------------------------------------
# CLI preview helpers
# ---------------------------------------------------------------------------------------------


def test_preview_parser() -> None:
    args = cli.build_parser().parse_args(
        ["preview", "cycle", "--seconds", "5", "--monitor", "DP-1", "--backdrop", "--log"]
    )
    assert (args.mode, args.seconds, args.monitor, args.backdrop, args.log) == (
        "cycle",
        5.0,
        "DP-1",
        True,
        True,
    )
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["preview", "green"])


def test_preview_steps() -> None:
    assert cli.preview_steps("red") == (Indicator.RED,)
    assert cli.preview_steps("blue") == (Indicator.BLUE,)
    assert cli.preview_steps("cycle") == (Indicator.RED, Indicator.BLUE, Indicator.HIDDEN)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('[{"name":"eDP-1","focused":false},{"name":"HDMI-A-1","focused":true}]', "HDMI-A-1"),
        ('[{"name":"eDP-1","focused":false}]', None),
        ('{"name":"x"}', None),
        ("not json", None),
    ],
)
def test_focused_monitor(monkeypatch: pytest.MonkeyPatch, reply: str, expected: str | None) -> None:
    from vpn_monitor import focus

    monkeypatch.setattr(focus, "socket_request", lambda _cmd: reply)
    assert cli.focused_monitor() == expected


def test_focused_monitor_without_hyprland(monkeypatch: pytest.MonkeyPatch) -> None:
    from vpn_monitor import focus

    def fail(_cmd: str) -> str:
        raise OSError("no socket")

    monkeypatch.setattr(focus, "socket_request", fail)
    assert cli.focused_monitor() is None


# ---------------------------------------------------------------------------------------------
# Defaults and privacy
# ---------------------------------------------------------------------------------------------


def test_example_config_matches_appearance_defaults() -> None:
    example = Path(__file__).parent.parent / "config" / "config.example.toml"
    assert load_config(example).appearance == Config().appearance


def test_overlay_module_has_no_network_or_title_access() -> None:
    source = Path(overlay.__file__).read_text()
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (
            node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")]
        )
    }
    assert not imported & {"socket", "http", "urllib", "requests", "ssl"}
    assert "title" not in source.lower()  # the overlay never sees a window title (S1)
