# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes Blender's calls to a runner after checking their parameters."""

import asyncio
import time
from typing import Protocol

from ..models import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS
from ..protocol import ErrorCode, Method
from .connection import BridgeCallError


class Runner(Protocol):
    async def start_session(self, params: dict) -> None: ...
    async def submit(self, turn_id: str, bundle_dir: str, prompt: str,
                     context: tuple[str, ...] = (), model: str | None = None,
                     effort: str | None = None) -> None: ...
    async def amend(self, turn_id: str, text: str, bundle_dir: str | None,
                    number: int | None) -> None: ...
    async def interrupt(self, turn_id: str) -> None: ...
    async def close(self) -> None: ...


def require(params: dict, key: str, types, *, default=..., optional: bool = False):
    if key not in params or (optional and params[key] is None):
        if default is not ...:
            return default
        if optional:
            return None
        raise BridgeCallError(ErrorCode.BAD_REQUEST, f"missing parameter {key!r}")
    value = params[key]
    if not isinstance(value, types) or (isinstance(value, bool) and bool not in _as_tuple(types)):
        raise BridgeCallError(ErrorCode.BAD_REQUEST, f"parameter {key!r} has the wrong type")
    return value


def _as_tuple(types) -> tuple:
    return types if isinstance(types, tuple) else (types,)


def require_effort(params: dict, **kwargs) -> str | None:
    effort = require(params, "effort", str, **kwargs)
    if effort is not None and effort not in EFFORTS:
        raise BridgeCallError(ErrorCode.BAD_REQUEST, f"parameter 'effort' must be one of {', '.join(EFFORTS)}")
    return effort


def session_params(params: dict) -> dict:
    """Normalises start_session params, filling defaults for optional fields."""
    settings = require(params, "settings", dict, default={})
    for key in ("max_turns", "self_check_rounds", "poly_budget", "render_size"):
        if settings.get(key) is not None and not isinstance(settings[key], int):
            raise BridgeCallError(ErrorCode.BAD_REQUEST, f"settings.{key} must be an integer")
    if settings.get("max_budget_usd") is not None and not isinstance(settings["max_budget_usd"], (int, float)):
        raise BridgeCallError(ErrorCode.BAD_REQUEST, "settings.max_budget_usd must be a number")
    return {
        "session_dir": require(params, "session_dir", str),
        "store_dir": require(params, "store_dir", str, optional=True),
        "model": require(params, "model", str, default=DEFAULT_MODEL),
        "effort": require_effort(params, default=DEFAULT_EFFORT),
        "resume": require(params, "resume", str, optional=True),
        "fork": require(params, "fork", bool, default=False),
        "resume_at": require(params, "resume_at", str, optional=True),
        "settings": settings,
    }


def make_dispatcher(runner: Runner, shutdown: asyncio.Event):
    async def dispatch(method: str, params: dict) -> dict:
        if method == Method.PING:
            return {"time": time.time()}
        if method == Method.SHUTDOWN:
            shutdown.set()
            return {}
        if method == Method.START_SESSION:
            await runner.start_session(session_params(params))
            return {}
        if method == Method.SUBMIT:
            context = require(params, "context", list, default=[])
            if not all(isinstance(line, str) for line in context):
                raise BridgeCallError(ErrorCode.BAD_REQUEST, "parameter 'context' must hold strings")
            await runner.submit(require(params, "turn_id", str),
                                require(params, "bundle_dir", str),
                                require(params, "prompt", str, default=""),
                                tuple(context),
                                # The chat's model: the runner switches a session on another one.
                                model=require(params, "model", str, optional=True),
                                # Its effort, likewise switched on the live session.
                                effort=require_effort(params, optional=True))
            return {"accepted": True}
        if method == Method.AMEND:
            await runner.amend(require(params, "turn_id", str),
                               require(params, "text", str),
                               require(params, "bundle_dir", str, optional=True),
                               require(params, "amend", int, optional=True))
            return {"queued": True}
        if method == Method.INTERRUPT:
            await runner.interrupt(require(params, "turn_id", str))
            return {}
        raise BridgeCallError(ErrorCode.UNKNOWN_METHOD, f"unknown method {method!r}")

    return dispatch
