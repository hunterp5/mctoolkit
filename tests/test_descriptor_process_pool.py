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

"""Descriptor worker process-pool thresholds and batched fingerprint calculation."""

from __future__ import annotations

from rdkit import Chem

from molmanager.platform_support.config import load_config
from molmanager.chem.rdkit_fingerprints import int_fns_include_fingerprints
from molmanager.workers.chemistry_descriptors import (
    _descriptor_output_headers,
    _descriptor_process_pool_min_rows,
    _mp_calc_descriptor_batch,
)


def test_int_fns_include_fingerprints():
    assert int_fns_include_fingerprints(["FP_Morgan_2_2048", "MolWt"])
    assert not int_fns_include_fingerprints(["MolWt", "SMILES"])


def test_descriptor_pool_min_rows_morgan_uses_fp_threshold():
    cfg = load_config()
    assert (
        _descriptor_process_pool_min_rows(cfg, ["FP_Morgan_2_2048"])
        == cfg.descriptor_fp_process_pool_min_rows
    )


def test_descriptor_pool_min_rows_pharm2d_is_two():
    cfg = load_config()
    assert _descriptor_process_pool_min_rows(cfg, ["FP_Pharm2D_Gobbi"]) == 2


def test_descriptor_pool_orbital_jobs_are_one_row_tasks():
    from molmanager.workers.chemistry_descriptors import _descriptor_process_pool_batch_size

    cfg = load_config()
    assert _descriptor_process_pool_min_rows(cfg, ["HOMO", "MolWt"]) == 2
    assert _descriptor_process_pool_batch_size(cfg, ["HOMO", "LUMO"]) == 1
    assert (
        _descriptor_process_pool_batch_size(cfg, ["MolWt"])
        == cfg.descriptor_process_pool_batch_size
    )


def test_descriptor_pool_min_rows_plain_descriptors_use_default(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_PROCESS_POOL_MIN_ROWS", "999")
    cfg = load_config()
    assert _descriptor_process_pool_min_rows(cfg, ["MolWt"]) == 999


def test_mp_calc_descriptor_batch_fingerprint_rows():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    blob = mol.ToBinary()
    items = [(10, blob, None), (11, blob, None)]
    rows = _mp_calc_descriptor_batch((items, ("Morgan on-bits",), ("FP_Morgan_2_2048",), False))
    assert len(rows) == 2
    assert rows[0][0] == 10
    assert rows[1][0] == 11
    assert int(rows[0][1]["Morgan on-bits"]) > 0
    assert rows[0][1]["Morgan on-bits"] == rows[1][1]["Morgan on-bits"]


def test_descriptor_output_headers_appends_shared_pka_column() -> None:
    assert _descriptor_output_headers(["LogD 7.4"], False) == ["LogD 7.4"]
    assert _descriptor_output_headers(["LogD 7.4"], True) == ["LogD 7.4", "pKa"]
    assert _descriptor_output_headers(["pKa", "LogD 7.4"], True) == ["pKa", "LogD 7.4"]


def test_calc_descriptor_row_values_adds_pka_from_ensemble() -> None:
    from molmanager.ionization.unipka_ensembles import (
        PicklableIonizationEnsemble,
        PicklableIonizationMicrostate,
    )
    from molmanager.workers.chemistry_descriptors import _calc_descriptor_row_values

    mol = Chem.MolFromSmiles("CCO")
    ens = PicklableIonizationEnsemble(
        microstates=(PicklableIonizationMicrostate("CCO", 0, 0.0, None),),
        macro_pkas=(4.2,),
    )
    oid, row = _calc_descriptor_row_values(1, mol, [], (), {}, pka_states=ens, pka_cache_used=True)
    assert oid == 1
    assert row["pKa"] == "4.20"
    assert "pI" not in row
