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

"""Compat grouping for calculator, SQL, dock, viewers, and predictors (not a window base)."""

from __future__ import annotations

from .dock_tools_mixin import DockToolsMixin
from .external_records_mixin import ExternalRecordsMixin
from .predict_tools_mixin import PredictToolsMixin
from .sql_load_mixin import SqlLoadMixin
from .table_calc_mixin import TableCalcMixin
from .viewer_openers_mixin import ViewerOpenersMixin

__all__ = [
    "ToolsSqlPredictMixin",
]


class ToolsSqlPredictMixin(
    TableCalcMixin,
    ViewerOpenersMixin,
    ExternalRecordsMixin,
    DockToolsMixin,
    SqlLoadMixin,
    PredictToolsMixin,
):
    """Compat grouping only. Do not add new empty composites; prefer ``WorkspaceTools``."""
