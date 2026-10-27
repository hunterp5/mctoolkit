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

"""File-split of the filter panel on ``ChemistryWorkspaceWindow`` (not a reusable mixin).

Filter cards, substructure matching, filter apply, and numeric bounds are
``WorkspaceTools`` hosts. This class remains so existing imports keep a name.
"""

from __future__ import annotations


class FilterPanelMixin:
    """Expects the :class:`~molmanager.ui.app_kernel.AppKernel` surface on ``self``.

    The methods now live on ``WorkspaceTools`` hosts. The window forwards them.
    """
