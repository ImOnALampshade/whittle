#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# The docs site's screenshots (docs/site/shots/README.md): ./docs_shots.sh
# <page-slug> [shot ...], --all, --list or --check. Every Blender runs in a
# hidden nested session of its own, against folders of its own under
# build/docs-shots/, and a limited number run at once across the machine, so
# many of these can run side by side. Everything in it is time-bounded.
set -eu
cd "$(dirname "$0")"
exec timeout -k 20 14400 .venv/bin/python -m tests.docshots.run "$@"
