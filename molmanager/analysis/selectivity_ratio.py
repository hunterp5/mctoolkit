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

"""Log selectivity of a primary assay against one or more off-target columns.

Both columns are treated as a p-scale (higher is more potent), matching SALI:
log selectivity is primary minus off-target. A value of 1 is 10-fold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

NARROW_WINDOW_HEADER = "Narrow window"
NARROW_WINDOW_YES = "yes"
NARROW_WINDOW_NO = "no"

# Headers that are assay readouts rather than physicochemical descriptors.
_ASSAY_KEYS = ("pic50", "pec50", "pki", "pkd", "ic50", "ec50", "activity", "potency")
_ASSAY_TOKENS = frozenset({"ki", "kd", "pic50", "ic50", "ec50", "pec50"})


@dataclass(frozen=True)
class SelectivityRatioParams:
    """Primary assay, off-target assays, and the narrow-window cutoffs."""

    primary_column: str
    secondary_columns: tuple[str, ...]
    potency_cutoff: float
    window: float


def looks_like_assay_column(name: str) -> bool:
    """True when *name* looks like pIC50, Ki, or another activity readout."""
    text = str(name or "")
    flat = text.casefold().replace(" ", "").replace("_", "").replace("-", "")
    if any(key in flat for key in _ASSAY_KEYS):
        return True
    tokens = [part for part in text.casefold().replace("-", " ").replace("_", " ").split() if part]
    return any(token in _ASSAY_TOKENS for token in tokens)


def selectivity_column_name(secondary: str) -> str:
    """Header for the log selectivity of *secondary* against the primary assay."""
    return f"logSel vs {secondary}"


def selectivity_headers(secondary_columns: Sequence[str]) -> tuple[str, ...]:
    """One log-selectivity column per off-target, then the narrow-window flag."""
    names = tuple(selectivity_column_name(name) for name in secondary_columns)
    return names + (NARROW_WINDOW_HEADER,)


def log_selectivity(primary: float, secondary: float) -> float:
    """Primary pActivity minus off-target pActivity."""
    return float(primary) - float(secondary)


def selectivity_cells(
    primary: float | None,
    off_targets: Sequence[tuple[str, float | None]],
    *,
    potency_cutoff: float,
    window: float,
) -> dict[str, str]:
    """Cell text for one row.

    A missing primary or off-target leaves that selectivity blank. The flag is
    ``yes`` when the primary is at least ``potency_cutoff`` and the smallest
    measured log selectivity is below ``window``. It is ``no`` when the row can
    be judged and is not in that narrow window. It stays blank when nothing
    can be compared.
    """
    measured: list[float] = []
    out: dict[str, str] = {}
    for name, value in off_targets:
        header = selectivity_column_name(name)
        if primary is None or value is None:
            out[header] = ""
            continue
        delta = log_selectivity(primary, value)
        measured.append(delta)
        out[header] = f"{delta:.2f}"
    if primary is None or not measured:
        out[NARROW_WINDOW_HEADER] = ""
    elif float(primary) >= float(potency_cutoff) and min(measured) < float(window):
        out[NARROW_WINDOW_HEADER] = NARROW_WINDOW_YES
    else:
        out[NARROW_WINDOW_HEADER] = NARROW_WINDOW_NO
    return out
