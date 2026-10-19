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

"""Fetch random ChEMBL compounds for Tools → Random → Molecule."""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

_CHEMBL_MOLECULE_JSON = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"
_DEFAULT_MAX_CHEMBL_NUM = 6_200_000
_USER_AGENT = "MolManager/1.0 (random ChEMBL sample; local desktop app)"


@dataclass(frozen=True)
class RandomChemblMolecule:
    """One compound pulled from ChEMBL for table import."""

    chembl_id: str
    smiles: str
    fields: dict[str, str]


def _http_get_json(url: str, *, timeout: float = 60.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"ChEMBL HTTP {e.code}: {body or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"ChEMBL network error: {e}") from e


def small_molecule_total_count(*, timeout: float = 60.0) -> int:
    """Return ChEMBL ``page_meta.total_count`` for small molecules."""
    qs = urllib.parse.urlencode({"limit": 1, "molecule_type": "Small molecule"})
    data = _http_get_json(f"{_CHEMBL_MOLECULE_JSON}?{qs}", timeout=timeout)
    meta = data.get("page_meta") or {}
    total = int(meta.get("total_count") or 0)
    if total <= 0:
        raise RuntimeError("ChEMBL did not report a molecule total_count.")
    return total


def _record_to_hit(rec: dict[str, Any]) -> RandomChemblMolecule | None:
    if not isinstance(rec, dict):
        return None
    chembl_id = str(rec.get("molecule_chembl_id") or "").strip()
    structs = rec.get("molecule_structures") or {}
    smiles = ""
    if isinstance(structs, dict):
        smiles = str(structs.get("canonical_smiles") or "").strip()
    if not chembl_id or not smiles:
        return None
    fields: dict[str, str] = {"ChEMBL_ID": chembl_id}
    pref = rec.get("pref_name")
    if pref not in (None, ""):
        fields["PrefName"] = str(pref)
    max_phase = rec.get("max_phase")
    if max_phase not in (None, ""):
        fields["MaxPhase"] = str(max_phase)
    mol_type = rec.get("molecule_type")
    if mol_type not in (None, ""):
        fields["MoleculeType"] = str(mol_type)
    return RandomChemblMolecule(chembl_id=chembl_id, smiles=smiles, fields=fields)


def _fetch_page(offset: int, limit: int, *, timeout: float = 60.0) -> list[dict[str, Any]]:
    qs = urllib.parse.urlencode(
        {
            "limit": int(limit),
            "offset": int(offset),
            "molecule_type": "Small molecule",
        }
    )
    data = _http_get_json(f"{_CHEMBL_MOLECULE_JSON}?{qs}", timeout=timeout)
    mols = data.get("molecules")
    if not isinstance(mols, list):
        return []
    return [m for m in mols if isinstance(m, dict)]


def fetch_random_chembl_molecules(
    count: int,
    *,
    seed: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    total_count: int | None = None,
    page_size: int = 25,
    max_pages: int | None = None,
    keep: Callable[[RandomChemblMolecule], bool] | None = None,
    filtered: bool = False,
) -> list[RandomChemblMolecule]:
    """
    Sample *count* random small molecules from ChEMBL (with canonical SMILES).

    Uses random offsets into the small-molecule index so results are spread across
    the database rather than a single contiguous page.
    """
    n = int(count)
    if n <= 0:
        raise ValueError("Count must be a positive integer.")
    if n > 500:
        raise ValueError("Count must be at most 500 per request.")
    page = max(1, min(int(page_size), 50))
    rng = random.Random(seed)
    total = int(total_count) if total_count is not None else small_molecule_total_count()
    if total <= 0:
        raise RuntimeError("ChEMBL small-molecule catalog appears empty.")

    out: list[RandomChemblMolecule] = []
    seen: set[str] = set()
    pages_done = 0
    if max_pages is not None:
        page_budget = int(max_pages)
    else:
        page_budget = max(8, (n + page - 1) // page * 4 + 4)
        if filtered or keep is not None:
            page_budget = min(80, max(page_budget * 6, 32))

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    while len(out) < n and pages_done < page_budget:
        if _cancelled():
            raise RuntimeError("Cancelled.")
        max_start = max(0, total - page)
        offset = rng.randint(0, max_start)
        try:
            records = _fetch_page(offset, page)
        except RuntimeError:
            pages_done += 1
            continue
        pages_done += 1
        # Shuffle within the page so consecutive DB order is not preserved.
        order = list(range(len(records)))
        rng.shuffle(order)
        for i in order:
            hit = _record_to_hit(records[i])
            if hit is None or hit.chembl_id in seen:
                continue
            seen.add(hit.chembl_id)
            if keep is not None and not keep(hit):
                continue
            out.append(hit)
            if progress:
                progress(len(out), n)
            if len(out) >= n:
                break

    if len(out) < n:
        extra = " that match the property filters" if (filtered or keep is not None) else ""
        raise RuntimeError(
            f"Only retrieved {len(out)} of {n} random ChEMBL molecule(s){extra}. "
            "Try again, loosen the filters, or request fewer compounds."
        )
    return out[:n]


# Kept for tests / callers that want ID-based sampling without depending on offsets.
def chembl_id_from_number(num: int) -> str:
    return f"CHEMBL{int(num)}"


def default_max_chembl_number() -> int:
    return _DEFAULT_MAX_CHEMBL_NUM
