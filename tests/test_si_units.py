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

"""SI prefix, base-unit, and compound-unit conversion."""

from __future__ import annotations

import math

import pytest

from molmanager.chem.si_units import (
    convert,
    is_amount_concentration,
    is_mass_concentration,
    is_molar_mass,
    parse_measured_unit,
    parse_unit,
)


def test_strict_parser_keeps_length_and_molar_distinct():
    nanometer = parse_unit("nm")
    nanomolar = parse_unit("nM")
    assert nanometer is not None and nanomolar is not None
    assert nanometer.dimension == (("length", 1),)
    assert is_amount_concentration(nanomolar)
    assert parse_unit("m").dimension == (("length", 1),)
    assert is_amount_concentration(parse_unit("M"))


def test_prefixes_bind_before_exponents():
    assert math.isclose(convert(1, "cm^3", "mL"), 1)
    assert math.isclose(convert(1, "dm^3", "L"), 1)
    assert math.isclose(convert(1, "mL", "L"), 0.001)
    assert math.isclose(convert(1, "kg", "g"), 1000)


def test_mass_and_amount_concentrations_share_a_scale():
    assert math.isclose(convert(1, "mg/mL", "g/L"), 1)
    assert math.isclose(convert(1, "g/L", "kg/m^3"), 1)
    assert math.isclose(convert(1, "ug/uL", "mg/mL"), 1)
    assert math.isclose(convert(1, "mg/dL", "g/L"), 0.01)
    assert math.isclose(convert(1, "mM", "mol/m^3"), 1)
    molar = parse_unit("mol/L")
    assert molar is not None and is_amount_concentration(molar)
    mass = parse_unit("g/mol")
    assert mass is not None and is_molar_mass(mass)
    assert not is_mass_concentration(mass)


def test_measured_units_read_assay_shorthand_as_molar():
    assert parse_measured_unit("nm").label == "nM"
    assert parse_measured_unit("uM").label == "µM"
    assert parse_measured_unit("µM").label == "µM"
    assert parse_measured_unit("mm").label == "mM"
    parsed = parse_measured_unit("MG/ML")
    assert parsed is not None and parsed.label == "mg/mL"
    assert parse_measured_unit("ug.mL-1").label == "µg/mL"
    assert parse_measured_unit("g per L").label == "g/L"


def test_unknown_text_does_not_parse():
    assert parse_unit("") is None
    assert parse_unit("hello") is None
    assert parse_measured_unit("not a unit") is None
    with pytest.raises(ValueError):
        convert(1, "g", "L")
