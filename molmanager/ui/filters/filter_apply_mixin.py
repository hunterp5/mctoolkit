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

"""SQLite/chunked/sync filter apply for the compound table."""

from __future__ import annotations

import logging
from contextlib import nullcontext

from ...platform_support.config import MolManagerConfig, load_config
from ...table.filter_compute import build_sqlite_where, fetch_matching_oids
from ...services.filter_config import cfg_column
from ...chem.molecule_conversion import safe_float
from ... import workers
from ..background_jobs import register_background_job, unregister_background_job
from .cards import CategoryFilterCard, FilterCard, SubstructureFilterCard, TextFilterCard

logger = logging.getLogger(__name__)


class FilterApplyMixin:
    """Route filter apply through SQL pushdown, chunks, or a sync pass."""

    def _filterable_data_column_names(self) -> list[str]:
        return [h for h in self.headers[2:] if h and not self._table_model.is_pixmap_data_column(h)]

    def _filter_specs_for_sqlite(self) -> list[dict]:
        """Serializable filter specs for SQL pushdown (substructure cards may be present but disabled)."""
        specs: list[dict] = []
        for f in self.filters:
            if isinstance(f, SubstructureFilterCard):
                specs.append({"kind": "substructure", "enabled": f.filter_enabled()})
                continue
            if isinstance(f, CategoryFilterCard):
                specs.append(
                    {
                        "kind": "category",
                        "enabled": f.filter_enabled(),
                        "column": f.column_name(),
                        "values": sorted(f.checked_values()),
                    }
                )
                continue
            if isinstance(f, FilterCard):
                cfg = f.get_cfg()
                specs.append(
                    {
                        "kind": "numeric",
                        "enabled": bool(cfg.get("enabled", True)),
                        "column": cfg_column(cfg),
                        "min": float(cfg.get("min", 0.0)),
                        "max": float(cfg.get("max", 0.0)),
                        "inverted": bool(cfg.get("inverted", False)),
                    }
                )
                continue
            if isinstance(f, TextFilterCard):
                cfg = f.get_cfg()
                specs.append(
                    {
                        "kind": "text",
                        "enabled": bool(cfg.get("enabled", True)),
                        "column": cfg_column(cfg),
                        "text": str(cfg.get("text", "") or ""),
                        "case_sensitive": bool(cfg.get("case_sensitive", False)),
                        "partial_match": bool(cfg.get("partial_match", True)),
                        "inverted": bool(cfg.get("inverted", False)),
                    }
                )
                continue
            specs.append({"kind": "unknown", "enabled": True})
        return specs

    def _sqlite_filter_where_clause(self) -> tuple[str, tuple] | None:
        """Try SQL pushdown for simple enabled filters; return None when unsupported."""
        ensure_sqlite = getattr(self, "_ensure_sqlite_store_current", None)
        if callable(ensure_sqlite) and not ensure_sqlite():
            return None
        return build_sqlite_where(self._filter_specs_for_sqlite(), headers=self.headers)

    def _sqlite_filter_matched_oids(self) -> frozenset[int] | None:
        """Try SQL pushdown for simple enabled filters; return None when unsupported."""
        where = self._sqlite_filter_where_clause()
        if where is None:
            return None
        store = getattr(self, "_sqlite_store", None)
        if store is None:
            return None
        where_sql, args = where
        cfg = load_config()
        page = max(1000, int(cfg.sqlite_backend_page_size))
        return fetch_matching_oids(
            store.db_path,
            where_sql,
            args,
            page_size=page,
        )

    def _filters_include_substructure(self) -> bool:
        return any(
            isinstance(f, SubstructureFilterCard) and f.filter_enabled() for f in self.filters
        )

    def apply_filters(self) -> None:
        """Coalesce expensive filter passes on large tables (slider drags)."""
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        n = self._table_model.rowCount()
        cfg = load_config()
        # Substructure matching runs RDKit per row — debounce earlier and slightly longer while typing SMARTS.
        if self._filters_include_substructure():
            threshold, delay_ms = (
                cfg.filter_debounce_substructure_rows,
                cfg.filter_debounce_substructure_ms,
            )
        else:
            threshold, delay_ms = cfg.filter_debounce_default_rows, cfg.filter_debounce_default_ms
        if n < threshold:
            self._apply_filters_impl(cfg)
            return
        self._apply_filters_timer.stop()
        self._apply_filters_timer.start(delay_ms)

    def _invalidate_substructure_async_jobs(self) -> None:
        """Drop in-flight substructure jobs (completion handler will no-op)."""
        self._substructure_job_gen = int(getattr(self, "_substructure_job_gen", 0)) + 1
        self._substructure_job_smarts = None
        self._substructure_job_source = None
        self._substructure_job_queries = None

    def _invalidate_filter_jobs(self) -> None:
        """Drop in-flight SQL/chunked filter jobs (completion handler will no-op)."""
        self._filter_job_gen = int(getattr(self, "_filter_job_gen", 0)) + 1
        self._filter_pending_substructure = None
        timer = getattr(self, "_chunked_filter_timer", None)
        if timer is not None:
            timer.stop()
        self._chunked_filter_state = None
        self._unregister_filter_background_job()

    def _unregister_filter_background_job(self, job_gen: int | None = None) -> None:
        job_id = getattr(self, "_filter_bg_job_id", None)
        if job_id is None:
            return
        if job_gen is not None and job_id != f"filter-{job_gen}":
            return
        unregister_background_job(self, job_id)
        self._filter_bg_job_id = None

    def _cancel_async_filter_apply(self) -> None:
        """Processes Cancel: discard the in-flight SQLite/chunked filter job."""
        job_id = getattr(self, "_filter_bg_job_id", None)
        self._invalidate_filter_jobs()
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Applying filters", status_message="Filter cancelled.", job_id=job_id)

    def _on_filter_apply_finished(self, job_gen: int, matched) -> None:
        job_id = getattr(self, "_filter_bg_job_id", None)
        self._unregister_filter_background_job(job_gen)
        if job_gen != getattr(self, "_filter_job_gen", 0):
            return
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Applying filters", status_message=None, job_id=job_id)
        sub = getattr(self, "_filter_pending_substructure", None)
        self._filter_pending_substructure = None
        oids = matched if isinstance(matched, frozenset) else frozenset()
        self._apply_filters_impl_sync(sub, sqlite_oids=oids)

    def _on_filter_apply_failed(self, job_gen: int, msg: str) -> None:
        job_id = getattr(self, "_filter_bg_job_id", None)
        self._unregister_filter_background_job(job_gen)
        if job_gen != getattr(self, "_filter_job_gen", 0):
            return
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Applying filters", status_message=None, job_id=job_id)
        logger.warning("Filter apply job failed: %s", msg)
        pending = getattr(self, "_filter_pending_substructure", None)
        self._filter_pending_substructure = None
        self._start_chunked_filter_apply(pending)

    def _start_async_sqlite_filter_apply(
        self,
        substructure_matches: tuple[str, frozenset] | None,
    ) -> None:
        where = self._sqlite_filter_where_clause()
        store = getattr(self, "_sqlite_store", None)
        if where is None or store is None:
            self._start_chunked_filter_apply(substructure_matches)
            return
        where_sql, args = where
        self._invalidate_filter_jobs()
        gen = self._filter_job_gen
        self._filter_pending_substructure = substructure_matches
        n_rows = self._table_model.rowCount()
        cfg = load_config()
        sigs = getattr(self, "_filter_apply_signals", None)
        if sigs is None:
            self._apply_filters_impl_sync(substructure_matches)
            return
        job_id = f"filter-{gen}"
        self._filter_bg_job_id = job_id
        register_background_job(
            self,
            job_id,
            f"Applying filters ({n_rows:,} rows)",
            cancel=self._cancel_async_filter_apply,
        )
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("Applying filters", n_rows, job_id=job_id)
        worker_signals = getattr(self, "signals", None)
        progress_state = getattr(self, "_tool_progress_state", None)
        bind = getattr(progress_state, "bind", None)
        if callable(bind):
            progress_state = bind(job_id)
        self.threadpool.start(
            workers.FilterApplyWorker(
                gen,
                str(store.db_path),
                where_sql,
                args,
                max(1000, int(cfg.sqlite_backend_page_size)),
                sigs,
                progress_state=progress_state,
                worker_signals=worker_signals,
            )
        )

    def _start_chunked_filter_apply(
        self,
        substructure_matches: tuple[str, frozenset] | None,
    ) -> None:
        self._invalidate_filter_jobs()
        gen = self._filter_job_gen
        n_rows = self._table_model.rowCount()
        self._chunked_filter_state = {
            "job_gen": gen,
            "row": 0,
            "n_rows": n_rows,
            "visible_oids": set(),
            "substructure_matches": substructure_matches,
            "sqlite_oids": self._sqlite_filter_matched_oids(),
        }
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("Applying filters", n_rows)
        timer = getattr(self, "_chunked_filter_timer", None)
        if timer is None:
            self._apply_filters_impl_sync(substructure_matches)
            return
        timer.start(0)

    def _chunked_filter_step(self) -> None:
        state = getattr(self, "_chunked_filter_state", None)
        if not state:
            return
        if state["job_gen"] != getattr(self, "_filter_job_gen", 0):
            state.clear()
            self._chunked_filter_state = None
            return
        cfg = load_config()
        chunk = max(64, int(cfg.filter_chunk_rows))
        n_rows = int(state["n_rows"])
        start = int(state["row"])
        end = min(n_rows, start + chunk)
        override_smarts = None
        override_source = None
        override_oids = None
        overrides: list[tuple[str, str | None, frozenset]] = []
        sub = state.get("substructure_matches")
        if sub:
            overrides = self._normalize_substructure_overrides(sub)
            if len(overrides) == 1:
                override_smarts, override_source, override_oids = overrides[0]
        sqlite_oids = state.get("sqlite_oids")
        h_map = {h: i for i, h in enumerate(self.headers)}
        visible_oids: set[int] = state["visible_oids"]
        for r in range(start, end):
            hide = False
            oid = self._table_model.row_oid(r)
            if sqlite_oids is not None:
                hide = oid not in sqlite_oids
            for f in [] if sqlite_oids is not None else self.filters:
                if isinstance(f, SubstructureFilterCard):
                    if not f.filter_enabled():
                        continue
                    inv = f.filter_inverted()
                    ov_oids = self._override_for_substructure_card(f, overrides)
                    if ov_oids is not None:
                        matched = oid in ov_oids
                        if inv:
                            if matched:
                                hide = True
                                break
                        elif not matched:
                            hide = True
                            break
                        continue
                    mol = self._mol_for_substructure_filter_row(r, f.structure_source())
                    matched = f.match_mol(mol)
                    if inv:
                        if matched:
                            hide = True
                            break
                    elif not matched:
                        hide = True
                        break
                    continue
                if isinstance(f, TextFilterCard):
                    if not f.filter_enabled():
                        continue
                    if not f.row_matches(r):
                        hide = True
                        break
                    continue
                if isinstance(f, CategoryFilterCard):
                    if not f.filter_enabled():
                        continue
                    if not f.row_matches(r):
                        hide = True
                        break
                    continue
                if not isinstance(f, FilterCard):
                    continue
                fcfg = f.get_cfg()
                if not fcfg.get("enabled", True):
                    continue
                prop = cfg_column(fcfg)
                if not prop or prop not in h_map:
                    continue
                v = safe_float(self._table_model.value_for_header(r, prop))
                if v is None:
                    hide = True
                    break
                lo, hi = fcfg["min"], fcfg["max"]
                inside = lo <= v <= hi
                if fcfg.get("inverted", False):
                    if inside:
                        hide = True
                        break
                elif not inside:
                    hide = True
                    break
            if not hide:
                visible_oids.add(oid)
        state["row"] = end
        state["visible_oids"] = visible_oids
        on_progress = getattr(self, "_on_tool_progress", None)
        if callable(on_progress):
            on_progress("Applying filters…", end, n_rows)
        if end >= n_rows:
            self._chunked_filter_state = None
            finish = getattr(self, "_finish_tool_progress", None)
            if callable(finish):
                finish("Applying filters", status_message=None)
            if sqlite_oids is not None and overrides:
                visible_oids = self._apply_substructure_overrides_to_visible(
                    frozenset(sqlite_oids),
                    overrides,
                )
            elif (
                overrides
                and sqlite_oids is None
                and len([f for f in self.filters if f.filter_enabled()])
                == len(
                    [
                        f
                        for f in self.filters
                        if isinstance(f, SubstructureFilterCard) and f.filter_enabled()
                    ]
                )
            ):
                # Only substructure filters: combine override OID sets.
                all_oids = set(self.mols)
                visible_oids = self._apply_substructure_overrides_to_visible(all_oids, overrides)
            elif (
                override_oids is not None
                and override_smarts is not None
                and sqlite_oids is None
                and len([f for f in self.filters if f.filter_enabled()]) == 1
            ):
                for f in self.filters:
                    if isinstance(f, SubstructureFilterCard) and f.filter_enabled():
                        if not self._substructure_override_matches_card(
                            f, override_smarts, override_source
                        ):
                            break
                        inv = f.filter_inverted()
                        visible_oids = (
                            {oid for oid in self.mols if oid not in override_oids}
                            if inv
                            else set(override_oids)
                        )
                        break
            self._finalize_filter_apply(set(visible_oids), n_rows)
            return
        timer = getattr(self, "_chunked_filter_timer", None)
        if timer is not None:
            timer.start(0)

    def _finalize_filter_apply(self, visible_oids: set[int] | frozenset[int], n_rows: int) -> None:
        proxy = self._filter_proxy_model
        table = getattr(self, "table", None)
        oids_fs = visible_oids if isinstance(visible_oids, frozenset) else frozenset(visible_oids)
        if table is not None:
            table.setUpdatesEnabled(False)
        try:
            visibility_changed = proxy.set_visible_oids(oids_fs)
        finally:
            if table is not None:
                table.setUpdatesEnabled(True)
        if visibility_changed:
            invalidate = getattr(self, "_invalidate_visible_source_rows_cache", None)
            if callable(invalidate):
                invalidate()
        invalid_smarts_msg = None
        for f in self.filters:
            if isinstance(f, SubstructureFilterCard):
                sm = (f.smarts_edit.text() or "").strip()
                if sm and f._compiled_query() is None:
                    invalid_smarts_msg = "Substructure filter: invalid SMARTS."
                    break
        vis = len(oids_fs)
        if invalid_smarts_msg:
            self.status_label.setText(invalid_smarts_msg)
        else:
            self.status_label.setText(f"Showing {vis} / {len(self.mols)} molecules")
        if visibility_changed:
            schedule_replot = getattr(self, "_schedule_active_plots_replot", None)
            if callable(schedule_replot):
                schedule_replot(force=True)
        self._finish_macro_filter_wait()

    def _finish_macro_filter_wait(self) -> None:
        """Release a macro step that is waiting on this filter pass."""
        callback = getattr(self, "_macro_filter_done", None)
        if callback is None:
            return
        self._macro_filter_done = None
        callback()

    def _route_filter_apply(self, substructure_matches: tuple | None) -> None:
        """Pick sync, async SQLite, or chunked apply based on table size and filter mix."""
        cfg = load_config()
        n_rows = self._table_model.rowCount()
        if n_rows >= cfg.filter_async_min_rows:
            where = self._sqlite_filter_where_clause()
            if where is not None:
                self._start_async_sqlite_filter_apply(substructure_matches)
                return
            self._start_chunked_filter_apply(substructure_matches)
            return
        self._apply_filters_impl_sync(substructure_matches)

    def _apply_filters_impl_sync(
        self,
        substructure_matches: tuple | None,
        *,
        sqlite_oids: frozenset[int] | None = None,
    ) -> None:
        """Apply all filters on the UI thread.

        If ``substructure_matches`` is ``(smarts, structure_source, oids)``, use that
        for the matching SMARTS card instead of re-matching on the UI thread.
        """
        n_rows = self._table_model.rowCount()
        proxy = self._filter_proxy_model
        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        if not self.filters:
            with scope("filters.apply_sync"):
                visibility_changed = proxy.set_visible_oids(None)
            if visibility_changed:
                invalidate = getattr(self, "_invalidate_visible_source_rows_cache", None)
                if callable(invalidate):
                    invalidate()
            self.status_label.setText(f"Showing {n_rows} / {len(self.mols)} molecules")
            if visibility_changed:
                schedule_replot = getattr(self, "_schedule_active_plots_replot", None)
                if callable(schedule_replot):
                    schedule_replot(force=True)
            self._finish_macro_filter_wait()
            return

        overrides = self._normalize_substructure_overrides(substructure_matches)
        override_smarts, override_source, override_oids = (None, None, None)
        if len(overrides) == 1:
            override_smarts, override_source, override_oids = overrides[0]
        if sqlite_oids is None:
            sqlite_oids = self._sqlite_filter_matched_oids()

        h_map = {h: i for i, h in enumerate(self.headers)}
        vis = 0
        visible_oids: set[int] = set()
        table = getattr(self, "table", None)
        if table is not None:
            table.setUpdatesEnabled(False)
        try:
            with scope("filters.apply_sync"):
                if sqlite_oids is not None and not overrides:
                    visible_oids = sqlite_oids
                    vis = len(visible_oids)
                elif sqlite_oids is not None and overrides:
                    visible_oids = self._apply_substructure_overrides_to_visible(
                        sqlite_oids,
                        overrides,
                    )
                    vis = len(visible_oids)
                elif (
                    overrides
                    and sqlite_oids is None
                    and len([f for f in self.filters if f.filter_enabled()])
                    == len(
                        [
                            f
                            for f in self.filters
                            if isinstance(f, SubstructureFilterCard) and f.filter_enabled()
                        ]
                    )
                ):
                    visible_oids = self._apply_substructure_overrides_to_visible(
                        set(self.mols), overrides
                    )
                    vis = len(visible_oids)
                elif (
                    override_oids is not None
                    and override_smarts is not None
                    and sqlite_oids is None
                    and len([f for f in self.filters if f.filter_enabled()]) == 1
                ):
                    for f in self.filters:
                        if isinstance(f, SubstructureFilterCard) and f.filter_enabled():
                            if not self._substructure_override_matches_card(
                                f, override_smarts, override_source
                            ):
                                break
                            inv = f.filter_inverted()
                            visible_oids = (
                                {oid for oid in self.mols if oid not in override_oids}
                                if inv
                                else set(override_oids)
                            )
                            vis = len(visible_oids)
                            break
                else:
                    for r in range(n_rows):
                        hide = False
                        oid = self._table_model.row_oid(r)
                        if sqlite_oids is not None:
                            hide = oid not in sqlite_oids
                        for f in [] if sqlite_oids is not None else self.filters:
                            if isinstance(f, SubstructureFilterCard):
                                if not f.filter_enabled():
                                    continue
                                inv = f.filter_inverted()
                                ov_oids = self._override_for_substructure_card(f, overrides)
                                if ov_oids is not None:
                                    matched = oid in ov_oids
                                    if inv:
                                        if matched:
                                            hide = True
                                            break
                                    elif not matched:
                                        hide = True
                                        break
                                    continue
                                mol = self._mol_for_substructure_filter_row(r, f.structure_source())
                                matched = f.match_mol(mol)
                                if inv:
                                    if matched:
                                        hide = True
                                        break
                                elif not matched:
                                    hide = True
                                    break
                                continue
                            if isinstance(f, TextFilterCard):
                                if not f.filter_enabled():
                                    continue
                                if not f.row_matches(r):
                                    hide = True
                                    break
                                continue
                            if isinstance(f, CategoryFilterCard):
                                if not f.filter_enabled():
                                    continue
                                if not f.row_matches(r):
                                    hide = True
                                    break
                                continue
                            if not isinstance(f, FilterCard):
                                continue
                            cfg = f.get_cfg()
                            if not cfg.get("enabled", True):
                                continue
                            prop = cfg_column(cfg)
                            if not prop or prop not in h_map:
                                continue
                            v = safe_float(self._table_model.value_for_header(r, prop))
                            if v is None:
                                hide = True
                                break
                            lo, hi = cfg["min"], cfg["max"]
                            inside = lo <= v <= hi
                            if cfg.get("inverted", False):
                                if inside:
                                    hide = True
                                    break
                            elif not inside:
                                hide = True
                                break
                        if not hide:
                            visible_oids.add(oid)
                            vis += 1
        finally:
            if table is not None:
                table.setUpdatesEnabled(True)
        self._finalize_filter_apply(visible_oids, n_rows)

    def _apply_filters_impl(self, cfg: MolManagerConfig | None = None) -> None:
        if cfg is None:
            cfg = load_config()
        n_rows = self._table_model.rowCount()
        if self.filters and not self._filters_include_substructure():
            ensure_sqlite = getattr(self, "_ensure_sqlite_store_current", None)
            if callable(ensure_sqlite) and not ensure_sqlite():
                self._sqlite_rebuild_pending_filters = True
                if n_rows >= cfg.filter_async_min_rows:
                    self._invalidate_substructure_async_jobs()
                    self._start_chunked_filter_apply(None)
                    return
                if getattr(self, "_macro_filter_done", None) is not None:
                    self._apply_filters_impl_sync(None)
                    return
                return
        if not self.filters:
            self._invalidate_substructure_async_jobs()
            self._invalidate_filter_jobs()
            self._apply_filters_impl_sync(None)
            return

        ss_cards = [
            f for f in self.filters if isinstance(f, SubstructureFilterCard) and f.filter_enabled()
        ]
        thresh = cfg.substructure_async_rows

        ready: list[tuple[str, str, SubstructureFilterCard]] = []
        for card in ss_cards:
            smarts = (card.smarts_edit.text() or "").strip()
            if smarts and card._compiled_query() is not None:
                ready.append((smarts, card.structure_source(), card))

        if ready and n_rows >= thresh:
            self._invalidate_filter_jobs()
            self._substructure_job_gen = int(getattr(self, "_substructure_job_gen", 0)) + 1
            gen = self._substructure_job_gen
            self._substructure_job_queries = [(s, src) for s, src, _c in ready]
            # Keep legacy attrs for older call sites / debugging.
            self._substructure_job_smarts = ready[0][0]
            self._substructure_job_source = ready[0][1]
            perf = getattr(self, "_perf", None)
            scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
            targets_by_src: dict[str, list] = {}
            queries: list[tuple[str, str, list]] = []
            with scope("filters.substructure_targets"):
                for smarts, src, _card in ready:
                    if src not in targets_by_src:
                        targets_by_src[src] = self._substructure_filter_targets(src)
                    queries.append((smarts, src, targets_by_src[src]))
            sigs = getattr(self, "_substructure_filter_signals", None)
            if sigs is None:
                self._route_filter_apply(None)
                return
            job_id = f"substructure-{gen}"
            self._substructure_bg_job_id = job_id
            register_background_job(
                self,
                job_id,
                f"Substructure filter ({n_rows:,} rows)",
                cancel=self._cancel_substructure_filter_job,
            )
            begin = getattr(self, "_begin_tool_progress", None)
            if callable(begin):
                begin("Filtering substructure", n_rows, job_id=job_id)
            worker_signals = getattr(self, "signals", None)
            progress_state = getattr(self, "_tool_progress_state", None)
            bind = getattr(progress_state, "bind", None)
            if callable(bind):
                progress_state = bind(job_id)
            self.threadpool.start(
                workers.SubstructureFilterWorker(
                    gen,
                    signals=sigs,
                    queries=queries,
                    progress_state=progress_state,
                    worker_signals=worker_signals,
                )
            )
            return

        self._invalidate_substructure_async_jobs()
        self._route_filter_apply(None)
