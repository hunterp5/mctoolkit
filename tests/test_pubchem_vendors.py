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

"""Parser tests for PubChem chemical-vendor categories. No network."""

from __future__ import annotations

from molmanager.sources.pubchem_vendors import (
    COLUMN_PRODUCT_ID,
    COLUMN_URL,
    COLUMN_VENDOR,
    VendorLookup,
    VendorOffer,
    first_cid_from_text,
    vendor_offers_from_categories,
)
from molmanager.ui.external.vendors import _append_lookup

_PRODUCT = "https://en.cato-chem.com/goodsDetail/CATO/C1343073"


def _payload(*sources: dict, category: str = "Chemical Vendors") -> dict:
    return {
        "SourceCategories": {
            "Categories": [
                {"Category": "Biological Test Results", "Sources": [{"SourceName": "ChEMBL"}]},
                {"Category": category, "Sources": list(sources)},
            ]
        }
    }


def test_chemical_vendors_keep_name_product_id_and_product_url():
    offers = vendor_offers_from_categories(
        _payload(
            {
                "SourceName": "CATO Research Chemicals Inc.",
                "RegistryID": "C1343073",
                "SourceURL": "https://en.cato-chem.com/",
                "SourceRecordURL": _PRODUCT,
            }
        )
    )
    assert len(offers) == 1
    offer = offers[0]
    assert offer.vendor == "CATO Research Chemicals Inc."
    assert offer.product_id == "C1343073"
    assert offer.url == _PRODUCT
    assert offer.as_fields() == {
        COLUMN_VENDOR: "CATO Research Chemicals Inc.",
        COLUMN_PRODUCT_ID: "C1343073",
        COLUMN_URL: _PRODUCT,
    }


def test_other_categories_and_missing_product_url_are_not_used():
    offers = vendor_offers_from_categories(
        _payload(
            {
                "SourceName": "Example Vendor",
                "RegistryID": 42,
                "SourceURL": "https://vendor.example/",
            }
        )
    )
    assert len(offers) == 1
    assert offers[0].product_id == "42"
    assert offers[0].url == ""


def test_no_chemical_vendors_returns_no_offers():
    assert vendor_offers_from_categories(_payload(category="Literature")) == []
    assert vendor_offers_from_categories({}) == []
    assert vendor_offers_from_categories({"SourceCategories": {"Categories": []}}) == []


def test_sources_without_a_vendor_name_are_skipped_and_duplicates_collapse():
    offers = vendor_offers_from_categories(
        _payload(
            {"RegistryID": "NO-NAME", "SourceRecordURL": "https://example.test/a"},
            {"SourceName": "Sigma", "RegistryID": "S1"},
            {
                "SourceName": "sigma",
                "RegistryID": "S1",
                "SourceRecordURL": "https://example.test/s1",
            },
        )
    )
    assert len(offers) == 1
    assert offers[0].vendor == "Sigma"
    assert offers[0].product_id == "S1"
    assert offers[0].url == "https://example.test/s1"


def test_missing_vendors_produce_no_result_rows():
    results: list = []
    logs: list[str] = []
    _append_lookup(results, logs, "C", VendorLookup(cid=2244, offers=()))
    _append_lookup(results, logs, "CC", VendorLookup(cid=None, offers=()))
    _append_lookup(
        results, logs, "CCC", VendorLookup(cid=None, offers=(), error="PubChem HTTP 503.")
    )
    assert results == []
    assert logs == [
        "C | no vendors",
        "CC | no PubChem compound",
        "CCC | ERROR: PubChem HTTP 503.",
    ]


def test_each_vendor_product_is_one_result_row():
    offer = VendorOffer("CATO", "C1343073", _PRODUCT)
    results: list = []
    logs: list[str] = []
    _append_lookup(results, logs, "CC(=O)O", VendorLookup(cid=176, offers=(offer,)))
    assert len(results) == 1
    assert results[0].smiles == "CC(=O)O"
    assert results[0].fields[COLUMN_VENDOR] == "CATO"
    assert results[0].fields[COLUMN_PRODUCT_ID] == "C1343073"
    assert results[0].fields[COLUMN_URL] == _PRODUCT
    assert logs == ["CC(=O)O | CID=176 | 1 vendor(s)"]


def test_first_cid_from_text_uses_the_first_numeric_line():
    assert first_cid_from_text("176\n") == 176
    assert first_cid_from_text("12\n34\n") == 12
    assert first_cid_from_text("") is None
    assert first_cid_from_text("Status: not found\n") is None
