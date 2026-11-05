#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds the documentation site from docs/site into build/docs/html. No Blender
# and no network: the source's imports are mocked and the theme is local.
#
#   --out DIR  put html and doctrees wholly in DIR (DIR/html, DIR/doctrees),
#              so builds running at once never share a folder
#   --strict   make warnings errors. Rebuilds every page, because an
#              incremental build would not repeat an unchanged page's warnings.
set -eu
cd "$(dirname "$0")"

out=build/docs
strict=""
while [ $# -gt 0 ]; do
    case "$1" in
        --out)
            [ $# -ge 2 ] || { echo "docs.sh: --out needs a folder" >&2; exit 2; }
            out="$2"
            shift 2
            ;;
        --strict)
            strict="--fail-on-warning --keep-going --fresh-env --write-all"
            shift
            ;;
        *)
            echo "usage: ./docs.sh [--out DIR] [--strict]" >&2
            exit 2
            ;;
    esac
done

if [ ! -x .venv-docs/bin/sphinx-build ]; then
    cat >&2 <<'HELP'
docs.sh: .venv-docs is missing. Make it from the hash-pinned lock:
  python3 -m venv .venv-docs
  .venv-docs/bin/pip install --require-hashes --only-binary :all: --no-deps -r docs/site/requirements.lock
HELP
    exit 1
fi

# Autodoc imports the source; builds running at once should not race on its
# bytecode, and a docs build has no reason to leave any behind.
export PYTHONDONTWRITEBYTECODE=1
timeout 600 .venv-docs/bin/sphinx-build --builder html --quiet $strict \
    --doctree-dir "$out/doctrees" docs/site "$out/html"
echo "docs.sh: built $out/html/index.html"
