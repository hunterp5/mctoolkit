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

"""PubChem chemical-vendor lookup for Tools → Query Database → Vendors.

Identity is a SMILES-to-CID PUG call. Product rows come only from the
``Chemical Vendors`` category of PUG View source categories. Depositor
cross-reference lists are not aligned and are not used.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

PUG_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
CHEMICAL_VENDORS = "Chemical Vendors"
COLUMN_VENDOR = "Vendor"
COLUMN_PRODUCT_ID = "Product ID"
COLUMN_URL = "URL"
_USER_AGENT = "MolManager/1.0 (chemical vendor lookup)"
_MIN_INTERVAL_S = 0.25
_TIMEOUT_S = 60.0
_RETRIES = 3
_RETRY_CODES = frozenset({429, 500, 502, 503})

_limiter_lock = threading.Lock()
_last_request = 0.0


class PubChemVendorError(RuntimeError):
    """PubChem vendor lookup failed after retries."""


@dataclass(frozen=True)
class VendorOffer:
    """One deposited chemical-vendor product for a compound."""

    vendor: str
    product_id: str
    url: str

    def as_fields(self) -> dict[str, str]:
        """Column values added with the query SMILES."""
        return {
            COLUMN_VENDOR: self.vendor,
            COLUMN_PRODUCT_ID: self.product_id,
            COLUMN_URL: self.url,
        }


@dataclass(frozen=True)
class VendorLookup:
    """Outcome of one structure lookup. No offers means no table row."""

    cid: int | None
    offers: tuple[VendorOffer, ...]
    error: str = ""


def first_cid_from_text(text: str) -> int | None:
    """First CID from a PUG ``cids/TXT`` body, or ``None`` when none is listed."""
    for line in (text or "").splitlines():
        token = line.strip()
        if token.isdigit():
            return int(token)
    return None


def vendor_offers_from_categories(payload: object) -> list[VendorOffer]:
    """Chemical-vendor products in a PUG View categories document.

    ``SourceRecordURL`` is the product page. The depositor homepage is not
    used when that link is missing. Other source categories are ignored.
    """
    categories = _category_list(payload)
    offers: list[VendorOffer] = []
    index: dict[tuple[str, str], int] = {}
    for category in categories:
        if str(category.get("Category") or "").strip() != CHEMICAL_VENDORS:
            continue
        sources = category.get("Sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            offer = _offer_from_source(source)
            if offer is None:
                continue
            key = (offer.vendor.casefold(), offer.product_id)
            existing = index.get(key)
            if existing is None:
                index[key] = len(offers)
                offers.append(offer)
            elif not offers[existing].url and offer.url:
                kept = offers[existing]
                offers[existing] = VendorOffer(
                    vendor=kept.vendor,
                    product_id=kept.product_id,
                    url=offer.url,
                )
    return offers


def cid_for_smiles(smiles: str) -> int | None:
    """Resolve one SMILES to a PubChem CID. ``None`` when PubChem has no compound."""
    query = (smiles or "").strip()
    if not query:
        return None
    body = urllib.parse.urlencode({"smiles": query}).encode("utf-8")
    url = f"{PUG_BASE}/compound/smiles/cids/TXT"
    raw = _request(url, data=body, accept="text/plain")
    if raw is None:
        return None
    return first_cid_from_text(raw.decode("utf-8", errors="replace"))


def vendor_offers_for_cid(cid: int) -> list[VendorOffer]:
    """Chemical-vendor products deposited for ``cid``. Empty when none are listed."""
    url = f"{PUG_VIEW_BASE}/categories/compound/{int(cid)}/JSON"
    raw = _request(url, data=None, accept="application/json")
    if raw is None:
        return []
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise PubChemVendorError("PubChem returned an unreadable vendor list.") from exc
    return vendor_offers_from_categories(payload)


def lookup_vendors(smiles: str) -> VendorLookup:
    """Vendor products for one SMILES. An empty offer list means no result row."""
    try:
        cid = cid_for_smiles(smiles)
    except PubChemVendorError as exc:
        return VendorLookup(cid=None, offers=(), error=str(exc))
    if cid is None:
        return VendorLookup(cid=None, offers=())
    try:
        offers = vendor_offers_for_cid(cid)
    except PubChemVendorError as exc:
        return VendorLookup(cid=cid, offers=(), error=str(exc))
    return VendorLookup(cid=cid, offers=tuple(offers))


def _category_list(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    source_categories = payload.get("SourceCategories")
    if not isinstance(source_categories, dict):
        return []
    categories = source_categories.get("Categories")
    if not isinstance(categories, list):
        return []
    return [item for item in categories if isinstance(item, dict)]


def _offer_from_source(source: object) -> VendorOffer | None:
    if not isinstance(source, dict):
        return None
    vendor = str(source.get("SourceName") or "").strip()
    if not vendor:
        return None
    product_id = str(source.get("RegistryID") or "").strip()
    url = str(source.get("SourceRecordURL") or "").strip()
    return VendorOffer(vendor=vendor, product_id=product_id, url=url)


def _request(url: str, *, data: bytes | None, accept: str) -> bytes | None:
    """HTTP body, or ``None`` on 404. Other failures raise ``PubChemVendorError``."""
    last_error: BaseException | None = None
    for attempt in range(_RETRIES):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"User-Agent": _USER_AGENT, "Accept": accept},
            method="POST" if data is not None else "GET",
        )
        try:
            return _read(req)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code == 404:
                return None
            last_error = exc
            if code not in _RETRY_CODES or attempt + 1 >= _RETRIES:
                raise PubChemVendorError(f"PubChem HTTP {code}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 >= _RETRIES:
                raise PubChemVendorError(f"PubChem network error: {exc}") from exc
        time.sleep(0.5 * (attempt + 1))
    raise PubChemVendorError(f"PubChem network error: {last_error}")


def _read(req: urllib.request.Request) -> bytes:
    global _last_request
    with _limiter_lock:
        delay = _MIN_INTERVAL_S - (time.monotonic() - _last_request)
        if delay > 0:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = resp.read()
        finally:
            _last_request = time.monotonic()
    return body
