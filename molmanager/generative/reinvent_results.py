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

"""Open REINVENT rows in a new MolManager table before they join the current one."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from rdkit import Chem

Record = tuple[str, dict[str, str]]


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


def results_status(
    *,
    count: int,
    cancelled: bool,
    skipped: str,
    open_error: str = "",
) -> str:
    """Status line after a run. The current table is left unchanged."""
    if open_error:
        return (
            f"Could not open a new table ({open_error}).{skipped} "
            "Add to this table keeps the molecules here."
        )
    if count <= 0:
        lead = "Stopped." if cancelled else "REINVENT finished without any valid molecules."
        return f"{lead}{skipped}"
    lead = "Stopped. " if cancelled else ""
    noun = "molecule" if count == 1 else "molecules"
    return f"{lead}Opened {count} {noun} in a new table.{skipped}"


def write_results_sdf(path: Path, records: Sequence[Record]) -> int:
    """Write depictable rows and their score columns. Unreadable SMILES are skipped."""
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(path))
    written = 0
    try:
        for index, (smiles, fields) in enumerate(records, start=1):
            text = (smiles or "").strip()
            if not text:
                continue
            mol = Chem.MolFromSmiles(text)
            if mol is None:
                continue
            mol.SetProp("_Name", f"REINVENT {index}")
            mol.SetProp("SMILES", text)
            for key, value in fields.items():
                name = " ".join(str(key).split())[:80]
                if not name or name.startswith("_"):
                    continue
                mol.SetProp(name, str(value))
            writer.write(mol)
            written += 1
    finally:
        writer.close()
    return written


def open_results_table(records: Sequence[Record], *, stem: str) -> Path:
    """Write an SDF and launch a new MolManager window on it. Return the SDF path."""
    directory = Path(tempfile.mkdtemp(prefix="molmanager-reinvent-results-"))
    path = directory / f"{stem}.sdf"
    written = write_results_sdf(path, records)
    if written < 1:
        raise OSError("None of the result SMILES could be written.")
    subprocess.Popen(
        [sys.executable, "-m", "molmanager", "--open", str(path)],
        close_fds=True,
    )
    return path
