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

"""Numeric bounds cache for CompoundTableModel filter sliders."""

from __future__ import annotations

from ..services.numeric_bounds import (
    is_non_numeric_blob_header,
    merge_numeric_bounds_rows as merge_numeric_bounds_rows_fn,
    merge_numeric_range,
    scan_numeric_column,
)


class CompoundTableBoundsMixin:
    def _bounds_data_headers(self) -> frozenset[str]:
        return frozenset(
            h
            for h in self._headers[2:]
            if h not in ("ID_HIDDEN", "Structure")
            and h not in self._pixmap_columns
            and not is_non_numeric_blob_header(h)
        )

    def _invalidate_numeric_bounds_all(self) -> None:
        self._numeric_bounds_cache = None
        self._numeric_bounds_key = None
        self._numeric_bounds_dirty_cols = None

    def _mark_numeric_bounds_dirty(self, columns: set[str]) -> None:
        if not columns:
            return
        if self._numeric_bounds_cache is None:
            return
        if self._numeric_bounds_dirty_cols is None:
            return
        self._numeric_bounds_dirty_cols |= columns

    def _sorted_bounds_data_headers(self) -> list[str]:
        return sorted(
            h
            for h in self._headers[2:]
            if h not in ("ID_HIDDEN", "Structure")
            and h not in self._pixmap_columns
            and not is_non_numeric_blob_header(h)
        )

    def _mark_headers_added_for_bounds(self, new_headers: list[str]) -> None:
        """Extend bounds cache metadata when columns are appended (avoid full-table rescan)."""
        bounds_headers = [h for h in new_headers if h in self._bounds_data_headers()]
        if not bounds_headers:
            return
        if self._numeric_bounds_cache is None:
            return
        self._numeric_bounds_key = tuple(self._sorted_bounds_data_headers())
        if self._numeric_bounds_dirty_cols is None:
            self._numeric_bounds_dirty_cols = set()
        self._numeric_bounds_dirty_cols.update(bounds_headers)

    def _mark_header_removed_for_bounds(self, removed: str) -> None:
        """Drop one column from the bounds cache without rescanning the full table."""
        if self._numeric_bounds_cache is None:
            return
        self._numeric_bounds_cache.pop(removed, None)
        self._numeric_bounds_key = tuple(self._sorted_bounds_data_headers())
        if self._numeric_bounds_dirty_cols is not None:
            self._numeric_bounds_dirty_cols.discard(removed)

    def numeric_bounds_for_header(self, header_name: str) -> dict | None:
        """Min/max metadata for a single data column (one pass over rows)."""
        if header_name not in self._bounds_data_headers():
            return None
        return self._scan_numeric_column(self._rows, header_name)

    def refresh_numeric_bounds_for_headers(self, headers: list[str]) -> None:
        """Update cached min/max for specific columns only (avoids rescanning the full table)."""
        if not headers:
            return
        targets = [h for h in headers if h in self._bounds_data_headers()]
        if not targets:
            return
        if self._numeric_bounds_cache is None:
            self._numeric_bounds_cache = {}
            self._numeric_bounds_dirty_cols = set()
        self._numeric_bounds_key = tuple(self._sorted_bounds_data_headers())
        for h in targets:
            meta = self._scan_numeric_column(self._rows, h)
            if meta is not None:
                self._numeric_bounds_cache[h] = meta
            else:
                self._numeric_bounds_cache.pop(h, None)
        if self._numeric_bounds_dirty_cols is not None:
            self._numeric_bounds_dirty_cols -= set(targets)

    def _scan_numeric_column(self, rows, h: str) -> dict | None:
        if rows is self._rows:
            return self.merge_numeric_bounds_chunk(h, 0, len(rows), None)
        return scan_numeric_column(rows, h)

    @staticmethod
    def merge_numeric_bounds_rows(
        rows, h: str, start_row: int, end_row: int, acc: dict | None
    ) -> dict | None:
        """Merge numeric min/max for ``rows[start_row:end_row]`` into *acc*."""
        return merge_numeric_bounds_rows_fn(rows, h, start_row, end_row, acc)

    def list_bounds_data_headers(self) -> list[str]:
        return self._sorted_bounds_data_headers()

    def merge_numeric_bounds_chunk(
        self,
        header: str,
        start_row: int,
        end_row: int,
        acc: dict | None,
    ) -> dict | None:
        rows = self._rows
        if getattr(rows, "column_kind", lambda _h: None)(header) == "float":
            found = rows.float_range(header, start_row, end_row)
            return merge_numeric_range(acc, *found) if found else acc
        return self.merge_numeric_bounds_rows(rows, header, start_row, end_row, acc)

    def install_numeric_bounds_cache(self, cache: dict[str, dict]) -> None:
        self._numeric_bounds_cache = dict(cache)
        self._numeric_bounds_key = tuple(self._sorted_bounds_data_headers())
        self._numeric_bounds_dirty_cols = set()

    def _full_numeric_bounds_scan(self) -> dict[str, dict]:
        data_headers = sorted(
            h
            for h in self._headers[2:]
            if h not in ("ID_HIDDEN", "Structure")
            and h not in self._pixmap_columns
            and not is_non_numeric_blob_header(h)
        )
        if not data_headers:
            return {}
        out: dict[str, dict] = {}
        for h in data_headers:
            meta = self._scan_numeric_column(self._rows, h)
            if meta is not None:
                out[h] = meta
        return out

    def numeric_bounds_by_column(self) -> dict[str, dict]:
        """Numeric min/max per data column for filter sliders.

        Maintains a cache and only rescans columns touched since the last call when possible.
        """
        data_headers = sorted(
            h
            for h in self._headers[2:]
            if h not in ("ID_HIDDEN", "Structure")
            and h not in self._pixmap_columns
            and not is_non_numeric_blob_header(h)
        )
        key = tuple(data_headers)
        if not data_headers:
            self._invalidate_numeric_bounds_all()
            return {}

        if self._numeric_bounds_cache is None or self._numeric_bounds_key != key:
            self._numeric_bounds_cache = self._full_numeric_bounds_scan()
            self._numeric_bounds_key = key
            self._numeric_bounds_dirty_cols = set()
            return dict(self._numeric_bounds_cache)

        if not self._numeric_bounds_dirty_cols:
            return dict(self._numeric_bounds_cache)

        cache = self._numeric_bounds_cache
        for h in list(self._numeric_bounds_dirty_cols):
            if h not in key:
                continue
            meta = self._scan_numeric_column(self._rows, h)
            if meta is None:
                cache.pop(h, None)
            else:
                cache[h] = meta
        self._numeric_bounds_dirty_cols = set()
        return dict(cache)
