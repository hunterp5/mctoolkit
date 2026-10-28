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

"""Gnina dock job policy: argv, ligand files, and pose post-process (no Qt)."""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..conformers.conformer_column_codec import is_packed_ensemble_header
from .gnina_launch import gnina_uses_wsl, write_gnina_config

_FLEXRES_TOKEN = re.compile(r"^[A-Za-z0-9]+:-?\d+[A-Za-z]?$")


@dataclass
class GninaJobSettings:
    """Search, CNN, and flexible-residue options collected from the dock dialog."""

    receptor: str = ""
    autobox: bool = False
    autobox_ligand: str = ""
    autobox_add: float = 4.0
    center_x: float = 0.0
    center_y: float = 0.0
    center_z: float = 0.0
    size_x: float = 20.0
    size_y: float = 20.0
    size_z: float = 20.0
    exhaustiveness: int = 8
    num_modes: int = 9
    cpu: int = 0
    extra: str = ""
    flex_mode: str = "off"
    flexdist_ligand: str = ""
    crystal_ligand: str = ""
    flexdist: float = 3.5
    flex_max: int = 0
    flexres: str = ""
    full_flex: bool = False
    cnn_scoring: str = "rescore"
    emp_scoring: str = "vina"
    pose_sort: str = "CNNscore"
    cnn_model: str = ""
    no_gpu: bool = False
    save_sdf: bool = True
    work_dir: str = ""


def ligand_cli_args(ligand: str | Sequence[str]) -> tuple[list[str], str]:
    """Expand one or more ligand paths to repeated ``--ligand`` flags.

    Gnina accepts several ``--ligand`` files in one process. Concatenated Meeko
    PDBQT is invalid as a single file, so split records are passed this way.
    SDF/MOL2 is passed through so Gnina never needs a ligand PDBQT file.
    """
    if isinstance(ligand, (str, Path)):
        paths = [str(ligand).strip()] if str(ligand).strip() else []
    else:
        paths = [str(p).strip() for p in ligand if str(p).strip()]
    if not paths:
        raise ValueError("Choose a ligand file (PDBQT or SDF).")
    args: list[str] = []
    for path in paths:
        args.extend(["--ligand", path])
    return args, paths[0]


_ligand_cli_args = ligand_cli_args


def normalize_flexres(text: str) -> str:
    """Comma-separated Gnina ``--flexres`` tokens (``CHAIN:RESNUM``)."""
    parts: list[str] = []
    for raw in (text or "").replace(";", ",").split(","):
        tok = raw.strip().replace(" ", "")
        if not tok:
            continue
        if not _FLEXRES_TOKEN.match(tok):
            raise ValueError(
                f"Invalid flexible residue '{raw.strip()}'. Use CHAIN:RESNUM (e.g. A:123,A:145)."
            )
        parts.append(tok)
    if not parts:
        raise ValueError("Enter flexible residues as CHAIN:RESNUM (e.g. A:123,A:145).")
    return ",".join(parts)


def flex_out_path(out_path: str) -> str:
    """PDB path for Gnina ``--out_flex`` beside the pose output file."""
    p = Path((out_path or "").strip() or "out.sdf")
    stem = p.stem or "out"
    return str(p.with_name(f"{stem}_flex.pdb"))


def ensemble_column_headers(app) -> list[str]:
    """Packed-ensemble table headers (confs / superpose / poses) plus sidecar columns."""
    if app is None:
        return []
    headers = [str(h).strip() for h in (getattr(app, "headers", None) or []) if str(h).strip()]
    names: list[str] = []
    for header in headers:
        if is_packed_ensemble_header(header):
            names.append(header)
    sidecar = getattr(app, "_confs_blocks_sidecar", None)
    if sidecar is None:
        sidecar = {}
    for key in sidecar:
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        col = str(key[1] or "").strip()
        if col and col not in names and col in headers:
            names.append(col)
    return names


def table_row_dock_problem(*, has_window: bool, selected_rows: int, column: str) -> str | None:
    """Why selected table rows cannot be docked, or ``None`` when they can."""
    if not has_window:
        return "Open Gnina from the main window to dock selected table rows."
    if int(selected_rows) <= 0:
        return "Select one or more table rows to dock."
    if not (column or "").strip():
        return "Choose a conformations column."
    return None


def no_table_ligands_message(column_label: str) -> str:
    """Shown when the chosen column has no 3D ligand in the selected rows."""
    col = (column_label or "").strip() or "the chosen column"
    return f"No 3D ligands in the selected rows for “{col}”."


def ligands_from_row_mols(pairs: Sequence[tuple[int, object]]) -> list:
    """One Gnina ligand per ``(oid, mol)`` that has 3D coordinates."""
    ligands = []
    for oid, mol in pairs:
        ligand = ligand_mol_from_ensemble(mol, int(oid))
        if ligand is not None:
            ligands.append(ligand)
    return ligands


@dataclass(frozen=True)
class GninaRunPlan:
    """Whether a Gnina launch has the files it needs, and how the crystal ligand is used."""

    message: str | None = None
    ligand_paths_are_crystal: bool = False
    extra_validation: bool = False
    stamp_crystal_on_poses: bool = False

    @property
    def is_ready(self) -> bool:
        return self.message is None


def gnina_receptor_problem(receptor: str, receptor_path: Path) -> str | None:
    """Why the receptor field cannot be used, or ``None`` when the file is present."""
    if not (receptor or "").strip():
        return "Choose a receptor PDB or PDBQT file."
    if not receptor_path.is_file():
        return f"Receptor file not found:\n{receptor_path}"
    return None


def gnina_output_problem(output: str) -> str | None:
    """Why the output field cannot be used, or ``None`` when it is set."""
    if not (output or "").strip():
        return "Set an output path."
    return None


def plan_gnina_run(
    *,
    ligand_paths: Sequence[Path],
    crystal_ligand: str,
    same_crystal_ligand: bool,
) -> GninaRunPlan:
    """Decide how a Gnina run uses the ligand and the crystal ligand.

    Call this after the receptor, pharmacophore, and output path are accepted
    and crystal validation has filled ``crystal_ligand``.
    """
    crystal = (crystal_ligand or "").strip()
    paths = list(ligand_paths)
    if not paths and not crystal:
        return GninaRunPlan(message="Choose a ligand file (PDBQT or SDF).")
    if not paths and crystal:
        return GninaRunPlan(ligand_paths_are_crystal=True, stamp_crystal_on_poses=True)
    if crystal and (len(paths) != 1 or not same_crystal_ligand):
        return GninaRunPlan(extra_validation=True)
    if crystal:
        return GninaRunPlan(stamp_crystal_on_poses=True)
    return GninaRunPlan()


def ligand_mol_from_ensemble(mol, oid: int):
    """One 3D ligand per table row.

    Gnina searches from this start; extra packed confs are not docked.
    """
    from rdkit import Chem

    if mol is None:
        return None
    clone = Chem.Mol(mol)
    n_conf = int(clone.GetNumConformers())
    if n_conf > 1:
        keep = Chem.Conformer(clone.GetConformer(0))
        clone.RemoveAllConformers()
        clone.AddConformer(keep, assignId=True)
    clone.SetProp("_Name", str(oid))
    from ..services.column_labels import COLUMN_PARENT_OID

    clone.SetProp(COLUMN_PARENT_OID, str(oid))
    return clone


def write_smina_config(argv: list[str], dest: Path) -> Path:
    """Write a Gnina ``--config`` file (legacy name used by tests)."""
    return write_gnina_config(argv, dest, linux_paths=gnina_uses_wsl())


_write_smina_config = write_smina_config


def effective_out_path(out: str, *, save_sdf: bool) -> str:
    """SDF sibling when Save as SDF is on; otherwise the given path."""
    from .pose_file_io import sdf_path_for_pdbqt

    text = (out or "").strip()
    if not text:
        return text
    if save_sdf:
        return str(sdf_path_for_pdbqt(text))
    return text


def resolve_work_path(path: str, work_dir: str = "") -> Path:
    """Resolve *path* against an optional Gnina working directory."""
    p = Path(path)
    if p.is_absolute():
        return p
    wd = (work_dir or "").strip()
    if wd:
        return Path(wd) / p
    return p


def same_input_path(left: str, right: str, *, work_dir: str = "") -> bool:
    """True when two receptor/ligand fields name the same file."""
    a = str(left or "").strip()
    b = str(right or "").strip()
    if not a or not b:
        return False
    pa = resolve_work_path(a, work_dir)
    pb = resolve_work_path(b, work_dir)
    try:
        if pa.is_file() and pb.is_file():
            return pa.resolve() == pb.resolve()
    except OSError:
        pass
    return str(pa) == str(pb)


def ligand_arg(lig_paths: list[Path]) -> str | list[str]:
    """Single path, or a list when Gnina should see several ``--ligand`` flags."""
    if len(lig_paths) == 1:
        return str(lig_paths[0])
    return [str(p) for p in lig_paths]


def autobox_ligand_path(explicit: str, dock_ligand: str) -> str:
    """Autobox reference ligand, falling back to the docking ligand."""
    text = (explicit or "").strip()
    return text or dock_ligand


def flexdist_ligand_path(
    *,
    explicit: str,
    autobox: str,
    crystal: str,
    dock_ligand: str,
) -> str:
    """Reference ligand for ``--flexdist_ligand`` (explicit → autobox → crystal → dock)."""
    for candidate in (explicit, autobox, crystal, dock_ligand):
        text = (candidate or "").strip()
        if text:
            return text
    return ""


def sidecar_for_receptor(
    rec: str,
    *,
    sidecar: str,
    prepare_receptor: str,
    work_dir: str = "",
) -> str:
    """Crystal-ligand sidecar only when the receptor is still the Prepare output."""
    side = (sidecar or "").strip()
    prep = (prepare_receptor or "").strip()
    if side and prep and not same_input_path(rec, prep, work_dir=work_dir):
        return ""
    return side


def launch_argv_with_config(argv: list[str], cfg_path: Path) -> list[str]:
    """Use ``--config`` when several ligands would bloat the command line."""
    if argv.count("--ligand") <= 1:
        return argv
    write_gnina_config(argv, cfg_path, linux_paths=gnina_uses_wsl())
    return ["--config", str(cfg_path)]


def build_cnn_argv(settings: GninaJobSettings) -> list[str]:
    """CNN / empirical scoring flags, including ``--no_gpu`` when forced."""
    scoring = str(settings.cnn_scoring or "rescore")
    argv = ["--cnn_scoring", scoring]
    if scoring == "none":
        emp = str(settings.emp_scoring or "vina")
        argv.extend(["--scoring", emp])
    else:
        argv.extend(["--pose_sort_order", str(settings.pose_sort or "CNNscore")])
        model = str(settings.cnn_model or "")
        if model:
            argv.extend(["--cnn", model])
    if settings.no_gpu:
        argv.append("--no_gpu")
    return argv


def build_flex_argv(
    settings: GninaJobSettings,
    *,
    dock_ligand: str,
    out_path: str,
) -> list[str]:
    """Gnina flexible-side-chain flags, or empty when the receptor is rigid."""
    mode = str(settings.flex_mode or "off")
    if mode == "off":
        return []
    argv: list[str] = []
    if mode == "dist":
        lig = flexdist_ligand_path(
            explicit=settings.flexdist_ligand,
            autobox=settings.autobox_ligand,
            crystal=settings.crystal_ligand,
            dock_ligand=dock_ligand,
        )
        if not lig:
            raise ValueError(
                "Choose a reference ligand for flexible side chains "
                "(or set Autobox / a crystal ligand from Prepare)."
            )
        argv.extend(
            [
                "--flexdist_ligand",
                lig,
                "--flexdist",
                f"{float(settings.flexdist):.2f}",
            ]
        )
        nmax = int(settings.flex_max)
        if nmax > 0:
            argv.extend(["--flex_max", str(nmax)])
    elif mode == "res":
        argv.extend(["--flexres", normalize_flexres(settings.flexres)])
    else:
        return []
    argv.extend(["--out_flex", flex_out_path(out_path)])
    if settings.full_flex:
        argv.append("--full_flex_output")
    return argv


def build_gnina_argv(
    settings: GninaJobSettings,
    *,
    ligand: str | Sequence[str],
    out: str,
    receptor: str = "",
) -> list[str]:
    """Full Gnina placement argv from collected settings."""
    rec = (receptor or settings.receptor or "").strip()
    lig_args, first_lig = ligand_cli_args(ligand)
    out_path = (out or "").strip()
    if not rec:
        raise ValueError("Choose a receptor PDB or PDBQT file.")
    if not out_path:
        raise ValueError("Set an output path.")

    argv = ["--receptor", rec, *lig_args, "--out", out_path]
    if settings.autobox:
        box_lig = autobox_ligand_path(settings.autobox_ligand, first_lig)
        if not box_lig:
            raise ValueError("Choose a ligand file, or a box ligand, for autobox.")
        argv.extend(
            [
                "--autobox_ligand",
                box_lig,
                "--autobox_add",
                f"{float(settings.autobox_add):.2f}",
            ]
        )
    else:
        argv.extend(
            [
                "--center_x",
                f"{float(settings.center_x):.3f}",
                "--center_y",
                f"{float(settings.center_y):.3f}",
                "--center_z",
                f"{float(settings.center_z):.3f}",
                "--size_x",
                f"{float(settings.size_x):.2f}",
                "--size_y",
                f"{float(settings.size_y):.2f}",
                "--size_z",
                f"{float(settings.size_z):.2f}",
            ]
        )
    argv.extend(
        [
            "--exhaustiveness",
            str(int(settings.exhaustiveness)),
            "--num_modes",
            str(int(settings.num_modes)),
        ]
    )
    argv.extend(build_cnn_argv(settings))
    cpu = int(settings.cpu)
    if cpu > 0:
        argv.extend(["--cpu", str(cpu)])
    argv.extend(build_flex_argv(settings, dock_ligand=first_lig, out_path=out_path))
    extra = (settings.extra or "").strip()
    if extra:
        argv.extend(shlex.split(extra))
    return argv


def build_minimize_argv(
    settings: GninaJobSettings,
    ligand: str | Sequence[str],
    out: str,
    *,
    receptor: str = "",
) -> list[str]:
    """Gnina ``--minimize`` argv (no search box or exhaustiveness)."""
    rec = (receptor or settings.receptor or "").strip()
    if not rec:
        raise ValueError("Choose a receptor PDB or PDBQT file.")
    lig_args, _first = ligand_cli_args(ligand)
    argv = ["--receptor", rec, *lig_args, "--out", out, "--minimize"]
    argv.extend(build_cnn_argv(settings))
    cpu = int(settings.cpu)
    if cpu > 0:
        argv.extend(["--cpu", str(cpu)])
    return argv


def require_dock_pharmacophore(path: str) -> None:
    """Raise if the Pharmacophore field is set but the JSON cannot be used."""
    from ..protein.pharmacophore import load_pharmacophore

    text = (path or "").strip()
    if not text:
        return
    dest = Path(text)
    if not dest.is_file():
        raise ValueError(f"Pharmacophore file not found: {path}")
    pharma = load_pharmacophore(dest)
    if not pharma.enabled_features():
        raise ValueError("Pharmacophore file has no enabled features.")


def apply_dock_pharmacophore_filter(
    mols: list,
    path: str,
    *,
    slack: float,
) -> tuple[list, str | None]:
    """Keep docked poses that occupy the query spheres. Returns (mols, log line)."""
    from ..protein.pharmacophore import load_pharmacophore
    from ..protein.pharmacophore_screen import filter_docked_poses

    text = (path or "").strip()
    if not text or not mols:
        return list(mols), None
    try:
        pharma = load_pharmacophore(text)
    except Exception as exc:
        return list(mols), f"Pharmacophore filter skipped: {exc}"
    if not pharma.enabled_features():
        return list(mols), None
    kept, dropped = filter_docked_poses(mols, pharma, slack=slack)
    n_all = len(kept) + len(dropped)
    if kept:
        msg = f"Pharmacophore: kept {len(kept)} of {n_all} pose(s) (slack {slack:.2f} Å)."
        return kept, msg
    msg = (
        f"Pharmacophore: 0 of {n_all} pose(s) matched "
        f"(slack {slack:.2f} Å); keeping all for inspection."
    )
    return list(mols), msg


def load_ligand_template_mols(paths: Sequence[str | Path]) -> list:
    """Input ligand molecules used to restore Kekulé/aromatic bonds on SDF poses."""
    from rdkit import Chem

    from .pose_file_io import load_sdf_mols

    mols: list = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        suf = path.suffix.lower()
        try:
            if suf in {".sdf", ".sd"}:
                mols.extend(load_sdf_mols(path))
            elif suf == ".mol":
                mol = Chem.MolFromMolFile(str(path), removeHs=False)
                if mol is not None:
                    mols.append(mol)
        except Exception:
            continue
    return mols


def prepare_file_ligands(ligand_path: Path, tmp_dir: Path) -> tuple[list[Path], list[Path]]:
    """Return (paths for Gnina, temp files that belong to the batch).

    OpenBabel formats (SDF/MOL/MOL2) are passed through. PDBQT is converted to
    SDF when bond orders can be restored; otherwise concatenated records are
    split into one PDBQT per ligand.
    """
    from .pose_file_io import (
        ligand_is_openbabel_format,
        split_ligand_pdbqt_records,
        write_ligand_pdbqt_as_sdf,
    )

    if ligand_is_openbabel_format(ligand_path):
        return [ligand_path], []
    raw = ligand_path.read_text(encoding="utf-8", errors="replace")
    records = split_ligand_pdbqt_records(raw)
    dest = tmp_dir / f"{ligand_path.stem}.sdf"
    _, n_written = write_ligand_pdbqt_as_sdf(ligand_path, dest)
    if n_written:
        return [dest], [dest]
    if len(records) <= 1:
        return [ligand_path], []
    written: list[Path] = []
    for i, rec in enumerate(records, start=1):
        lp = tmp_dir / f"lig_{i:03d}.pdbqt"
        lp.write_text(rec, encoding="utf-8")
        written.append(lp)
    return list(written), list(written)


def write_sidecar_sdf(pdbqt_out: str, template) -> tuple[str | None, str]:
    """Convert PDBQT poses to a sibling SDF. Returns (path or None, log)."""
    from .pose_file_io import is_sdf_path, write_pdbqt_poses_sdf

    src = Path(pdbqt_out)
    if is_sdf_path(src):
        return None, ""
    if not src.is_file():
        return None, "Output PDBQT not found; skipped SDF."
    try:
        sdf_path, n_written = write_pdbqt_poses_sdf(src, template=template)
    except Exception as exc:
        return None, f"SDF conversion failed: {exc}"
    if n_written:
        return str(sdf_path), f"Wrote {n_written} pose(s) to {sdf_path}."
    return None, "Could not convert PDBQT poses to SDF."


def restore_sdf_bonds(sdf_path: str, templates: list) -> str:
    """Restore Kekulé/aromatic bonds on SDF poses. Returns a log line or empty."""
    from .pose_file_io import is_sdf_path, restore_sdf_bond_orders

    if not is_sdf_path(sdf_path) or not templates:
        return ""
    try:
        n = restore_sdf_bond_orders(sdf_path, templates)
    except Exception as exc:
        return f"Could not restore SDF bond orders: {exc}"
    if n:
        return f"Restored bond orders on {n} pose(s) from the input ligand."
    return ""


def write_combined_minimize_results(
    dest: str,
    min_path: Path,
    templates: list,
) -> list[str]:
    """Interleave placement and minimized poses. Returns log lines."""
    from .pose_file_io import (
        combine_placement_and_minimized,
        combine_sdf_placement_and_minimized,
        is_sdf_path,
        split_pdbqt_models,
    )

    src = Path(dest)
    logs: list[str] = []
    if is_sdf_path(src):
        _, n_written = combine_sdf_placement_and_minimized(src, min_path, src)
        bond_log = restore_sdf_bonds(dest, templates)
        if bond_log:
            logs.append(bond_log)
        logs.append(f"Wrote placement and minimized poses ({n_written} record(s)) to {dest}.")
        return logs
    placement = src.read_text(encoding="utf-8", errors="replace")
    if min_path.is_file() and min_path.stat().st_size > 0:
        min_blocks = split_pdbqt_models(min_path.read_text(encoding="utf-8", errors="replace"))
    else:
        min_blocks = []
    combined = combine_placement_and_minimized(placement, min_blocks)
    src.write_text(combined, encoding="utf-8")
    n_min = sum(1 for b in min_blocks if (b or "").strip())
    logs.append(f"Wrote placement and minimized poses ({n_min} minimized) to {dest}.")
    return logs


def prepare_minimize_inputs(placement_path: str, tmp_dir: Path) -> tuple[list[Path], Path, int]:
    """Split placement poses for one Gnina ``--minimize`` process.

    Returns ``(ligand_paths, minimize_out, n_poses)``.
    """
    from .pose_file_io import is_sdf_path, load_sdf_mols, split_ligand_pdbqt_records

    src = Path(placement_path)
    if not src.is_file():
        return [], src, 0
    if is_sdf_path(src):
        n_poses = len(load_sdf_mols(src))
        if n_poses < 1:
            return [], src, 0
        return [src], tmp_dir / "min_all.sdf", n_poses
    try:
        records = split_ligand_pdbqt_records(src.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return [], src, 0
    if not records:
        return [], src, 0
    ins: list[Path] = []
    for i, rec in enumerate(records, start=1):
        lig = tmp_dir / f"place_{i:03d}.pdbqt"
        lig.write_text(rec, encoding="utf-8")
        ins.append(lig)
    return ins, tmp_dir / "min_all.pdbqt", len(records)


def durable_apo_receptor(apo_path: str, durable_dir: Path) -> str:
    """Copy a temp apo receptor next to the dock output so it survives cleanup."""
    src = Path(apo_path)
    durable = Path(durable_dir) / src.name
    try:
        durable.parent.mkdir(parents=True, exist_ok=True)
        if not durable.exists() or durable.resolve() != src.resolve():
            durable.write_bytes(src.read_bytes())
            return str(durable)
    except OSError:
        pass
    return apo_path
