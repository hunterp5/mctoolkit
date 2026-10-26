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

"""User choices for the recipe tools, with no molecules and no Qt.

A dialog builds one of these from its widgets. Dispatch builds the same
object from a saved step after ``${step.key}`` references are resolved.
The table is read later, when the job starts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .macro_recipe import (
    FILTER_NUMERIC,
    FILTER_SUBSTRUCTURE,
    FILTER_TEXT,
    ROW_SCOPE_SELECTION,
    ROW_SCOPE_TABLE,
)


@dataclass(frozen=True)
class DescriptorCalculationRequest:
    """Descriptors to calculate, and which structure column they come from."""

    structure_source: str
    keys: tuple[str, ...]
    displays: tuple[str, ...] = ()
    row_scope: str = ROW_SCOPE_TABLE


@dataclass(frozen=True)
class CalculatorColumnRequest:
    """One numeric column defined by an expression."""

    column: str
    expression: str
    row_scope: str = ROW_SCOPE_TABLE


@dataclass(frozen=True)
class ProtonateRequest:
    """Dominant protomer at one pH, written into a named column."""

    structure_source: str
    ph: float
    output_column: str
    render_2d: bool = False
    row_scope: str = ROW_SCOPE_TABLE


@dataclass(frozen=True)
class NumericFilterClause:
    """Keep rows whose numeric value lies between two bounds."""

    column: str
    minimum: float
    maximum: float
    inverted: bool = False


@dataclass(frozen=True)
class TextFilterClause:
    """Keep rows whose text matches a needle."""

    column: str
    text: str
    partial_match: bool = True
    case_sensitive: bool = False
    inverted: bool = False


@dataclass(frozen=True)
class SubstructureFilterClause:
    """Keep rows whose structure matches SMARTS."""

    smarts: str
    structure_source: str
    inverted: bool = False


FilterClause = NumericFilterClause | TextFilterClause | SubstructureFilterClause


@dataclass(frozen=True)
class FilterApplyRequest:
    """The filter cards a macro step installs."""

    clauses: tuple[FilterClause, ...]
    replace: bool = True


def row_scope_from_only_selected(only_selected: bool) -> str:
    """Map a Selected Rows Only checkbox onto a recipe row scope."""
    return ROW_SCOPE_SELECTION if only_selected else ROW_SCOPE_TABLE


def filter_request_from_params(
    params: Mapping[str, Any],
    *,
    resolve: Callable[[str], str],
) -> FilterApplyRequest:
    """Build a filter request from a recipe step, resolving column references."""
    raw = params.get("clauses") or []
    if not isinstance(raw, list):
        raise ValueError("Filter clauses must be a list.")
    clauses = tuple(_clause_from_mapping(item, resolve) for item in raw)
    return FilterApplyRequest(clauses=clauses, replace=bool(params.get("replace", True)))


def clause_as_mapping(clause: FilterClause) -> dict[str, Any]:
    """The dict shape the filter cards already restore from."""
    if isinstance(clause, NumericFilterClause):
        return {
            "kind": FILTER_NUMERIC,
            "column": clause.column,
            "min": clause.minimum,
            "max": clause.maximum,
            "inverted": clause.inverted,
        }
    if isinstance(clause, TextFilterClause):
        return {
            "kind": FILTER_TEXT,
            "column": clause.column,
            "text": clause.text,
            "partial_match": clause.partial_match,
            "case_sensitive": clause.case_sensitive,
            "inverted": clause.inverted,
        }
    return {
        "kind": FILTER_SUBSTRUCTURE,
        "smarts": clause.smarts,
        "structure_source": clause.structure_source,
        "inverted": clause.inverted,
    }


def _clause_from_mapping(raw: Any, resolve: Callable[[str], str]) -> FilterClause:
    if not isinstance(raw, Mapping):
        raise ValueError("Each filter clause must be an object.")
    kind = str(raw.get("kind") or "")
    inverted = bool(raw.get("inverted", False))
    if kind == FILTER_NUMERIC:
        return NumericFilterClause(
            column=_resolved_text(raw.get("column"), resolve),
            minimum=float(raw["min"]),
            maximum=float(raw["max"]),
            inverted=inverted,
        )
    if kind == FILTER_TEXT:
        return TextFilterClause(
            column=_resolved_text(raw.get("column"), resolve),
            text=str(raw.get("text") or ""),
            partial_match=bool(raw.get("partial_match", True)),
            case_sensitive=bool(raw.get("case_sensitive", False)),
            inverted=inverted,
        )
    if kind == FILTER_SUBSTRUCTURE:
        return SubstructureFilterClause(
            smarts=str(raw.get("smarts") or "").strip(),
            structure_source=_resolved_text(raw.get("structure_source") or "Structure", resolve)
            or "Structure",
            inverted=inverted,
        )
    raise ValueError(f"Unknown filter kind {kind!r}.")


def _resolved_text(value: Any, resolve: Callable[[str], str]) -> str:
    return resolve(str(value or "")).strip()
