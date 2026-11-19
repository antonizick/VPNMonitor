import dataclasses

import pytest

from vpn_monitor.model import (
    Decision,
    FamilyRoute,
    FocusEvent,
    Indicator,
    MonitorInfo,
    RouteKind,
    VpnReading,
    VpnState,
)


def test_focus_event_has_no_title_field() -> None:
    names = {f.name for f in dataclasses.fields(FocusEvent)}
    assert not any("title" in n for n in names)
    assert names == {"window_class", "address", "monitor", "fullscreen"}


def test_no_type_has_a_title_field() -> None:
    for cls in (MonitorInfo, FocusEvent, FamilyRoute, VpnReading, Decision):
        assert all("title" not in f.name for f in dataclasses.fields(cls))


def test_focus_event_is_immutable() -> None:
    ev = FocusEvent("brave-browser", "0x1", "DP-1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.window_class = "other"  # type: ignore[misc]


def test_reading_and_decision_are_immutable() -> None:
    route = FamilyRoute(4, "192.0.2.1", "proton0", RouteKind.ROUTED, True)
    reading = VpnReading(VpnState.VPN, (route,), "ok", 1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        reading.state = VpnState.NO_VPN  # type: ignore[misc]
    decision = Decision(Indicator.BLUE, "DP-1", "vpn")
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.indicator = Indicator.RED  # type: ignore[misc]


def test_enum_values() -> None:
    assert {s.value for s in VpnState} == {"vpn", "no_vpn", "unknown"}
    assert {i.value for i in Indicator} == {"hidden", "red", "blue"}
