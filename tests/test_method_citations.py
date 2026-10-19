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

"""Sanity checks for citation helper strings."""

from __future__ import annotations

from molmanager.reference import method_citations as sc


def test_plain_citations_contain_dois() -> None:
    assert "10.1021/jacsau.4c00271" in sc.UNIPKA
    assert "10.1021/acs.jcim.1c00075" in sc.MOLGPKA
    assert "10.1021/ci034243x" in sc.ESOL_DELANEY
    assert "10.1021/cn100008c" in sc.WAGER_CNS_MPO
    assert "10.1186/1758-2946-3-8" in sc.CONFAB
    assert "10.1021/acs.jcim.3c00563" in sc.CONFORGE


def test_descriptor_footer_html_links() -> None:
    html = sc.descriptor_dialog_footer_html()
    assert "doi.org" in html
    assert "Luo" in html
    assert "Sauer" in html
    assert "Firth" in html
    assert "PubChem" in html


def test_descriptor_checkbox_citations() -> None:
    assert sc.descriptor_checkbox_citation_html("LOGD74") is not None
    assert "Luo" in sc.descriptor_checkbox_citation_html("LOGD74") or ""
    assert sc.descriptor_checkbox_citation_html("FP_Pharm2D_Gobbi") is not None
    assert sc.descriptor_checkbox_citation_html("AB_MPS") is not None
    assert "DeGoey" in (sc.descriptor_checkbox_citation_html("AB_MPS") or "")
    assert sc.descriptor_checkbox_citation_html("MolWt") is None
    assert sc.descriptor_checkbox_citation_html("PMI1") is not None
    assert "Sauer" in (sc.descriptor_checkbox_citation_html("NPR1") or "")
    assert sc.descriptor_checkbox_citation_html("PBF") is not None
    assert "Firth" in (sc.descriptor_checkbox_citation_html("PBF") or "")
    assert "PubChem" in (sc.descriptor_checkbox_citation_html("COMMON_NAME") or "")
    assert "PubChem" in (sc.descriptor_checkbox_citation_html("SYNONYMS") or "")


def test_ab_mps_score_formula() -> None:
    from rdkit import Chem

    from molmanager.descriptors.medchem_descriptors import ab_mps_score

    mol = Chem.MolFromSmiles("c1ccccc1")
    score = ab_mps_score(mol)
    assert score >= 0.0
    assert score == abs(score)  # non-negative sum of positive terms


def test_surechembl_patent_html() -> None:
    html = sc.surechembl_patent_search_html()
    assert "SureChEMBL" in html
    assert "surechembl" in html.lower()
