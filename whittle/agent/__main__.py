# SPDX-License-Identifier: GPL-3.0-or-later
"""`python -m whittle.agent --port N [--fake SCRIPT]`

Connects back to Blender, performs the handshake, then serves calls until
Blender sends shutdown or closes the socket. Exit codes: 0 on shutdown or EOF,
2 on a failed handshake or startup.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys

from .connection import Connection, HandshakeError
from .dispatch import make_dispatcher

log = logging.getLogger("whittle.agent")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m whittle.agent")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--fake", metavar="SCRIPT", help="play a scripted fake agent")
    parser.add_argument("--host", default="127.0.0.1")
    return parser.parse_args(argv)


def make_runner(args, connection):
    if args.fake:
        from .fake import FakeRunner

        return FakeRunner(connection, args.fake)
    from .runner import SdkRunner, list_api_models

    return SdkRunner(connection, list_models=list_api_models)


def watch_signals(loop, shutdown: asyncio.Event, signals=signal) -> list:
    """Makes a terminate signal end the agent like shutdown, and returns the
    signals watched.

    On Linux and macOS Blender terminates an agent that takes too long to
    stop with SIGTERM: it still closes its session, so the SDK's temporary
    config folder (which holds a copy of the credentials) and the CLI go too.
    Windows' event loop takes no signal handlers, so a plain handler passes
    the signal on; it sees SIGBREAK from a console (Ctrl+Break), but Blender
    stops a Windows agent with TerminateProcess, which no handler sees. There
    the shutdown call is the only graceful stop, and the Job Object Blender
    puts the agent in makes sure the CLI ends with it."""
    watched = []
    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signals, name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, shutdown.set)
        except (NotImplementedError, RuntimeError):
            try:
                signals.signal(sig, lambda *_: loop.call_soon_threadsafe(shutdown.set))
            except (OSError, ValueError, RuntimeError):
                continue
        watched.append(sig)
    return watched


async def main(argv: list[str]) -> int:
    args = parse_args(argv)
    shutdown = asyncio.Event()
    watch_signals(asyncio.get_running_loop(), shutdown)
    token = os.environ.get("WHITTLE_TOKEN", "")
    mode = "fake" if args.fake else "sdk"
    try:
        connection = await Connection.open(args.port, token, mode, host=args.host)
    except HandshakeError as exc:
        log.error("%s", exc)
        return 2
    log.info("connected to Blender on port %d (%s mode)", args.port, mode)
    try:
        runner = make_runner(args, connection)
    except Exception:
        log.exception("cannot start the %s runner", mode)
        await connection.close()
        return 2

    connection.set_handler(make_dispatcher(runner, shutdown))
    serve = asyncio.create_task(connection.serve())
    stop = asyncio.create_task(shutdown.wait())
    await asyncio.wait({serve, stop}, return_when=asyncio.FIRST_COMPLETED)
    log.info("shutting down (%s)", "shutdown requested" if shutdown.is_set() else "Blender closed the socket")
    try:
        await asyncio.wait_for(runner.close(), 15.0)
    except Exception:
        log.exception("runner did not close cleanly")
    await connection.close()
    for task in (serve, stop):
        task.cancel()
    return 0


def run() -> int:
    logging.basicConfig(level=os.environ.get("WHITTLE_LOG_LEVEL", "INFO"), stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(main(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(run())
