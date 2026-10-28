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

"""Main window package: ``ChemistryWorkspaceWindow`` is a QMainWindow facade over kernel collaborators.

The class is imported on first use. Loading it from this package's init pulls the
progress owner while that owner is still importing a mixin from this package.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ChemistryWorkspaceWindow"]


def __getattr__(name: str) -> Any:
    if name == "ChemistryWorkspaceWindow":
        from .chemistry_workspace_window import ChemistryWorkspaceWindow

        globals()[name] = ChemistryWorkspaceWindow
        return ChemistryWorkspaceWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
