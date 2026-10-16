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

"""Parse and evaluate in-table search query terms (operators, NOT, numeric compares)."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Literal

from ..services.sqlite_text_match import sqlite_text_match_clause
from ..chem.molecule_conversion import safe_float

SearchOp = Literal[
    "contains",
    "not_contains",
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "empty",
    "not_empty",
]

_NUMERIC_OPS: frozenset[SearchOp] = frozenset({"eq", "ne", "gt", "gte", "lt", "lte"})
_COMPARISON_PREFIXES: tuple[tuple[str, SearchOp], ...] = (
    (">=", "gte"),
    ("<=", "lte"),
    ("<>", "ne"),
    ("!=", "ne"),
    (">", "gt"),
    ("<", "lt"),
    ("=", "eq"),
)
_EMPTY_KEYWORDS = frozenset({"empty", "blank", "is:empty", "is:blank"})
_NOT_EMPTY_KEYWORDS = frozenset(
    {"!empty", "not empty", "notempty", "is:notempty", "is:notblank", "not blank"}
)


@dataclass(frozen=True)
class SearchCondition:
    """One comma-separated search term after operator parsing."""

    op: SearchOp
    value: str | None = None


def split_search_terms(query: str) -> list[str]:
    """Split a search box query on commas only (trimmed, non-empty). Prefer :func:`parse_search_term_groups`."""
    return flatten_search_term_groups(parse_search_term_groups(query))


def _unwrap_quoted_term(term: str) -> tuple[bool, str]:
    """If *term* is a quoted string literal, return ``(True, inner)``."""
    t = (term or "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'"):
        return True, t[1:-1]
    return False, t


_OR_SEPARATORS = frozenset({",", "|"})
_AND_SEPARATORS = frozenset({"&"})
# Daylight SMARTS bond primitives / operators that may appear outside [...].
_SMARTS_BOND_EXPR_CHARS = frozenset("-=#:~@/\\!")


def _prev_significant_char(text: str, index: int) -> str:
    j = index - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    return text[j] if j >= 0 else ""


def _next_significant_char(text: str, index: int) -> str:
    j = index + 1
    while j < len(text) and text[j].isspace():
        j += 1
    return text[j] if j < len(text) else ""


def _is_smarts_internal_logic_op(text: str, index: int, op: str) -> bool:
    """
    True when ``,`` / ``&`` at *index* belongs to Daylight SMARTS atom/bond logic.

    Inside ``[...]`` (caller tracks bracket depth). Outside brackets, Daylight allows
    bond expressions such as ``=,`` / ``@;!:`` between atoms — those must not be treated
    as search-level OR/AND separators.
    """
    if op == "|":
        # Pipe is not a Daylight SMARTS logical operator; keep as search OR.
        return False
    if op not in {",", "&"}:
        return False
    prev = _prev_significant_char(text, index)
    nxt = _next_significant_char(text, index)
    if prev in _SMARTS_BOND_EXPR_CHARS or nxt in _SMARTS_BOND_EXPR_CHARS:
        return True
    # e.g. ]=,#[  after closing an atom bracket
    if prev == "]" and nxt in _SMARTS_BOND_EXPR_CHARS:
        return True
    return False


def _flush_and_between_quoted_literals(text: str, index: int) -> bool:
    """True when ``&`` at *index* joins two quoted literals (``"a"&"b"``), not ``>5 & <10``."""
    if index < 0 or index >= len(text) or text[index] != "&":
        return False
    before = text[index - 1] if index > 0 else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    return before in ('"', "'") or after in ('"', "'")


def _join_and_terms_for_branch(terms: list[str]) -> str:
    if not terms:
        return ""
    if len(terms) == 1:
        return terms[0]
    return " & ".join(terms)


def _split_or_branches(text: str) -> list[str]:
    """
    Split on top-level ``,`` and ``|`` only.

    ``&`` ends an AND-term within the branch but does not start a new OR branch.
    Quote-adjacent ``&`` (``"a"&"b"``) is not copied into the branch text so AND parsing works.
    Daylight SMARTS ``,`` / ``&`` inside ``[...]`` or bond expressions (e.g. ``=,``) do not split.
    """
    s = text or ""
    if not s.strip():
        return []
    branches: list[str] = []
    branch_terms: list[str] = []
    buf: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    in_quote: str | None = None
    segment_quoted = False
    i = 0
    n = len(s)

    def _flush_term() -> None:
        nonlocal segment_quoted
        part = "".join(buf).strip()
        if part:
            branch_terms.append(f'"{part}"' if segment_quoted else part)
        buf.clear()
        segment_quoted = False

    def _flush_branch() -> None:
        nonlocal branch_terms
        _flush_term()
        if branch_terms:
            branches.append(_join_and_terms_for_branch(branch_terms))
        branch_terms = []

    while i < n:
        ch = s[i]
        if in_quote is not None:
            if ch == in_quote:
                in_quote = None
            else:
                buf.append(ch)
            i += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
            segment_quoted = True
            i += 1
            continue
        if ch == "[":
            bracket_depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            paren_depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
            i += 1
            continue
        top_level = paren_depth == 0 and bracket_depth == 0
        if top_level:
            if ch in _OR_SEPARATORS:
                if ch == "," and _is_smarts_internal_logic_op(s, i, ","):
                    buf.append(ch)
                    i += 1
                    continue
                _flush_branch()
                i += 1
                continue
            if ch == "&":
                if _flush_and_between_quoted_literals(s, i):
                    _flush_term()
                elif _is_smarts_internal_logic_op(s, i, "&"):
                    buf.append(ch)
                else:
                    buf.append(ch)
                i += 1
                continue
        if top_level and ch in "<>":
            if ch == "<" and i + 1 < n and s[i + 1] == ">":
                buf.append("<>")
                i += 2
                continue
            if i + 1 < n and s[i + 1] == "=":
                buf.append(ch)
                buf.append("=")
                i += 2
                continue
            buf.append(ch)
            i += 1
            continue
        if top_level and ch == "!" and i + 1 < n and s[i + 1] == "=":
            buf.append("!=")
            i += 2
            continue
        buf.append(ch)
        i += 1
    _flush_branch()
    return branches


def _split_top_level(
    text: str,
    separators: frozenset[str],
    *,
    flush_on: frozenset[str] | None = None,
) -> list[str]:
    """
    Split *text* on separator characters at parenthesis/bracket depth zero.

    Comparison prefixes (``>=``, ``<=``, ``<>``, ``!=``) and numeric ``>`` / ``<`` are not split points.
    Commas, ``|``, and ``&`` inside ``"..."`` / ``'...'`` literals do not split.
    Daylight SMARTS operators inside ``[...]`` or bond expressions do not split.

    *flush_on* ends the current segment without keeping the character (used when splitting AND
    terms inside one OR branch so ``,``/``|`` are not absorbed).
    """
    s = text or ""
    if not s.strip():
        return []
    parts: list[str] = []
    buf: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    in_quote: str | None = None
    segment_quoted = False
    i = 0
    n = len(s)

    def _flush() -> None:
        nonlocal segment_quoted
        part = "".join(buf).strip()
        if part:
            if segment_quoted:
                parts.append(f'"{part}"')
            else:
                parts.append(part)
        buf.clear()
        segment_quoted = False

    while i < n:
        ch = s[i]
        if in_quote is not None:
            if ch == in_quote:
                in_quote = None
            else:
                buf.append(ch)
            i += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
            segment_quoted = True
            i += 1
            continue
        if ch == "[":
            bracket_depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            paren_depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
            i += 1
            continue
        top_level = paren_depth == 0 and bracket_depth == 0 and in_quote is None
        if top_level:
            if ch in separators and not _is_smarts_internal_logic_op(s, i, ch):
                _flush()
                i += 1
                continue
            if flush_on and ch in flush_on and not _is_smarts_internal_logic_op(s, i, ch):
                _flush()
                i += 1
                continue
        if top_level and ch in "<>":
            if ch == "<" and i + 1 < n and s[i + 1] == ">":
                buf.append("<>")
                i += 2
                continue
            if i + 1 < n and s[i + 1] == "=":
                buf.append(ch)
                buf.append("=")
                i += 2
                continue
            buf.append(ch)
            i += 1
            continue
        if top_level and ch == "!" and i + 1 < n and s[i + 1] == "=":
            buf.append("!=")
            i += 2
            continue
        buf.append(ch)
        i += 1
    _flush()
    return parts


def parse_search_term_groups(query: str) -> list[list[str]]:
    """
    Parse query into OR-groups of AND-terms.

    * ``|`` and ``,`` separate OR branches (comma defaults to OR).
    * ``&`` separates AND terms within one branch.
    * Parentheses group a sub-expression without splitting inside them.
    * Square brackets protect Daylight SMARTS atom expressions (``[F,Cl]``, ``[n&H1]``).
    * Bond-level SMARTS logic outside brackets (e.g. ``=,``) is not treated as a separator.
    * String literals use ``"..."`` or ``'...'`` so operators inside the text are not split.
    """
    q = (query or "").strip()
    if not q:
        return []
    or_parts = _split_or_branches(q)
    groups: list[list[str]] = []
    for part in or_parts:
        and_terms = [
            t for t in _split_top_level(part, _AND_SEPARATORS, flush_on=_OR_SEPARATORS) if t.strip()
        ]
        if and_terms:
            groups.append(and_terms)
    return groups


def flatten_search_term_groups(groups: list[list[str]]) -> list[str]:
    """All term strings in an expression (order preserved, quotes stripped for literals)."""
    out: list[str] = []
    for g in groups:
        for t in g:
            quoted, inner = _unwrap_quoted_term(t)
            out.append(inner if quoted else t)
    return out


def validate_search_text_query(query: str, *, partial: bool) -> str | None:
    """
      Return an error message when a text-search term must be quoted, else ``None``.

      String literals must use ``"..."`` or ``'...'`` so ``|``, ``,``, and ``&`` are not ambiguous.
    Numeric comparisons, ``empty`` / ``not empty``, and quoted strings are allowed.
    """
    q = (query or "").strip()
    if not q:
        return None
    for and_terms in parse_search_term_groups(q):
        for term in and_terms:
            if parse_search_condition(term, partial=partial) is None:
                return (
                    "Search: put string text in double or single quotes "
                    f'(e.g. "your text"); unquoted term {term!r} is invalid.'
                )
    return None


def parse_search_condition(term: str, *, partial: bool) -> SearchCondition | None:
    """
    Parse one search term into a condition.

    Supports:
    - Comparisons: ``>5``, ``>= 10``, ``< 3.2``, ``<= 1``, ``= "foo"``, ``!= "bar"``
    - Negation: ``NOT "x"``, ``!"x"``, ``-"x"`` (not a numeric literal)
    - Emptiness: ``empty``, ``blank``, ``not empty``
    - Plain text: ``"substring"`` (partial) or ``"exact"`` (exact) — quotes required
    - Wildcards inside quotes: ``"eth*"`` (fnmatch semantics)
    """
    term = (term or "").strip()
    if not term:
        return None
    quoted, inner = _unwrap_quoted_term(term)
    if quoted:
        default: SearchOp = "contains" if partial else "eq"
        return SearchCondition(default, inner)

    low = term.lower()
    if low in _EMPTY_KEYWORDS:
        return SearchCondition("empty")
    if low in _NOT_EMPTY_KEYWORDS:
        return SearchCondition("not_empty")

    negate = False
    if low.startswith("not "):
        rest = term[4:].strip()
        q, inner = _unwrap_quoted_term(rest)
        if not q:
            return None
        negate = True
        term = inner
        low = term.lower()
    elif term.startswith("!") and not term.startswith("!="):
        rest = term[1:].strip()
        q, inner = _unwrap_quoted_term(rest)
        if not q or _looks_numeric_literal(inner):
            return None
        negate = True
        term = inner
        low = term.lower()
    elif term.startswith("-") and len(term) > 1 and not _looks_numeric_literal(term):
        rest = term[1:].strip()
        q, inner = _unwrap_quoted_term(rest)
        if not q:
            return None
        negate = True
        term = inner
        low = term.lower()

    for prefix, op in _COMPARISON_PREFIXES:
        if term.startswith(prefix):
            val = term[len(prefix) :].strip()
            if not val:
                return None
            if op in ("eq", "ne") and not _looks_numeric_literal(val):
                q, inner = _unwrap_quoted_term(val)
                if not q:
                    return None
                val = inner
            if op in _NUMERIC_OPS and safe_float(val) is None and op not in ("eq", "ne"):
                return SearchCondition(op, val)
            cond = SearchCondition(op, val)
            if negate:
                return _negate_condition(cond)
            return cond

    if _looks_numeric_literal(term):
        cond = SearchCondition("eq", term)
        if negate:
            return SearchCondition("ne", term)
        return cond

    if negate:
        default: SearchOp = "contains" if partial else "eq"
        op: SearchOp = "not_contains" if default == "contains" else "ne"
        return SearchCondition(op, term)

    return None


def parse_search_expression(query: str, *, partial: bool) -> list[list[SearchCondition]]:
    """Parse query into OR-groups of AND-joined :class:`SearchCondition` lists."""
    groups: list[list[SearchCondition]] = []
    for and_terms in parse_search_term_groups(query):
        and_conds: list[SearchCondition] = []
        for term in and_terms:
            cond = parse_search_condition(term, partial=partial)
            if cond is not None:
                and_conds.append(cond)
        if and_conds:
            groups.append(and_conds)
    return groups


def parse_search_conditions(query: str, *, partial: bool) -> list[SearchCondition]:
    """Flatten all conditions (single OR-group semantics only — prefer :func:`parse_search_expression`)."""
    out: list[SearchCondition] = []
    for group in parse_search_expression(query, partial=partial):
        out.extend(group)
    return out


def _looks_numeric_literal(text: str) -> bool:
    return bool(re.match(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$", (text or "").strip()))


def _negate_condition(cond: SearchCondition) -> SearchCondition:
    if cond.op == "contains":
        return SearchCondition("not_contains", cond.value)
    if cond.op == "not_contains":
        return SearchCondition("contains", cond.value)
    if cond.op == "eq":
        return SearchCondition("ne", cond.value)
    if cond.op == "ne":
        return SearchCondition("eq", cond.value)
    if cond.op == "gt":
        return SearchCondition("lte", cond.value)
    if cond.op == "gte":
        return SearchCondition("lt", cond.value)
    if cond.op == "lt":
        return SearchCondition("gte", cond.value)
    if cond.op == "lte":
        return SearchCondition("gt", cond.value)
    if cond.op == "empty":
        return SearchCondition("not_empty")
    if cond.op == "not_empty":
        return SearchCondition("empty")
    return cond


def _wildcard_match(hay: str, pattern: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return fnmatch.fnmatchcase(hay, pattern)
    return fnmatch.fnmatch(hay.casefold(), pattern.casefold())


def _text_contains(hay: str, needle: str, *, case_sensitive: bool) -> bool:
    if "*" in needle or "?" in needle:
        return _wildcard_match(hay, needle, case_sensitive=case_sensitive)
    if case_sensitive:
        return needle in hay
    return needle.casefold() in hay.casefold()


def evaluate_search_condition(
    cell_text: str,
    cond: SearchCondition,
    *,
    partial: bool,
    case_sensitive: bool,
) -> bool:
    """Return whether *cell_text* satisfies *cond*."""
    raw = cell_text or ""
    cell = raw.strip()

    if cond.op == "empty":
        return not cell
    if cond.op == "not_empty":
        return bool(cell)

    if cond.op in _NUMERIC_OPS:
        left = safe_float(cell)
        right = safe_float(cond.value) if cond.value is not None else None
        if left is None or right is None:
            if cond.op in ("eq", "ne"):
                left_s = raw if case_sensitive else raw.casefold()
                right_s = cond.value or ""
                if not case_sensitive:
                    right_s = right_s.casefold()
                if cond.op == "eq":
                    return left_s == right_s
                return left_s != right_s
            return False
        if cond.op == "gt":
            return left > right
        if cond.op == "gte":
            return left >= right
        if cond.op == "lt":
            return left < right
        if cond.op == "lte":
            return left <= right
        if cond.op == "eq":
            return left == right
        if cond.op == "ne":
            return left != right

    needle = cond.value or ""
    if cond.op == "contains":
        if partial:
            return _text_contains(raw, needle, case_sensitive=case_sensitive)
        if case_sensitive:
            return cell == needle
        return cell.casefold() == needle.casefold()
    if cond.op == "not_contains":
        if partial:
            return not _text_contains(raw, needle, case_sensitive=case_sensitive)
        if case_sensitive:
            return cell != needle
        return cell.casefold() != needle.casefold()
    if cond.op == "eq":
        if case_sensitive:
            return cell == needle
        return cell.casefold() == needle.casefold()
    if cond.op == "ne":
        if case_sensitive:
            return cell != needle
        return cell.casefold() != needle.casefold()
    return False


def evaluate_search_conditions(
    cell_text: str,
    conditions: list[SearchCondition],
    *,
    match_and: bool,
    partial: bool,
    case_sensitive: bool,
) -> bool:
    if not conditions:
        return False
    results = [
        evaluate_search_condition(cell_text, c, partial=partial, case_sensitive=case_sensitive)
        for c in conditions
    ]
    return all(results) if match_and else any(results)


def combine_search_row_sets(glues: list[str | None], row_sets: list[set[int]]) -> set[int]:
    """
    Combine per-criterion row sets left to right.

    ``and`` is intersection, ``or`` is union, and ``not`` removes rows that match
    that criterion from the result so far. The first set is the starting result.
    """
    if not row_sets:
        return set()
    result = set(row_sets[0])
    for i in range(1, len(row_sets)):
        glue = glues[i] if i < len(glues) and glues[i] else "and"
        nxt = row_sets[i]
        if glue == "or":
            result |= nxt
        elif glue == "not":
            result -= nxt
        else:
            result &= nxt
    return result


def evaluate_search_expression(
    cell_text: str,
    expression: list[list[SearchCondition]],
    *,
    partial: bool,
    case_sensitive: bool,
) -> bool:
    """True if any OR-group matches and every condition in that group matches (AND)."""
    if not expression:
        return False
    for and_group in expression:
        if and_group and all(
            evaluate_search_condition(cell_text, c, partial=partial, case_sensitive=case_sensitive)
            for c in and_group
        ):
            return True
    return False


def describe_search_expression(expression: list[list[SearchCondition]]) -> str:
    """Short summary for status text (empty string if a single simple term)."""
    n_or = len(expression)
    n_and = max((len(g) for g in expression), default=0)
    if n_or <= 1 and n_and <= 1:
        return ""
    if n_or > 1 and n_and > 1:
        return f", {n_or} OR groups (≤{n_and} AND terms each)"
    if n_or > 1:
        return f", {n_or} terms (OR)"
    return f", {n_and} terms (AND)"


def sqlite_where_for_expression(
    header_quoted: str,
    expression: list[list[SearchCondition]],
    *,
    partial: bool,
    case_sensitive: bool,
) -> tuple[str, list[object]] | None:
    """Build a SQLite WHERE clause for a full OR-of-AND expression, or None if unsupported."""
    if not expression:
        return None
    or_sql: list[str] = []
    args: list[object] = []
    for and_group in expression:
        and_sql: list[str] = []
        for cond in and_group:
            frag = sqlite_clause_for_condition(
                header_quoted, cond, partial=partial, case_sensitive=case_sensitive
            )
            if frag is None:
                return None
            and_sql.append(frag[0])
            args.extend(frag[1])
        if and_sql:
            or_sql.append("(" + " AND ".join(f"({p})" for p in and_sql) + ")")
    if not or_sql:
        return None
    if len(or_sql) == 1:
        return or_sql[0], args
    return "(" + " OR ".join(or_sql) + ")", args


def sqlite_clause_for_condition(
    header_quoted: str,
    cond: SearchCondition,
    *,
    partial: bool,
    case_sensitive: bool,
) -> tuple[str, list[object]] | None:
    """
    Build a SQLite WHERE fragment for one condition, or None if pushdown is unsupported.
    """
    qh = header_quoted
    if cond.op == "empty":
        return f'(TRIM(COALESCE("{qh}", "")) = "")', []
    if cond.op == "not_empty":
        return f'(TRIM(COALESCE("{qh}", "")) <> "")', []

    col = f'CAST("{qh}" AS REAL)'
    if cond.op in _NUMERIC_OPS:
        rhs = safe_float(cond.value)
        if rhs is None and cond.op not in ("eq", "ne"):
            return None
        sym = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "=", "ne": "!="}[cond.op]
        if rhs is not None:
            return f"({col} {sym} ?)", [rhs]
        if cond.op in ("eq", "ne"):
            if case_sensitive:
                return f'("{qh}" {sym} ?)', [cond.value or ""]
            op = "=" if cond.op == "eq" else "!="
            return f'(LOWER("{qh}") {op} ?)', [(cond.value or "").lower()]
        return None

    if cond.op == "contains":
        if "*" in (cond.value or "") or "?" in (cond.value or ""):
            return None
        return sqlite_text_match_clause(
            qh, cond.value or "", partial=partial, case_sensitive=case_sensitive
        )

    if cond.op == "not_contains":
        inner = sqlite_clause_for_condition(
            header_quoted,
            SearchCondition("contains", cond.value),
            partial=partial,
            case_sensitive=case_sensitive,
        )
        if inner is None:
            return None
        return f"(NOT ({inner[0]}))", list(inner[1])

    return None


def parse_substructure_term(term: str) -> tuple[str, bool]:
    """Return ``(pattern_text, negated)`` for one substructure search term."""
    term = (term or "").strip()
    if not term:
        return "", False
    low = term.lower()
    if low.startswith("not "):
        rest = term[4:].strip()
        return rest, bool(rest)
    if term.startswith("!"):
        rest = term[1:].strip()
        return rest, bool(rest)
    if term.startswith("-") and len(term) > 1:
        rest = term[1:].strip()
        return rest, bool(rest)
    return term, False
