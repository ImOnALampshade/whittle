#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs the whole suite: agent-side tests in the dev venv, then Blender-side
# tests inside a background Blender. Every step is time-bounded so a hung
# bridge or render can never stall the run.
#
# WHITTLE_LIVE=1 also runs the live tests, which call the Claude API; Blender
# then needs --online-mode or it refuses to start the real agent.
set -eu
cd "$(dirname "$0")"

online=""
if [ "${WHITTLE_LIVE:-}" = "1" ]; then
    online="--online-mode"
fi

# unittest exits 5 when it ran no test. With -k a pattern may match tests on
# one side only, so a side that matched nothing is not a failure unless the
# other side matched nothing too.
agent=0
timeout 300 .venv/bin/python -m unittest discover -s tests/agent -t . "$@" || agent=$?
if [ "$agent" -ne 0 ] && [ "$agent" -ne 5 ]; then
    exit "$agent"
fi
blender=0
timeout 900 blender -b --factory-startup $online --python-exit-code 1 \
    --python tests/blender/run.py -- "$@" || blender=$?
if [ "$blender" -ne 0 ] && [ "$blender" -ne 5 ]; then
    exit "$blender"
fi
if [ "$agent" -eq 5 ] && [ "$blender" -eq 5 ]; then
    echo "run_tests.sh: no test matched" >&2
    exit 5
fi
