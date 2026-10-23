#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# The GUI checks (tests/gui/catalog.py): flows only a real GUI Blender can
# show, driven with simulated input in a hidden nested session, one Blender
# per phase, each under a timeout. The agent is the fake one; results and
# logs go to build/gui-checks/.
set -eu
cd "$(dirname "$0")"
exec timeout 3600 .venv/bin/python -m tests.gui.run "$@"
