#!/usr/bin/env python3
# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.
"""Run the test suite as a sequence of short pytest processes.

One pytest process for the whole suite accumulates Qt widgets, RDKit stores, and worker
children until the machine runs out of memory, and native state left by one module can abort a
later one (docs/CONTRIBUTING.md). Each batch here is a fresh process, so its memory is returned
to the OS before the next batch starts. WebEngine-touching viewer modules always run alone.

Examples::

    python scripts/run_tests_in_batches.py
    python scripts/run_tests_in_batches.py --batch-size 10 --stop-on-fail
    python scripts/run_tests_in_batches.py -- --run-slow -x
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
ISOLATED_MODULES = frozenset({"test_protein_viewer.py"})


def batches(files: list[Path], size: int) -> list[list[Path]]:
    """Group test files into batches, with each isolated module in a batch of its own."""
    shared = [f for f in files if f.name not in ISOLATED_MODULES]
    out = [shared[i : i + size] for i in range(0, len(shared), size)]
    out.extend([f] for f in files if f.name in ISOLATED_MODULES)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=20, help="test files per process")
    parser.add_argument(
        "--stop-on-fail", action="store_true", help="stop after the first failing batch"
    )
    parser.add_argument("pytest_args", nargs="*", help="extra pytest arguments (after --)")
    args = parser.parse_args()

    files = sorted(TESTS.glob("test_*.py"))
    groups = batches(files, max(1, args.batch_size))
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    failed: list[int] = []
    start = time.monotonic()
    for index, group in enumerate(groups, start=1):
        names = ", ".join(f.name for f in group[:3]) + (" …" if len(group) > 3 else "")
        print(f"\n=== batch {index}/{len(groups)}: {names}", flush=True)
        cmd = [sys.executable, "-m", "pytest", "-q", *map(str, group), *args.pytest_args]
        code = subprocess.call(cmd, cwd=ROOT, env=env)
        # 5 means every test in the batch was deselected or skipped.
        if code not in (0, 5):
            failed.append(index)
            if args.stop_on_fail:
                break
    minutes = (time.monotonic() - start) / 60
    if failed:
        print(f"\nFailed batches: {failed} ({minutes:.1f} min)")
        return 1
    print(f"\nAll {len(groups)} batches passed ({minutes:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
