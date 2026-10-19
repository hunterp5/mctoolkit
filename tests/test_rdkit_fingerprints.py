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

"""RDKit fingerprint registry."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.rdkit_fingerprints import (
    FINGERPRINT_SPECS,
    SIMILARITY_FP_TYPE_LABELS,
    descriptor_fingerprint_categories,
    fingerprint_bitvect_for_ui_choice,
    fingerprint_is_gil_heavy,
    fingerprint_onbits_for_internal_key,
    resolve_fingerprint_label,
    spec_for_label,
)


def test_similarity_labels_match_specs():
    assert len(SIMILARITY_FP_TYPE_LABELS) == len(FINGERPRINT_SPECS)
    assert "FCFP Morgan" in "\n".join(SIMILARITY_FP_TYPE_LABELS)
    assert "Pattern fingerprint" in SIMILARITY_FP_TYPE_LABELS


def test_descriptor_categories_cover_all_specs():
    cats = descriptor_fingerprint_categories()
    assert len(cats) == len(FINGERPRINT_SPECS)
    assert cats["Morgan (r=2, n=1024)"] == "FP_Morgan_2_1024"
    assert all(not name.endswith("on-bits") for name in cats)


def test_gobbi_fingerprint_is_gil_heavy():
    assert fingerprint_is_gil_heavy("2D pharmacophore (Gobbi)")
    assert not fingerprint_is_gil_heavy("Morgan (r=2, n=1024)")


def test_legacy_rdk_label_alias():
    assert resolve_fingerprint_label("RDK (2048)") == "RDK path (2048)"
    assert spec_for_label("RDK (2048)") is not None


def test_every_spec_computes_for_benzene():
    mol = Chem.MolFromSmiles("c1ccccc1")
    assert mol is not None
    for spec in FINGERPRINT_SPECS:
        fp = fingerprint_bitvect_for_ui_choice(mol, spec.label)
        assert fp is not None, spec.label
        onbits = fingerprint_onbits_for_internal_key(spec.internal_key)(mol)
        assert isinstance(onbits, int) and onbits >= 0, spec.internal_key
