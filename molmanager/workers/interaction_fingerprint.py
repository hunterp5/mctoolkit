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

"""Interaction fingerprint worker (Protein → Interaction Fingerprint)."""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..protein.interaction_fingerprint import (
    InteractionFingerprintError,
    InteractionFingerprintJobResult,
    InteractionFingerprintRow,
    fingerprint_pose,
    load_receptor_polymer_atoms,
)
from .signals import WorkerSignals

logger = logging.getLogger(__name__)


class InteractionFingerprintWorker(QRunnable):
    """Type the first stored pose of each row against one receptor."""

    def __init__(
        self,
        poses: list[tuple[int, Chem.Mol | None]],
        *,
        receptor_path: str,
        fingerprint_header: str,
        residues_header: str,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.poses = poses
        self.receptor_path = receptor_path
        self.fingerprint_header = fingerprint_header
        self.residues_header = residues_header
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        ev = self.cancel_event
        total = max(len(self.poses), 1)
        if ev is not None and ev.is_set():
            self._fail("Cancelled.")
            return
        try:
            polymer = load_receptor_polymer_atoms(self.receptor_path)
        except InteractionFingerprintError as exc:
            self._fail(str(exc))
            return
        rows: list[InteractionFingerprintRow] = []
        missing = 0
        cancelled = False
        for index, (oid, pose) in enumerate(self.poses):
            if ev is not None and ev.is_set():
                cancelled = True
                break
            report_tool_progress(
                message="Interaction fingerprint",
                done=index,
                total=total,
                progress_state=self.progress_state,
                signals=self.signals,
                force_signal=index == 0,
            )
            if pose is None:
                missing += 1
                rows.append(InteractionFingerprintRow(int(oid), "N/A", "N/A"))
                continue
            try:
                fingerprint, residues = fingerprint_pose(polymer, pose)
            except InteractionFingerprintError as exc:
                self._fail(str(exc))
                return
            rows.append(InteractionFingerprintRow(int(oid), fingerprint, residues))
        report_tool_progress(
            message="Interaction fingerprint",
            done=total if not cancelled else len(rows),
            total=total,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        result = InteractionFingerprintJobResult(
            rows=tuple(rows),
            fingerprint_header=self.fingerprint_header,
            residues_header=self.residues_header,
            n_missing_pose=missing,
            cancelled=cancelled,
        )
        try:
            self.signals.ifp_finished.emit(result)
        except RuntimeError:
            logger.warning("ifp_finished emit failed", exc_info=True)

    def _fail(self, message: str) -> None:
        try:
            self.signals.ifp_failed.emit(message)
        except RuntimeError:
            logger.warning("ifp_failed emit failed", exc_info=True)
