"""GLibScheduler against a real GLib main context (skipped without PyGObject)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from vpn_monitor.fakes import FakeScheduler

pytestmark = pytest.mark.gi


def _run(loop: Any, glib: Any, max_ms: int = 2000) -> None:
    glib.timeout_add(max_ms, lambda: loop.quit() or False)
    loop.run()


def test_call_later_fires_once_and_cancel_is_safe() -> None:
    from gi.repository import GLib

    from vpn_monitor.mainloop import GLibScheduler

    sched, loop, fired = GLibScheduler(), GLib.MainLoop(), []
    handle = sched.call_later(0.01, lambda: (fired.append(1), loop.quit()))
    cancelled = sched.call_later(0.005, lambda: fired.append(99))
    sched.cancel(cancelled)
    _run(loop, GLib)
    assert fired == [1]
    sched.cancel(handle)  # already fired: ignored
    sched.cancel(424242)  # unknown: ignored


def test_watch_fd_reports_data_and_stops_on_false() -> None:
    from gi.repository import GLib

    from vpn_monitor.mainloop import GLibScheduler

    sched, loop = GLibScheduler(), GLib.MainLoop()
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    got: list[bytes] = []

    def ready() -> bool:
        chunk = os.read(read_fd, 100)
        got.append(chunk)
        if chunk == b"":
            loop.quit()
            return False
        os.close(write_fd)  # next wake-up is EOF
        return True

    handle = sched.watch_fd(read_fd, ready)
    os.write(write_fd, b"x\n")
    _run(loop, GLib)
    os.close(read_fd)
    assert got == [b"x\n", b""]
    sched.cancel(handle)  # removed already: ignored


def test_fake_scheduler_orders_timers() -> None:
    sched, order = FakeScheduler(), []
    sched.call_later(2, lambda: order.append("b"))
    sched.call_later(
        1, lambda: (order.append("a"), sched.call_later(0.5, lambda: order.append("c")))
    )
    sched.advance(3)
    assert order == ["a", "c", "b"]
    assert sched.now == 1003.0
