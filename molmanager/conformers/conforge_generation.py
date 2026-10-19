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

"""CONFORGE (CDPKit) conformer generation via Python bindings or the ``confgen`` CLI."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

from ..platform_support.bundled_paths import (
    default_external_executable,
    resolve_user_executable,
    system_cdpkit_confgen,
)
from .conformer_column_codec import mol_has_3d_coordinates
from .openbabel_confab import apply_sdf_conformers, iter_sdf_mols

logger = logging.getLogger(__name__)

CDPKIT_RELEASES_URL = "https://github.com/molinfo-vienna/CDPKit/releases"
MISSING_CONFORGE_MSG = (
    "CONFORGE (CDPKit) is required. On Windows, PyPI has no cdpkit wheel for Python 3.11, "
    "so `pip install cdpkit` tries to compile from source and fails without Boost. "
    f"Install the CDPKit Windows MSVC package from {CDPKIT_RELEASES_URL}, then Browse to "
    r"confgen.exe (usually C:\Program Files\CDPKit\Bin\confgen.exe) or add that Bin folder "
    "to PATH. On Linux/macOS, `pip install cdpkit` works when a wheel exists for your Python."
)

CONFGEN_PROCESS_PAD_S = 60
CONFORGE_PRESETS = (
    "SMALL_SET_DIVERSE",
    "MEDIUM_SET_DIVERSE",
    "LARGE_SET_DIVERSE",
    "SMALL_SET_DENSE",
    "MEDIUM_SET_DENSE",
    "LARGE_SET_DENSE",
)
CONFORGE_MODES = ("AUTO", "SYSTEMATIC", "STOCHASTIC")
_FORCE_FIELD = "MMFF94"


@dataclass(frozen=True)
class ConforgeParams:
    """Options for Chemistry → Conformations → Generate → CONFORGE."""

    num_confs: int = 100
    energy_window: float = 15.0
    rmsd_cutoff: float = 0.5
    mode: str = "AUTO"
    preset: str = "MEDIUM_SET_DIVERSE"
    timeout_s: int = 3600
    include_input: bool = False
    from_scratch: bool = True
    keep_hydrogens: bool = False
    confgen_path: str = ""


def python_conforge_available() -> bool:
    """True when CDPKit Python bindings expose ``ConfGen.ConformerGenerator``."""
    try:
        from CDPL import ConfGen  # noqa: F401
        from CDPL.ConfGen import ConformerGenerator  # noqa: F401
    except Exception:
        return False
    return True


def resolve_confgen_executable(user_path: str = "") -> str | None:
    """Resolve ``confgen`` from an explicit path, PATH, bundled dir, or CDPKit install."""
    text = (user_path or "").strip()
    if text:
        found = resolve_user_executable(text)
        if found:
            return found
    found = resolve_user_executable(default_external_executable("confgen"))
    if found:
        return found
    cdpkit = system_cdpkit_confgen()
    return str(cdpkit) if cdpkit is not None else None


def ensure_conforge_ready(confgen_path: str = "") -> str | None:
    """Return an error string when neither CDPKit Python nor ``confgen`` is available."""
    if python_conforge_available():
        return None
    if resolve_confgen_executable(confgen_path):
        return None
    return MISSING_CONFORGE_MSG


def normalize_conforge_preset(name: str) -> str:
    text = (name or "").strip().upper().replace(" ", "_").replace("-", "_")
    return text if text in CONFORGE_PRESETS else "MEDIUM_SET_DIVERSE"


def normalize_conforge_mode(name: str) -> str:
    text = (name or "").strip().upper()
    return text if text in CONFORGE_MODES else "AUTO"


def confgen_cli_command(confgen: str, inp: Path, out: Path, params: ConforgeParams) -> list[str]:
    """Build the ``confgen`` command used by the CLI backend."""
    timeout_s = max(0, int(params.timeout_s))
    cmd = [
        confgen,
        "-i",
        str(inp),
        "-o",
        str(out),
        "-C",
        normalize_conforge_preset(params.preset),
        "-m",
        normalize_conforge_mode(params.mode),
        "-e",
        f"{float(params.energy_window):g}",
        "-r",
        f"{float(params.rmsd_cutoff):g}",
        "-n",
        str(max(0, int(params.num_confs))),
        "-T",
        str(timeout_s),
        "-t",
        "0",
        "-v",
        "QUIET",
        "-p",
        "0",
    ]
    if params.include_input:
        cmd.extend(["-u", "1"])
    if not params.from_scratch:
        cmd.extend(["-S", "0"])
    return cmd


def run_conforge_generation(
    mol: Chem.Mol,
    params: ConforgeParams,
    cancel_event: threading.Event | None = None,
) -> tuple[Chem.Mol | None, dict]:
    """
    Generate a CONFORGE ensemble for *mol* and return ``(mol_or_None, meta)``.

    Hydrogens are removed unless ``keep_hydrogens`` is set. CONFORGE does not
    require input 3D coordinates unless the input pose is kept.
    """
    meta: dict = {
        "ok": False,
        "n_requested": int(params.num_confs),
        "ewin_kcal": round(float(params.energy_window), 4),
        "ff": _FORCE_FIELD,
        "op": "conforge",
        "preset": normalize_conforge_preset(params.preset),
        "mode": normalize_conforge_mode(params.mode),
    }
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta
    if mol is None or mol.GetNumAtoms() == 0:
        meta["err"] = "empty_molecule"
        return None, meta

    missing = ensure_conforge_ready(params.confgen_path)
    if missing:
        meta["err"] = "conforge_unavailable"
        return None, meta

    try:
        prepared = _prepare_mol_for_conforge(mol, params)
    except Exception as e:
        meta["err"] = f"prepare:{e.__class__.__name__}"
        return None, meta
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta

    sdf_in = _mol_to_sdf(prepared)
    try:
        sdf_out = _run_conforge(sdf_in, params)
    except Exception as e:
        logger.exception("CONFORGE failed")
        meta["err"] = str(e)[:200]
        return None, meta
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta

    sdf_mols = list(iter_sdf_mols(sdf_out))
    meta["n_embedded"] = len(sdf_mols)
    if not sdf_mols:
        meta["err"] = "no_conforge_confs"
        return None, meta

    combined = apply_sdf_conformers(prepared, sdf_mols)
    if combined is None or combined.GetNumConformers() < 1:
        meta["err"] = "conforge_merge_failed"
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


def _mol_to_sdf(mol: Chem.Mol) -> str:
    block = Chem.MolToMolBlock(mol)
    if not block.endswith("\n"):
        block += "\n"
    if "$$$$" not in block:
        block += "$$$$\n"
    return block


def _prepare_mol_for_conforge(mol: Chem.Mol, params: ConforgeParams) -> Chem.Mol:
    """Add hydrogens; embed once when the input pose is kept but the ligand is 2D."""
    m = Chem.Mol(mol)
    try:
        Chem.SanitizeMol(m)
    except Exception:
        pass
    mh = Chem.AddHs(m, addCoords=True)
    need_input_3d = bool(params.include_input) and not bool(params.from_scratch)
    if not need_input_3d or mol_has_3d_coordinates(mh):
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
    return mh


def _run_conforge(sdf: str, params: ConforgeParams) -> str:
    py_err: Exception | None = None
    if python_conforge_available():
        try:
            return _run_conforge_python(sdf, params)
        except Exception as e:
            py_err = e
            logger.debug("CDPKit Python CONFORGE failed; trying confgen CLI", exc_info=True)
    exe = resolve_confgen_executable(params.confgen_path)
    if not exe:
        if py_err is not None:
            raise py_err
        raise RuntimeError("conforge_unavailable")
    return _run_conforge_cli(sdf, params, exe)


def _run_conforge_python(sdf: str, params: ConforgeParams) -> str:
    import CDPL.Chem as CdChem
    import CDPL.ConfGen as ConfGen

    with tempfile.TemporaryDirectory(prefix="mm_conforge_") as tmp:
        inp = Path(tmp) / "in.sdf"
        out = Path(tmp) / "out.sdf"
        inp.write_text(sdf, encoding="utf-8")
        reader = CdChem.MoleculeReader(str(inp))
        mol = CdChem.BasicMolecule()
        try:
            if not reader.read(mol):
                raise RuntimeError("cdpl_read_failed")
        finally:
            closer = getattr(reader, "close", None)
            if callable(closer):
                closer()
        ConfGen.prepareForConformerGeneration(mol)
        gen = ConfGen.ConformerGenerator()
        _apply_python_settings(gen, params)
        status = gen.generate(mol)
        ok = _python_success_codes(ConfGen)
        if int(status) not in ok:
            raise RuntimeError(_python_status_label(ConfGen, status))
        gen.setConformers(mol)
        writer = CdChem.MolecularGraphWriter(str(out))
        multi = getattr(CdChem, "setMultiConfExportParameter", None)
        if callable(multi):
            try:
                multi(writer, True)
            except Exception:
                logger.debug("CONFORGE multi-conf export flag failed", exc_info=True)
        try:
            if not writer.write(mol):
                raise RuntimeError("cdpl_write_failed")
        finally:
            closer = getattr(writer, "close", None)
            if callable(closer):
                closer()
        return out.read_text(encoding="utf-8", errors="replace")


def _set_cdpl_attr(obj: object, names: tuple[str, ...], value: object) -> None:
    for name in names:
        if not hasattr(obj, name):
            continue
        try:
            setattr(obj, name, value)
            return
        except Exception:
            logger.debug("CONFORGE setting %s failed", name, exc_info=True)


def _apply_python_settings(gen, params: ConforgeParams) -> None:
    from CDPL import ConfGen

    settings = gen.settings
    preset = getattr(
        ConfGen.ConformerGeneratorSettings, normalize_conforge_preset(params.preset), None
    )
    if preset is not None:
        assign = getattr(settings, "assign", None)
        if callable(assign):
            try:
                assign(preset)
                settings = gen.settings
            except Exception:
                logger.debug("CONFORGE preset assign failed", exc_info=True)
        else:
            try:
                gen.settings = preset
                settings = gen.settings
            except Exception:
                logger.debug("CONFORGE preset copy failed", exc_info=True)
    mode = getattr(ConfGen.ConformerSamplingMode, normalize_conforge_mode(params.mode), None)
    if mode is not None:
        _set_cdpl_attr(settings, ("samplingMode",), mode)
    _set_cdpl_attr(settings, ("maxNumOutputConformers",), max(0, int(params.num_confs)))
    _set_cdpl_attr(settings, ("energyWindow",), float(params.energy_window))
    _set_cdpl_attr(settings, ("minRMSD",), float(params.rmsd_cutoff))
    _set_cdpl_attr(settings, ("timeout",), max(0, int(params.timeout_s)) * 1000)
    _set_cdpl_attr(
        settings,
        ("includeInput", "includeInputCoords", "includeInputCoordinates"),
        bool(params.include_input),
    )
    _set_cdpl_attr(
        settings,
        ("generateCoordinatesFromScratch", "genCoordsFromScratch"),
        bool(params.from_scratch),
    )


def _python_success_codes(conf_gen_mod) -> set[int]:
    codes = {0}
    for name in ("SUCCESS", "TOO_MUCH_SYMMETRY"):
        val = getattr(getattr(conf_gen_mod, "ReturnCode", None), name, None)
        if val is not None:
            try:
                codes.add(int(val))
            except (TypeError, ValueError):
                continue
    return codes


def _python_status_label(conf_gen_mod, status: object) -> str:
    try:
        code = int(status)
    except (TypeError, ValueError):
        return f"conforge_status:{status}"
    rc = getattr(conf_gen_mod, "ReturnCode", None)
    names = (
        "TIMEOUT",
        "ABORTED",
        "FORCEFIELD_SETUP_FAILED",
        "FORCEFIELD_MINIMIZATION_FAILED",
        "FRAGMENT_LIBRARY_NOT_SET",
        "FRAGMENT_CONF_GEN_FAILED",
        "FRAGMENT_CONF_GEN_TIMEOUT",
        "TORSION_DRIVING_FAILED",
        "CONF_GEN_FAILED",
        "NO_FIXED_SUBSTRUCT_COORDS",
        "TOO_MUCH_SYMMETRY",
        "SUCCESS",
    )
    for name in names:
        val = getattr(rc, name, None)
        try:
            if val is not None and int(val) == code:
                return str(name).lower()
        except (TypeError, ValueError):
            continue
    return f"conforge_status:{code}"


def _run_conforge_cli(sdf: str, params: ConforgeParams, exe: str) -> str:
    timeout_s = max(1, int(params.timeout_s) + CONFGEN_PROCESS_PAD_S)
    with tempfile.TemporaryDirectory(prefix="mm_conforge_") as tmp:
        inp = Path(tmp) / "in.sdf"
        out = Path(tmp) / "out.sdf"
        inp.write_text(sdf, encoding="utf-8")
        cmd = confgen_cli_command(exe, inp, out, params)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise RuntimeError(err[:200])
        if not out.is_file():
            raise RuntimeError("confgen_no_output")
        return out.read_text(encoding="utf-8", errors="replace")
