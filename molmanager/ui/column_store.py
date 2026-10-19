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

"""Columnar cell storage for the compound table.

Numeric columns that share one exact display format live in a float64 array.
Everything else stays text. Display text round-trips: ``1.50`` is not stored as
``1.5``, and ``00123`` stays a string.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

import numpy as np

_NUMBER = re.compile(r"^[+-]?(\d+)(?:\.(\d+))?$")
_MAX_EXACT_INT = 2**53


def format_number(value: float, decimals: int | None) -> str:
    """Render *value* the way a uniform column displays it."""
    if decimals is None:
        return str(int(value))
    return f"{value:.{decimals}f}"


def classify_number(text: str) -> tuple[float, int | None] | None:
    """Return ``(value, decimals)`` when *text* is an exact plain number.

    ``decimals`` is ``None`` for an integer. ``None`` means the text must stay
    a string (blank, leading zeros, scientific notation, or a format that does
    not round-trip through float64).
    """
    if not text or text[0] == "+":
        return None
    match = _NUMBER.fullmatch(text)
    if match is None:
        return None
    digits, frac = match.group(1), match.group(2)
    if len(digits) > 1 and digits[0] == "0":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    decimals = None if frac is None else len(frac)
    if decimals is None and abs(value) > _MAX_EXACT_INT:
        return None
    if format_number(value, decimals) != text:
        return None
    return value, decimals


class _TextColumn:
    kind = "text"

    def __init__(self, texts: list[str], *, blank_only: bool) -> None:
        self.texts = texts
        self.blank_only = blank_only

    @classmethod
    def blanks(cls, n: int) -> _TextColumn:
        return cls([""] * n, blank_only=True)

    def text_at(self, index: int) -> str:
        return self.texts[index]

    def set_text(self, index: int, text: str) -> None:
        self.texts[index] = text
        if text:
            self.blank_only = False

    def grow_blank(self) -> None:
        self.texts.append("")

    def insert_blank(self, index: int) -> None:
        self.texts.insert(index, "")

    def permute(self, order: np.ndarray) -> None:
        self.texts = [self.texts[int(i)] for i in order]

    def take(self, keep: np.ndarray) -> None:
        self.texts = [text for text, flag in zip(self.texts, keep) if flag]


class _FloatColumn:
    kind = "float"

    def __init__(self, n: int, decimals: int | None) -> None:
        cap = max(n, 16)
        self.values = np.zeros(cap, dtype=np.float64)
        self.valid = np.zeros(cap, dtype=np.bool_)
        self.decimals = decimals
        self.n = n
        self.cap = cap

    def _grow_cap(self, need: int) -> None:
        if need <= self.cap:
            return
        cap = max(need, self.cap * 2)
        values = np.zeros(cap, dtype=np.float64)
        valid = np.zeros(cap, dtype=np.bool_)
        values[: self.n] = self.values[: self.n]
        valid[: self.n] = self.valid[: self.n]
        self.values = values
        self.valid = valid
        self.cap = cap

    def text_at(self, index: int) -> str:
        if not self.valid[index]:
            return ""
        return format_number(float(self.values[index]), self.decimals)

    def set_blank(self, index: int) -> None:
        self.valid[index] = False

    def set_value(self, index: int, value: float) -> None:
        self.values[index] = value
        self.valid[index] = True

    def grow_blank(self) -> None:
        self._grow_cap(self.n + 1)
        self.valid[self.n] = False
        self.n += 1

    def insert_blank(self, index: int) -> None:
        self._grow_cap(self.n + 1)
        if index < self.n:
            self.values[index + 1 : self.n + 1] = self.values[index : self.n]
            self.valid[index + 1 : self.n + 1] = self.valid[index : self.n]
        self.valid[index] = False
        self.n += 1

    def permute(self, order: np.ndarray) -> None:
        self.values[: self.n] = self.values[: self.n][order]
        self.valid[: self.n] = self.valid[: self.n][order]

    def take(self, keep: np.ndarray) -> None:
        self.values = self.values[: self.n][keep]
        self.valid = self.valid[: self.n][keep]
        self.n = int(self.values.shape[0])
        self.cap = self.n


class _CellView(Mapping[str, str]):
    """Mapping view of one row. Writes go back to the columnar store."""

    def __init__(self, store: ColumnStore, index: int) -> None:
        self._store = store
        self._index = index

    def __getitem__(self, key: str) -> str:
        return self._store.get_text(self._index, key)

    def __setitem__(self, key: str, value: object) -> None:
        self._store.set_text(self._index, key, "" if value is None else str(value))

    def __delitem__(self, key: str) -> None:
        self.pop(key)

    def __iter__(self):
        return iter(self._store.columns)

    def __len__(self) -> int:
        return len(self._store.columns)

    def __contains__(self, key: object) -> bool:
        return key in self._store.columns

    def get(self, key: str, default: str = "") -> str:  # type: ignore[override]
        if key not in self._store.columns:
            return default
        return self._store.get_text(self._index, key)

    def pop(self, key: str, default: str | None = None) -> str | None:
        if key not in self._store.columns:
            return default
        previous = self._store.get_text(self._index, key)
        self._store.set_text(self._index, key, "")
        return previous


class _RowView:
    """One row's oid plus a live cell mapping. Not retained by the store."""

    __slots__ = ("oid", "values", "index")

    def __init__(self, store: ColumnStore, index: int) -> None:
        self.oid = int(store.oids[index])
        self.values = _CellView(store, index)
        self.index = index


class ColumnStore:
    """Row order plus per-column values. List-like so the table model can own it."""

    def __init__(self) -> None:
        self.oids = np.empty(0, dtype=np.int64)
        self._cap = 0
        self.n = 0
        self.columns: dict[str, _TextColumn | _FloatColumn] = {}

    def __len__(self) -> int:
        return self.n

    def __bool__(self) -> bool:
        return self.n > 0

    def __iter__(self):
        for i in range(self.n):
            yield _RowView(self, i)

    def __getitem__(self, index: int | slice):
        if isinstance(index, slice):
            return [_RowView(self, i) for i in range(*index.indices(self.n))]
        if index < 0:
            index += self.n
        if index < 0 or index >= self.n:
            raise IndexError(index)
        return _RowView(self, index)

    def oid_at(self, index: int) -> int:
        return int(self.oids[index])

    def clear(self) -> None:
        self.oids = np.empty(0, dtype=np.int64)
        self._cap = 0
        self.n = 0
        self.columns.clear()

    def get_text(self, index: int, header: str) -> str:
        column = self.columns.get(header)
        if column is None:
            return ""
        return column.text_at(index)

    def set_text(self, index: int, header: str, text: str) -> None:
        text = "" if text is None else str(text)
        column = self.columns.get(header)
        if column is None:
            self.columns[header] = self._new_column(text)
            column = self.columns[header]
            if column.kind == "float" and text:
                parsed = classify_number(text)
                if parsed is not None:
                    column.set_value(index, parsed[0])
            elif text:
                column.set_text(index, text)
            return
        if column.kind == "text" and column.blank_only and text:
            parsed = classify_number(text)
            if parsed is not None:
                promoted = _FloatColumn(self.n, parsed[1])
                promoted.set_value(index, parsed[0])
                self.columns[header] = promoted
                return
        if column.kind == "float":
            if not text:
                column.set_blank(index)
                return
            parsed = classify_number(text)
            if parsed is None or parsed[1] != column.decimals:
                self._demote(header)
                self.columns[header].set_text(index, text)
                return
            column.set_value(index, parsed[0])
            return
        column.set_text(index, text)

    def _new_column(self, text: str) -> _TextColumn | _FloatColumn:
        parsed = classify_number(text) if text else None
        if parsed is None:
            column = _TextColumn.blanks(self.n)
            return column
        return _FloatColumn(self.n, parsed[1])

    def _demote(self, header: str) -> None:
        column = self.columns[header]
        texts = [column.text_at(i) for i in range(self.n)]
        self.columns[header] = _TextColumn(texts, blank_only=not any(texts))

    def _grow_oids(self) -> None:
        if self.n < self._cap:
            return
        cap = max(16, self._cap * 2)
        oids = np.empty(cap, dtype=np.int64)
        if self.n:
            oids[: self.n] = self.oids[: self.n]
        self.oids = oids
        self._cap = cap

    def _write_mapping(self, index: int, values: Mapping[str, str]) -> None:
        for key, value in values.items():
            self.set_text(index, key, "" if value is None else str(value))

    def append(self, row: object) -> None:
        """Append a row that exposes ``.oid`` and ``.values``."""
        index = self.n
        self._grow_oids()
        self.oids[index] = int(row.oid)  # type: ignore[attr-defined]
        self.n += 1
        for column in self.columns.values():
            column.grow_blank()
        self._write_mapping(index, row.values)  # type: ignore[attr-defined]

    def insert(self, index: int, row: object) -> None:
        index = max(0, min(int(index), self.n))
        self._grow_oids()
        if index < self.n:
            self.oids[index + 1 : self.n + 1] = self.oids[index : self.n]
        self.oids[index] = int(row.oid)  # type: ignore[attr-defined]
        self.n += 1
        for column in self.columns.values():
            column.insert_blank(index)
        self._write_mapping(index, row.values)  # type: ignore[attr-defined]

    def pop(self, index: int) -> _RowView:
        """Remove one row and return a snapshot that :meth:`insert` can put back."""
        if index < 0:
            index += self.n
        snapshot = _Snapshot(self.oid_at(index), self._row_dict(index))
        keep = np.ones(self.n, dtype=np.bool_)
        keep[index] = False
        self._compress(keep)
        return snapshot  # type: ignore[return-value]

    def delete_oids(self, oids: set[int]) -> None:
        if not oids or self.n == 0:
            return
        keep = np.fromiter(
            (int(oid) not in oids for oid in self.oids[: self.n]), dtype=np.bool_, count=self.n
        )
        self._compress(keep)

    def drop_column(self, header: str) -> None:
        self.columns.pop(header, None)

    def rename_column(self, old: str, new: str) -> None:
        if old not in self.columns or old == new:
            return
        self.columns[new] = self.columns.pop(old)

    def _row_dict(self, index: int) -> dict[str, str]:
        return {name: column.text_at(index) for name, column in self.columns.items()}

    def _compress(self, keep: np.ndarray) -> None:
        self.oids = self.oids[: self.n][keep]
        self.n = int(self.oids.shape[0])
        self._cap = self.n
        for column in self.columns.values():
            column.take(keep)

    def sort(self, *, key, reverse: bool = False) -> None:
        views = [_RowView(self, i) for i in range(self.n)]
        views.sort(key=key, reverse=reverse)
        if not views:
            return
        order = np.fromiter((view.index for view in views), dtype=np.intp, count=self.n)
        self.oids[: self.n] = self.oids[: self.n][order]
        for column in self.columns.values():
            column.permute(order)

    def column_kind(self, header: str) -> str | None:
        column = self.columns.get(header)
        if column is None:
            return None
        return column.kind

    def analysis_values(self, header: str, indices: list[int] | None) -> np.ndarray | list[str]:
        """Float64 column (blank cells are NaN) or stripped text.

        ``indices`` is ``None`` for every row. A float column does not rebuild
        the display strings.
        """
        column = self.columns.get(header)
        n = self.n
        if isinstance(column, _FloatColumn):
            values = column.values[: column.n]
            valid = column.valid[: column.n]
            if indices is None:
                out = np.full(n, np.nan, dtype=np.float64)
                if n:
                    out[valid] = values[valid]
                return out
            idx = np.asarray(indices, dtype=np.intp)
            out = np.full(idx.shape[0], np.nan, dtype=np.float64)
            if idx.size:
                picked = valid[idx]
                out[picked] = values[idx][picked]
            return out
        if isinstance(column, _TextColumn):
            texts = column.texts
            if indices is None:
                return [text.strip() for text in texts]
            return [texts[i].strip() for i in indices]
        width = n if indices is None else len(indices)
        return [""] * width


class _Snapshot:
    """Detached row returned by :meth:`ColumnStore.pop`."""

    def __init__(self, oid: int, values: dict[str, str]) -> None:
        self.oid = oid
        self.values = values
