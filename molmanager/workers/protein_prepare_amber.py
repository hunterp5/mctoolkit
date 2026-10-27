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

"""AmberTools GAFF/GAFF2 parameterization for Protein Prepare (WSL on Windows)."""

from __future__ import annotations

from collections.abc import Sequence
from io import StringIO
from pathlib import Path

from .protein_prepare_constants import (
    _LIGAND_FF_GAFF,
    _LIGAND_FF_GAFF2,
    _LIGAND_FF_NONE,
    _PROTEIN_FF_AMBER14,
    _PROTEIN_FF_AMBER99,
    _SOLVENT_GBN2,
    _SOLVENT_OBC2,
    _SOLVENT_VACUUM,
    ResidueKey,
)
from .protein_prepare_io import _is_cif_path, _open_openmm_structure, _write_text, log_prepare

_ANTECHAMBER_TIMEOUT_S = 900.0
_PARMCHK_TIMEOUT_S = 120.0
_TLEAP_TIMEOUT_S = 180.0
_WHICH_TIMEOUT_S = 20.0

_HIS_RESNS = frozenset({"HIS", "HID", "HIE", "HIP", "HSD", "HSE", "HSP"})
_HIS_HD1_ATOMS = frozenset({"HD1", "1HD", "HND1"})
_HIS_HE2_ATOMS = frozenset({"HE2", "2HE", "HNE2"})
_HIS_CHARMM_TO_AMBER = {"HSD": "HID", "HSE": "HIE", "HSP": "HIP"}


def _normalize_ligand_ff(name: str) -> str:
    raw = (name or _LIGAND_FF_NONE).strip().lower().replace(" ", "")
    if raw in {_LIGAND_FF_GAFF2, "gaff-2.11", "gaff-2.2.1", "gaff2.11"}:
        return _LIGAND_FF_GAFF2
    if raw in {_LIGAND_FF_GAFF, "gaff1", "gaff-1.81"}:
        return _LIGAND_FF_GAFF
    return _LIGAND_FF_NONE


def _ligand_ff_is_gaff(name: str) -> bool:
    return _normalize_ligand_ff(name) in {_LIGAND_FF_GAFF, _LIGAND_FF_GAFF2}


def _ligand_ff_tag(name: str) -> str:
    ff = _normalize_ligand_ff(name)
    if ff == _LIGAND_FF_GAFF2:
        return "GAFF2"
    if ff == _LIGAND_FF_GAFF:
        return "GAFF"
    return ""


def _gaff_atom_type(name: str) -> str:
    return "gaff2" if _normalize_ligand_ff(name) == _LIGAND_FF_GAFF2 else "gaff"


def _leaprc_protein(protein_ff: str) -> str:
    raw = (protein_ff or _PROTEIN_FF_AMBER14).strip().lower()
    if raw in {_PROTEIN_FF_AMBER99, "amber99", "ff99sbildn"}:
        return "oldff/leaprc.ff99SBildn"
    return "leaprc.protein.ff14SB"


def _leaprc_gaff(ligand_ff: str) -> str:
    return "leaprc.gaff2" if _normalize_ligand_ff(ligand_ff) == _LIGAND_FF_GAFF2 else "leaprc.gaff"


def _pbradii(solvent: str) -> str | None:
    raw = (solvent or _SOLVENT_GBN2).strip().lower()
    if raw in {_SOLVENT_VACUUM, "none", "vac"}:
        return None
    if raw in {_SOLVENT_OBC2, "obc", "gbsa-obc"}:
        return "mbondi2"
    return "mbondi3"


def leap_input(
    *,
    protein_pdb: str,
    ligands: Sequence[tuple[str, str, str]],
    protein_ff: str,
    ligand_ff: str,
    keep_water: bool,
    solvent: str,
    prmtop: str,
    inpcrd: str,
) -> str:
    """tleap script: protein AMBER + GAFF ligand units combined in place."""
    lines = [
        f"source {_leaprc_protein(protein_ff)}",
        f"source {_leaprc_gaff(ligand_ff)}",
    ]
    if keep_water:
        lines.append("source leaprc.water.tip3p")
    radii = _pbradii(solvent)
    if radii:
        lines.append(f"set default PBradii {radii}")
    unit_names: list[str] = []
    for i, (mol2, frcmod, _resn) in enumerate(ligands):
        unit = f"LIG{i}"
        unit_names.append(unit)
        lines.append(f"loadamberparams {frcmod}")
        lines.append(f"{unit} = loadMol2 {mol2}")
    lines.append(f"PROT = loadPdb {protein_pdb}")
    combo = " ".join(["PROT", *unit_names])
    lines.append(f"COMP = combine {{ {combo} }}")
    lines.append(f"saveAmberParm COMP {prmtop} {inpcrd}")
    lines.append("quit")
    return "\n".join(lines) + "\n"


def ligand_only_leap_input(
    *,
    mol2: str,
    frcmod: str,
    ligand_ff: str,
    prmtop: str,
    inpcrd: str,
) -> str:
    """tleap script: vacuum GAFF ligand (no protein)."""
    return (
        f"source {_leaprc_gaff(ligand_ff)}\n"
        f"loadamberparams {frcmod}\n"
        f"LIG = loadMol2 {mol2}\n"
        f"saveAmberParm LIG {prmtop} {inpcrd}\n"
        "quit\n"
    )


def _proc_tail(proc, extra: str = "") -> str:
    parts = [
        (proc.stderr or "").strip(),
        (proc.stdout or "").strip(),
        (extra or "").strip(),
    ]
    text = "\n".join(p for p in parts if p)
    if len(text) > 2500:
        text = text[-2500:]
    return text


_AMBER_BASENAMES = frozenset(
    {
        "antechamber",
        "parmchk2",
        "tleap",
        "antechamber.exe",
        "parmchk2.exe",
        "tleap.exe",
    }
)


def _amber_missing_message() -> str:
    return (
        "AmberTools (antechamber) was not found. On Windows install AmberTools in "
        "WSL and set Settings → Configure → WSL so a login shell can see `antechamber` "
        "on PATH (conda activate in ~/.bashrc, or apt), or set the binary under "
        "Settings → Configure → AmberTools. On Linux put AmberTools on PATH or set "
        "that same AmberTools entry."
    )


def _split_tool_path(path: str) -> tuple[str, str, str]:
    """Return ``(parent, separator, leaf)`` without changing slash style."""
    text = (path or "").strip().strip('"')
    if "\\" in text and "/" not in text:
        parent, leaf = text.rsplit("\\", 1)
        return parent, "\\", leaf
    if "/" in text:
        parent, leaf = text.rsplit("/", 1)
        return parent, "/", leaf
    return "", "", text


def _join_tool_path(directory: str, name: str) -> str:
    text = directory.rstrip("/\\")
    if "\\" in text and "/" not in text:
        return f"{text}\\{name}"
    return f"{text}/{name}"


def _command_is_path(command: str) -> bool:
    text = (command or "").strip()
    if text.startswith(("/", "\\")):
        return True
    return len(text) >= 3 and text[1] == ":" and text[2] in {"\\", "/"}


def amber_program(name: str, user_path: str = "") -> str:
    """Command for ``antechamber``, ``parmchk2``, or ``tleap``.

    *user_path* may be empty (Settings → Configure → AmberTools), a bare command,
    a bin directory, or one of those executables. Sibling tools stay beside it.
    """
    if name not in {"antechamber", "parmchk2", "tleap"}:
        raise ValueError(f"Unknown AmberTools program: {name}")
    raw = (user_path or "").strip().strip('"')
    if not raw:
        from ..platform_support.tool_paths import TOOL_AMBER, configured_executable

        raw = configured_executable(TOOL_AMBER).strip().strip('"')
    if not raw:
        return name
    parent, sep, leaf = _split_tool_path(raw)
    leaf_l = leaf.lower()
    if leaf_l in _AMBER_BASENAMES:
        suffix = ".exe" if leaf_l.endswith(".exe") else ""
        if not sep:
            return f"{name}{suffix}"
        return f"{parent}{sep}{name}{suffix}"
    if sep or raw.endswith(("/", "\\")) or Path(raw).expanduser().is_dir():
        return _join_tool_path(raw, name)
    return raw if name == "antechamber" else name


def _amber_probe_argv(command: str) -> list[str]:
    from ..platform_support.wsl_launcher import linux_path

    text = (command or "antechamber").strip()
    if _command_is_path(text):
        return ["test", "-x", linux_path(text)]
    which_name = "antechamber" if text.lower() in {"antechamber", "antechamber.exe"} else text
    return ["which", which_name]


def ambertools_available(*, timeout: float = _WHICH_TIMEOUT_S, user_path: str = "") -> bool:
    """True when ``antechamber`` is on the Linux/WSL PATH or at the configured path."""
    from ..platform_support.wsl_launcher import run_linux_tool

    argv = _amber_probe_argv(amber_program("antechamber", user_path))
    try:
        proc = run_linux_tool(argv, work_dir=Path("."), timeout=timeout)
    except FileNotFoundError:
        return False
    except Exception:
        return False
    if argv[0] == "which":
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    return proc.returncode == 0


def describe_ambertools(user_path: str = "") -> tuple[bool, str]:
    """Status line for Settings → Configure → AmberTools."""
    cmd = amber_program("antechamber", user_path)
    if ambertools_available(user_path=user_path):
        return True, f"OK: {cmd}"
    return False, _amber_missing_message()


def _require_ambertools() -> None:
    if not ambertools_available():
        raise RuntimeError(_amber_missing_message())


def _amber_resn(resn: str) -> str:
    text = (resn or "LIG").strip().upper() or "LIG"
    return text[:3]


def _formal_charge(mol) -> int:
    from rdkit import Chem

    try:
        return int(Chem.GetFormalCharge(mol))
    except Exception:
        return 0


def _mol2_has_atoms(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return "@<TRIPOS>ATOM" in text and any(
        line.strip() and not line.startswith("@")
        for line in text.split("@<TRIPOS>ATOM", 1)[-1].splitlines()[1:]
    )


def _parameterize_ligand(
    stem: str,
    *,
    charge: int,
    atom_type: str,
    resn: str,
    work_dir: Path,
) -> str:
    """Run antechamber + parmchk2. Returns the charge-method tag used."""
    from ..platform_support.wsl_launcher import run_linux_tool

    gaff_mol2 = f"{stem}_gaff.mol2"
    frcmod = f"{stem}.frcmod"
    last = None
    used = ""
    for method, label, extra in (
        ("bcc", "AM1-BCC", []),
        ("gas", "GASTEIGER", ["-dr", "no"]),
    ):
        argv = [
            amber_program("antechamber"),
            "-i",
            f"{stem}.mol2",
            "-fi",
            "mol2",
            "-o",
            gaff_mol2,
            "-fo",
            "mol2",
            "-c",
            method,
            "-nc",
            str(int(charge)),
            "-at",
            atom_type,
            "-rn",
            resn,
            "-s",
            "2",
            *extra,
        ]
        try:
            proc = run_linux_tool(argv, work_dir=work_dir, timeout=_ANTECHAMBER_TIMEOUT_S)
        except FileNotFoundError as exc:
            raise RuntimeError(_amber_missing_message()) from exc
        last = proc
        if proc.returncode == 0 and _mol2_has_atoms(work_dir / gaff_mol2):
            used = label
            break
        if method == "bcc":
            log_prepare("AmberTools: AM1-BCC failed; retrying with Gasteiger charges")
    if not used:
        detail = _proc_tail(last) if last is not None else ""
        raise RuntimeError(
            "AmberTools antechamber failed to assign GAFF atom types. " + (detail or "")
        )
    parm_s = "2" if atom_type == "gaff2" else "1"
    try:
        proc = run_linux_tool(
            [amber_program("parmchk2"), "-i", gaff_mol2, "-f", "mol2", "-o", frcmod, "-s", parm_s],
            work_dir=work_dir,
            timeout=_PARMCHK_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(_amber_missing_message()) from exc
    if proc.returncode != 0 or not (work_dir / frcmod).is_file():
        raise RuntimeError("AmberTools parmchk2 failed. " + _proc_tail(proc))
    return used


def _amber_histidine_resn(atom_names: set[str], current: str) -> str:
    """HID / HIE / HIP from ND1 vs NE2 hydrogens (Amber ff14SB templates)."""
    names = {(name or "").strip().upper() for name in atom_names}
    has_hd1 = bool(names & _HIS_HD1_ATOMS)
    has_he2 = bool(names & _HIS_HE2_ATOMS)
    if has_hd1 and has_he2:
        return "HIP"
    if has_hd1:
        return "HID"
    if has_he2:
        return "HIE"
    cur = (current or "HIS").strip().upper()
    return _HIS_CHARMM_TO_AMBER.get(cur, cur if cur in {"HIS", "HID", "HIE", "HIP"} else "HIS")


def relabel_amber_histidines_pdb(text: str) -> str:
    """Match HIS tautomer residue names to the hydrogens tleap will see.

    OpenMM ``PDBFile.writeFile`` can emit HIE while leaving HID's ``HD1`` atoms,
    which tleap then rejects (``Atom .R<HIE n>.A<HD1> does not have a type``).
    """
    from collections import defaultdict

    from ..protein.structure_components import _norm_chain, rewrite_pdb_residue_names

    atoms_by_key: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    resn_by_key: dict[tuple[str, str, str], str] = {}
    for line in (text or "").splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec not in {"ATOM", "HETATM"}:
            continue
        padded = line.ljust(80)
        resn = padded[17:20].strip().upper()
        if resn not in _HIS_RESNS:
            continue
        chain = _norm_chain(padded[21:22])
        resi = padded[22:26].strip() or "0"
        icode = padded[26:27].strip()
        key = (chain, resi, icode)
        atoms_by_key[key].add(padded[12:16].strip().upper())
        resn_by_key[key] = resn
    changes: list[tuple[str, str, str, str]] = []
    for key, names in atoms_by_key.items():
        new_resn = _amber_histidine_resn(names, resn_by_key[key])
        if new_resn != resn_by_key[key]:
            chain, resi, icode = key
            changes.append((chain, resi, icode, new_resn))
    if not changes:
        return text
    return rewrite_pdb_residue_names(text, changes)


def _write_protein_pdb(holo: Path, dest: Path, ligand_keys: set[ResidueKey]) -> None:
    """Ligand-stripped PDB for tleap (AMBER names, hydrogens kept)."""
    text = holo.read_text(encoding="utf-8", errors="replace")
    if _is_cif_path(holo):
        from ..protein.structure_components import delete_cif_residues

        stripped = delete_cif_residues(text, ligand_keys)
        scratch = dest.with_suffix(".cif")
    else:
        from ..protein.structure_components import delete_pdb_residues

        stripped = delete_pdb_residues(text, ligand_keys)
        scratch = dest.with_name(dest.stem + ".src.pdb")
    scratch.write_text(stripped, encoding="utf-8", newline="\n")
    try:
        pdb = _open_openmm_structure(scratch)
        from openmm.app import PDBFile

        buf = StringIO()
        PDBFile.writeFile(pdb.topology, pdb.positions, buf, keepIds=True)
        raw = buf.getvalue()
        labeled = relabel_amber_histidines_pdb(raw)
        if labeled != raw:
            log_prepare("AmberTools: renamed histidines to HID/HIE/HIP from ND1/NE2 hydrogens.")
        _write_text(dest, labeled)
    finally:
        try:
            scratch.unlink()
        except OSError:
            pass


def build_gaff_prmtop(
    holo_path: Path,
    *,
    ligand_mols: Sequence,
    ligand_keys: set[ResidueKey],
    keep_water: bool,
    protein_ff: str,
    ligand_ff: str,
    solvent: str,
    work_dir: Path,
    box_shape: str = "",
    box_padding_a: float = 0.0,
    ion_mode: str = "",
    cation: str = "Na+",
    anion: str = "Cl-",
    ion_conc_m: float = 0.0,
    write_split: bool = False,
    explicit_solvent: str = "",
) -> tuple[Path, Path, str]:
    """Parameterize ligands with AmberTools and build a holo prmtop/inpcrd.

    Returns ``(prmtop, inpcrd, charge_method_tag)``. ``explicit_solvent`` and
    ``write_split`` select the simulation tleap script, which also writes
    receptor, ligand, and dry-complex topologies.
    """
    from .protein_prepare_ligand import ligand_residue_blocks, write_ligand_mol2

    log_prepare(f"AmberTools: looking up {amber_program('antechamber')}…")
    _require_ambertools()
    ff = _normalize_ligand_ff(ligand_ff)
    if not _ligand_ff_is_gaff(ff):
        raise RuntimeError(f"Not a GAFF ligand force field: {ligand_ff}")
    atom_type = _gaff_atom_type(ff)
    fmt = "cif" if _is_cif_path(holo_path) else "pdb"
    text = holo_path.read_text(encoding="utf-8", errors="replace")
    blocks = ligand_residue_blocks(text, ligand_keys, fmt=fmt)
    if not blocks:
        raise RuntimeError("GAFF minimization found no ligand residues in the structure.")
    if not ligand_mols:
        raise RuntimeError(
            "GAFF/GAFF2 minimization needs ligand chemistry (SMILES, SDF/MOL2, or "
            "mmCIF _chem_comp_bond) so AmberTools can assign atom types."
        )
    protein_pdb = work_dir / "protein_leap.pdb"
    _write_protein_pdb(holo_path, protein_pdb, ligand_keys)
    leap_ligands: list[tuple[str, str, str]] = []
    charge_tags: list[str] = []
    n = min(len(ligand_mols), len(blocks))
    for i in range(n):
        mol = ligand_mols[i]
        _key, resn, _block = blocks[i]
        stem = f"lig{i}"
        resn_s = _amber_resn(resn)
        write_ligand_mol2(mol, work_dir / f"{stem}.mol2", resn=resn_s, resi=str(i + 1))
        log_prepare(
            f"AmberTools: antechamber {atom_type} for {resn_s} "
            "(AM1-BCC; this can take a few minutes)…"
        )
        tag = _parameterize_ligand(
            stem,
            charge=_formal_charge(mol),
            atom_type=atom_type,
            resn=resn_s,
            work_dir=work_dir,
        )
        log_prepare(f"AmberTools: {resn_s} parameterized ({tag})")
        charge_tags.append(tag)
        leap_ligands.append((f"{stem}_gaff.mol2", f"{stem}.frcmod", resn_s))
    if not leap_ligands:
        raise RuntimeError("GAFF minimization could not export a ligand MOL2.")
    leap_in = work_dir / "leap.in"
    prmtop = work_dir / "complex.prmtop"
    inpcrd = work_dir / "complex.inpcrd"
    if write_split or explicit_solvent:
        from ..sim.system_build import leap_script

        script = leap_script(
            protein_pdb=protein_pdb.name,
            ligands=leap_ligands,
            protein_ff=protein_ff,
            ligand_ff=ff,
            solvent=explicit_solvent or solvent,
            box_shape=box_shape or "cubic",
            padding_a=box_padding_a or 10.0,
            cation=cation,
            anion=anion,
            ion_mode=ion_mode or "neutralize",
            ion_conc_m=ion_conc_m,
            prmtop=prmtop.name,
            inpcrd=inpcrd.name,
        )
    else:
        script = leap_input(
            protein_pdb=protein_pdb.name,
            ligands=leap_ligands,
            protein_ff=protein_ff,
            ligand_ff=ff,
            keep_water=keep_water,
            solvent=solvent,
            prmtop=prmtop.name,
            inpcrd=inpcrd.name,
        )
    leap_in.write_text(script, encoding="utf-8", newline="\n")
    log_prepare("AmberTools: tleap building protein–ligand topology…")
    from ..platform_support.wsl_launcher import run_linux_tool

    try:
        proc = run_linux_tool(
            [amber_program("tleap"), "-f", leap_in.name],
            work_dir=work_dir,
            timeout=_TLEAP_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(_amber_missing_message()) from exc
    leap_log = ""
    log_path = work_dir / "leap.log"
    if log_path.is_file():
        leap_log = log_path.read_text(encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not prmtop.is_file() or not inpcrd.is_file():
        raise RuntimeError(
            "AmberTools tleap failed to build the protein–ligand system. "
            + _proc_tail(proc, leap_log)
        )
    charge_tag = charge_tags[0] if len(set(charge_tags)) == 1 else "+".join(charge_tags)
    return prmtop, inpcrd, charge_tag
