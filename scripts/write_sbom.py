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

"""Write a CycloneDX SBOM for the environment that is about to ship."""

from __future__ import annotations

import importlib.metadata as metadata
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _license_name(dist: metadata.Distribution) -> str:
    declared = (dist.metadata.get("License") or "").strip()
    if declared and declared.upper() != "UNKNOWN":
        return declared.splitlines()[0].strip()
    for line in dist.metadata.get_all("Classifier") or []:
        if line.startswith("License ::"):
            return line.split("::")[-1].strip()
    return ""


def build_sbom() -> dict:
    """CycloneDX 1.5 document for the current Python environment."""
    from molmanager import __version__

    components: list[dict] = []
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").strip()
        if not name:
            continue
        version = dist.version or "0"
        component: dict = {
            "type": "library",
            "name": name,
            "version": version,
            "bom-ref": f"{name}@{version}",
            "purl": f"pkg:pypi/{name.lower()}@{version}",
        }
        license_name = _license_name(dist)
        if license_name:
            component["licenses"] = [{"license": {"name": license_name}}]
        components.append(component)
    components.sort(key=lambda item: item["name"].lower())
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "MolManager",
                "version": __version__,
            }
        },
        "components": components,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dest = Path(args[0]) if args else Path("sbom.cdx.json")
    dest.write_text(json.dumps(build_sbom(), indent=2) + "\n", encoding="utf-8")
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
