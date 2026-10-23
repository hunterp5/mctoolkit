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

"""Session cache of Uni-pKa ionization ensembles (structure key → picklable ensemble).

Keyed by :func:`molmanager.services.structure_grouping.structure_key` (canonical SMILES)
and by each microstate SMILES in the ensemble so Protonated / protomer rows reuse the
same prediction. Shared by Predict pKa, Protonate, Generate Protomers, and ionization
descriptors (LogD/LogS 7.4, CNS MPO, AB-MPS, BBB Score). Saved into ``.cms`` session files and
restored on Open / Duplicate. Cleared on Clear / shutdown. Does not persist to SDF/CSV.
"""

from __future__ import annotations

import base64
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# Present keys may map to ``None`` (valid empty / non-applicable prediction).
_store: dict[str, list[Any] | None] = {}

IONIZATION_SIDECAR_VERSION = 1
_SIDECAR_ENGINE = "unipka"


def _alias_keys_for_states(states: Any, *, from_blobs: bool = True) -> list[str]:
    """Canonical SMILES for every microstate so later tools can look up the same ensemble."""
    from molmanager.ionization.unipka_ensembles import PicklableIonizationEnsemble
    from molmanager.chem.molecule_conversion import mol_to_canonical_smiles
    from rdkit import Chem

    if not isinstance(states, PicklableIonizationEnsemble):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for ms in states.microstates:
        smi = str(getattr(ms, "smiles", "") or "").strip()
        key = smi
        if from_blobs:
            mol = None
            blob = getattr(ms, "mol_binary", None)
            if blob:
                try:
                    mol = Chem.Mol(blob)
                except Exception:
                    mol = None
            if mol is None and smi:
                mol = Chem.MolFromSmiles(smi)
            key = mol_to_canonical_smiles(mol) if mol is not None else smi
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _write_entry(
    store: dict[str, Any],
    structure_key: str,
    states: list[Any] | None,
    *,
    from_blobs: bool = True,
) -> None:
    store[structure_key] = states
    if states is None:
        return
    for alias in _alias_keys_for_states(states, from_blobs=from_blobs):
        store[alias] = states


def lookup(structure_key: str) -> tuple[bool, list[Any] | None]:
    """
    Return ``(True, states)`` on a cache hit (``states`` may be ``None``).

    Return ``(False, None)`` on a miss.
    """
    key = str(structure_key or "")
    if not key:
        return False, None
    with _lock:
        if key not in _store:
            return False, None
        return True, _store[key]


def store(structure_key: str, states: list[Any] | None) -> None:
    """Write-through a picklable microstate list (or ``None`` for empty / N/A)."""
    key = str(structure_key or "")
    if not key:
        return
    with _lock:
        _write_entry(_store, key, states)


def store_many(items: dict[str, list[Any] | None]) -> None:
    if not items:
        return
    with _lock:
        for key, states in items.items():
            k = str(key or "")
            if k:
                _write_entry(_store, k, states)


def clear() -> None:
    with _lock:
        _store.clear()


def size() -> int:
    with _lock:
        return len(_store)


def snapshot() -> dict[str, Any]:
    """Copy of the in-memory store for session serialization."""
    with _lock:
        return dict(_store)


def _b64_bytes(blob: bytes | None) -> str | None:
    if not blob:
        return None
    return base64.b64encode(blob).decode("ascii")


def _bytes_b64(raw: object) -> bytes | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return base64.b64decode(raw.encode("ascii"), validate=False)
    except Exception:
        return None


def _entry_to_json(states: Any) -> dict[str, Any] | None:
    from molmanager.ionization.unipka_ensembles import (
        PicklableIonizationEnsemble,
        PicklableMicrostate,
    )

    if states is None:
        return None
    if isinstance(states, PicklableIonizationEnsemble):
        micros = []
        for ms in states.microstates:
            row: dict[str, Any] = {
                "smiles": str(ms.smiles or ""),
                "charge": int(ms.charge),
                "free_energy": float(ms.free_energy),
            }
            b64 = _b64_bytes(ms.mol_binary)
            if b64:
                row["mol_b64"] = b64
            micros.append(row)
        return {
            "kind": "unipka",
            "macro_pkas": [float(v) for v in states.macro_pkas],
            "microstates": micros,
        }
    if isinstance(states, (list, tuple)) and states and isinstance(states[0], PicklableMicrostate):
        pairs = []
        for s in states:
            row = {"pka": float(s.pka)}
            for attr, key in (
                ("protonated_mol", "protonated_b64"),
                ("deprotonated_mol", "deprotonated_b64"),
                ("ph7_mol", "ph7_b64"),
            ):
                b64 = _b64_bytes(getattr(s, attr, None))
                if b64:
                    row[key] = b64
            pairs.append(row)
        return {"kind": "ha_pairs", "pairs": pairs}
    return None


def _entry_from_json(raw: Any) -> Any | None:
    from molmanager.ionization.unipka_ensembles import (
        PicklableIonizationEnsemble,
        PicklableIonizationMicrostate,
        PicklableMicrostate,
    )

    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "")
    if kind == "unipka":
        micros = []
        for row in raw.get("microstates") or []:
            if not isinstance(row, dict):
                continue
            micros.append(
                PicklableIonizationMicrostate(
                    smiles=str(row.get("smiles") or ""),
                    charge=int(row.get("charge") or 0),
                    free_energy=float(row.get("free_energy") or 0.0),
                    mol_binary=_bytes_b64(row.get("mol_b64")),
                )
            )
        pkas = tuple(float(v) for v in (raw.get("macro_pkas") or []) if v is not None)
        if not micros and not pkas:
            return None
        return PicklableIonizationEnsemble(microstates=tuple(micros), macro_pkas=pkas)
    if kind == "ha_pairs":
        pairs = []
        for row in raw.get("pairs") or []:
            if not isinstance(row, dict):
                continue
            pairs.append(
                PicklableMicrostate(
                    pka=float(row.get("pka") or 0.0),
                    protonated_mol=_bytes_b64(row.get("protonated_b64")),
                    deprotonated_mol=_bytes_b64(row.get("deprotonated_b64")),
                    ph7_mol=_bytes_b64(row.get("ph7_b64")),
                )
            )
        return pairs or None
    return None


def serialize_ionization_sidecar(store: dict[str, Any] | None = None) -> dict[str, Any]:
    """JSON-safe Uni-pKa ensembles for ``.cms`` sessions (successful predictions only)."""
    src = snapshot() if store is None else store
    entries: dict[str, Any] = {}
    seen_ids: set[int] = set()
    for key, states in src.items():
        packed = _entry_to_json(states)
        if packed is None:
            continue
        k = str(key or "")
        if not k:
            continue
        obj_id = id(states)
        if obj_id in seen_ids:
            continue
        seen_ids.add(obj_id)
        entries[k] = packed
    return {
        "v": IONIZATION_SIDECAR_VERSION,
        "engine": _SIDECAR_ENGINE,
        "pka_mean": _sidecar_pka_mean(),
        "entries": entries,
    }


def _sidecar_pka_mean() -> float:
    from molmanager.ionization.unipka_ensembles import UNIPKA_DWAR_PKA_MEAN

    return float(UNIPKA_DWAR_PKA_MEAN)


def _sidecar_pka_mean_matches(raw: dict[str, Any]) -> bool:
    try:
        mean = float(raw.get("pka_mean"))
    except (TypeError, ValueError):
        return False
    return abs(mean - _sidecar_pka_mean()) < 1e-6


def deserialize_ionization_sidecar(raw: Any) -> dict[str, Any]:
    """Restore ensembles from a session sidecar; ignore unknown or corrupt entries."""
    if not isinstance(raw, dict):
        return {}
    try:
        ver = int(raw.get("v") or 0)
    except (TypeError, ValueError):
        return {}
    if ver != IONIZATION_SIDECAR_VERSION:
        return {}
    if not _sidecar_pka_mean_matches(raw):
        return {}
    blob = raw.get("entries")
    if not isinstance(blob, dict):
        return {}
    out: dict[str, Any] = {}
    for key, entry in blob.items():
        k = str(key or "")
        if not k:
            continue
        try:
            restored = _entry_from_json(entry)
        except Exception:
            logger.debug("skipping corrupt ionization sidecar entry %s", k[:48], exc_info=True)
            continue
        if restored is not None:
            _write_entry(out, k, restored, from_blobs=False)
    return out


def restore_ionization_sidecar(raw: Any) -> int:
    """Replace the in-memory cache with deserialized session ensembles. Returns entry count."""
    restored = deserialize_ionization_sidecar(raw)
    with _lock:
        _store.clear()
        _store.update(restored)
    return len(restored)
