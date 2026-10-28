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
"""Pure column-header policy for chemistry tools (no Qt)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence

from ..chem.reaction_file_io import looks_like_reaction_smarts, parse_reaction_smarts
from ..chem.structure_source_headers import (
    header_looks_like_structure_text,
    is_tool_generated_structure_header,
)
from ..chem.molecule_conversion import (
    looks_like_mol_block,
    looks_like_structure_cell_text,
    parse_molecule_from_cell_text,
)

_PLACEHOLDER_CELLS = frozenset({"", "n/a", "cancelled", "cancelled."})


def skip_chemistry_tool_column_dropdown(header: str) -> bool:
    """Exclude non-molecular columns from chemistry-tool source dropdowns."""
    if header in ("ID_HIDDEN", "Structure"):
        return True
    nl = (header or "").lower()
    if nl == "pka":
        return True
    if nl == "pi":
        return True
    # Columns written by the removed site-of-metabolism predictor.
    if nl.startswith("som "):
        return True
    if nl == "cluster" or nl.startswith("cluster ("):
        return True
    if "inchikey" in nl and "smiles" not in nl and "inchi" not in nl and "mol" not in nl:
        return True
    return False


def is_legacy_som_map_header(header: str) -> bool:
    """Map column left by the removed site-of-metabolism predictor.

    Old sessions stored a highlighted image here. The cell text is the parent
    SMILES, so these names stay ordinary text columns.
    """
    name = (header or "").strip().lower()
    return name == "som map" or name.startswith("som map ")


def should_skip_chemical_scan_column(
    header: str,
    *,
    is_pixmap_column: Callable[[str], bool] | None = None,
) -> bool:
    """True for columns that should not be probed for parseable molecules."""
    if header in ("ID_HIDDEN", "Structure"):
        return True
    if is_pixmap_column is not None and is_pixmap_column(header):
        return True
    nl = (header or "").lower()
    if "inchikey" in nl:
        return True
    return False


def is_smiles_named_header(header: str) -> bool:
    lo = (header or "").strip().lower()
    return lo == "smiles" or (("smiles" in lo) and ("inchikey" not in lo))


def canonical_smiles_header_for_updates(headers: Sequence[str]) -> str | None:
    """Column to store canonical SMILES after chemistry tools (prefer ``SMILES``)."""
    if "SMILES" in headers:
        return "SMILES"
    for h in headers[2:]:
        if is_smiles_named_header(h):
            return h
    return None


def ordered_headers_for_molecule_lookup(
    headers: Sequence[str],
    *,
    structure_field_override: str | None = None,
    is_pixmap_column: Callable[[str], bool] | None = None,
) -> list[str]:
    """Column names to probe for parseable chemistry (likely names first)."""
    seen: set[str] = set()
    out: list[str] = []
    ov = (structure_field_override or "").strip()

    def add(name: str | None) -> None:
        if not name or name not in headers:
            return
        if name != ov and should_skip_chemical_scan_column(name, is_pixmap_column=is_pixmap_column):
            return
        if name not in seen:
            seen.add(name)
            out.append(name)

    if ov:
        add(ov)
    for h in headers[2:]:
        if should_skip_chemical_scan_column(h, is_pixmap_column=is_pixmap_column):
            continue
        if is_smiles_named_header(h):
            add(h)
    for h in headers[2:]:
        if is_tool_generated_structure_header(h):
            continue
        if header_looks_like_structure_text(h):
            add(h)
    for h in headers[2:]:
        if is_tool_generated_structure_header(h):
            continue
        if not should_skip_chemical_scan_column(h, is_pixmap_column=is_pixmap_column):
            add(h)
    return out


def _placeholder_cell(text: str) -> bool:
    """Blank, ``N/A``, cancel, and error cells are not structures and not evidence against one."""
    lowered = (text or "").strip().lower()
    return lowered in _PLACEHOLDER_CELLS or lowered.startswith("error")


def text_is_depictable_structure(text: str) -> bool:
    """True when *text* is one molecule or one reaction the table can draw.

    A semicolon-separated list (metabolites, several transforms) is not one picture.
    """
    raw = (text or "").strip()
    if not raw or _placeholder_cell(raw) or "; " in raw:
        return False
    if len(raw) > 20000 and not looks_like_mol_block(raw):
        return False
    if parse_molecule_from_cell_text(raw) is not None:
        return True
    if looks_like_reaction_smarts(raw):
        return parse_reaction_smarts(raw) is not None
    return False


def headers_with_depictable_structures(
    headers: Sequence[str],
    rows: Iterable[tuple[object, Mapping[str, str] | None]],
    *,
    max_samples: int = 8,
) -> list[str]:
    """Return *headers* whose real cells are molecules or reactions.

    Sampling stops after *max_samples* non-placeholder cells per header. One cell
    that is not a structure rejects that header, so counts and other text stay text.
    """
    pending = [header for header in headers if header]
    if not pending:
        return []
    hits = dict.fromkeys(pending, 0)
    checked = dict.fromkeys(pending, 0)
    failed: set[str] = set()
    open_headers = set(pending)
    for _oid, row in rows:
        if not open_headers:
            break
        values = row or {}
        for header in list(open_headers):
            text = str(values.get(header, "") or "")
            if _placeholder_cell(text):
                continue
            checked[header] += 1
            if text_is_depictable_structure(text):
                hits[header] += 1
            else:
                failed.add(header)
                open_headers.discard(header)
                continue
            if checked[header] >= max_samples:
                open_headers.discard(header)
    return [header for header in pending if hits[header] > 0 and header not in failed]


def cell_texts_have_parseable_molecule(
    cell_texts: Iterable[str],
    *,
    max_nonempty_samples: int = 80,
) -> bool:
    """True if any sampled non-empty cell parses as a molecule."""
    tries = 0
    for raw in cell_texts:
        text = (raw or "").strip()
        if not text:
            continue
        tries += 1
        if tries > max_nonempty_samples:
            break
        if len(text) > 20000 and not looks_like_mol_block(text):
            continue
        if not looks_like_structure_cell_text(text):
            continue
        if parse_molecule_from_cell_text(text) is not None:
            return True
    return False


def data_headers_confirmed_for_chemistry_tools(
    headers: Sequence[str],
    *,
    structure_field_override: str | None = None,
    column_has_parseable_sample: Callable[[str], bool] | None = None,
) -> list[str]:
    """
    Data columns suitable as chemistry-tool sources: structural-looking names,
    optional override, or at least one parseable cell (via callback).
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if not name or name in seen:
            return
        if name not in headers or skip_chemistry_tool_column_dropdown(name):
            return
        seen.add(name)
        out.append(name)

    ov = (structure_field_override or "").strip()
    if ov:
        add(ov)
    for h in headers[2:]:
        if skip_chemistry_tool_column_dropdown(h):
            continue
        if header_looks_like_structure_text(h):
            add(h)
            continue
        if column_has_parseable_sample is not None and column_has_parseable_sample(h):
            add(h)
    return out
