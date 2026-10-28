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

"""Fetch SQL rows and parse SMILES off the GUI thread."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from ..platform_support.exception_policy import log_swallowed_exception
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress

logger = logging.getLogger(__name__)


def _safe_emit(obj: QObject | None, emitter_name: str, *args) -> None:
    if obj is None:
        return
    try:
        if sip.isdeleted(obj):
            return
    except Exception:
        return
    try:
        getattr(obj, emitter_name).emit(*args)
    except RuntimeError:
        pass


def _redact_url(text: str) -> str:
    from ..chem.molecule_conversion import redact_sqlalchemy_url

    return redact_sqlalchemy_url(text)


def mol_blob_from_smiles(smiles: str) -> bytes | None:
    """Parse *smiles* to an RDKit pickle, or ``None`` when the string is invalid."""
    smi = (smiles or "").strip()
    if not smi:
        return None
    try:
        mol = Chem.MolFromSmiles(smi)
    except Exception:
        return None
    if mol is None:
        return None
    try:
        blob = mol.ToBinary()
    except Exception:
        return None
    return bytes(blob) if blob else None


def cells_from_sql_mapping(cols: list[str], mapping: Any) -> dict[str, str]:
    """Stringify one SQLAlchemy row mapping into table cells."""
    row_cells: dict[str, str] = {}
    for c in cols:
        v = mapping.get(c)
        row_cells[c] = "" if v is None else str(v)
    return row_cells


@dataclass
class SqlLoadParseResult:
    """One page of prepared table rows, or a finished summary with empty rows."""

    columns: list[str] = field(default_factory=list)
    prepared_rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    mol_blobs: dict[int, bytes] = field(default_factory=dict)
    next_oid: int = 0
    rows_hit_limit: bool = False
    limit_eff: int = 0
    smiles_column: str | None = None
    is_first: bool = False
    is_last: bool = False

    @property
    def mols(self) -> dict[int, Any]:
        out: dict[int, Any] = {}
        for oid, blob in self.mol_blobs.items():
            try:
                mol = Chem.Mol(blob)
            except Exception:
                continue
            if mol is not None:
                out[int(oid)] = mol
        return out


class SqlLoadSignals(QObject):
    """Signals for SQL load workers (owned on the GUI thread)."""

    chunk = pyqtSignal(object)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class SqlLoadWorker(QRunnable):
    """Stream a SQL result set and parse SMILES away from the GUI thread."""

    def __init__(
        self,
        *,
        url: str,
        engine_kwargs: dict,
        sql: str,
        page_size: int,
        limit_eff: int,
        apply_limit: bool,
        signals: SqlLoadSignals,
        generation: int,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
        read_only: bool = True,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.url = str(url)
        self.engine_kwargs = dict(engine_kwargs or {})
        self.read_only = bool(read_only)
        self.sql = str(sql)
        self.page_size = max(1, int(page_size))
        self.limit_eff = max(0, int(limit_eff))
        self.apply_limit = bool(apply_limit)
        self.signals = signals
        self.generation = int(generation)
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def _emit_progress(self, done: int, total: int) -> None:
        report_tool_progress(
            message="SQL load: fetching…",
            done=int(done),
            total=max(1, int(total)),
            progress_state=self.progress_state,
            throttle=self._progress_throttle,
        )

    def run(self) -> None:
        if self._cancelled():
            _safe_emit(self.signals, "failed", "Cancelled.")
            return
        try:
            from sqlalchemy import create_engine, text
        except Exception as exc:
            _safe_emit(
                self.signals,
                "failed",
                "sqlalchemy is required for SQL loading. Install requirements-core.txt "
                f"(or requirements.txt). ({exc})",
            )
            return

        eng = None
        try:
            eng = create_engine(self.url, **self.engine_kwargs)
            if self.read_only:
                from ..services.sql_load_policy import install_read_only_guards

                install_read_only_guards(eng, self.url)
            self.url = _redact_url(self.url)
            with eng.connect() as conn:
                if self._cancelled():
                    _safe_emit(self.signals, "failed", "Cancelled.")
                    return
                rs = conn.execution_options(stream_results=True).execute(text(self.sql))
                cols = [str(c) for c in rs.keys()]
                if not cols:
                    rs.close()
                    _safe_emit(self.signals, "failed", "Query returned 0 rows.")
                    return

                smiles_col = next((c for c in cols if c.lower() == "smiles"), None)
                oid = 0
                rows_hit_limit = False
                emitted_any = False
                progress_total = self.limit_eff if self.apply_limit and self.limit_eff > 0 else 0
                self._emit_progress(0, progress_total if progress_total > 0 else 1)

                while True:
                    if self._cancelled():
                        try:
                            rs.close()
                        except Exception:
                            log_swallowed_exception(logger, "SQL load cancel: close result")
                        _safe_emit(self.signals, "failed", "Cancelled.")
                        return
                    recs = list(rs.fetchmany(self.page_size) or ())
                    if not recs:
                        break
                    # Drivers (notably SQLite) may return more than page_size; emit
                    # fixed windows so the GUI never waits on the full result.
                    for start in range(0, len(recs), self.page_size):
                        if self._cancelled():
                            _safe_emit(self.signals, "failed", "Cancelled.")
                            return
                        page = recs[start : start + self.page_size]
                        prepared: list[tuple[int, dict[str, str]]] = []
                        mol_blobs: dict[int, bytes] = {}
                        for rec in page:
                            row_cells = cells_from_sql_mapping(cols, rec._mapping)
                            prepared.append((oid, row_cells))
                            if smiles_col is not None:
                                blob = mol_blob_from_smiles(row_cells.get(smiles_col, "") or "")
                                if blob:
                                    mol_blobs[oid] = blob
                            oid += 1
                            if self.apply_limit and self.limit_eff and oid >= self.limit_eff:
                                rows_hit_limit = True
                                break
                        _safe_emit(
                            self.signals,
                            "chunk",
                            SqlLoadParseResult(
                                columns=cols,
                                prepared_rows=prepared,
                                mol_blobs=mol_blobs,
                                next_oid=oid,
                                rows_hit_limit=rows_hit_limit,
                                limit_eff=self.limit_eff,
                                smiles_column=smiles_col,
                                is_first=not emitted_any,
                            ),
                        )
                        emitted_any = True
                        total_ui = progress_total if progress_total > 0 else max(oid, 1)
                        self._emit_progress(oid, total_ui)
                        if rows_hit_limit:
                            break
                    if rows_hit_limit:
                        break
                rs.close()

            if oid <= 0:
                _safe_emit(self.signals, "failed", "Query returned 0 rows.")
                return
            if self._cancelled():
                _safe_emit(self.signals, "failed", "Cancelled.")
                return

            self._emit_progress(oid, oid)
            _safe_emit(
                self.signals,
                "finished",
                SqlLoadParseResult(
                    columns=cols,
                    next_oid=oid,
                    rows_hit_limit=rows_hit_limit,
                    limit_eff=self.limit_eff,
                    smiles_column=smiles_col,
                    is_last=True,
                ),
            )
        except Exception as exc:
            message = _redact_url(str(exc) or exc.__class__.__name__)
            logger.error("SQL load failed: %s", message)
            _safe_emit(self.signals, "failed", message)
        finally:
            if eng is not None:
                try:
                    eng.dispose()
                except Exception:
                    log_swallowed_exception(logger, "SQL load engine dispose failed")
