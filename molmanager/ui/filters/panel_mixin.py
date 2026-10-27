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

"""File-split of the filter panel on ``ChemistryWorkspaceWindow`` (not a reusable mixin)."""

from __future__ import annotations

from .filter_apply_mixin import FilterApplyMixin
from .filter_bounds_mixin import FilterBoundsMixin


class FilterPanelMixin(
    FilterApplyMixin,
    FilterBoundsMixin,
):
    """Expects the :class:`~molmanager.ui.app_kernel.AppKernel` surface on ``self``
    (``headers``, ``_table_model``, ``table``, ``mols``, ``filters``, ``f_panel``,
    ``f_container``, ``global_bounds``, ``status_label``, ``threadpool``,
    ``_apply_filters_timer``, optional ``_substructure_filter_signals``), provided by
    ``ChemistryWorkspaceWindow``.
    """
