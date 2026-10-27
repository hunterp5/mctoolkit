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

"""SureChEMBL REST client for patent-literature chemical similarity search.

SureChEMBL (EMBL-EBI / Open Targets) links chemistry extracted from patents and documents.
Similarity search uses Tanimoto on RDKit Morgan fingerprints (256 bits, radius 2) on their
servers — see https://chembl.gitbook.io/surechembl/chemical-search/similarity-search-tanimoto-coefficient-and-fingerprint-generation
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ..services.column_labels import COLUMN_TANIMOTO_SIMILARITY

BASE_URL = "https://www.surechembl.org/api"
DEFAULT_POLL_TIMEOUT_S = 120.0
POLL_INTERVAL_S = 0.35


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    from ..platform_support.session_runtime import require_network

    require_network("SureChEMBL")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            pass
        raise RuntimeError(f"SureChEMBL HTTP {e.code}: {body or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"SureChEMBL network error: {e}") from e
    return json.loads(raw)


def _similarity_options_string(min_tanimoto: float) -> str:
    """API expects a string threshold for SIMILARITY search ``options``."""
    x = float(min_tanimoto)
    if x < 0.0 or x > 1.0:
        raise ValueError("Tanimoto threshold must be between 0 and 1.")
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def similarity_search(
    smiles: str,
    *,
    min_tanimoto: float = 0.7,
    max_hits: int = 25,
    poll_timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    cancel_event=None,
) -> list[dict[str, str]]:
    """
    Run a SureChEMBL SIMILARITY search and return hit rows for the table.

    Each dict has keys: SMILES, Tanimoto Similarity, SureChEMBL_ID, Name, InChIKey, Patent_hits.
    """
    smi = (smiles or "").strip()
    if not smi:
        return []
    nh = max(1, min(int(max_hits), 500))
    body = {
        "StructureSearchRequest": {
            "struct": smi,
            "structSearchType": "SIMILARITY",
            "maxResults": nh,
            "options": _similarity_options_string(min_tanimoto),
        }
    }
    start = _json_request(f"{BASE_URL}/search/structure", method="POST", payload=body, timeout=60.0)
    if start.get("status") != "OK":
        raise RuntimeError(start.get("error_message") or str(start))
    h = (start.get("data") or {}).get("hash")
    if not h:
        raise RuntimeError("SureChEMBL did not return a search hash.")

    t0 = time.monotonic()
    while time.monotonic() - t0 < poll_timeout_s:
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            raise RuntimeError("Cancelled.")
        st = _json_request(f"{BASE_URL}/search/{h}/status", timeout=30.0)
        msg = ((st.get("data") or {}).get("message") or "").lower()
        if "finished" in msg:
            break
        time.sleep(POLL_INTERVAL_S)
    else:
        raise TimeoutError("SureChEMBL search timed out while waiting for completion.")

    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        raise RuntimeError("Cancelled.")

    res = _json_request(f"{BASE_URL}/search/{h}/results?page=0&max_results={nh}", timeout=120.0)
    if res.get("status") != "OK":
        raise RuntimeError(res.get("error_message") or str(res))
    structs = (res.get("data") or {}).get("results", {}).get("structures") or []
    out: list[dict[str, str]] = []
    for row in structs:
        try:
            tc = float(row.get("similarity") or 0.0)
        except (TypeError, ValueError):
            tc = 0.0
        if tc + 1e-9 < float(min_tanimoto):
            continue
        out.append(
            {
                "SMILES": str(row.get("smiles") or "").strip(),
                COLUMN_TANIMOTO_SIMILARITY: f"{tc:.4f}",
                "SureChEMBL_ID": str(row.get("chemical_id") or row.get("id") or ""),
                "Name": str(row.get("name") or ""),
                "InChIKey": str(row.get("inchi_key") or ""),
                "Patent_hits": str(row.get("global_frequency") or ""),
            }
        )
    out.sort(key=lambda d: float(d[COLUMN_TANIMOTO_SIMILARITY]), reverse=True)
    if len(out) > nh:
        out = out[:nh]
    return out
