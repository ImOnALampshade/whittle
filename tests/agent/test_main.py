# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import signal
import sys
import types
import unittest

from whittle.agent.__main__ import watch_signals


class FakeLoop:
    def __init__(self, error=None):
        self.error = error
        self.handlers = {}
        self.soon = []

    def add_signal_handler(self, sig, callback):
        if self.error is not None:
            raise self.error
        self.handlers[sig] = callback

    def call_soon_threadsafe(self, callback):
        self.soon.append(callback)


class FakeSignals(types.SimpleNamespace):
    def signal(self, sig, handler):
        if sig in getattr(self, "refused", ()):
            raise ValueError("not here")
        self.installed[sig] = handler


class WatchSignalsTest(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "the loop takes signal handlers")
    def test_posix_loop_handles_sigterm(self):
        async def watch():
            shutdown = asyncio.Event()
            loop = asyncio.get_running_loop()
            try:
                return watch_signals(loop, shutdown), shutdown
            finally:
                loop.remove_signal_handler(signal.SIGTERM)

        watched, _shutdown = asyncio.run(watch())
        self.assertEqual(watched, [signal.SIGTERM])

    def test_loop_handler(self):
        loop, shutdown = FakeLoop(), asyncio.Event()
        signals = FakeSignals(SIGTERM=15, installed={})
        self.assertEqual(watch_signals(loop, shutdown, signals), [15])
        self.assertEqual(loop.handlers, {15: shutdown.set})
        self.assertEqual(signals.installed, {})

    def test_windows_loop_falls_back_to_a_plain_handler(self):
        # The proactor loop raises NotImplementedError; Windows also has SIGBREAK.
        loop, shutdown = FakeLoop(NotImplementedError()), asyncio.Event()
        signals = FakeSignals(SIGTERM=15, SIGBREAK=21, installed={})
        self.assertEqual(watch_signals(loop, shutdown, signals), [15, 21])
        self.assertEqual(set(signals.installed), {15, 21})
        signals.installed[21](21, None)
        self.assertEqual(loop.soon, [shutdown.set], "the handler hands the signal to the loop")

    def test_a_refused_signal_is_skipped(self):
        loop, shutdown = FakeLoop(RuntimeError()), asyncio.Event()
        signals = FakeSignals(SIGTERM=15, SIGBREAK=21, installed={}, refused={15})
        self.assertEqual(watch_signals(loop, shutdown, signals), [21])


if __name__ == "__main__":
    unittest.main()
