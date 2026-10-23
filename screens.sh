#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Screenshots of the Whittle sidebar in a real GUI Blender, one scenario at a
# time, into build/screens/ (see tests/screens/run.py). Each Blender runs
# under its own timeout and quits by itself; the agent is the fake one.
set -eu
cd "$(dirname "$0")"
exec timeout 3600 .venv/bin/python -m tests.screens.run "$@"
