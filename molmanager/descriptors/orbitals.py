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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""GFN2-xTB HOMO, LUMO, and gap for Calculate Descriptors.

Values are gas-phase orbital energies in eV from one closed-shell singlet single
point. The geometry is the lowest-energy packed conformer when ``confs`` or
``superpose`` has 3D coordinates (MMFF94, UFF fallback). A 2D structure with no
packed conformer gets one ETKDG embedding, minimized with MMFF94 (UFF fallback),
and that pose is used only for this single point. The ``xtb`` binary is preferred;
the ``tblite`` package is used only when that binary cannot be resolved.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Iterable

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.conformers.conformer_column_codec import mol_has_3d_coordinates
from molmanager.descriptors.descriptors_3d import mol_for_3d_descriptors
from molmanager.descriptors.medchem_descriptors import mol_net_formal_charge
from molmanager.platform_support.bundled_paths import (
    default_external_executable,
    resolve_user_executable,
)
from molmanager.platform_support.tool_paths import TOOL_XTB, effective_tool_path

logger = logging.getLogger(__name__)

# Display label, internal worker key. Order is the Electronic-tab order.
ORBITAL_ITEMS: tuple[tuple[str, str], ...] = (
    ("HOMO (eV)", "HOMO"),
    ("LUMO (eV)", "LUMO"),
    ("HOMO-LUMO gap (eV)", "HOMO_LUMO_GAP"),
)
ORBITAL_KEYS: frozenset[str] = frozenset(key for _disp, key in ORBITAL_ITEMS)

MISSING_XTB_MSG = (
    "xtb is required for HOMO, LUMO, and the HOMO–LUMO gap. Install xtb "
    "(https://github.com/grimme-lab/xtb) and set it under Settings → Configure → xtb, "
    "or install the tblite package (pip install tblite)."
)

_HARTREE_EV = 27.211386245988
_XTB_TIMEOUT_S = 180
_CACHE_MAX = 256
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_HOMO_EV_RE = re.compile(r"([+-]?\d+\.\d+(?:[eE][+-]?\d+)?)\s+\(HOMO\)", re.IGNORECASE)
_LUMO_EV_RE = re.compile(r"([+-]?\d+\.\d+(?:[eE][+-]?\d+)?)\s+\(LUMO\)", re.IGNORECASE)

_cache: OrderedDict[tuple, dict[str, float] | None] = OrderedDict()
_cache_lock = threading.Lock()
_tblite_lock = threading.Lock()


def mol_for_orbital_single_point(
    mol: Chem.Mol | None,
    packed_cell: str | None = None,
    prepared_3d: Chem.Mol | None = None,
) -> Chem.Mol | None:
    """3D conformer with explicit H for one GFN2-xTB single point.

    Prefers *prepared_3d* or a packed ensemble. When the structure is only 2D,
    embeds one ETKDG conformer and minimizes it. The embedded pose is not stored
    on the table.
    """
    if prepared_3d is not None and mol_has_3d_coordinates(prepared_3d):
        return prepared_3d
    packed = mol_for_3d_descriptors(mol, packed_cell=packed_cell)
    if packed is not None:
        return packed
    return embed_conformer_for_orbitals(mol)


def embed_conformer_for_orbitals(mol: Chem.Mol | None) -> Chem.Mol | None:
    """One explicit-H ETKDG conformer, MMFF94-minimized, or ``None`` if embedding fails."""
    try:
        return _embed_conformer_for_orbitals(mol)
    except Exception as exc:  # noqa: BLE001 — a failed embed is a missing orbital value
        logger.debug("Could not embed a conformer for orbital energies", exc_info=exc)
        return None


def _embed_conformer_for_orbitals(mol: Chem.Mol | None) -> Chem.Mol | None:
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    work = Chem.Mol(mol)
    Chem.SanitizeMol(work)
    work.RemoveAllConformers()
    work = Chem.AddHs(work)
    params = _etkdg_params()
    if params is None or AllChem.EmbedMolecule(work, params) != 0:
        if AllChem.EmbedMolecule(work, randomSeed=0xF00D) != 0:
            return None
    if not _minimize_embedded_conformer(work):
        return None
    if not mol_has_3d_coordinates(work) or _has_implicit_hydrogens(work):
        return None
    return work


def _etkdg_params():
    for name in ("ETKDGv3", "ETKDGv2", "ETKDG"):
        factory = getattr(AllChem, name, None)
        if factory is None:
            continue
        params = factory()
        params.randomSeed = 0xF00D
        if hasattr(params, "clearConfs"):
            params.clearConfs = True
        if hasattr(params, "numThreads"):
            params.numThreads = 1
        return params
    return None


def _minimize_embedded_conformer(mol: Chem.Mol) -> bool:
    """Relax *mol* in place. A hit of the iteration cap is still a usable pose."""
    try:
        if AllChem.MMFFHasAllMoleculeParams(mol):
            status = AllChem.MMFFOptimizeMolecule(mol, mmffVariant="MMFF94", maxIters=500)
            if status >= 0:
                return mol_has_3d_coordinates(mol)
    except (ValueError, RuntimeError):
        pass
    try:
        status = AllChem.UFFOptimizeMolecule(mol, maxIters=500)
    except (ValueError, RuntimeError):
        return False
    return status >= 0 and mol_has_3d_coordinates(mol)


def int_fns_need_orbitals(int_fns: Iterable[str] | None) -> bool:
    """True when any selected descriptor is a GFN2-xTB orbital energy."""
    return any(isinstance(f, str) and f in ORBITAL_KEYS for f in (int_fns or ()))


def clear_orbital_cache() -> None:
    """Drop memoized single points (tests, and a geometry that must be rerun)."""
    with _cache_lock:
        _cache.clear()


def resolve_xtb_executable(user_path: str = "") -> str | None:
    """Resolve ``xtb`` from an explicit path, Configure, PATH, or a bundled copy."""
    text = effective_tool_path(TOOL_XTB, user_path)
    if text:
        found = resolve_user_executable(text)
        if found:
            return found
    return resolve_user_executable(default_external_executable("xtb"))


def tblite_available() -> bool:
    """True when the optional ``tblite`` package can be imported."""
    try:
        import tblite.interface  # noqa: F401
    except ImportError:
        return False
    return True


def gfn2_available(user_path: str = "") -> bool:
    """True when an xtb binary or the tblite package can run GFN2-xTB."""
    return resolve_xtb_executable(user_path) is not None or tblite_available()


def describe_xtb(path: str) -> tuple[bool, str]:
    """Status line for Settings → Configure → xtb."""
    found = resolve_xtb_executable(path)
    if found:
        version = _xtb_version_line(found)
        if version:
            return True, f"OK: {found} ({version})"
        return False, f"xtb ran but did not report a version ({found})."
    if not (path or "").strip() and tblite_available():
        return True, "OK: tblite Python package (no xtb path set)."
    return False, MISSING_XTB_MSG


def parse_xtb_orbital_output(
    text: str,
    json_payload: dict | None = None,
) -> dict[str, float] | None:
    """HOMO, LUMO, and gap (eV) from xtb stdout and, if needed, ``xtbout.json``."""
    pair = _frontier_from_stdout(text or "")
    if pair is None and isinstance(json_payload, dict):
        pair = _frontier_from_xtb_json(json_payload)
    if pair is None:
        return None
    homo, lumo = pair
    return {
        "HOMO": float(homo),
        "LUMO": float(lumo),
        "HOMO_LUMO_GAP": float(lumo) - float(homo),
    }


def orbital_energies_ev(mol: Chem.Mol | None) -> dict[str, float] | None:
    """
    GFN2-xTB HOMO, LUMO, and gap in eV for one 3D conformer.

    Returns ``None`` when coordinates, an explicit-hydrogen closed-shell singlet,
    or a GFN2 engine are missing, and when the single point fails. Repeated calls
    with the same coordinates, charge, and element list reuse a process-local cache.
    """
    if mol is None or not mol_has_3d_coordinates(mol):
        return None
    if _has_implicit_hydrogens(mol):
        return None
    charge = int(mol_net_formal_charge(mol))
    if _electron_count(mol, charge) % 2 != 0:
        return None
    if not gfn2_available():
        return None
    key = _geometry_key(mol, charge)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    result = _safe_orbitals(mol, charge)
    with _cache_lock:
        _cache[key] = result
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return result


def _safe_orbitals(mol: Chem.Mol, charge: int) -> dict[str, float] | None:
    try:
        return _compute_orbital_energies_ev(mol, charge)
    except Exception as exc:  # noqa: BLE001 — xtb/tblite errors are a missing descriptor
        logger.debug("GFN2-xTB single point failed", exc_info=exc)
        return None


def _compute_orbital_energies_ev(mol: Chem.Mol, charge: int) -> dict[str, float] | None:
    exe = resolve_xtb_executable()
    if exe:
        return _xtb_cli_orbitals(mol, charge, exe)
    if tblite_available():
        return _tblite_orbitals(mol, charge)
    return None


def _xtb_cli_orbitals(mol: Chem.Mol, charge: int, exe: str) -> dict[str, float] | None:
    xyz = _xyz_block(mol)
    with tempfile.TemporaryDirectory(prefix="molmanager-xtb-") as folder:
        inp = os.path.join(folder, "mol.xyz")
        with open(inp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(xyz)
        proc = _run_xtb(
            [exe, "mol.xyz", "--gfn", "2", "--chrg", str(int(charge)), "--uhf", "0", "--norestart"],
            cwd=folder,
            timeout=_XTB_TIMEOUT_S,
        )
        text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        payload = _read_xtb_json(os.path.join(folder, "xtbout.json"))
    parsed = parse_xtb_orbital_output(text, payload)
    if parsed is None:
        tail = (proc.stderr or proc.stdout or "").strip()
        logger.debug("xtb produced no orbital energies (exit %s): %s", proc.returncode, tail[-500:])
    return parsed


def _xtb_version_line(exe: str) -> str | None:
    try:
        proc = _run_xtb([exe, "--version"], cwd=None, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    text = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
    if not text:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and "version" in stripped.lower():
            return stripped
    if proc.returncode == 0:
        return text.splitlines()[0].strip()
    return None


def _run_xtb(
    argv: list[str], *, cwd: str | None, timeout: float
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    kwargs: dict = {
        "cwd": cwd,
        "env": env,
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": timeout,
        "check": False,
    }
    if sys.platform.startswith("win") and _CREATE_NO_WINDOW:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    from ..platform_support.session_runtime import require_tool

    require_tool(argv[0], "xtb")
    return subprocess.run(argv, **kwargs)


def _read_xtb_json(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        import json

        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _frontier_from_stdout(text: str) -> tuple[float, float] | None:
    homos = [float(match.group(1)) for match in _HOMO_EV_RE.finditer(text)]
    lumos = [float(match.group(1)) for match in _LUMO_EV_RE.finditer(text)]
    if not homos or not lumos:
        return None
    return homos[-1], lumos[-1]


def _frontier_from_xtb_json(payload: dict) -> tuple[float, float] | None:
    energies: list[float] | None = None
    occupations: list[float] | None = None
    unit: str | None = None
    for key, value in payload.items():
        if not isinstance(value, list) or not value:
            continue
        name = str(key).lower().replace("_", " ").replace("-", " ")
        try:
            numbers = [float(item) for item in value]
        except (TypeError, ValueError):
            continue
        if "orbital" in name and "energ" in name:
            energies = numbers
            if "eh" in name or "hartree" in name:
                unit = "eh"
            elif "ev" in name:
                unit = "ev"
        elif "occupation" in name:
            occupations = numbers
    if energies is None or occupations is None or len(energies) != len(occupations):
        return None
    if unit == "eh":
        energies = [value * _HARTREE_EV for value in energies]
    elif unit != "ev":
        return None
    return _homo_lumo_from_occupations(energies, occupations)


def _tblite_orbitals(mol: Chem.Mol, charge: int) -> dict[str, float] | None:
    with _tblite_lock:
        return _tblite_orbitals_unlocked(mol, charge)


def _tblite_orbitals_unlocked(mol: Chem.Mol, charge: int) -> dict[str, float] | None:
    import numpy as np
    from tblite.interface import Calculator

    count = mol.GetNumAtoms()
    conf = mol.GetConformer()
    numbers = np.array([atom.GetAtomicNum() for atom in mol.GetAtoms()], dtype=np.int32)
    positions = np.zeros((count, 3), dtype=np.float64)
    for index in range(count):
        point = conf.GetAtomPosition(index)
        positions[index, 0] = float(point.x)
        positions[index, 1] = float(point.y)
        positions[index, 2] = float(point.z)
    positions *= 1.88972612546  # Å → Bohr
    calc = Calculator("GFN2-xTB", numbers, positions, charge=int(charge), uhf=0)
    result = calc.singlepoint()
    raw_energies = _mapping_value(result, "orbital-energies")
    raw_occ = _mapping_value(result, "orbital-occupations")
    if raw_energies is None or raw_occ is None:
        return None
    energies = [float(value) * _HARTREE_EV for value in raw_energies]
    occupations = [float(value) for value in raw_occ]
    pair = _homo_lumo_from_occupations(energies, occupations)
    if pair is None:
        return None
    homo, lumo = pair
    return {"HOMO": homo, "LUMO": lumo, "HOMO_LUMO_GAP": lumo - homo}


def _mapping_value(result: object, key: str):
    getter = getattr(result, "get", None)
    if callable(getter):
        return getter(key)
    try:
        return result[key]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        return None


def _homo_lumo_from_occupations(
    energies: list[float],
    occupations: list[float],
) -> tuple[float, float] | None:
    homo: float | None = None
    lumo: float | None = None
    for energy, occupation in zip(energies, occupations):
        if occupation > 0.5:
            homo = energy
            continue
        lumo = energy
        break
    if homo is None or lumo is None:
        return None
    return homo, lumo


def _xyz_block(mol: Chem.Mol) -> str:
    conf = mol.GetConformer()
    lines = [str(mol.GetNumAtoms()), "molmanager GFN2-xTB"]
    for atom in mol.GetAtoms():
        point = conf.GetAtomPosition(atom.GetIdx())
        lines.append(
            f"{atom.GetSymbol():<2} {float(point.x):.8f} {float(point.y):.8f} {float(point.z):.8f}"
        )
    return "\n".join(lines) + "\n"


def _geometry_key(mol: Chem.Mol, charge: int) -> tuple:
    conf = mol.GetConformer()
    coords = []
    for atom in mol.GetAtoms():
        point = conf.GetAtomPosition(atom.GetIdx())
        coords.append(
            (
                int(atom.GetAtomicNum()),
                round(float(point.x), 4),
                round(float(point.y), 4),
                round(float(point.z), 4),
            )
        )
    return (int(charge), tuple(coords))


def _electron_count(mol: Chem.Mol, charge: int) -> int:
    nuclei = sum(int(atom.GetAtomicNum()) for atom in mol.GetAtoms())
    return nuclei - int(charge)


def _has_implicit_hydrogens(mol: Chem.Mol) -> bool:
    try:
        return any(int(atom.GetNumImplicitHs()) > 0 for atom in mol.GetAtoms())
    except (ValueError, RuntimeError):
        return True
