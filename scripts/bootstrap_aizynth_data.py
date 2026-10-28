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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Download AiZynthFinder public models, the ZINC stock, and config.yml."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from molmanager.predictions.aizynthfinder_data import download_public_data


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/bootstrap_aizynth_data.py FOLDER", file=sys.stderr)
        return 2
    config = download_public_data(Path(sys.argv[1]), progress=print)
    print(f"Ready: {config}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
