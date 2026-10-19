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

"""External data source dialogs (SQL, PubChem, ChEMBL, vendors, patent chemistry)."""

from .chembl import ChEMBLDialog
from .external_db import ExternalDBDialog
from .patent_query import PatentQueryDialog
from .pubchem import PubChemDialog
from .vendors import VendorQueryDialog

__all__ = [
    "ChEMBLDialog",
    "ExternalDBDialog",
    "PatentQueryDialog",
    "PubChemDialog",
    "VendorQueryDialog",
]
