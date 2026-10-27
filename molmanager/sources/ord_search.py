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

"""Build and run an Open Reaction Database search."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

_SEARCH_URL = "https://open-reaction-database.org/api/search"
_RECORD_URL = "https://open-reaction-database.org/id/{reaction_id}"
_TEMPERATURE = "conditions.temperature.setpoint_kelvin"
_MEASUREMENTS = "outcomes.products.measurements"
_TIMEOUT_S = 75


class OrdSearchError(Exception):
    """The Open Reaction Database refused the query or did not answer."""


@dataclass
class OrdSearchOptions:
    """Filters for one conditions search. Temperatures are Celsius."""

    reaction_smarts: str
    chirality: bool = False
    limit: int = 100
    recorded_temperature: bool = False
    min_celsius: float | None = None
    max_celsius: float | None = None
    min_yield_percent: float | None = None
    component_role: str = ""
    component_structure: str = ""
    component_match: str = "substructure"
    similarity: float = 0.7
    order: str = ""


@dataclass(frozen=True)
class OrdSearchResult:
    """Reaction IDs from one search."""

    reaction_ids: list[str]
    truncated: bool


def reaction_record_url(reaction_id: str) -> str:
    """Public page for one Open Reaction Database record."""
    return _RECORD_URL.format(reaction_id=reaction_id)


def build_ord_query(options: OrdSearchOptions) -> dict:
    """Turn *options* into the search grammar sent to ``POST /api/search``."""
    smarts = options.reaction_smarts.strip()
    if ">>" not in smarts:
        raise ValueError("Enter a reaction SMARTS.")
    if not isinstance(options.limit, int) or not 1 <= options.limit <= 1000:
        raise ValueError("Keep between 1 and 1000 reactions.")
    if (
        options.min_celsius is not None
        and options.max_celsius is not None
        and options.min_celsius > options.max_celsius
    ):
        raise ValueError("Minimum temperature is above the maximum.")
    if options.min_yield_percent is not None and not 0 <= options.min_yield_percent <= 100:
        raise ValueError("Yield must be between 0 and 100.")
    clauses: list[dict] = [
        {"op": "reaction_smarts", "smarts": smarts, "chirality": bool(options.chirality)}
    ]
    clauses.extend(_temperature_clauses(options))
    if options.min_yield_percent is not None:
        clauses.append(_yield_clause(options.min_yield_percent))
    component = _component_clause(options)
    if component is not None:
        clauses.append(component)
    query: dict = {"where": _and(clauses), "limit": options.limit}
    order = _order(options)
    if order is not None:
        query["order_by"] = order
    return query


def search_reactions(query: dict, *, timeout: float = _TIMEOUT_S) -> OrdSearchResult:
    """Run *query* against the public Open Reaction Database."""
    body = json.dumps({"query": query}).encode("utf-8")
    request = urllib.request.Request(
        _SEARCH_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MolManager",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise OrdSearchError(_http_message(exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        reason = getattr(exc, "reason", exc)
        raise OrdSearchError(f"The Open Reaction Database did not respond. {reason}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "reactions":
        raise OrdSearchError("The search did not return a list of reactions.")
    ids = payload.get("reaction_ids")
    if not isinstance(ids, list):
        raise OrdSearchError("The search did not return a list of reactions.")
    return OrdSearchResult([str(item) for item in ids], bool(payload.get("truncated")))


def _temperature_clauses(options: OrdSearchOptions) -> list[dict]:
    clauses: list[dict] = []
    if options.recorded_temperature:
        clauses.append({"op": "not_null", "path": _TEMPERATURE})
    if options.min_celsius is not None:
        clauses.append(
            {"op": "ge", "path": _TEMPERATURE, "value": {"literal": options.min_celsius + 273.15}}
        )
    if options.max_celsius is not None:
        clauses.append(
            {"op": "le", "path": _TEMPERATURE, "value": {"literal": options.max_celsius + 273.15}}
        )
    return clauses


def _yield_clause(percent: float) -> dict:
    return {
        "op": "exists",
        "path": _MEASUREMENTS,
        "where": _and(
            [
                {"op": "eq", "path": "type", "value": {"literal": "YIELD"}},
                {"op": "ge", "path": "percentage.value", "value": {"literal": percent}},
            ]
        ),
    }


def _component_clause(options: OrdSearchOptions) -> dict | None:
    parts: list[dict] = []
    role = options.component_role.strip()
    if role:
        parts.append({"op": "eq", "path": "reaction_role", "value": {"literal": role}})
    structure = options.component_structure.strip()
    if structure:
        parts.append(_structure_clause(options, structure))
    if not parts:
        return None
    return {"op": "exists", "path": "inputs.components", "where": _and(parts)}


def _structure_clause(options: OrdSearchOptions, structure: str) -> dict:
    match = options.component_match
    if match == "substructure":
        return {
            "op": "substructure",
            "path": "smiles",
            "smarts": structure,
            "chirality": bool(options.chirality),
        }
    if match == "similarity":
        return {
            "op": "similarity",
            "path": "smiles",
            "smiles": structure,
            "threshold": float(options.similarity),
        }
    if match == "same_parent":
        return {"op": "same_parent", "path": "smiles", "smiles": structure}
    if match == "same_compound":
        return {"op": "same_compound", "path": "smiles", "smiles": structure}
    raise ValueError("Choose how the component structure should match.")


def _order(options: OrdSearchOptions) -> list[dict] | None:
    if not options.order:
        return None
    if options.order == "temperature_desc":
        return [{"key": _TEMPERATURE, "descending": True}]
    if options.order == "temperature_asc":
        return [{"key": _TEMPERATURE, "descending": False}]
    if options.order == "yield_desc":
        return [
            {
                "key": {
                    "reduce": "max",
                    "path": f"{_MEASUREMENTS}.percentage.value",
                    "where": {"op": "eq", "path": "type", "value": {"literal": "YIELD"}},
                },
                "descending": True,
            }
        ]
    raise ValueError("Choose a sort.")


def _and(clauses: list[dict]) -> dict:
    if len(clauses) == 1:
        return clauses[0]
    return {"op": "and", "clauses": clauses}


def _http_message(code: int, body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, list):
            parts = [
                str(item.get("msg") or item)
                for item in detail
                if isinstance(item, dict) or isinstance(item, str)
            ]
            if parts:
                return "; ".join(parts)
    text = body.strip()
    if text:
        return text[:400]
    return f"The search failed (HTTP {code})."
