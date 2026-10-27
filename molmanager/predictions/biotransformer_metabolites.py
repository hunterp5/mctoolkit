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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Local BioTransformer 3 JAR: metabolite structure prediction (not atom SOM maps)."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from rdkit import Chem

from ..platform_support.bundled_paths import (
    biotransformer_layout_errors,
    biotransformer_support_root,
    java_executable,
    resolve_biotransformer_jar,
)
from ..chem.molecule_conversion import mol_to_canonical_smiles

logger = logging.getLogger(__name__)

MetabolismOption = Literal["cyp450", "phaseII", "ecbased", "hgut", "allHuman", "superbio"]

METABOLISM_OPTIONS: tuple[tuple[str, str], ...] = (
    ("allHuman", "Human (tissues + gut)"),
    ("cyp450", "CYP450"),
    ("phaseII", "Phase II"),
    ("ecbased", "EC-based"),
    ("hgut", "Human gut microbial"),
    ("superbio", "SuperBio"),
)

CYP_MODE_METABOLISM = frozenset({"cyp450", "allHuman"})
DEFAULT_NSTEPS = 1
DEFAULT_CYP_MODE = 1
DEFAULT_MAX_METABOLITES = 200
CYP_MODE_LABELS: tuple[tuple[int, str], ...] = (
    (1, "CypReact + rules"),
    (2, "CyProduct only"),
    (3, "Combined"),
)
DEFAULT_TIMEOUT_S = 600.0
DEFAULT_JAVA_HEAP = "2g"
_JAVA_HEAP_32BIT = "1024m"
SMILES_COLUMN_MAX_CHARS = 2000
BIOTRANSFORMER_CANCELLED = "Cancelled."

METABOLITE_COUNT_COLUMN = "Metabolite Count"
METABOLITE_REACTIONS_COLUMN = "Metabolite Reactions"
METABOLITE_SMILES_COLUMN = "Metabolite SMILES"

CancelCallback = Callable[[], bool]

_PROP_SMILES = ("SMILES", "Canonical SMILES", "Metabolite SMILES", "InChI")
_PROP_REACTION = ("Reaction", "Reaction Name", "ReactionID", "Reaction ID")
_PROP_ENZYME = ("Enzyme(s)", "Enzymes", "Enzyme")
_PROP_BIOSYSTEM = ("Biosystem", "BioSystem", "Biosystem Name")
_PROP_PRECURSOR = ("Precursor SMILES", "Precursor_SMILES", "Precursor")
_PROP_GENERATION = ("Generation", "Step", "Iteration", "Metabolic Level", "Depth")


@dataclass(frozen=True)
class MetaboliteHit:
    """One predicted metabolite structure."""

    smiles: str
    reaction: str = ""
    enzyme: str = ""
    biosystem: str = ""
    generation: int | None = None
    precursor_smiles: str = ""


@dataclass(frozen=True)
class MetabolitePrediction:
    """BioTransformer products for one parent molecule."""

    smiles: str
    metabolites: tuple[MetaboliteHit, ...]
    error: str | None = None


def uses_cyp_mode(metabolism: str) -> bool:
    return str(metabolism) in CYP_MODE_METABOLISM


@lru_cache(maxsize=8)
def _java_reports_64bit(java: str) -> bool:
    """True when ``java -version`` looks 64-bit, or when the binary cannot be probed."""
    try:
        from ..platform_support.session_runtime import ToolDenied, require_tool

        require_tool(java, "BioTransformer")
        proc = subprocess.run(
            [java, "-version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except ToolDenied:
        return False
    except (OSError, subprocess.SubprocessError):
        return True
    text = f"{proc.stdout} {proc.stderr}"
    if not text.strip():
        return True
    return "64-Bit" in text or "64-bit" in text


def resolve_java_heap(java: Path) -> str:
    """``2g`` on 64-bit JREs; ``1024m`` on 32-bit (``-Xmx2g`` fails to start)."""
    if _java_reports_64bit(str(java)):
        return DEFAULT_JAVA_HEAP
    return _JAVA_HEAP_32BIT


def metabolite_output_columns() -> list[str]:
    return [METABOLITE_COUNT_COLUMN, METABOLITE_REACTIONS_COLUMN, METABOLITE_SMILES_COLUMN]


def is_metabolite_column_header(header: str, base: str) -> bool:
    """True for *base* or a numbered duplicate such as ``Metabolite SMILES (1)``."""
    h = (header or "").strip().lower()
    b = (base or "").strip().lower()
    if not h or not b:
        return False
    return h == b or h.startswith(f"{b} (")


def parse_metabolite_smiles_cell(text: str) -> list[str]:
    """Split a parent-row Metabolite SMILES cell into product SMILES strings."""
    raw = (text or "").strip()
    if not raw or raw.upper() == "N/A":
        return []
    raw = re.sub(r"\s*\(\+\d+ more\)\s*$", "", raw)
    return [part.strip() for part in raw.split(";") if part.strip()]


def format_metabolite_columns(pred: MetabolitePrediction | None) -> dict[str, str]:
    """Parent-row text columns for a BioTransformer result."""
    empty = {
        METABOLITE_COUNT_COLUMN: "N/A",
        METABOLITE_REACTIONS_COLUMN: "N/A",
        METABOLITE_SMILES_COLUMN: "N/A",
    }
    if pred is None:
        return dict(empty)
    if pred.error:
        return {
            METABOLITE_COUNT_COLUMN: "N/A",
            METABOLITE_REACTIONS_COLUMN: pred.error,
            METABOLITE_SMILES_COLUMN: "N/A",
        }
    hits = pred.metabolites
    reactions = []
    seen: set[str] = set()
    for hit in hits:
        label = (hit.reaction or "").strip()
        if label and label not in seen:
            seen.add(label)
            reactions.append(label)
    smiles_parts = [h.smiles for h in hits if (h.smiles or "").strip()]
    joined = "; ".join(smiles_parts)
    if len(joined) > SMILES_COLUMN_MAX_CHARS:
        kept: list[str] = []
        acc = 0
        for smi in smiles_parts:
            extra = len(smi) + (2 if kept else 0)
            if acc + extra > SMILES_COLUMN_MAX_CHARS:
                break
            kept.append(smi)
            acc += extra
        n_more = len(smiles_parts) - len(kept)
        joined = "; ".join(kept)
        if n_more:
            joined = f"{joined} (+{n_more} more)"
    return {
        METABOLITE_COUNT_COLUMN: str(len(hits)),
        METABOLITE_REACTIONS_COLUMN: "; ".join(reactions) if reactions else "",
        METABOLITE_SMILES_COLUMN: joined,
    }


def _app_is_shutting_down() -> bool:
    try:
        from ..workers.process_pool_utils import application_is_shutting_down

        return bool(application_is_shutting_down())
    except Exception:
        return False


def _mol_prop(mol: Chem.Mol, names: tuple[str, ...]) -> str:
    for name in names:
        if mol.HasProp(name):
            raw = str(mol.GetProp(name) or "").strip()
            if raw:
                return raw
    lower = {k.lower(): k for k in mol.GetPropNames()}
    for name in names:
        key = lower.get(name.lower())
        if key:
            raw = str(mol.GetProp(key) or "").strip()
            if raw:
                return raw
    return ""


def _as_int(raw: str) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def parse_biotransformer_sdf(
    path: Path | str,
    *,
    parent_smiles: str = "",
) -> list[MetaboliteHit]:
    """Read BioTransformer SDF products; skip the parent structure when recognized."""
    src = Path(path)
    if not src.is_file():
        return []
    parent_can = ""
    parent_mol = Chem.MolFromSmiles(parent_smiles) if parent_smiles else None
    if parent_mol is not None:
        parent_can = mol_to_canonical_smiles(parent_mol)
    hits: list[MetaboliteHit] = []
    seen: set[str] = set()
    suppl = Chem.SDMolSupplier(str(src), sanitize=True, removeHs=False)
    for mol in suppl:
        if mol is None:
            continue
        smi = _mol_prop(mol, _PROP_SMILES)
        if not smi or smi.upper().startswith("INCHI="):
            try:
                smi = mol_to_canonical_smiles(mol)
            except Exception:
                smi = ""
        if not smi:
            continue
        parsed = Chem.MolFromSmiles(smi)
        can = mol_to_canonical_smiles(parsed) if parsed is not None else smi
        if parent_can and can == parent_can:
            continue
        if can in seen:
            continue
        seen.add(can)
        hits.append(
            MetaboliteHit(
                smiles=can or smi,
                reaction=_mol_prop(mol, _PROP_REACTION),
                enzyme=_mol_prop(mol, _PROP_ENZYME),
                biosystem=_mol_prop(mol, _PROP_BIOSYSTEM),
                generation=_as_int(_mol_prop(mol, _PROP_GENERATION)),
                precursor_smiles=_mol_prop(mol, _PROP_PRECURSOR),
            )
        )
    return hits


def biotransformer_command(
    *,
    java: Path,
    jar: Path,
    smiles: str,
    output_sdf: Path,
    metabolism: str,
    nsteps: int,
    cyp_mode: int,
    heap: str | None = None,
) -> list[str]:
    """Build the ``java -jar`` argv for one parent SMILES."""
    heap_size = (heap or "").strip() or resolve_java_heap(java)
    cmd = [
        str(java),
        f"-Xmx{heap_size}",
        "-jar",
        str(jar),
        "-k",
        "pred",
        "-b",
        str(metabolism),
        "-ismi",
        str(smiles),
        "-osdf",
        str(output_sdf),
        "-s",
        str(max(1, int(nsteps))),
    ]
    if uses_cyp_mode(metabolism):
        cmd.extend(["-cm", str(max(1, min(3, int(cyp_mode))))])
    return cmd


def _kill_process(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except Exception:
        return
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def run_java_command(
    args: list[str],
    *,
    cwd: Path,
    timeout_s: float,
    cancel: CancelCallback | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess, honouring cancel and timeout. Returns (returncode, stdout, stderr)."""
    if _app_is_shutting_down() or (cancel is not None and cancel()):
        raise RuntimeError(BIOTRANSFORMER_CANCELLED)
    from ..platform_support.session_runtime import require_tool

    require_tool(args[0], "BioTransformer")
    proc = subprocess.Popen(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    deadline = time.monotonic() + max(5.0, float(timeout_s))
    try:
        while True:
            if _app_is_shutting_down() or (cancel is not None and cancel()):
                _kill_process(proc)
                raise RuntimeError(BIOTRANSFORMER_CANCELLED)
            rc = proc.poll()
            if rc is not None:
                stdout, stderr = proc.communicate()
                return int(rc), stdout or "", stderr or ""
            if time.monotonic() >= deadline:
                _kill_process(proc)
                raise RuntimeError("BioTransformer timed out.")
            time.sleep(0.15)
    except Exception:
        if proc.poll() is None:
            _kill_process(proc)
        raise


def predict_one_smiles(
    smiles: str,
    *,
    metabolism: MetabolismOption = "allHuman",
    nsteps: int = DEFAULT_NSTEPS,
    cyp_mode: int = DEFAULT_CYP_MODE,
    max_metabolites: int = DEFAULT_MAX_METABOLITES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cancel: CancelCallback | None = None,
    jar: Path | None = None,
    java: Path | None = None,
) -> MetabolitePrediction:
    """Run BioTransformer on one parent SMILES."""
    smi = (smiles or "").strip()
    if not smi:
        return MetabolitePrediction("", (), error="Empty SMILES.")
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return MetabolitePrediction(smi, (), error="Could not parse SMILES.")
    parent = mol_to_canonical_smiles(mol) or smi
    jar_path = jar if jar is not None else resolve_biotransformer_jar()
    java_path = java if java is not None else java_executable()
    problems = biotransformer_layout_errors(jar_path)
    if java_path is None and not any(str(item).startswith("Java ") for item in problems):
        problems.insert(0, "Java is not on PATH.")
    if problems:
        return MetabolitePrediction(parent, (), error=" ".join(problems))
    assert jar_path is not None and java_path is not None
    cwd = biotransformer_support_root(jar_path)
    if cwd is None:
        return MetabolitePrediction(parent, (), error="BioTransformer JAR folder is missing.")
    cap = max(1, int(max_metabolites))
    with tempfile.TemporaryDirectory(prefix="molmanager_bt_") as tmp:
        out_sdf = Path(tmp) / "out.sdf"
        cmd = biotransformer_command(
            java=java_path,
            jar=jar_path,
            smiles=parent,
            output_sdf=out_sdf,
            metabolism=metabolism,
            nsteps=nsteps,
            cyp_mode=cyp_mode,
        )
        try:
            rc, stdout, stderr = run_java_command(
                cmd,
                cwd=cwd,
                timeout_s=timeout_s,
                cancel=cancel,
                env=os.environ.copy(),
            )
        except RuntimeError as e:
            if str(e) == BIOTRANSFORMER_CANCELLED:
                return MetabolitePrediction(parent, (), error=BIOTRANSFORMER_CANCELLED)
            return MetabolitePrediction(parent, (), error=str(e))
        if not out_sdf.is_file():
            detail = (stderr or stdout or "").strip().replace("\n", " ")[:400]
            if rc:
                msg = f"BioTransformer exited {rc}"
                if detail:
                    msg = f"{msg}: {detail}"
                return MetabolitePrediction(parent, (), error=msg)
            return MetabolitePrediction(
                parent,
                (),
                error=detail or "BioTransformer wrote no SDF output.",
            )
        hits = parse_biotransformer_sdf(out_sdf, parent_smiles=parent)[:cap]
        return MetabolitePrediction(parent, tuple(hits))


def predict_metabolites_batch(
    smiles: list[str],
    *,
    metabolism: MetabolismOption = "allHuman",
    nsteps: int = DEFAULT_NSTEPS,
    cyp_mode: int = DEFAULT_CYP_MODE,
    max_metabolites: int = DEFAULT_MAX_METABOLITES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cancel: CancelCallback | None = None,
    progress: Callable[[int, int], None] | None = None,
    jar: Path | None = None,
    java: Path | None = None,
) -> list[MetabolitePrediction]:
    """Predict metabolites for each SMILES (empty entries become error results)."""
    if metabolism not in {k for k, _ in METABOLISM_OPTIONS}:
        raise ValueError(f"Unknown BioTransformer metabolism: {metabolism}")
    total = max(len(smiles), 1)
    out: list[MetabolitePrediction] = []
    for i, raw in enumerate(smiles):
        if progress is not None:
            progress(i, total)
        if _app_is_shutting_down() or (cancel is not None and cancel()):
            remaining = len(smiles) - i
            out.extend(
                MetabolitePrediction((s or "").strip(), (), error=BIOTRANSFORMER_CANCELLED)
                for s in smiles[i:]
            )
            if remaining and progress is not None:
                progress(len(smiles), total)
            return out
        out.append(
            predict_one_smiles(
                raw,
                metabolism=metabolism,
                nsteps=nsteps,
                cyp_mode=cyp_mode,
                max_metabolites=max_metabolites,
                timeout_s=timeout_s,
                cancel=cancel,
                jar=jar,
                java=java,
            )
        )
    if progress is not None:
        progress(len(smiles), total)
    return out


def install_ready_message() -> str | None:
    """None when Java + JAR layout are ready; otherwise a dialog message."""
    errors = biotransformer_layout_errors()
    if not errors:
        return None
    return "\n".join(errors)
