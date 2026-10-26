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

"""Find-and-replace for one table cell's text.

Literal text is non-overlapping, the same way :meth:`str.replace` works.
``*`` and ``?`` are wildcards. A find text that starts with a comparison
(``>10``, ``=10``, ``empty``) matches the whole cell. AND/OR and SMARTS stay in Search.
"""

from __future__ import annotations

import fnmatch
import re
from re import Pattern

from ..chem.molecule_conversion import safe_float

# Blank-cell words, the same set Search accepts.
_EMPTY_KEYWORDS = frozenset({"empty", "blank", "is:empty", "is:blank"})
_NOT_EMPTY_KEYWORDS = frozenset(
    {"!empty", "not empty", "notempty", "is:notempty", "is:notblank", "not blank"}
)
_COMPARE_PREFIXES: tuple[tuple[str, str], ...] = (
    (">=", "gte"),
    ("<=", "lte"),
    ("<>", "ne"),
    ("!=", "ne"),
    (">", "gt"),
    ("<", "lt"),
    ("=", "eq"),
)
_ORDERED_OPS = frozenset({"gt", "gte", "lt", "lte"})


def _classify_find(find: str) -> tuple[str, str]:
    """Return ``(op, value)`` when *find* is a comparison, else ``("", "")``."""
    stripped = find.strip()
    low = stripped.lower()
    if low in _EMPTY_KEYWORDS:
        return "empty", ""
    if low in _NOT_EMPTY_KEYWORDS:
        return "not_empty", ""
    for prefix, op in _COMPARE_PREFIXES:
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if value:
            return op, value
        return "", ""
    return "", ""


def _compile_wildcard(pattern: str, *, case_sensitive: bool) -> Pattern[str]:
    """Turn ``*`` / ``?`` into a greedy pattern. Other characters stay literal."""
    parts: list[str] = []
    for char in pattern:
        if char == "*":
            parts.append(".*")
        elif char == "?":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    flags = re.DOTALL
    if not case_sensitive:
        flags |= re.IGNORECASE
    return re.compile("".join(parts), flags)


def _wildcard_whole(text: str, pattern: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return fnmatch.fnmatchcase(text, pattern)
    return fnmatch.fnmatch(text.casefold(), pattern.casefold())


def _wildcard_spans(text: str, pattern: Pattern[str], replacement: str) -> tuple[str, int]:
    """Replace each non-empty match. ``*`` is greedy and backtracks to a following literal."""
    chunks: list[str] = []
    count = 0
    last = 0
    for match in pattern.finditer(text):
        if match.start() == match.end():
            continue
        chunks.append(text[last : match.start()])
        chunks.append(replacement)
        last = match.end()
        count += 1
    if count == 0:
        return text, 0
    chunks.append(text[last:])
    return "".join(chunks), count


def _ordered(left: float, right: float, op: str) -> bool:
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    return left <= right


class LiteralReplace:
    """One compiled find/replace applied to cell strings."""

    def __init__(
        self,
        find: str,
        replacement: str,
        *,
        case_sensitive: bool,
        whole_cell: bool,
    ) -> None:
        self.find = find
        self.replacement = replacement
        self.case_sensitive = case_sensitive
        self.whole_cell = whole_cell
        op, value = _classify_find(find)
        self._op = op
        self._value = value
        self._wildcard = bool(not op and ("*" in find or "?" in find))
        self._pattern: Pattern[str] | None = None
        if find and self._wildcard and not whole_cell:
            self._pattern = _compile_wildcard(find, case_sensitive=case_sensitive)
        elif find and not op and not self._wildcard and not whole_cell and not case_sensitive:
            self._pattern = re.compile(re.escape(find), re.IGNORECASE)

    def matches(self, text: str) -> bool:
        """True when *text* contains the find text under this operation's rules."""
        return self.occurrence_count(text) > 0

    def occurrence_count(self, text: str) -> int:
        """How many non-overlapping matches *text* contains. Empty find counts as zero."""
        if not self.find:
            return 0
        if self._op:
            return 1 if self._comparison_matches(text) else 0
        if self._wildcard and self.whole_cell:
            return 1 if _wildcard_whole(text, self.find, case_sensitive=self.case_sensitive) else 0
        if self._wildcard:
            pattern = self._pattern
            if pattern is None:
                return 0
            return _wildcard_spans(text, pattern, self.replacement)[1]
        if self.whole_cell:
            return 1 if self._equals(text) else 0
        if self.case_sensitive:
            return text.count(self.find)
        pattern = self._pattern
        if pattern is None:
            return 0
        return len(pattern.findall(text))

    def apply(self, text: str) -> str | None:
        """Return the edited cell, or ``None`` when the text would not change.

        Every substring match is replaced. Whole-cell mode, and every comparison,
        replaces the cell only when the entire value matches. The replacement is
        inserted as typed, so a backslash or a ``*`` in the replacement stays
        literal. An empty replacement deletes the matched text.
        """
        if not self.find:
            return None
        if self._op or self.whole_cell:
            if not self.matches(text) or text == self.replacement:
                return None
            return self.replacement
        if self._wildcard:
            pattern = self._pattern
            if pattern is None:
                return None
            new, count = _wildcard_spans(text, pattern, self.replacement)
            if count == 0 or new == text:
                return None
            return new
        if self.case_sensitive:
            if self.find not in text:
                return None
            new = text.replace(self.find, self.replacement)
        else:
            pattern = self._pattern
            if pattern is None or pattern.search(text) is None:
                return None
            new = pattern.sub(lambda _match: self.replacement, text)
        if new == text:
            return None
        return new

    def _comparison_matches(self, text: str) -> bool:
        cell = (text or "").strip()
        if self._op == "empty":
            return cell == ""
        if self._op == "not_empty":
            return cell != ""
        left = safe_float(cell)
        right = safe_float(self._value)
        if self._op in _ORDERED_OPS:
            if left is None or right is None:
                return False
            return _ordered(left, right, self._op)
        if left is not None and right is not None:
            return left == right if self._op == "eq" else left != right
        left_text = cell if self.case_sensitive else cell.casefold()
        right_text = self._value if self.case_sensitive else self._value.casefold()
        return left_text == right_text if self._op == "eq" else left_text != right_text

    def _equals(self, text: str) -> bool:
        if self.case_sensitive:
            return text == self.find
        return text.casefold() == self.find.casefold()


def compile_literal_replace(
    find: str,
    replacement: str,
    *,
    case_sensitive: bool,
    whole_cell: bool,
) -> LiteralReplace | None:
    """Compile a replace operation. ``None`` when *find* is empty."""
    if find == "":
        return None
    return LiteralReplace(
        find,
        replacement,
        case_sensitive=case_sensitive,
        whole_cell=whole_cell,
    )


def occurrence_count(
    text: str,
    find: str,
    *,
    case_sensitive: bool,
    whole_cell: bool,
) -> int:
    """Non-overlapping matches of *find* in *text*. Empty *find* counts as zero."""
    compiled = compile_literal_replace(
        find,
        "",
        case_sensitive=case_sensitive,
        whole_cell=whole_cell,
    )
    if compiled is None:
        return 0
    return compiled.occurrence_count(text)


def cell_matches(
    text: str,
    find: str,
    *,
    case_sensitive: bool,
    whole_cell: bool,
) -> bool:
    """True when *text* matches *find* under the case and whole-cell rules."""
    return (
        occurrence_count(
            text,
            find,
            case_sensitive=case_sensitive,
            whole_cell=whole_cell,
        )
        > 0
    )


def replace_cell_text(
    text: str,
    find: str,
    replacement: str,
    *,
    case_sensitive: bool,
    whole_cell: bool,
) -> str | None:
    """Return edited *text*, or ``None`` when *find* is empty or the cell would not change."""
    compiled = compile_literal_replace(
        find,
        replacement,
        case_sensitive=case_sensitive,
        whole_cell=whole_cell,
    )
    if compiled is None:
        return None
    return compiled.apply(text)
