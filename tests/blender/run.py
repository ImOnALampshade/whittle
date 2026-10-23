# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point for Blender-side tests: `blender -b --python tests/blender/run.py`.

Blender swallows a script's unittest exit status unless we exit explicitly,
so the result is turned into the process exit code here.
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    verbosity = 2 if "-v" in argv else 1
    loader = unittest.TestLoader()
    # -k PATTERN runs only the matching tests, as unittest's own -k does.
    patterns = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "-k"]
    if patterns:
        loader.testNamePatterns = [p if "*" in p else f"*{p}*" for p in patterns]
    suite = loader.discover(os.path.join(REPO, "tests", "blender"), pattern="test_*.py",
                            top_level_dir=REPO)
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    if result.testsRun == 0:
        # unittest's own exit code for an empty run, so run_tests.sh can tell
        # "nothing matched here" from a failure.
        print("NO BLENDER TESTS RAN", file=sys.stderr)
        return 5
    return 0 if result.wasSuccessful() else 1


sys.exit(main())
