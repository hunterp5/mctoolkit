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

"""Core-based decomposition (Chemistry → Structure Decomposition → Core-Based Decomposition)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from PyQt5.QtCore import QRunnable
from rdkit import Chem
from rdkit.Chem import rdRGroupDecomposition

from .signals import WorkerSignals

logger = logging.getLogger(__name__)


def _rgroup_decomp_failure_message(exc: BaseException) -> str:
    """Turn RDKit failures into short UI text; detect known invariant / core errors."""
    msg = (str(exc) or "").strip()
    low = msg.lower()
    if "could not prepare" in low and "core" in low:
        return (
            "RDKit could not prepare the core for core-based decomposition. "
            "Check that dummy atoms ([*], [1*], …) label attachment sites correctly and that "
            "the pattern is valid SMARTS (or try a simpler core)."
        )
    if "invariant violation" in low and "core" in low:
        return (
            "Core-based decomposition failed while processing the core. "
            "Verify the core SMARTS/SMILES and R-group dummy labels match your row structures."
        )
    return msg or "Core-based decomposition failed."


def _rg_col_sort_key(k: str) -> tuple:
    if k == "Core":
        return (0, 0, k)
    if k.startswith("R") and len(k) > 1 and k[1:].isdigit():
        return (1, int(k[1:]), k)
    return (2, 0, k)


def _collect_rg_columns(rows: list[dict[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for r in rows:
        keys.update(r.keys())
    return sorted(keys, key=_rg_col_sort_key)


def _assemble_table_rows(
    oids: list[int],
    rg_rows: list[dict[str, Any]],
    unmatched: list[int],
    col_keys: list[str],
    prefix: str,
) -> list[tuple[int, dict[str, str]]]:
    """Align RDKit row output to table oids; unmatched rows get N/A cells."""
    um = set(int(i) for i in unmatched)
    named = [f"{prefix}_{k}" for k in col_keys]
    blank = {h: "N/A" for h in named}
    out: list[tuple[int, dict[str, str]]] = []
    ri = 0
    for i, oid in enumerate(oids):
        if i in um:
            out.append((int(oid), dict(blank)))
        else:
            src = rg_rows[ri] if ri < len(rg_rows) else {}
            ri += 1
            row = {f"{prefix}_{k}": str(src.get(k, "N/A")) for k in col_keys}
            out.append((int(oid), row))
    return out


class RGroupDecompositionWorker(QRunnable):
    """Run :func:`rdRGroupDecomposition.RGroupDecompose` off the GUI thread."""

    def __init__(
        self,
        data: list[tuple[int, Chem.Mol]],
        core_smarts: str,
        col_prefix: str,
        only_match_at_r_groups: bool,
        remove_h_post_match: bool,
        matching: str,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.data = data
        self.core_smarts = (core_smarts or "").strip()
        self.col_prefix = (col_prefix or "RGD").strip() or "RGD"
        self.only_match_at_r_groups = bool(only_match_at_r_groups)
        self.remove_h_post_match = bool(remove_h_post_match)
        self.matching = (matching or "greedy").strip().lower()
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        ev = self.cancel_event
        if ev is not None and ev.is_set():
            return
        core = Chem.MolFromSmarts(self.core_smarts)
        if core is None:
            core = Chem.MolFromSmiles(self.core_smarts)
        if core is None:
            try:
                self.signals.rgroup_decomp_failed.emit("Core is not valid SMARTS or SMILES.")
            except Exception:
                pass
            return

        from ..platform_support.tool_progress import report_tool_progress

        oids = [int(o) for o, _ in self.data]
        mols = [m for _, m in self.data]
        tot = max(len(mols), 1)
        report_tool_progress(
            message="Core-based decomposition",
            done=0,
            total=tot,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )

        p = rdRGroupDecomposition.RGroupDecompositionParameters()
        p.onlyMatchAtRGroups = self.only_match_at_r_groups
        p.removeHydrogensPostMatch = self.remove_h_post_match
        if self.matching == "exhaustive":
            p.matchingStrategy = rdRGroupDecomposition.RGroupMatching.Exhaustive
        else:
            p.matchingStrategy = rdRGroupDecomposition.RGroupMatching.Greedy

        if ev is not None and ev.is_set():
            return
        try:
            rows, unmatched = rdRGroupDecomposition.RGroupDecompose(
                [core], mols, asSmiles=True, asRows=True, options=p
            )
            unmatched = list(unmatched) if unmatched is not None else []
        except Exception as e:
            user_msg = _rgroup_decomp_failure_message(e)
            el = str(e).lower()
            if isinstance(e, RuntimeError) and (
                "could not prepare" in el or ("invariant violation" in el and "core" in el)
            ):
                logger.warning("RGroupDecompose: %s", user_msg)
            else:
                logger.exception("RGroupDecompose failed")
            try:
                self.signals.rgroup_decomp_failed.emit(user_msg)
            except Exception:
                pass
            return

        if not rows:
            try:
                self.signals.rgroup_decomp_failed.emit(
                    "No rows matched the core (check labels and attachment-point dummies)."
                )
            except Exception:
                pass
            return

        col_keys = _collect_rg_columns(rows)
        table_rows = _assemble_table_rows(oids, rows, unmatched, col_keys, self.col_prefix)
        headers = [f"{self.col_prefix}_{k}" for k in col_keys]
        report_tool_progress(
            message="Core-based decomposition",
            done=tot,
            total=tot,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        try:
            self.signals.rgroup_decomp_finished.emit(table_rows, headers)
        except Exception:
            logger.warning("rgroup_decomp_finished emit failed", exc_info=True)
