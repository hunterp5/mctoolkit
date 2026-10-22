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

"""Fingerprint similarity helpers and worker."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.rdkit_fingerprints import fingerprint_bitvect_for_ui_choice
from molmanager.workers.fingerprint_similarity import pairwise_fingerprint_similarity


def _benzene() -> Chem.Mol:
    return Chem.MolFromSmiles("c1ccccc1")


def _toluene() -> Chem.Mol:
    return Chem.MolFromSmiles("Cc1ccccc1")


def test_similarity_dialogs_default_to_morgan_r2_2048(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.bulk_similarity import BulkSimilarityDialog
    from molmanager.ui.dialogs.fp_similarity import FPSimilarityDialog

    for dialog_cls in (FPSimilarityDialog, BulkSimilarityDialog):
        dlg = dialog_cls(None)
        try:
            assert dlg.fp_combo.currentText() == "Morgan (r=2, n=2048)"
        finally:
            dlg.close()


def test_pairwise_metrics_for_related_molecules():
    qmol, tmol = _benzene(), _toluene()
    fp_choice = "Morgan (r=2, n=1024)"
    qfp = fingerprint_bitvect_for_ui_choice(qmol, fp_choice)
    fp = fingerprint_bitvect_for_ui_choice(tmol, fp_choice)
    assert qfp is not None and fp is not None
    t = pairwise_fingerprint_similarity(qfp, fp, "Tanimoto")
    d = pairwise_fingerprint_similarity(qfp, fp, "Dice")
    c = pairwise_fingerprint_similarity(qfp, fp, "Cosine")
    assert 0.0 < t < 1.0
    assert 0.0 < d <= 1.0
    assert 0.0 < c <= 1.0


def test_identical_molecules_similarity_one():
    mol = _benzene()
    fp_choice = "Morgan (r=2, n=1024)"
    qfp = fingerprint_bitvect_for_ui_choice(mol, fp_choice)
    assert qfp is not None
    assert pairwise_fingerprint_similarity(qfp, qfp, "Tanimoto") == 1.0
