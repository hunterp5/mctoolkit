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

"""RDKit FilterCatalog structural alerts for the table.

Each selected catalog writes two columns: a match count (``0`` when nothing
hits) and the matched pattern names joined with ``"; "``. Catalogs are built
once per worker thread and reused across rows. ChEMBL sets are included when
the installed RDKit exposes them.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

_ALERT_PREFIX = "ALERT:"
_COUNT_KIND = "count"
_NAMES_KIND = "names"
_local = threading.local()


@dataclass(frozen=True)
class AlertCatalogSpec:
    """One FilterCatalog set on the Calculate Descriptors Structural Alerts tab."""

    key: str
    label: str
    summary: str

    @property
    def enum_name(self) -> str:
        """RDKit ``FilterCatalogs`` member name. The key is that name."""
        return self.key

    def column_pairs(self) -> tuple[tuple[str, str], tuple[str, str]]:
        """``(display header, internal key)`` for the count and the name list."""
        return (
            (f"{self.label} count", alert_internal_key(self.key, _COUNT_KIND)),
            (f"{self.label} alerts", alert_internal_key(self.key, _NAMES_KIND)),
        )


ALERT_CATALOG_SPECS: tuple[AlertCatalogSpec, ...] = (
    AlertCatalogSpec(
        "PAINS",
        "PAINS",
        "Pan-assay interference filters, families A, B, and C (Baell and Holloway, 2010).",
    ),
    AlertCatalogSpec(
        "BRENK",
        "Brenk",
        "Unwanted groups for screening libraries (Brenk et al., 2008).",
    ),
    AlertCatalogSpec(
        "NIH",
        "NIH",
        "NIH Molecular Libraries excluded-functionality filters shipped with RDKit.",
    ),
    AlertCatalogSpec(
        "ZINC",
        "ZINC",
        "Unwanted functional groups from the ZINC catalog shipped with RDKit.",
    ),
    AlertCatalogSpec(
        "CHEMBL_Glaxo",
        "ChEMBL Glaxo",
        "ChEMBL Glaxo hard filters shipped with RDKit.",
    ),
    AlertCatalogSpec(
        "CHEMBL_Dundee",
        "ChEMBL Dundee",
        "ChEMBL Dundee filters shipped with RDKit.",
    ),
    AlertCatalogSpec(
        "CHEMBL_BMS",
        "ChEMBL BMS",
        "ChEMBL BMS filters shipped with RDKit.",
    ),
    AlertCatalogSpec(
        "CHEMBL_SureChEMBL",
        "ChEMBL SureChEMBL",
        "ChEMBL SureChEMBL filters shipped with RDKit.",
    ),
    AlertCatalogSpec(
        "CHEMBL_MLSMR",
        "ChEMBL MLSMR",
        "ChEMBL MLSMR filters shipped with RDKit.",
    ),
    AlertCatalogSpec(
        "CHEMBL_Inpharmatica",
        "ChEMBL Inpharmatica",
        "ChEMBL Inpharmatica filters shipped with RDKit.",
    ),
    AlertCatalogSpec(
        "CHEMBL_LINT",
        "ChEMBL LINT",
        "ChEMBL LINT filters shipped with RDKit.",
    ),
)


def alert_internal_key(catalog_key: str, kind: str) -> str:
    """Worker key for one catalog column. ``kind`` is ``count`` or ``names``."""
    return f"{_ALERT_PREFIX}{catalog_key}:{kind}"


def parse_alert_internal_key(internal: str) -> tuple[str, str] | None:
    """Return ``(catalog key, kind)`` for an alert worker key."""
    if not isinstance(internal, str) or not internal.startswith(_ALERT_PREFIX):
        return None
    catalog, sep, kind = internal[len(_ALERT_PREFIX) :].partition(":")
    if not sep or not catalog or kind not in {_COUNT_KIND, _NAMES_KIND}:
        return None
    return catalog, kind


_available: tuple[AlertCatalogSpec, ...] | None = None


def available_alert_catalogs() -> tuple[AlertCatalogSpec, ...]:
    """Catalogs this RDKit build can actually run, in dialog order."""
    global _available
    if _available is None:
        present = _filter_catalog_enum_names()
        _available = tuple(spec for spec in ALERT_CATALOG_SPECS if spec.enum_name in present)
    return _available


def clear_thread_catalog_cache() -> None:
    """Drop FilterCatalog objects cached on this thread."""
    _local.catalogs = {}


def build_alert_catalog(enum_name: str):
    """Compile one RDKit FilterCatalog set."""
    from rdkit.Chem import FilterCatalog

    params = FilterCatalog.FilterCatalogParams()
    enum = getattr(FilterCatalog.FilterCatalogParams.FilterCatalogs, enum_name)
    if not params.AddCatalog(enum):
        raise ValueError(f"RDKit rejected FilterCatalog set {enum_name}")
    return FilterCatalog.FilterCatalog(params)


def match_structural_alerts(mol, catalog) -> tuple[int, str]:
    """Return ``(unique pattern count, '; '-joined descriptions)``."""
    names: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(catalog.GetMatches(mol), start=1):
        desc = str(entry.GetDescription() or "").strip()
        if not desc:
            desc = f"match {index}"
        if desc in seen:
            continue
        seen.add(desc)
        names.append(desc)
    return len(names), "; ".join(names)


def callable_for_alert_key(internal: str, row_ctx: dict | None = None):
    """``callable(mol)`` for one alert column. Hits for a catalog are computed once per row."""
    parsed = parse_alert_internal_key(internal)
    ctx = row_ctx if row_ctx is not None else {}

    def _value(mol, parsed_key=parsed, row=ctx):
        if parsed_key is None:
            return "N/A"
        catalog_key, kind = parsed_key
        if mol is None:
            return 0 if kind == _COUNT_KIND else ""
        hits = row.setdefault("_alert_hits", {})
        pair = hits.get(catalog_key)
        if pair is None:
            catalog = _catalog_for_thread(catalog_key)
            pair = match_structural_alerts(mol, catalog)
            hits[catalog_key] = pair
        count, names = pair
        return count if kind == _COUNT_KIND else names

    return _value


def _catalog_for_thread(enum_name: str):
    catalogs = getattr(_local, "catalogs", None)
    if catalogs is None:
        catalogs = {}
        _local.catalogs = catalogs
    catalog = catalogs.get(enum_name)
    if catalog is None:
        catalog = build_alert_catalog(enum_name)
        catalogs[enum_name] = catalog
    return catalog


def _filter_catalog_enum_names() -> frozenset[str]:
    from rdkit.Chem import FilterCatalog

    enum = FilterCatalog.FilterCatalogParams.FilterCatalogs
    return frozenset(name for name in dir(enum) if name[:1].isupper())
