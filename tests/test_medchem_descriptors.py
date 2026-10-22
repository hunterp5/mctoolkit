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

"""Tests for Lipinski, InChI key, formula, and CNS MPO-style descriptors."""

from __future__ import annotations

import re

from unittest.mock import patch

from rdkit import Chem

from molmanager.descriptors.medchem_descriptors import (
    cns_mpo_score,
    esol_logS_intrinsic,
    lipinski_violations,
    logd74_value,
    logs74_value,
    mol_formula,
    mol_inchi_key,
    mol_net_formal_charge,
    ro5_pass,
)
from molmanager.ionization.unipka_ensembles import int_fns_need_ionization
from molmanager.workers.chemistry_tools import descriptor_callable_for_int_fn


def test_lipinski_ethanol_zero_violations() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    assert lipinski_violations(mol) == 0
    assert ro5_pass(mol) == "Yes"


def test_ro5_fail_high_mw() -> None:
    mol = Chem.MolFromSmiles("C" * 120)
    assert mol is not None
    assert lipinski_violations(mol) >= 1
    assert ro5_pass(mol) == "No"


def test_net_formal_charge() -> None:
    neutral = Chem.MolFromSmiles("CCO")
    assert neutral is not None
    assert mol_net_formal_charge(neutral) == 0
    salt = Chem.MolFromSmiles("[NH4+].[Cl-]")
    assert salt is not None
    assert mol_net_formal_charge(salt) == 0
    cation = Chem.MolFromSmiles("[NH4+]")
    assert cation is not None
    assert mol_net_formal_charge(cation) == 1
    assert descriptor_callable_for_int_fn("NET_FORMAL_CHARGE", {})(cation) == 1


def test_inchi_key_and_formula_ethanol() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    key = mol_inchi_key(mol)
    assert re.match(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$", key)
    assert mol_formula(mol) == "C2H6O"


@patch("molmanager.descriptors.medchem_descriptors.microstates_for_mol", return_value=None)
def test_cns_mpo_in_range(_mock_ms: object) -> None:
    mol = Chem.MolFromSmiles("c1ccccc1CCN")
    assert mol is not None
    s = cns_mpo_score(mol)
    assert 0.0 <= s <= 6.0


@patch("molmanager.descriptors.medchem_descriptors.microstates_for_mol", return_value=None)
def test_descriptor_dispatch_custom_ids(_mock_ms: object) -> None:
    cache: dict = {}
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    assert descriptor_callable_for_int_fn("INCHIKEY", cache, None)(mol) == mol_inchi_key(mol)
    assert descriptor_callable_for_int_fn("MOLFORMULA", cache)(mol) == "C2H6O"
    assert descriptor_callable_for_int_fn("RO5_VIOLATIONS", cache)(mol) == 0
    assert descriptor_callable_for_int_fn("RO5_PASS", cache)(mol) == "Yes"
    assert isinstance(descriptor_callable_for_int_fn("CNS_MPO", cache)(mol), float)
    assert isinstance(descriptor_callable_for_int_fn("LOGS_ESOL", cache)(mol), float)


def test_int_fns_need_ionization() -> None:
    assert int_fns_need_ionization(("MolWt", "LOGD74"))
    assert int_fns_need_ionization(("LOGS74",))
    assert int_fns_need_ionization(("CNS_MPO",))
    assert not int_fns_need_ionization(("QED", "MolWt", "LOGS_ESOL"))


def test_logd74_value_heuristic_when_no_microstates() -> None:
    mol = Chem.MolFromSmiles("[Na+].[Cl-]")
    assert mol is not None
    v = logd74_value(mol, [])
    assert isinstance(v, float)


def test_logs74_value_intrinsic_when_no_microstates() -> None:
    mol = Chem.MolFromSmiles("[Na+].[Cl-]")
    assert mol is not None
    intrinsic = esol_logS_intrinsic(mol)
    assert logs74_value(mol, []) == intrinsic


def test_esol_intrinsic_ethanol() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    s = esol_logS_intrinsic(mol)
    assert -2.0 < s < 2.0
