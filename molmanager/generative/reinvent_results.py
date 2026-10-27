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

"""Status text after a REINVENT run. The molecules open in the results browser."""


def skipped_suffix(*, invalid: int, scaffold: int) -> str:
    """Trailing sentence for rows the CSV parse dropped."""
    parts: list[str] = []
    if invalid:
        parts.append(f"Skipped {invalid} invalid SMILES.")
    if scaffold:
        parts.append(f"Skipped {scaffold} that missed the scaffold.")
    if not parts:
        return ""
    return " " + " ".join(parts)


def results_status(*, count: int, cancelled: bool, skipped: str) -> str:
    """Status line after a run. The compound table is left unchanged."""
    if count <= 0:
        lead = "Stopped." if cancelled else "REINVENT finished without any valid molecules."
        return f"{lead}{skipped}"
    lead = "Stopped. " if cancelled else ""
    noun = "molecule" if count == 1 else "molecules"
    return f"{lead}Opened {count} {noun} in the REINVENT browser.{skipped}"
