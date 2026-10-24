#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Validates the extension and builds its zip into build/ (gitignored), or
# into the folder given as the first argument.
#
# The packaged lock must be a byte-identical copy of agent_env's. This script
# never copies it: a difference is something to look at, not to paper over.
# The packaged LICENSE is a copy of the repo's, so the zip carries the GPL.
#
# One zip serves every platform in the manifest. --split-platforms is for
# extensions that bundle wheels; Whittle bundles none (pip downloads the
# platform's own wheels at setup), so it would only make identical zips.
set -eu
cd "$(dirname "$0")"
out="${1:-build}"
cmp -s agent_env/requirements.lock whittle/requirements.lock || {
    echo "whittle/requirements.lock differs from agent_env/requirements.lock" >&2
    exit 1
}
cmp -s LICENSE whittle/LICENSE || {
    echo "whittle/LICENSE differs from LICENSE" >&2
    exit 1
}
mkdir -p "$out"
timeout 120 blender --factory-startup --command extension validate whittle
timeout 300 blender --factory-startup --command extension build --source-dir whittle --output-dir "$out"
