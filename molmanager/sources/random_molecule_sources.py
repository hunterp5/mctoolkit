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

"""Random molecules from ChEMBL, PubChem, or ZINC (Tools → Random → Molecule)."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from rdkit import Chem
from rdkit.Chem import Lipinski, rdMolDescriptors

from .chembl_random_compounds import RandomChemblMolecule, fetch_random_chembl_molecules

SOURCE_CHEMBL = "chembl"
SOURCE_PUBCHEM = "pubchem"
SOURCE_ZINC = "zinc"

SOURCE_CHOICES: tuple[tuple[str, str], ...] = (
    (SOURCE_CHEMBL, "ChEMBL"),
    (SOURCE_PUBCHEM, "PubChem"),
    (SOURCE_ZINC, "ZINC"),
)

_SOURCE_ALIASES = {
    "chembl": SOURCE_CHEMBL,
    "pubchem": SOURCE_PUBCHEM,
    "zinc": SOURCE_ZINC,
    "zinc15": SOURCE_ZINC,
    "zinc20": SOURCE_ZINC,
    "zinc22": SOURCE_ZINC,
}

_USER_AGENT = "MolManager/1.0 (random molecule sample; local desktop app)"
_EUTILS_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUG_CID_PROPERTY = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cids}/property/"
    "CanonicalSMILES,ConnectivitySMILES,MolecularFormula,MolecularWeight,IUPACName,Title/JSON"
)
_ZINC_CARTBLANCHE = "https://cartblanche22.docking.org"
_ZINC_RANDOM_SUBMIT = f"{_ZINC_CARTBLANCHE}/substance/random.json"
_ZINC_POLL_INTERVAL_S = 1.0
_ZINC_POLL_TIMEOUT_S = 90.0
_MAX_COUNT = 500


@dataclass(frozen=True)
class RandomSourceMolecule:
    """One compound pulled from a public catalog for table import."""

    source: str
    molecule_id: str
    smiles: str
    fields: dict[str, str]


@dataclass(frozen=True)
class IntBounds:
    """Inclusive integer range; ``None`` means no bound on that side."""

    minimum: int | None = None
    maximum: int | None = None

    def contains(self, value: int) -> bool:
        if self.minimum is not None and int(value) < self.minimum:
            return False
        if self.maximum is not None and int(value) > self.maximum:
            return False
        return True

    def is_unconstrained(self) -> bool:
        return self.minimum is None and self.maximum is None

    def summary(self) -> str:
        lo = "any" if self.minimum is None else str(self.minimum)
        hi = "any" if self.maximum is None else str(self.maximum)
        return f"{lo}–{hi}"


# Keys match RandomMoleculeFilters fields and smiles_property_counts().
FILTER_PROPERTY_SPECS: tuple[tuple[str, str, str, int], ...] = (
    ("heavy_atoms", "Heavy atoms", "HeavyAtomCount", 200),
    ("nitrogen", "Nitrogen", "NitrogenCount", 50),
    ("oxygen", "Oxygen", "OxygenCount", 50),
    ("rotatable_bonds", "Rotatable bonds", "NumRotatableBonds", 50),
    ("rings", "Rings", "RingCount", 30),
    ("hbd", "H-bond donors", "NumHDonors", 20),
    ("hba", "H-bond acceptors", "NumHAcceptors", 30),
)


@dataclass(frozen=True)
class RandomMoleculeFilters:
    """Optional RDKit property windows applied while sampling."""

    heavy_atoms: IntBounds = field(default_factory=IntBounds)
    nitrogen: IntBounds = field(default_factory=IntBounds)
    oxygen: IntBounds = field(default_factory=IntBounds)
    rotatable_bonds: IntBounds = field(default_factory=IntBounds)
    rings: IntBounds = field(default_factory=IntBounds)
    hbd: IntBounds = field(default_factory=IntBounds)
    hba: IntBounds = field(default_factory=IntBounds)

    def is_unconstrained(self) -> bool:
        return all(getattr(self, key).is_unconstrained() for key, *_ in FILTER_PROPERTY_SPECS)

    def summary(self) -> str:
        if self.is_unconstrained():
            return "(none)"
        parts: list[str] = []
        for key, label, _col, _mx in FILTER_PROPERTY_SPECS:
            bounds: IntBounds = getattr(self, key)
            if not bounds.is_unconstrained():
                parts.append(f"{label} {bounds.summary()}")
        return "; ".join(parts) if parts else "(none)"


def smiles_property_counts(smiles: str) -> dict[str, int] | None:
    """Heavy-atom / heteroatom / topology counts for *smiles*, or ``None`` if unparseable."""
    mol = Chem.MolFromSmiles((smiles or "").strip())
    if mol is None or mol.GetNumAtoms() <= 0:
        return None
    return {
        "heavy_atoms": int(mol.GetNumHeavyAtoms()),
        "nitrogen": sum(1 for atom in mol.GetAtoms() if atom.GetAtomicNum() == 7),
        "oxygen": sum(1 for atom in mol.GetAtoms() if atom.GetAtomicNum() == 8),
        "rotatable_bonds": int(Lipinski.NumRotatableBonds(mol)),
        "rings": int(rdMolDescriptors.CalcNumRings(mol)),
        "hbd": int(Lipinski.NumHDonors(mol)),
        "hba": int(Lipinski.NumHAcceptors(mol)),
    }


def counts_pass_filters(counts: dict[str, int], filters: RandomMoleculeFilters | None) -> bool:
    if filters is None or filters.is_unconstrained():
        return True
    for key, *_rest in FILTER_PROPERTY_SPECS:
        bounds: IntBounds = getattr(filters, key)
        if not bounds.contains(int(counts.get(key, 0))):
            return False
    return True


def _count_fields(counts: dict[str, int]) -> dict[str, str]:
    return {col: str(counts[key]) for key, _label, col, _mx in FILTER_PROPERTY_SPECS}


def apply_molecule_filters(
    hit: RandomSourceMolecule,
    filters: RandomMoleculeFilters | None,
) -> RandomSourceMolecule | None:
    """Return *hit* (with count columns) if it matches *filters*, else ``None``."""
    if filters is None or filters.is_unconstrained():
        return hit
    counts = smiles_property_counts(hit.smiles)
    if counts is None or not counts_pass_filters(counts, filters):
        return None
    fields = dict(hit.fields)
    fields.update(_count_fields(counts))
    return replace(hit, fields=fields)


def _sample_page_budget(
    n: int,
    page: int,
    max_pages: int | None,
    *,
    filtered: bool,
) -> int:
    if max_pages is not None:
        return int(max_pages)
    base = max(8, (n + page - 1) // page * 4 + 4)
    if filtered:
        return min(80, max(base * 6, 32))
    return base


def source_label(source: str) -> str:
    """User-facing name for a source key (ChEMBL, PubChem, ZINC)."""
    key = normalize_source(source)
    for src, label in SOURCE_CHOICES:
        if src == key:
            return label
    return key


def normalize_source(source: str) -> str:
    """Map combo text / aliases onto ``chembl``, ``pubchem``, or ``zinc``."""
    key = (source or "").strip().lower()
    if key in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[key]
    raise ValueError(f"Unknown molecule source: {source or '(empty)'}")


def _validate_count(count: int) -> int:
    n = int(count)
    if n <= 0:
        raise ValueError("Count must be a positive integer.")
    if n > _MAX_COUNT:
        raise ValueError(f"Count must be at most {_MAX_COUNT} per request.")
    return n


def _looks_like_html_or_captcha(raw: str, content_type: str | None) -> bool:
    ctype = (content_type or "").lower()
    if "html" in ctype:
        return True
    head = (raw or "").lstrip()[:400].lower()
    return (
        head.startswith("<!doctype")
        or head.startswith("<html")
        or "verification required" in head
        or "/captcha" in head
    )


def _http_get_text(url: str, *, timeout: float, error_prefix: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json, text/plain, */*", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            ctype = resp.headers.get("Content-Type")
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"{error_prefix} HTTP {e.code}: {body or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"{error_prefix} network error: {e}") from e
    if _looks_like_html_or_captcha(raw, ctype) or "/captcha" in (final_url or "").lower():
        raise RuntimeError(
            f"{error_prefix} blocked the request (CAPTCHA or HTML instead of data). "
            "Try again later, or sample from ChEMBL or PubChem."
        )
    return raw


def _http_get_json(url: str, *, timeout: float, error_prefix: str) -> Any:
    raw = _http_get_text(url, timeout=timeout, error_prefix=error_prefix)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{error_prefix} returned non-JSON.") from e


def _as_record_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "substances", "results", "data"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def _chembl_to_source(hit: RandomChemblMolecule) -> RandomSourceMolecule:
    fields = dict(hit.fields)
    fields["Source"] = "ChEMBL"
    return RandomSourceMolecule(
        source=SOURCE_CHEMBL,
        molecule_id=hit.chembl_id,
        smiles=hit.smiles,
        fields=fields,
    )


def pubchem_compound_total_count(*, timeout: float = 60.0) -> int:
    """Return Entrez ``esearchresult.count`` for PubChem compounds."""
    qs = urllib.parse.urlencode(
        {
            "db": "pccompound",
            "term": "all[filt]",
            "rettype": "count",
            "retmode": "json",
            "retmax": 0,
        }
    )
    data = _http_get_json(f"{_EUTILS_ESEARCH}?{qs}", timeout=timeout, error_prefix="PubChem")
    result = data.get("esearchresult") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("PubChem did not report a compound count.")
    total = int(result.get("count") or 0)
    if total <= 0:
        raise RuntimeError("PubChem did not report a compound count.")
    return total


def _fetch_pubchem_idlist(retstart: int, retmax: int, *, timeout: float = 60.0) -> list[int]:
    qs = urllib.parse.urlencode(
        {
            "db": "pccompound",
            "term": "all[filt]",
            "retstart": int(retstart),
            "retmax": int(retmax),
            "retmode": "json",
        }
    )
    data = _http_get_json(f"{_EUTILS_ESEARCH}?{qs}", timeout=timeout, error_prefix="PubChem")
    result = data.get("esearchresult") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        return []
    ids = result.get("idlist") or []
    out: list[int] = []
    for item in ids:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _fetch_pubchem_properties(cids: list[int], *, timeout: float = 60.0) -> list[dict[str, Any]]:
    if not cids:
        return []
    joined = ",".join(str(int(cid)) for cid in cids)
    url = _PUG_CID_PROPERTY.format(cids=joined)
    data = _http_get_json(url, timeout=timeout, error_prefix="PubChem")
    table = data.get("PropertyTable") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return []
    props = table.get("Properties") or []
    return [p for p in props if isinstance(p, dict)]


def _pubchem_record_to_hit(rec: dict[str, Any]) -> RandomSourceMolecule | None:
    try:
        cid = int(rec.get("CID"))
    except (TypeError, ValueError):
        return None
    smiles = str(rec.get("CanonicalSMILES") or rec.get("ConnectivitySMILES") or "").strip()
    if cid <= 0 or not smiles:
        return None
    fields: dict[str, str] = {"CID": str(cid), "Source": "PubChem"}
    title = rec.get("Title")
    if title not in (None, ""):
        fields["Title"] = str(title)
    formula = rec.get("MolecularFormula")
    if formula not in (None, ""):
        fields["MolecularFormula"] = str(formula)
    mw = rec.get("MolecularWeight")
    if mw not in (None, ""):
        fields["MolecularWeight"] = str(mw)
    iupac = rec.get("IUPACName")
    if iupac not in (None, ""):
        fields["IUPAC"] = str(iupac)
    return RandomSourceMolecule(
        source=SOURCE_PUBCHEM,
        molecule_id=str(cid),
        smiles=smiles,
        fields=fields,
    )


def fetch_random_pubchem_molecules(
    count: int,
    *,
    seed: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    total_count: int | None = None,
    page_size: int = 25,
    max_pages: int | None = None,
    filters: RandomMoleculeFilters | None = None,
) -> list[RandomSourceMolecule]:
    """Sample *count* random PubChem compounds (canonical SMILES + CID)."""
    n = _validate_count(count)
    page = max(1, min(int(page_size), 50))
    rng = random.Random(seed)
    total = int(total_count) if total_count is not None else pubchem_compound_total_count()
    if total <= 0:
        raise RuntimeError("PubChem compound catalog appears empty.")
    filtered = bool(filters) and not filters.is_unconstrained()

    out: list[RandomSourceMolecule] = []
    seen: set[str] = set()
    pages_done = 0
    page_budget = _sample_page_budget(n, page, max_pages, filtered=filtered)

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    while len(out) < n and pages_done < page_budget:
        if _cancelled():
            raise RuntimeError("Cancelled.")
        max_start = max(0, total - page)
        retstart = rng.randint(0, max_start)
        try:
            cids = _fetch_pubchem_idlist(retstart, page)
            records = _fetch_pubchem_properties(cids)
        except RuntimeError:
            pages_done += 1
            continue
        pages_done += 1
        order = list(range(len(records)))
        rng.shuffle(order)
        for i in order:
            hit = _pubchem_record_to_hit(records[i])
            if hit is None or hit.molecule_id in seen:
                continue
            seen.add(hit.molecule_id)
            kept = apply_molecule_filters(hit, filters)
            if kept is None:
                continue
            out.append(kept)
            if progress:
                progress(len(out), n)
            if len(out) >= n:
                break

    if len(out) < n:
        extra = " that match the property filters" if filtered else ""
        raise RuntimeError(
            f"Only retrieved {len(out)} of {n} random PubChem molecule(s){extra}. "
            "Try again, loosen the filters, or request fewer compounds."
        )
    return out[:n]


def _zinc_field(rec: dict[str, Any], *keys: str) -> str:
    lower = {str(k).lower(): v for k, v in rec.items()}
    for key in keys:
        val = rec.get(key)
        if val not in (None, ""):
            return str(val).strip()
        val = lower.get(key.lower())
        if val not in (None, ""):
            return str(val).strip()
    return ""


def _zinc_record_to_hit(rec: dict[str, Any]) -> RandomSourceMolecule | None:
    zid = _zinc_field(rec, "zinc_id", "zincid", "id")
    smiles = _zinc_field(rec, "smiles", "smiles_clean", "smiles_stereo")
    if not zid or not smiles:
        return None
    fields: dict[str, str] = {"ZINC_ID": zid, "Source": "ZINC"}
    for raw_key, col in (
        ("mwt", "MW"),
        ("mw", "MW"),
        ("logp", "LogP"),
        ("formula", "Formula"),
        ("tranche", "Tranche"),
    ):
        val = _zinc_field(rec, raw_key)
        if val and col not in fields:
            fields[col] = val
    return RandomSourceMolecule(
        source=SOURCE_ZINC,
        molecule_id=zid,
        smiles=smiles,
        fields=fields,
    )


def _coerce_zinc_records(payload: Any) -> list[dict[str, Any]]:
    """Turn CartBlanche JSON (list, wrapped dict, or JSON-encoded string) into records."""
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
    recs = _as_record_list(payload)
    if recs:
        return recs
    if isinstance(payload, dict):
        nested = payload.get("result")
        if nested is not None and nested is not payload:
            return _coerce_zinc_records(nested)
    return []


def _zinc_task_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    task = str(data.get("task") or "").strip()
    return task


def _zinc_poll_url(task: str) -> str:
    return f"{_ZINC_CARTBLANCHE}/substance/random/{urllib.parse.quote(task, safe='')}.json"


def _fetch_zinc_page(
    count: int,
    *,
    timeout: float = 60.0,
    poll_timeout: float = _ZINC_POLL_TIMEOUT_S,
    cancel_check: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Submit a ZINC22 CartBlanche random job and poll until SMILES records arrive."""
    n = max(1, int(count))
    qs = urllib.parse.urlencode({"count": n})
    submit_url = f"{_ZINC_RANDOM_SUBMIT}?{qs}"
    data = _http_get_json(submit_url, timeout=timeout, error_prefix="ZINC")
    recs = _coerce_zinc_records(data)
    if recs:
        return recs
    task = _zinc_task_id(data)
    if not task:
        raise RuntimeError("ZINC did not return a random-sample task or molecule records.")

    poll_url = _zinc_poll_url(task)
    deadline = time.monotonic() + max(5.0, float(poll_timeout))
    last_status = ""
    while True:
        if cancel_check and cancel_check():
            raise RuntimeError("Cancelled.")
        data = _http_get_json(poll_url, timeout=timeout, error_prefix="ZINC")
        recs = _coerce_zinc_records(data)
        if recs:
            return recs
        status = ""
        if isinstance(data, dict):
            status = str(data.get("status") or "").strip().upper()
            last_status = status or last_status
            if status in {"FAILURE", "ERROR", "REVOKED"}:
                msg = str(data.get("message") or data.get("error") or status)
                raise RuntimeError(f"ZINC random sample failed: {msg}")
            if status == "SUCCESS":
                return []
        if time.monotonic() >= deadline:
            detail = f" (last status {last_status})" if last_status else ""
            raise RuntimeError(f"ZINC random sample timed out{detail}.")
        sleep(_ZINC_POLL_INTERVAL_S)


def fetch_random_zinc_molecules(
    count: int,
    *,
    seed: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    page_size: int = 25,
    max_pages: int | None = None,
    filters: RandomMoleculeFilters | None = None,
) -> list[RandomSourceMolecule]:
    """Sample *count* random ZINC substances (SMILES + ZINC_ID)."""
    n = _validate_count(count)
    page = max(1, min(int(page_size), 100))
    rng = random.Random(seed)
    filtered = bool(filters) and not filters.is_unconstrained()
    out: list[RandomSourceMolecule] = []
    seen: set[str] = set()
    pages_done = 0
    last_err: Exception | None = None
    page_budget = _sample_page_budget(n, page, max_pages, filtered=filtered)

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    while len(out) < n and pages_done < page_budget:
        if _cancelled():
            raise RuntimeError("Cancelled.")
        try:
            records = _fetch_zinc_page(
                min(page, n - len(out)),
                cancel_check=cancel_check,
            )
        except RuntimeError as e:
            last_err = e
            pages_done += 1
            continue
        pages_done += 1
        order = list(range(len(records)))
        rng.shuffle(order)
        for i in order:
            hit = _zinc_record_to_hit(records[i])
            if hit is None or hit.molecule_id in seen:
                continue
            seen.add(hit.molecule_id)
            kept = apply_molecule_filters(hit, filters)
            if kept is None:
                continue
            out.append(kept)
            if progress:
                progress(len(out), n)
            if len(out) >= n:
                break

    if len(out) < n:
        if not out and last_err is not None:
            raise last_err
        extra = " that match the property filters" if filtered else ""
        raise RuntimeError(
            f"Only retrieved {len(out)} of {n} random ZINC molecule(s){extra}. "
            "Try again, loosen the filters, or request fewer compounds."
        )
    return out[:n]


def fetch_random_molecules(
    source: str,
    count: int,
    *,
    seed: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    filters: RandomMoleculeFilters | None = None,
) -> list[RandomSourceMolecule]:
    """Fetch random compounds from ChEMBL, PubChem, or ZINC."""
    key = normalize_source(source)
    if key == SOURCE_CHEMBL:
        filtered = bool(filters) and not filters.is_unconstrained()

        def _keep(hit: RandomChemblMolecule) -> bool:
            return apply_molecule_filters(_chembl_to_source(hit), filters) is not None

        hits = fetch_random_chembl_molecules(
            count,
            seed=seed,
            cancel_check=cancel_check,
            progress=progress,
            keep=_keep if filtered else None,
            filtered=filtered,
        )
        out: list[RandomSourceMolecule] = []
        for hit in hits:
            kept = apply_molecule_filters(_chembl_to_source(hit), filters)
            if kept is not None:
                out.append(kept)
        return out
    if key == SOURCE_PUBCHEM:
        return fetch_random_pubchem_molecules(
            count,
            seed=seed,
            cancel_check=cancel_check,
            progress=progress,
            filters=filters,
        )
    return fetch_random_zinc_molecules(
        count,
        seed=seed,
        cancel_check=cancel_check,
        progress=progress,
        filters=filters,
    )
