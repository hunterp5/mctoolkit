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

"""Substructure filter batch worker."""

from __future__ import annotations

import logging

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..chem.molecule_conversion import mol_from_tool_input
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from .signals import SubstructureFilterSignals

logger = logging.getLogger(__name__)


def mol_matches_pattern_groups(
    mol: Chem.Mol | None,
    or_groups: list[list[tuple[Chem.Mol, bool]]],
) -> bool:
    """True when *mol* matches any AND-group of ``(query_mol, negated)`` pairs."""
    if mol is None or not or_groups:
        return False
    for and_patterns in or_groups:
        group_ok = True
        for q, negated in and_patterns:
            try:
                hit = bool(mol.HasSubstructMatch(q))
            except Exception:
                hit = False
            if negated:
                hit = not hit
            if not hit:
                group_ok = False
                break
        if group_ok:
            return True
    return False


class SubstructureFilterWorker(QRunnable):
    """Compute substructure matches off the UI thread.

    Accepts either a single ``(smarts, targets)`` job or ``queries`` as a list of
    ``(smarts, structure_source, targets)``. Always emits
    ``finished(job_gen, results)`` where *results* is
    ``list[(smarts, structure_source, frozenset[oid])]``.
    """

    def __init__(
        self,
        job_gen: int,
        smarts: str | None = None,
        targets: list[tuple[int, Chem.Mol | str | None]] | None = None,
        signals: SubstructureFilterSignals | None = None,
        *,
        queries: list[tuple[str, str, list[tuple[int, Chem.Mol | str | None]]]] | None = None,
        progress_state: ToolProgressState | None = None,
        worker_signals=None,
        group_queries: list[
            tuple[
                str, str, list[tuple[int, Chem.Mol | str | None]], list[list[tuple[Chem.Mol, bool]]]
            ]
        ]
        | None = None,
    ):
        super().__init__()
        self.job_gen = job_gen
        self.group_queries = list(group_queries or [])
        if queries is not None:
            self.queries = [
                (str(s or ""), str(src or "Structure"), list(tgts or []))
                for s, src, tgts in queries
            ]
        elif self.group_queries:
            self.queries = []
        else:
            self.queries = [
                (str(smarts or ""), "Structure", list(targets or [])),
            ]
        self.signals = signals
        self.progress_state = progress_state
        self.worker_signals = worker_signals
        self._progress_throttle = [0, 0.0]

    def run(self):
        try:
            from ..chem.smarts_macropatterns import mol_from_smarts

            results: list[tuple[str, str, frozenset[int]]] = []
            if self.group_queries:
                total_steps = max(
                    1, sum(max(1, len(tgts)) for _q, _src, tgts, _g in self.group_queries)
                )
                done_steps = 0
                for label, source, targets, or_groups in self.group_queries:
                    matched: set[int] = set()
                    if or_groups:
                        for i, (oid, raw_target) in enumerate(targets):
                            try:
                                m = mol_from_tool_input(raw_target)
                                if mol_matches_pattern_groups(m, or_groups):
                                    matched.add(int(oid))
                            except Exception:
                                pass
                            done_steps += 1
                            if (i + 1) % 256 == 0 or i + 1 == len(targets):
                                report_tool_progress(
                                    message="Searching substructure…",
                                    done=done_steps,
                                    total=total_steps,
                                    progress_state=self.progress_state,
                                    signals=self.worker_signals,
                                    throttle=self._progress_throttle,
                                )
                    else:
                        done_steps += max(1, len(targets))
                    results.append(
                        (str(label or ""), str(source or "Structure"), frozenset(matched))
                    )
                if self.signals is not None:
                    self.signals.finished.emit(self.job_gen, results)
                return
            total_steps = max(1, sum(max(1, len(tgts)) for _s, _src, tgts in self.queries))
            done_steps = 0
            for smarts, source, targets in self.queries:
                s = (smarts or "").strip()
                if not s:
                    results.append((smarts, source, frozenset()))
                    done_steps += max(1, len(targets))
                    continue
                q = mol_from_smarts(s)
                if q is None:
                    results.append((smarts, source, frozenset()))
                    done_steps += max(1, len(targets))
                    continue
                matched: set[int] = set()
                for i, (oid, raw_target) in enumerate(targets):
                    try:
                        m = mol_from_tool_input(raw_target)
                        if m is not None and m.HasSubstructMatch(q):
                            matched.add(int(oid))
                    except Exception:
                        pass
                    done_steps += 1
                    if (i + 1) % 256 == 0 or i + 1 == len(targets):
                        report_tool_progress(
                            message="Filtering substructure…",
                            done=done_steps,
                            total=total_steps,
                            progress_state=self.progress_state,
                            signals=self.worker_signals,
                            throttle=self._progress_throttle,
                        )
                results.append((smarts, source, frozenset(matched)))
            if self.signals is not None:
                self.signals.finished.emit(self.job_gen, results)
        except Exception as e:
            logger.exception("SubstructureFilterWorker failed")
            if self.signals is not None:
                self.signals.failed.emit(self.job_gen, str(e))
