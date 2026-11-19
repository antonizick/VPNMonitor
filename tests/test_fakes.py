from vpn_monitor.fakes import FakeFocusSource, FakeVpnSource, RecordingSink
from vpn_monitor.model import (
    Decision,
    FocusEvent,
    FocusSource,
    Indicator,
    IndicatorSink,
    VpnReading,
    VpnSource,
    VpnState,
)

A = FocusEvent("brave-browser", "0x1", "DP-1")
B = FocusEvent("Alacritty", "0x2", "DP-1")


def test_fakes_satisfy_protocols() -> None:
    assert isinstance(FakeFocusSource(), FocusSource)
    assert isinstance(FakeVpnSource(), VpnSource)
    assert isinstance(RecordingSink(), IndicatorSink)


def test_focus_source_delivers_initial_then_script() -> None:
    src = FakeFocusSource([A, B])
    got: list[FocusEvent] = []
    src.start(got.append)
    assert got == [A]
    assert src.emit_next() is True
    assert got == [A, B]
    assert src.emit_next() is False
    src.stop()
    src.emit(A)
    assert got == [A, B]


def test_vpn_source_records_active_and_delivers() -> None:
    r1 = VpnReading(VpnState.VPN, (), "ok", 1.0)
    r2 = VpnReading(VpnState.UNKNOWN, (), "stale", 2.0)
    src = FakeVpnSource([r1, r2])
    got: list[VpnReading] = []
    src.start(got.append)
    src.set_active(True)
    src.set_active(False)
    src.emit_next()
    assert got == [r1, r2]
    assert src.active_history == [True, False]
    assert src.active is False


def test_recording_sink() -> None:
    sink = RecordingSink()
    assert sink.last is None
    d = Decision(Indicator.RED, "DP-1", "no vpn")
    sink.apply(d)
    sink.close()
    assert sink.last == d
    assert sink.closed
