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

"""Open Babel Confab systematic conformer generation."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

from ..platform_support.bundled_paths import (
    apply_openbabel_runtime_env,
    default_external_executable,
    openbabel_launch_env,
    resolve_user_executable,
)
from ..platform_support.tool_paths import TOOL_OBABEL, effective_tool_path
from .conformer_column_codec import mol_has_3d_coordinates

logger = logging.getLogger(__name__)

MISSING_OPENBABEL_MSG = (
    "Open Babel is required for Systematic conformers. Install it with "
    "`pip install openbabel` (included in requirements-core), place obabel under "
    "resources/bin, put `obabel` on PATH, or set it under Settings → Configure → Open Babel."
)

CONFAB_CLI_TIMEOUT_S = 600
_FORCE_FIELD = "MMFF94"


@dataclass(frozen=True)
class SystematicConfParams:
    """Options for Open Babel Confab (Chemistry → Conformations → Generate → Systematic)."""

    num_confs: int = 100
    rmsd_cutoff: float = 0.5
    energy_cutoff: float = 50.0
    include_original: bool = False
    keep_hydrogens: bool = False
    obabel_path: str = ""


def python_confab_available(obabel_path: str = "") -> bool:
    """True when the Open Babel Python bindings expose Confab ``DiverseConfGen``."""
    ob = _openbabel_module(obabel_path)
    if ob is None:
        return False
    try:
        ff = ob.OBForceField.FindForceField("MMFF94") or ob.OBForceField.FindForceField("UFF")
    except Exception:
        return False
    if ff is None:
        return False
    return callable(getattr(ff, "DiverseConfGen", None))


def resolve_obabel_executable(user_path: str = "") -> str | None:
    """Resolve ``obabel`` from an explicit path, Configure, PATH, or the bundled directory."""
    text = effective_tool_path(TOOL_OBABEL, user_path)
    if text:
        found = resolve_user_executable(text)
        if found:
            return found
    return resolve_user_executable(default_external_executable("obabel"))


def ensure_openbabel_confab_ready(obabel_path: str = "") -> str | None:
    """Return an error string when neither Python Confab nor ``obabel`` is available."""
    if python_confab_available(obabel_path):
        return None
    if resolve_obabel_executable(obabel_path):
        return None
    return MISSING_OPENBABEL_MSG


def confab_cli_command(
    obabel: str, inp: Path, out: Path, params: SystematicConfParams
) -> list[str]:
    """Build the ``obabel --confab`` command used by the CLI backend."""
    cmd = [
        obabel,
        str(inp),
        "-O",
        str(out),
        "--confab",
        "--conf",
        str(max(1, int(params.num_confs))),
        "--rcutoff",
        f"{float(params.rmsd_cutoff):g}",
        "--ecutoff",
        f"{float(params.energy_cutoff):g}",
    ]
    if params.include_original:
        cmd.append("--original")
    return cmd


def run_systematic_conformer_generation(
    mol: Chem.Mol,
    params: SystematicConfParams,
    cancel_event: threading.Event | None = None,
) -> tuple[Chem.Mol | None, dict]:
    """
    Generate a Confab ensemble for *mol* and return ``(mol_or_None, meta)``.

    The input topology is preserved when Confab keeps the same atom order; otherwise
    the SDF records from Open Babel are merged. Hydrogens are removed unless
    ``keep_hydrogens`` is set.
    """
    meta: dict = {
        "ok": False,
        "n_requested": int(params.num_confs),
        "ewin_kcal": round(float(params.energy_cutoff), 4),
        "ff": _FORCE_FIELD,
        "op": "confab",
    }
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta
    if mol is None or mol.GetNumAtoms() == 0:
        meta["err"] = "empty_molecule"
        return None, meta

    missing = ensure_openbabel_confab_ready(params.obabel_path)
    if missing:
        meta["err"] = "openbabel_unavailable"
        return None, meta

    try:
        prepared = _prepare_mol_for_confab(mol)
    except Exception as e:
        meta["err"] = f"prepare:{e.__class__.__name__}"
        return None, meta
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta

    sdf_in = _mol_to_sdf(prepared)
    try:
        sdf_out = _run_confab(sdf_in, params)
    except Exception as e:
        logger.exception("Confab failed")
        meta["err"] = str(e)[:200]
        return None, meta
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta

    sdf_mols = list(iter_sdf_mols(sdf_out))
    meta["n_embedded"] = len(sdf_mols)
    if not sdf_mols:
        meta["err"] = "no_confab_confs"
        return None, meta

    combined = apply_sdf_conformers(prepared, sdf_mols)
    if combined is None or combined.GetNumConformers() < 1:
        meta["err"] = "confab_merge_failed"
        return None, meta

    if not params.keep_hydrogens:
        try:
            combined = Chem.RemoveHs(combined)
        except Exception:
            pass
    else:
        meta["keep_hs"] = True

    meta["n_kept"] = int(combined.GetNumConformers())
    meta["ok"] = True
    return combined, meta


def iter_sdf_mols(sdf: str) -> list[Chem.Mol]:
    """Parse SDF text into molecules that have at least one conformer."""
    text = sdf or ""
    if not text.strip():
        return []
    payload = text.encode("utf-8")
    suppl = Chem.ForwardSDMolSupplier(BytesIO(payload), removeHs=False, sanitize=True)
    mols: list[Chem.Mol] = []
    for mol in suppl:
        if mol is None:
            continue
        try:
            if int(mol.GetNumConformers()) < 1:
                continue
        except Exception:
            continue
        mols.append(mol)
    if mols:
        return mols
    # Fallback when the supplier rejects the block but MolFromMolBlock can parse records.
    for record in text.replace("\r\n", "\n").split("$$$$"):
        body = record.strip("\r\n")
        if not body.strip():
            continue
        mol = Chem.MolFromMolBlock(body, sanitize=True, removeHs=False)
        if mol is None or mol.GetNumConformers() < 1:
            continue
        mols.append(mol)
    return mols


def apply_sdf_conformers(template: Chem.Mol, sdf_mols: list[Chem.Mol]) -> Chem.Mol | None:
    """Copy Confab coordinates onto *template* when atom order matches; else merge SDF mols."""
    if not sdf_mols:
        return None
    n_atoms = int(template.GetNumAtoms())
    out = Chem.Mol(template)
    out.RemoveAllConformers()
    used = 0
    for mol in sdf_mols:
        if mol is None or int(mol.GetNumAtoms()) != n_atoms or mol.GetNumConformers() < 1:
            continue
        if not _same_element_order(out, mol):
            continue
        try:
            out.AddConformer(Chem.Conformer(mol.GetConformer()), assignId=True)
            used += 1
        except Exception:
            continue
    if used:
        return out
    return _merge_sdf_mols(sdf_mols)


def _merge_sdf_mols(mols: list[Chem.Mol]) -> Chem.Mol | None:
    usable = [m for m in mols if m is not None and m.GetNumConformers() >= 1]
    if not usable:
        return None
    n_atoms = int(usable[0].GetNumAtoms())
    base = Chem.Mol(usable[0])
    base.RemoveAllConformers()
    for mol in usable:
        if int(mol.GetNumAtoms()) != n_atoms:
            continue
        try:
            base.AddConformer(Chem.Conformer(mol.GetConformer()), assignId=True)
        except Exception:
            continue
    if base.GetNumConformers() < 1:
        return None
    return base


def _same_element_order(a: Chem.Mol, b: Chem.Mol) -> bool:
    if a.GetNumAtoms() != b.GetNumAtoms():
        return False
    for i in range(a.GetNumAtoms()):
        if a.GetAtomWithIdx(i).GetAtomicNum() != b.GetAtomWithIdx(i).GetAtomicNum():
            return False
    return True


def _openbabel_module(obabel_path: str = ""):
    ob = None
    try:
        from openbabel import openbabel as ob
    except ImportError:
        try:
            import openbabel as ob
        except ImportError:
            return None
    try:
        apply_openbabel_runtime_env(obabel_path)
    except Exception:
        logger.debug("Open Babel runtime env not applied", exc_info=True)
    return ob


def _prepare_mol_for_confab(mol: Chem.Mol) -> Chem.Mol:
    """Add hydrogens and ensure a 3D starting geometry (Confab requires 3D input)."""
    m = Chem.Mol(mol)
    try:
        Chem.SanitizeMol(m)
    except Exception:
        pass
    mh = Chem.AddHs(m, addCoords=True)
    if mol_has_3d_coordinates(mh):
        return mh
    embed = None
    for name in ("ETKDGv3", "ETKDGv2", "ETKDG"):
        factory = getattr(AllChem, name, None)
        if factory is None:
            continue
        try:
            embed = factory()
            embed.randomSeed = 0xC0FFEE
            break
        except Exception:
            continue
    if embed is None:
        raise RuntimeError("no_etkdg")
    if int(AllChem.EmbedMolecule(mh, embed)) != 0:
        raise RuntimeError("embed_failed")
    try:
        AllChem.MMFFOptimizeMolecule(mh, maxIters=80)
    except Exception:
        try:
            AllChem.UFFOptimizeMolecule(mh, maxIters=80)
        except Exception:
            pass
    return mh


def _mol_to_sdf(mol: Chem.Mol) -> str:
    block = Chem.MolToMolBlock(mol)
    if not block.endswith("\n"):
        block += "\n"
    if "$$$$" not in block:
        block += "$$$$\n"
    return block


def _run_confab(sdf: str, params: SystematicConfParams) -> str:
    apply_openbabel_runtime_env(params.obabel_path)
    if python_confab_available(params.obabel_path):
        try:
            return _run_confab_python(sdf, params)
        except Exception:
            logger.debug("Python Confab failed; trying obabel CLI", exc_info=True)
    exe = resolve_obabel_executable(params.obabel_path)
    if not exe:
        raise RuntimeError("openbabel_unavailable")
    return _run_confab_cli(sdf, params, exe)


def _run_confab_python(sdf: str, params: SystematicConfParams) -> str:
    ob = _openbabel_module(params.obabel_path)
    if ob is None:
        raise RuntimeError("openbabel_unavailable")
    conv = ob.OBConversion()
    conv.SetInFormat("sdf")
    obmol = ob.OBMol()
    if not conv.ReadString(obmol, sdf):
        raise RuntimeError("openbabel_read")
    obmol.AddHydrogens()
    ff = ob.OBForceField.FindForceField("MMFF94")
    if ff is None or not ff.Setup(obmol):
        ff = ob.OBForceField.FindForceField("UFF")
        if ff is None or not ff.Setup(obmol):
            raise RuntimeError("forcefield_setup")
    ff.DiverseConfGen(
        float(params.rmsd_cutoff),
        max(1, int(params.num_confs)),
        float(params.energy_cutoff),
        False,
    )
    ff.GetConformers(obmol)
    n = int(obmol.NumConformers())
    if n < 1:
        raise RuntimeError("no_confab_confs")
    start = 0
    end = n
    # DiverseConfGen typically appends the input geometry as the last conformer.
    # Keep a lone conformer even when include_original is off.
    if not params.include_original and n > 1:
        end = n - 1
    conv.SetOutFormat("sdf")
    parts: list[str] = []
    for i in range(start, end):
        obmol.SetConformer(i)
        parts.append(conv.WriteString(obmol))
    out = "".join(parts)
    if not out.strip():
        raise RuntimeError("no_confab_confs")
    return out


def _run_confab_cli(sdf: str, params: SystematicConfParams, obabel: str) -> str:
    env = os.environ.copy()
    env.update(openbabel_launch_env(obabel))
    with tempfile.TemporaryDirectory(prefix="molmanager_confab_") as tmp:
        tmp_path = Path(tmp)
        inp = tmp_path / "in.sdf"
        out = tmp_path / "out.sdf"
        inp.write_text(sdf, encoding="utf-8")
        cmd = confab_cli_command(obabel, inp, out, params)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=CONFAB_CLI_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("confab_timeout") from e
        if not out.is_file():
            err = ((proc.stderr or proc.stdout or "") + "").strip()[:200]
            raise RuntimeError(err or f"obabel_exit_{proc.returncode}")
        text = out.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            return text
        err = ((proc.stderr or proc.stdout or "") + "").strip()[:200]
        raise RuntimeError(err or f"obabel_exit_{proc.returncode}")
