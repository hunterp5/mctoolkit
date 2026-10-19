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

"""In-window table search (column text and substructure across rows)."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

from PyQt5.QtCore import QItemSelectionModel, QTimer, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ...platform_support.config import load_config
from ...workers import SubstructureFilterWorker
from ..search_panel import SearchCriterionRow
from ..search_query import (
    classify_search_query,
    combine_search_row_sets,
    evaluate_search_expression,
    parse_search_expression,
    parse_search_term_groups,
    parse_substructure_term,
    sqlite_where_for_expression,
)


@dataclass(frozen=True)
class _SearchCriterionSpec:
    col: int
    query: str
    term_groups: list[list[str]]
    glue: str | None  # None for first row; ``and`` / ``or`` / ``not`` vs previous
    partial: bool
    case_sensitive: bool
    substructure: bool


class TableSearchMixin:
    """Uses ``_search_*`` widgets, ``table``, ``headers``, ``_table_model``, ``status_label``,
    and ``_mol_for_structure_row`` from the concrete app / ``TableUIMixin``.
    """

    _search_criterion_rows: list[SearchCriterionRow]

    @property
    def _search_col_combo(self) -> QComboBox | None:
        """First search row column combo (tests and legacy callers)."""
        if not getattr(self, "_search_criterion_rows", None):
            return None
        return self._search_criterion_rows[0].col_combo

    @property
    def _search_query_edit(self):
        """First search row query field (tests and legacy callers)."""
        if not getattr(self, "_search_criterion_rows", None):
            return None
        return self._search_criterion_rows[0].query_edit

    @property
    def _search_partial_cb(self) -> QCheckBox | None:
        if not getattr(self, "_search_criterion_rows", None):
            return None
        return self._search_criterion_rows[0].partial_cb

    @property
    def _search_case_sensitive_cb(self) -> QCheckBox | None:
        if not getattr(self, "_search_criterion_rows", None):
            return None
        return self._search_criterion_rows[0].case_cb

    def _init_table_search_panel(self, panel: QFrame) -> None:
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)

        self._search_rows_host = QWidget(panel)
        self._search_rows_layout = QVBoxLayout(self._search_rows_host)
        self._search_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._search_rows_layout.setSpacing(4)
        outer.addWidget(self._search_rows_host)

        self._search_criterion_rows = []
        self._add_search_criterion_row()
        self._wire_table_search_column_refresh()

    def _wire_table_search_column_refresh(self) -> None:
        """Refresh search column combos when the table gains or loses columns."""
        if getattr(self, "_search_column_refresh_wired", False):
            return
        model = getattr(self, "_table_model", None)
        if model is None:
            return
        model.columnsInserted.connect(self._on_table_search_columns_changed)
        model.columnsRemoved.connect(self._on_table_search_columns_changed)
        model.modelReset.connect(self._on_table_search_columns_changed)
        model.headerDataChanged.connect(self._on_table_search_header_changed)
        self._search_column_refresh_wired = True

    def _on_table_search_columns_changed(self, *_args) -> None:
        self._refresh_table_search_column_combos()

    def _on_table_search_header_changed(self, orientation, *_args) -> None:
        if int(orientation) == Qt.Horizontal:
            self._refresh_table_search_column_combos()

    def _refresh_table_search_column_combos(self) -> None:
        if not getattr(self, "_search_criterion_rows", None):
            return
        self._populate_table_search_columns_combo()

    def _remove_search_criterion_row(self, row: SearchCriterionRow) -> None:
        rows = getattr(self, "_search_criterion_rows", None) or []
        if row not in rows:
            return
        if len(rows) == 1:
            self._clear_sole_search_and_close()
            return
        rows.remove(row)
        self._search_rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._sync_search_row_chrome()
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def _clear_sole_search_and_close(self) -> None:
        """Delete the last remaining query and hide the Search panel."""
        if getattr(self, "_search_criterion_rows", None):
            row = self._search_criterion_rows[0]
            row.query_edit.clear()
            row.partial_cb.setChecked(True)
            row.case_cb.setChecked(False)
            row.glue_combo.setCurrentIndex(0)
        panel = getattr(self, "_search_panel", None)
        if panel is not None:
            panel.setVisible(False)
        self.clear_table_selection()
        self.status_label.setText("Search closed.")
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def _sync_search_row_chrome(self) -> None:
        """Keep Add on the first row, NOT/AND/OR on every row, and − visible on every row."""
        rows = getattr(self, "_search_criterion_rows", None) or []
        n = len(rows)
        for i, row in enumerate(rows):
            row.remove_btn.setVisible(True)
            if n <= 1:
                row.remove_btn.setToolTip("Delete this search and close Search.")
            else:
                row.remove_btn.setToolTip("Remove this search row.")
            row.add_btn.setVisible(i == 0)
            row.glue_combo.setVisible(True)

    def _add_search_criterion_row(self) -> SearchCriterionRow:
        is_first = not self._search_criterion_rows
        row = SearchCriterionRow(
            self._search_rows_host,
            show_glue=True,
            show_add=is_first,
            on_add=self._add_search_criterion_row,
        )
        row.remove_btn.clicked.connect(
            lambda _checked=False, rw=row: self._remove_search_criterion_row(rw)
        )
        if not is_first:
            row.copy_options_from(self._search_criterion_rows[0])
        row.query_edit.returnPressed.connect(self._run_table_search)
        self._search_rows_layout.addWidget(row)
        self._search_criterion_rows.append(row)
        self._populate_search_row_columns(row)
        self._sync_search_row_chrome()
        if not is_first:
            row.query_edit.setFocus(Qt.ShortcutFocusReason)
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)
        return row

    @staticmethod
    def _search_combo_label_for_header(header: str) -> str:
        if header == "ID_HIDDEN":
            return "Row ID"
        return header or ""

    def _populate_search_row_columns(
        self,
        row: SearchCriterionRow,
        *,
        preferred_col: int | None = None,
        preferred_header: str | None = None,
    ) -> None:
        combo = row.col_combo
        prev = combo.currentData()
        if preferred_col is not None:
            prev = preferred_col
        combo.blockSignals(True)
        combo.clear()
        if not self.headers:
            combo.addItem("(no columns)", -1)
        else:
            ncols = self._table_model.columnCount()
            for i, h in enumerate(self.headers):
                if i >= ncols:
                    break
                combo.addItem(self._search_combo_label_for_header(h), i)
        combo.blockSignals(False)
        header = str(preferred_header or "").strip()
        if header:
            for j in range(combo.count()):
                data = combo.itemData(j)
                if (
                    isinstance(data, int)
                    and 0 <= data < len(self.headers)
                    and self.headers[data] == header
                ):
                    combo.setCurrentIndex(j)
                    return
        if prev is not None and isinstance(prev, int) and prev >= 0:
            for j in range(combo.count()):
                if combo.itemData(j) == prev:
                    combo.setCurrentIndex(j)
                    return
        if combo.count():
            combo.setCurrentIndex(0)

    def _populate_table_search_columns_combo(self) -> None:
        for row in self._search_criterion_rows:
            self._populate_search_row_columns(row)

    def toggle_table_search_panel(self) -> None:
        """Show or hide Search without clearing queries; − on the last row deletes them."""
        panel: QFrame = self._search_panel
        opening = panel.isHidden()
        panel.setVisible(opening)
        if opening:
            self._populate_table_search_columns_combo()
            if self._search_criterion_rows:
                self._search_criterion_rows[0].query_edit.setFocus(Qt.ShortcutFocusReason)
            self.status_label.setText(
                "Search: quote column text, or leave SMILES/SMARTS unquoted. "
                "NOT on the first row excludes matches. Add for more rows (AND/OR/NOT). "
                "Within a row: & AND, | or comma OR. Press Enter. "
                "− deletes a row; deleting the last row closes Search."
            )
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def open_table_search_with_column(self, logical_col: int) -> None:
        """Show the search bar and pre-select a column (e.g. from the header context menu)."""
        if logical_col < 0 or logical_col >= len(self.headers):
            return
        panel: QFrame = self._search_panel
        panel.setVisible(True)
        if not self._search_criterion_rows:
            self._add_search_criterion_row()
        self._populate_search_row_columns(self._search_criterion_rows[0], preferred_col=logical_col)
        self._search_criterion_rows[0].query_edit.setFocus(Qt.ShortcutFocusReason)
        hname = self.headers[logical_col]
        self.status_label.setText(
            f'Search: column "{hname}" selected. Enter a query, then press Enter.'
        )
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def _search_query_pattern_mol(self, text: str) -> Chem.Mol | None:
        """Parse one query string as a substructure pattern (SMARTS first, then SMILES)."""
        from ...chem.smarts_macropatterns import mol_from_smarts

        text = (text or "").strip()
        if not text:
            return None
        try:
            m = mol_from_smarts(text)
            if m is not None:
                return m
        except Exception:
            pass
        try:
            return Chem.MolFromSmiles(text)
        except Exception:
            return None

    def _coalesce_smarts_term_groups(
        self, needle: str, term_groups: list[list[str]]
    ) -> list[list[str]]:
        """
        If search-level splitting breaks a valid Daylight SMARTS string, keep the whole query.

        Prefer the split terms when every term parses; otherwise fall back to one pattern.
        """
        flat: list[str] = []
        for and_terms in term_groups:
            for t in and_terms:
                pat_text, _neg = parse_substructure_term(t)
                if pat_text:
                    flat.append(pat_text)
        if len(flat) <= 1:
            return term_groups
        if all(self._search_query_pattern_mol(t) is not None for t in flat):
            return term_groups
        whole = (needle or "").strip()
        if whole and self._search_query_pattern_mol(whole) is not None:
            return [[whole]]
        return term_groups

    def _resolve_search_column(self, combo: QComboBox) -> int | None:
        col = combo.currentData()
        if not self.headers or col is None or (isinstance(col, int) and col < 0):
            return None
        if not isinstance(col, int) or col >= self._table_model.columnCount():
            return None
        return col

    def _collect_search_criteria(self) -> list[_SearchCriterionSpec] | None:
        specs: list[_SearchCriterionSpec] = []
        for row in self._search_criterion_rows:
            needle = (row.query_edit.text() or "").strip()
            kind = classify_search_query(
                needle,
                partial=row.partial_cb.isChecked(),
                parses_pattern=lambda text: self._search_query_pattern_mol(text) is not None,
            )
            if kind not in {"text", "substructure"}:
                self.status_label.setText(kind)
                return None
            term_groups = parse_search_term_groups(needle)
            if not term_groups:
                continue
            substructure = kind == "substructure"
            if substructure:
                term_groups = self._coalesce_smarts_term_groups(needle, term_groups)
            col = self._resolve_search_column(row.col_combo)
            if col is None:
                self._populate_search_row_columns(row)
                col = self._resolve_search_column(row.col_combo)
            if col is None:
                self.status_label.setText("Search: no columns loaded.")
                return None
            specs.append(
                _SearchCriterionSpec(
                    col=col,
                    query=needle,
                    term_groups=term_groups,
                    glue=row.glue(),
                    partial=row.partial_cb.isChecked(),
                    case_sensitive=row.case_cb.isChecked(),
                    substructure=substructure,
                )
            )
        return specs

    def _compile_search_substructure_groups(
        self, term_groups: list[list[str]]
    ) -> list[list[tuple[Chem.Mol, bool]]] | None:
        """Compile search SMARTS groups; ``None`` if a term cannot be parsed."""
        or_patterns: list[list[tuple[Chem.Mol, bool]]] = []
        for and_terms in term_groups:
            and_patterns: list[tuple[Chem.Mol, bool]] = []
            for t in and_terms:
                pat_text, negated = parse_substructure_term(t)
                if not pat_text:
                    continue
                q = self._search_query_pattern_mol(pat_text)
                if q is None:
                    QMessageBox.warning(
                        self,
                        "Search",
                        f"Could not parse term as SMARTS or SMILES: {pat_text!r}",
                    )
                    return None
                and_patterns.append((q, negated))
            if and_patterns:
                or_patterns.append(and_patterns)
        return or_patterns

    def _find_rows_substructure(self, term_groups: list[list[str]]) -> list[int] | None:
        or_patterns = self._compile_search_substructure_groups(term_groups)
        if or_patterns is None:
            return None
        if not or_patterns:
            return []
        from ...workers.substructure_filter import mol_matches_pattern_groups

        rows: list[int] = []
        for r in range(self._table_model.rowCount()):
            mol = self._mol_for_structure_row(r)
            if mol is None:
                continue
            if mol_matches_pattern_groups(mol, or_patterns):
                rows.append(r)
        return rows

    def _find_rows_text(
        self,
        col: int,
        needle: str,
        *,
        partial: bool,
        case_sensitive: bool,
    ) -> list[int]:
        expression = parse_search_expression(needle, partial=partial)
        if not expression:
            return []
        ensure_sqlite = getattr(self, "_ensure_sqlite_store_current", None)
        sqlite_ready = True
        if callable(ensure_sqlite):
            sqlite_ready = ensure_sqlite()
        store = getattr(self, "_sqlite_store", None)
        if not sqlite_ready and self._table_model.rowCount() > 5000:
            self.status_label.setText(
                "Search: indexing table in background; scanning rows now (may take a moment)…"
            )
        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_a, **_k: nullcontext())

        if store is not None and sqlite_ready and col >= 2 and col < len(self.headers):
            header = self.headers[col]
            qh = str(header).replace('"', '""')
            sql_frag = sqlite_where_for_expression(
                qh, expression, partial=partial, case_sensitive=case_sensitive
            )
            if sql_frag is not None:
                where_sql, sql_args = sql_frag
                rows: list[int] = []
                with scope("search.sqlite_pushdown"):
                    page = max(1000, int(getattr(load_config(), "sqlite_backend_page_size", 5000)))
                    after_oid: int | None = None
                    fetch_oids = getattr(store, "fetch_oids", None)
                    while True:
                        if callable(fetch_oids):
                            oids = fetch_oids(
                                where_sql=where_sql,
                                args=tuple(sql_args),
                                after_oid=after_oid,
                                limit=page,
                            )
                        else:
                            recs = store.fetch_page(
                                limit=page,
                                after_oid=after_oid,
                                where_sql=where_sql,
                                args=tuple(sql_args),
                                sort_by="oid",
                                ascending=True,
                            )
                            oids = [int(oid) for oid, _ in recs]
                        if not oids:
                            break
                        for oid in oids:
                            rr = self._table_model.logical_row_for_oid(int(oid))
                            if rr >= 0:
                                rows.append(rr)
                        after_oid = int(oids[-1])
                        if len(oids) < page:
                            break
                return rows

        rows = []
        with scope("search.text"):
            for r in range(self._table_model.rowCount()):
                hay = self._table_model.cell_text(r, col)
                if evaluate_search_expression(
                    hay,
                    expression,
                    partial=partial,
                    case_sensitive=case_sensitive,
                ):
                    rows.append(r)
        return rows

    def _combine_search_row_sets(
        self, specs: list[_SearchCriterionSpec], row_sets: list[set[int]]
    ) -> set[int]:
        universe = set(range(self._table_model.rowCount()))
        return combine_search_row_sets([spec.glue for spec in specs], row_sets, universe=universe)

    def _select_table_rows(self, rows: list[int]) -> bool:
        """Select *rows* in the table view; return False if nothing selected."""
        if not rows:
            return False
        n = self.select_table_rows(rows)
        if n <= 0:
            return False
        first_shown = next(
            (r for r in sorted({int(r) for r in rows}) if self._is_source_row_visible(r)), None
        )
        view_rows = [] if first_shown is None else self._source_rows_to_view_rows([first_shown])
        if view_rows:
            view_model = self.table.model()
            if view_model is not None:
                anchor_col = 1 if self._table_model.columnCount() > 1 else 0
                idx = view_model.index(view_rows[0], anchor_col)
                sm = self.table.selectionModel()
                if sm is not None and idx.isValid():
                    sm.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
                    self.table.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        QTimer.singleShot(
            0,
            lambda: (
                self.activateWindow(),
                self.raise_(),
                self.table.setFocus(Qt.OtherFocusReason),
                self.table.viewport().update(),
            ),
        )
        return True

    def _apply_table_search_results(
        self, specs: list[_SearchCriterionSpec], row_sets: list[set[int]]
    ) -> None:
        combined = sorted(self._combine_search_row_sets(specs, row_sets))
        visible_combined = [r for r in combined if self._is_source_row_visible(r)]
        if not combined:
            self.clear_table_selection()
            self.status_label.setText("Search: no matches.")
            return
        if not visible_combined:
            self.clear_table_selection()
            self.status_label.setText("Search: no visible matches.")
            return
        if not self._select_table_rows(visible_combined):
            self.clear_table_selection()
            self.status_label.setText("Search: no visible matches.")
            return

        self.table.setFocus(Qt.ShortcutFocusReason)

        n_crit = len(specs)
        glue_bits = [s.glue for i, s in enumerate(specs) if s.glue and (i > 0 or s.glue == "not")]
        if n_crit > 1 or (specs and specs[0].glue == "not"):
            glue_note = f", {n_crit} criteria ({'/'.join(g.upper() for g in glue_bits)})"
        else:
            glue_note = ""
        self.status_label.setText(
            f"Search: {len(visible_combined)} matching row(s) selected{glue_note}."
        )

    def _run_table_search(self) -> None:
        specs = self._collect_search_criteria()
        if specs is None:
            return
        self._search_job_gen = int(getattr(self, "_search_job_gen", 0)) + 1
        if not specs:
            self.clear_table_selection()
            self.status_label.setText("Search: empty query; selection cleared.")
            return

        n_rows = self._table_model.rowCount()
        thresh = int(load_config().substructure_async_rows)
        async_needed = n_rows >= thresh and any(s.substructure for s in specs)
        row_sets: list[set[int] | None] = [None] * len(specs)
        group_queries: list = []
        for i, spec in enumerate(specs):
            if spec.substructure:
                or_patterns = self._compile_search_substructure_groups(spec.term_groups)
                if or_patterns is None:
                    return
                if not or_patterns:
                    row_sets[i] = set()
                    continue
                if not async_needed:
                    found = self._find_rows_substructure(spec.term_groups)
                    if found is None:
                        return
                    row_sets[i] = set(found)
                    continue
                targets = self._substructure_filter_targets("Structure")
                group_queries.append((str(i), "Structure", targets, or_patterns))
            else:
                row_sets[i] = set(
                    self._find_rows_text(
                        spec.col,
                        spec.query,
                        partial=spec.partial,
                        case_sensitive=spec.case_sensitive,
                    )
                )

        if not group_queries:
            self._apply_table_search_results(specs, [s or set() for s in row_sets])
            return

        sigs = getattr(self, "_search_substructure_signals", None)
        pool = getattr(self, "threadpool", None)
        if sigs is None or pool is None:
            for i, spec in enumerate(specs):
                if row_sets[i] is None and spec.substructure:
                    found = self._find_rows_substructure(spec.term_groups)
                    if found is None:
                        return
                    row_sets[i] = set(found)
            self._apply_table_search_results(specs, [s or set() for s in row_sets])
            return

        gen = int(self._search_job_gen)
        self._search_pending = {
            "gen": gen,
            "specs": specs,
            "row_sets": row_sets,
            "labels": [int(q[0]) for q in group_queries],
        }
        self.status_label.setText(f"Search: scanning substructure ({n_rows:,} rows)…")
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("Searching substructure", n_rows)
        pool.start(
            SubstructureFilterWorker(
                gen,
                signals=sigs,
                group_queries=group_queries,
                progress_state=getattr(self, "_tool_progress_state", None),
                worker_signals=getattr(self, "signals", None),
            )
        )

    def _on_search_substructure_finished(self, job_gen: int, matched) -> None:
        pending = getattr(self, "_search_pending", None)
        if not pending or int(job_gen) != int(pending.get("gen", -1)):
            return
        if int(job_gen) != int(getattr(self, "_search_job_gen", -1)):
            return
        self._search_pending = None
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Searching substructure", status_message=None)
        specs: list[_SearchCriterionSpec] = list(pending["specs"])
        row_sets: list[set[int] | None] = list(pending["row_sets"])
        labels: list[int] = list(pending.get("labels") or [])
        oid_sets: dict[int, frozenset[int]] = {}
        if isinstance(matched, list):
            for item in matched:
                if not item or len(item) < 3:
                    continue
                try:
                    oid_sets[int(item[0])] = frozenset(item[2] or ())
                except (TypeError, ValueError):
                    continue
        for idx in labels:
            if 0 <= idx < len(row_sets) and row_sets[idx] is None:
                oids = oid_sets.get(idx, frozenset())
                rows: set[int] = set()
                for oid in oids:
                    rr = self._table_model.logical_row_for_oid(int(oid))
                    if rr >= 0:
                        rows.add(rr)
                row_sets[idx] = rows
        self._apply_table_search_results(specs, [s or set() for s in row_sets])

    def _on_search_substructure_failed(self, job_gen: int, msg: str) -> None:
        pending = getattr(self, "_search_pending", None)
        if not pending or int(job_gen) != int(pending.get("gen", -1)):
            return
        self._search_pending = None
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Searching substructure", status_message=None)
        self.status_label.setText(f"Search failed: {msg}")

    def collect_table_search_session(self) -> dict | None:
        """Serialize the Search panel when it is open or any criterion has a query."""
        rows = list(getattr(self, "_search_criterion_rows", None) or [])
        panel = getattr(self, "_search_panel", None)
        visible = bool(panel is not None and not panel.isHidden())
        criteria: list[dict] = []
        has_query = False
        for i, row in enumerate(rows):
            query = str(row.query_edit.text() or "")
            if query.strip():
                has_query = True
            col = row.col_combo.currentData()
            header = ""
            if isinstance(col, int) and 0 <= col < len(self.headers):
                header = str(self.headers[col])
            criteria.append(
                {
                    "column": header,
                    "query": query,
                    "glue": row.glue(),
                    "partial": bool(row.partial_cb.isChecked()),
                    "case_sensitive": bool(row.case_cb.isChecked()),
                }
            )
        if not visible and not has_query:
            return None
        return {"visible": visible, "criteria": criteria}

    def _reset_table_search_panel(self) -> None:
        """Collapse Search to one empty hidden row (session New / Open)."""
        rows = list(getattr(self, "_search_criterion_rows", None) or [])
        for row in rows[1:]:
            self._remove_search_criterion_row(row)
        if getattr(self, "_search_criterion_rows", None):
            row = self._search_criterion_rows[0]
            row.query_edit.clear()
            row.partial_cb.setChecked(True)
            row.case_cb.setChecked(False)
            row.glue_combo.setCurrentIndex(0)
        self._sync_search_row_chrome()
        panel = getattr(self, "_search_panel", None)
        if panel is not None:
            panel.setVisible(False)
        self._session_search_want_visible = False
        self._session_search_rerun = False

    def restore_table_search_session(self, payload: object | None) -> None:
        """Rebuild Search rows from a session document; keep the panel hidden until reveal."""
        self._reset_table_search_panel()
        if not isinstance(payload, dict):
            return
        raw_criteria = payload.get("criteria")
        criteria = raw_criteria if isinstance(raw_criteria, list) else []
        restored_any = False
        for i, spec in enumerate(criteria):
            if not isinstance(spec, dict):
                continue
            row = (
                self._search_criterion_rows[0]
                if i == 0 and self._search_criterion_rows
                else self._add_search_criterion_row()
            )
            header = str(spec.get("column") or "")
            self._populate_search_row_columns(row, preferred_header=header)
            row.query_edit.setText(str(spec.get("query") or ""))
            row.partial_cb.setChecked(bool(spec.get("partial", True)))
            row.case_cb.setChecked(bool(spec.get("case_sensitive", False)))
            glue = spec.get("glue")
            if glue in ("and", "or", "not"):
                idx = row.glue_combo.findData(glue)
                if idx >= 0:
                    row.glue_combo.setCurrentIndex(idx)
            restored_any = True
        if restored_any:
            self._populate_table_search_columns_combo()
        has_query = any(
            (row.query_edit.text() or "").strip()
            for row in (getattr(self, "_search_criterion_rows", None) or [])
        )
        visible = bool(payload.get("visible", False))
        self._session_search_want_visible = visible
        self._session_search_rerun = has_query
        panel = getattr(self, "_search_panel", None)
        if panel is not None:
            panel.setVisible(False)

    def _rerun_restored_table_search(self) -> None:
        """Re-apply saved queries after the table is visible so the selection matches."""
        if not getattr(self, "_session_search_rerun", False):
            return
        self._session_search_rerun = False
        self._run_table_search()
