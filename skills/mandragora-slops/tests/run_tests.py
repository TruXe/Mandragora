"""Run the mandragora-slops test suite (standard library unittest).

    python tests/run_tests.py            # from the skill folder or anywhere

Generated fixtures that are missing are rebuilt first by make_fixtures.py.
Exit code 0 when every test passes, 1 otherwise.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(HERE))

import make_fixtures  # noqa: E402


def main() -> int:
    make_fixtures.main(skip_existing=True)
    suite = unittest.TestLoader().discover(str(HERE), pattern="test_*.py", top_level_dir=str(HERE))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    failed = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)
    passed = result.testsRun - failed - skipped
    print(f"SUMMARY: {result.testsRun} tests run, {passed} passed, {failed} failed, "
          f"{skipped} skipped")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
