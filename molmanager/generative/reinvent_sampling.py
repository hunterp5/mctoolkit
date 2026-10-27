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

"""Sampling-only adapter for a local REINVENT 4 install.

REINVENT is a separate command (``reinvent sampling.toml``). It is not imported
here: its PyTorch and NumPy pins conflict with MolManager. This module writes
the sampling config, runs that command, and reads the CSV it writes.
"""

from __future__ import annotations

import csv
import io
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from shutil import which

from ..chem.molecule_conversion import mol_to_canonical_smiles

EXTRA_FLAGS_PLACEHOLDER = "--log-level debug"
EXTRA_FLAGS_TOOLTIP = (
    "Extra options appended to the reinvent command. "
    "Examples: --log-level debug, --log-filename C:\\temp\\reinvent.log, "
    "--dotenv-filename C:\\env\\.env, --enable-rdkit-log-levels error. "
    "--device and --seed here override the fields above."
)

MISSING_REINVENT_MSG = (
    "REINVENT was not found. Install REINVENT 4 in its own Python environment "
    "(it cannot share MolManager's environment), then set the reinvent command "
    "under Settings → Configure → REINVENT. Leave the path blank to use reinvent on PATH."
)

# Ask before a seed model is asked to draw more than this many SMILES.
CONFIRM_SAMPLE_COUNT = 20_000

_SMILES_HEADERS = {"smiles", "smile", "output_smiles", "sampled_smiles"}
_NLL_HEADERS = {"nll", "likelihood", "neg_log_likelihood", "negative_log_likelihood"}
_SEED_HEADERS = {
    "input_smiles",
    "smiles_input",
    "scaffold",
    "seed",
    "seed_smiles",
    "input",
}
_SAMPLE_STRATEGIES = frozenset({"multinomial", "beamsearch"})
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_VALUE_FLAGS = frozenset(
    {
        "-f",
        "--config-format",
        "-d",
        "--device",
        "-l",
        "--log-filename",
        "--log-level",
        "-s",
        "--seed",
        "--dotenv-filename",
    }
)
_REPEAT_FLAGS = frozenset({"--enable-rdkit-log-levels"})
_STOP_FLAGS = frozenset({"-h", "--help", "-V", "--version"})


@dataclass(frozen=True)
class ReinventGenerator:
    """One REINVENT sampling generator and the prior id passed through by default."""

    key: str
    label: str
    blurb: str
    needs_seeds: bool
    seed_kind: str
    models: tuple[str, ...]
    uses_sample_strategy: bool
    uses_temperature: bool

    @property
    def default_model(self) -> str:
        return self.models[0]


GENERATORS: tuple[ReinventGenerator, ...] = (
    ReinventGenerator(
        key="denovo",
        label="De novo",
        blurb="Draw new molecules from a Reinvent prior. No seed structures.",
        needs_seeds=False,
        seed_kind="none",
        models=(".reinvent",),
        uses_sample_strategy=False,
        uses_temperature=False,
    ),
    ReinventGenerator(
        key="libinvent",
        label="R-groups (LibInvent)",
        blurb="Decorate each scaffold. Every scaffold needs an attachment point (*).",
        needs_seeds=True,
        seed_kind="scaffold",
        models=(".libinvent",),
        uses_sample_strategy=True,
        uses_temperature=False,
    ),
    ReinventGenerator(
        key="linkinvent",
        label="Linker (LinkInvent)",
        blurb="Propose a linker between two fragments written as fragment|fragment.",
        needs_seeds=True,
        seed_kind="pair",
        models=(".linkinvent",),
        uses_sample_strategy=True,
        uses_temperature=False,
    ),
    ReinventGenerator(
        key="mol2mol",
        label="Similar molecules (Mol2Mol)",
        blurb="Generate molecules conditioned on each seed SMILES.",
        needs_seeds=True,
        seed_kind="smiles",
        models=(".m2m_similarity",),
        uses_sample_strategy=True,
        uses_temperature=True,
    ),
)


@dataclass(frozen=True)
class SamplingRequest:
    """One sampling run. ``model_file`` is a prior id or a path to a model file."""

    generator: str
    model_file: str
    num_smiles: int
    device: str
    unique_molecules: bool
    randomize_smiles: bool
    sample_strategy: str
    temperature: float
    seeds: tuple[str, ...] = ()
    scaffold_smarts: str = ""
    seed: int = 0
    isomeric_smiles: bool = False
    extra_flags: str = ""


@dataclass(frozen=True)
class SampledMolecule:
    """One row of a REINVENT sampling CSV."""

    smiles: str
    nll: str
    seed_smiles: str


@dataclass(frozen=True)
class SamplingOutcome:
    """Molecules worth adding to the table, plus how many CSV rows were unreadable."""

    records: tuple[tuple[str, dict[str, str]], ...]
    parsed: int
    skipped_invalid: int
    cancelled: bool
    skipped_scaffold: int = 0


class ReinventSamplingError(Exception):
    """The REINVENT command could not be started or did not produce a usable CSV."""


class ReinventSamplingCancelled(ReinventSamplingError):
    """The user stopped the run."""


def generator_by_key(key: str) -> ReinventGenerator:
    """Return the generator spec for *key*."""
    for spec in GENERATORS:
        if spec.key == key:
            return spec
    raise KeyError(key)


def normalize_seed_lines(text: str) -> tuple[str, ...]:
    """Non-empty seed lines, skipping blanks and ``#`` comments."""
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return tuple(lines)


def table_seed_lines(app, *, only_selected: bool) -> list[str]:
    """Seed SMILES from the chemistry table, in table order, without duplicates.

    *app* is the workspace window. An object without a table yields an empty list.
    """
    if app is None or not hasattr(app, "_all_oids_in_table_order"):
        return []
    headers = getattr(app, "headers", None) or []
    oids = list(app._all_oids_in_table_order())
    if only_selected:
        allowed = set(app._selected_oids_set())
        oids = [oid for oid in oids if oid in allowed]
    header = ""
    if hasattr(app, "_canonical_smiles_header_for_updates"):
        header = app._canonical_smiles_header_for_updates() or ""
    lines: list[str] = []
    seen: set[str] = set()
    for oid in oids:
        row = app._table_model.logical_row_for_oid(int(oid))
        if row < 0:
            continue
        cell = ""
        if header and header in headers:
            cell = app._table_model.backing_value_for_row_header(row, header) or ""
            if not str(cell).strip():
                cell = app._table_model.cell_text(row, headers.index(header)) or ""
        mol = app._mol_for_structure_row(row) if hasattr(app, "_mol_for_structure_row") else None
        text = seed_text_for_row(str(cell), mol)
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return lines


def seed_text_for_row(cell_smiles: str, mol) -> str:
    """Seed text for one table row.

    A cell that already contains ``|`` or ``*`` is kept as written so linker
    pairs and attachment points are not rewritten. Other rows use canonical SMILES.
    """
    raw = (cell_smiles or "").strip()
    if "|" in raw or "*" in raw:
        return raw
    if mol is not None:
        return mol_to_canonical_smiles(mol).strip()
    return raw


def smiles_is_parseable(smiles: str) -> bool:
    """True when RDKit can build a molecule from *smiles*."""
    from rdkit import Chem, rdBase

    blocker = rdBase.BlockLogs()
    try:
        return Chem.MolFromSmiles(smiles) is not None
    finally:
        del blocker


def smarts_is_parseable(pattern: str) -> bool:
    """True when RDKit can compile *pattern* as SMARTS."""
    from rdkit import Chem, rdBase

    blocker = rdBase.BlockLogs()
    try:
        return Chem.MolFromSmarts(pattern) is not None
    finally:
        del blocker


def scaffold_error(smarts: str) -> str | None:
    """Return a user-facing error, or ``None`` when *smarts* is empty or readable."""
    text = (smarts or "").strip()
    if not text:
        return None
    if smarts_is_parseable(text):
        return None
    return "The scaffold is not SMARTS RDKit could read."


def decoration_seeds(pattern: str) -> tuple[str, ...]:
    """LibInvent scaffolds for a SMILES core, one ``*`` in place of each hydrogen.

    A pattern that already contains ``*`` is returned unchanged when it is SMILES.
    SMARTS that is not a molecule yields nothing, so de novo sampling can only
    filter on it.
    """
    text = (pattern or "").strip()
    if not text:
        return ()
    if "*" in text:
        return (text,) if smiles_is_parseable(text) else ()
    from rdkit import Chem, rdBase

    blocker = rdBase.BlockLogs()
    try:
        mol = Chem.MolFromSmiles(text)
        if mol is None:
            return ()
        found: list[str] = []
        seen: set[str] = set()
        for atom in mol.GetAtoms():
            if atom.GetAtomicNum() <= 1 or atom.GetTotalNumHs() < 1:
                continue
            smiles = _smiles_with_attachment(mol, atom.GetIdx())
            if smiles and smiles not in seen:
                seen.add(smiles)
                found.append(smiles)
        return tuple(found)
    finally:
        del blocker


def scaffold_scoring_smarts(pattern: str) -> str:
    """SMARTS for REINVENT's substructure scorer.

    A SMILES scaffold is converted without explicit hydrogens, so either
    tautomer of a ring such as indazole still matches. Patterns that already
    contain ``*``, and SMARTS that is not a molecule, are passed through.
    """
    text = (pattern or "").strip()
    if not text or "*" in text:
        return text
    from rdkit import Chem, rdBase

    blocker = rdBase.BlockLogs()
    try:
        mol = Chem.MolFromSmiles(text)
        if mol is None:
            return text
        return Chem.MolToSmarts(mol) or text
    finally:
        del blocker


def prepare_sampling_request(request: SamplingRequest) -> SamplingRequest:
    """Decorate a de novo SMILES scaffold with LibInvent.

    The Reinvent prior cannot be aimed at a core, so a molecule scaffold is
    sampled as R-groups on that core. A SMARTS pattern that is not a molecule
    stays a filter on the de novo draw.
    """
    if request.generator != "denovo":
        return request
    seeds = decoration_seeds(request.scaffold_smarts)
    if not seeds:
        return request
    per_seed = max(1, (int(request.num_smiles) + len(seeds) - 1) // len(seeds))
    return replace(
        request,
        generator="libinvent",
        model_file=generator_by_key("libinvent").default_model,
        sample_strategy="multinomial",
        num_smiles=per_seed,
        seeds=seeds,
    )


SCAFFOLD_DECORATION_NOTE = (
    "De novo cannot be aimed at a scaffold. Decorating it with the LibInvent prior instead."
)


def effective_seeds(
    generator: str,
    seeds: tuple[str, ...],
    scaffold_smarts: str,
) -> tuple[str, ...]:
    """Seeds plus an R-group scaffold, when that scaffold is SMILES with an attachment point."""
    text = (scaffold_smarts or "").strip()
    if generator != "libinvent" or "*" not in text or text in seeds:
        return seeds
    if not smiles_is_parseable(text):
        return seeds
    return (text, *seeds)


def smiles_matches_scaffold(smiles: str, smarts: str) -> bool:
    """True when *smiles* contains *smarts*. An empty pattern matches everything.

    A scaffold that is a molecule is matched as that molecule, so the explicit
    hydrogen in ``c1ccc2[nH]ncc2c1`` still hits the other indazole tautomer.
    """
    text = (smarts or "").strip()
    if not text:
        return True
    from rdkit import Chem, rdBase

    blocker = rdBase.BlockLogs()
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return False
        if "*" not in text:
            query = Chem.MolFromSmiles(text)
            if query is not None:
                return bool(mol.HasSubstructMatch(query))
        pattern = Chem.MolFromSmarts(text)
        if pattern is None:
            return False
        return bool(mol.HasSubstructMatch(pattern))
    finally:
        del blocker


def validate_seeds(generator_key: str, seeds: tuple[str, ...]) -> str | None:
    """Return a user-facing error, or ``None`` when *seeds* fit *generator_key*."""
    spec = generator_by_key(generator_key)
    if not spec.needs_seeds:
        return None
    if not seeds:
        return f"{spec.label} needs at least one seed structure."
    for index, line in enumerate(seeds, start=1):
        message = _validate_seed_line(spec, index, line)
        if message:
            return message
    return None


def validate_request(request: SamplingRequest) -> str | None:
    """Return a user-facing error, or ``None`` when *request* can be written."""
    request = prepare_sampling_request(request)
    try:
        spec = generator_by_key(request.generator)
    except KeyError:
        return "Choose a generator."
    if not (request.model_file or "").strip():
        return "Enter a REINVENT prior id or a model file."
    if int(request.num_smiles) < 1:
        return "Sample at least one SMILES."
    if not (request.device or "").strip():
        return "Choose a device (cpu or cuda:0)."
    if spec.uses_sample_strategy and request.sample_strategy not in _SAMPLE_STRATEGIES:
        return "Choose multinomial or beam search."
    if int(request.seed) < 0:
        return "The random seed cannot be negative."
    pattern = scaffold_error(request.scaffold_smarts)
    if pattern:
        return pattern
    try:
        parse_extra_flags(request.extra_flags)
    except ValueError as exc:
        return str(exc)
    return validate_seeds(
        request.generator,
        effective_seeds(request.generator, request.seeds, request.scaffold_smarts),
    )


def estimated_sample_count(request: SamplingRequest) -> int:
    """How many SMILES REINVENT will try to draw (seeds times samples per seed)."""
    request = prepare_sampling_request(request)
    spec = generator_by_key(request.generator)
    seeds = (
        len(effective_seeds(request.generator, request.seeds, request.scaffold_smarts))
        if spec.needs_seeds
        else 1
    )
    return max(0, seeds) * int(request.num_smiles)


def render_sampling_toml(
    request: SamplingRequest,
    *,
    output_file: Path,
    smiles_file: Path | None,
) -> str:
    """TOML for ``run_type = "sampling"``. Paths use forward slashes."""
    spec = generator_by_key(request.generator)
    lines = [
        'run_type = "sampling"',
        f"device = {_toml_str(request.device.strip())}",
    ]
    if int(request.seed) > 0:
        lines.append(f"seed = {int(request.seed)}")
    lines.extend(
        [
            "",
            "[parameters]",
            f"model_file = {_toml_str(_toml_path(request.model_file))}",
            f"output_file = {_toml_str(output_file.as_posix())}",
            f"num_smiles = {int(request.num_smiles)}",
            f"unique_molecules = {_toml_bool(request.unique_molecules)}",
            f"randomize_smiles = {_toml_bool(request.randomize_smiles)}",
            f"isomeric_smiles = {_toml_bool(request.isomeric_smiles)}",
        ]
    )
    if smiles_file is not None:
        lines.append(f"smiles_file = {_toml_str(smiles_file.as_posix())}")
    if spec.uses_sample_strategy:
        lines.append(f"sample_strategy = {_toml_str(request.sample_strategy)}")
    if spec.uses_temperature:
        lines.append(f"temperature = {float(request.temperature)}")
    lines.append("")
    return "\n".join(lines)


def write_sampling_inputs(directory: Path, request: SamplingRequest) -> tuple[Path, Path]:
    """Write ``sampling.toml`` and, when needed, ``seeds.smi``. Return both paths' config and CSV."""
    request = prepare_sampling_request(request)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "sampling.csv"
    smiles_path: Path | None = None
    seeds = effective_seeds(request.generator, request.seeds, request.scaffold_smarts)
    if generator_by_key(request.generator).needs_seeds:
        smiles_path = directory / "seeds.smi"
        payload = "\n".join(seeds) + "\n"
        smiles_path.write_text(payload, encoding="utf-8", newline="\n")
    config = directory / "sampling.toml"
    config.write_text(
        render_sampling_toml(request, output_file=output, smiles_file=smiles_path),
        encoding="utf-8",
        newline="\n",
    )
    return config, output


def parse_sampling_csv(path: Path) -> list[SampledMolecule]:
    """Read a REINVENT sampling CSV. The SMILES column is required; NLL and seed are optional."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        return []
    header, data = _split_header(rows)
    smiles_i = _column_index(header, _SMILES_HEADERS, fallback=0)
    nll_i = _column_index(header, _NLL_HEADERS, fallback=None)
    seed_i = _column_index(header, _SEED_HEADERS, fallback=None)
    if seed_i == smiles_i:
        seed_i = None
    molecules: list[SampledMolecule] = []
    for row in data:
        smiles = _cell(row, smiles_i)
        if not smiles or smiles.lower() in _SMILES_HEADERS:
            continue
        molecules.append(
            SampledMolecule(
                smiles=smiles,
                nll=_cell(row, nll_i),
                seed_smiles=_cell(row, seed_i),
            )
        )
    return molecules


def outcome_from_csv(
    path: Path,
    request: SamplingRequest,
    *,
    cancelled: bool,
) -> SamplingOutcome:
    """Turn a sampling CSV into table records. Unreadable SMILES are counted and dropped."""
    if not path.is_file():
        return SamplingOutcome(records=(), parsed=0, skipped_invalid=0, cancelled=cancelled)
    sampled = parse_sampling_csv(path)
    spec = generator_by_key(request.generator)
    model = request.model_file.strip()
    records: list[tuple[str, dict[str, str]]] = []
    skipped = 0
    missed_scaffold = 0
    for molecule in sampled:
        if not smiles_is_parseable(molecule.smiles):
            skipped += 1
            continue
        if not smiles_matches_scaffold(molecule.smiles, request.scaffold_smarts):
            missed_scaffold += 1
            continue
        fields = {
            "REINVENT_NLL": molecule.nll,
            "REINVENT_Generator": spec.label,
            "REINVENT_Model": model,
        }
        if molecule.seed_smiles:
            fields["REINVENT_Seed"] = molecule.seed_smiles
        records.append((molecule.smiles, fields))
    return SamplingOutcome(
        records=tuple(records),
        parsed=len(sampled),
        skipped_invalid=skipped,
        cancelled=cancelled,
        skipped_scaffold=missed_scaffold,
    )


def resolve_reinvent_executable(user_path: str = "") -> str | None:
    """Saved Configure path, *user_path*, or ``reinvent`` on PATH. ``None`` when missing."""
    text = (user_path or "").strip()
    if not text:
        from ..platform_support.tool_paths import TOOL_REINVENT, configured_executable

        text = configured_executable(TOOL_REINVENT)
    if text:
        from ..platform_support.bundled_paths import resolve_user_executable

        return resolve_user_executable(text)
    found = which("reinvent") or which("reinvent.exe")
    return found or None


def describe_reinvent(user_path: str = "") -> tuple[bool, str]:
    """Run ``reinvent -V``. Return whether it responded, and a short message."""
    exe = resolve_reinvent_executable(user_path)
    if not exe:
        return False, MISSING_REINVENT_MSG
    shared = _app_python_problem(exe)
    if shared:
        return False, shared
    try:
        from ..platform_support.session_runtime import ToolDenied, require_tool

        require_tool(exe, "REINVENT")
        proc = subprocess.run(
            [exe, "-V"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            stdin=subprocess.DEVNULL,
            env=_child_environment(exe),
            creationflags=_CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
        )
    except (OSError, subprocess.SubprocessError, ToolDenied) as exc:
        return False, f"Could not run REINVENT: {exc}"
    detail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    first = detail.splitlines()[0] if detail else f"exit code {proc.returncode}"
    named = "reinvent" in Path(exe).name.lower()
    mentions = "reinvent" in detail.lower()
    if (proc.returncode == 0 and (named or mentions)) or mentions:
        return True, f"OK ({exe}): {first}"
    failed = detail or first
    return False, f"REINVENT ran but the version check failed:\n{failed}"


def execute_sampling(
    executable: str,
    request: SamplingRequest,
    *,
    cancel: Callable[[], bool] | None = None,
    on_log: Callable[[str], None] | None = None,
    work_dir: Path | None = None,
) -> SamplingOutcome:
    """Write a temp config, run *executable*, and parse the CSV. The temp dir is removed."""
    prepared = prepare_sampling_request(request)
    message = validate_request(prepared)
    if message:
        raise ReinventSamplingError(message)
    shared = _app_python_problem(executable)
    if shared:
        raise ReinventSamplingError(shared)
    owns_dir = work_dir is None
    directory = (
        Path(work_dir)
        if work_dir is not None
        else Path(tempfile.mkdtemp(prefix="molmanager-reinvent-"))
    )
    log = on_log or (lambda _line: None)
    stopped = cancel or (lambda: False)
    try:
        if prepared.generator != request.generator:
            log(SCAFFOLD_DECORATION_NOTE)
        config, output = write_sampling_inputs(directory, prepared)
        log(f"REINVENT: {executable}")
        for line in config.read_text(encoding="utf-8").splitlines():
            log(line)
        if (prepared.extra_flags or "").strip():
            log(f"Extra flags: {prepared.extra_flags.strip()}")
        try:
            return_code = _run_process(
                executable,
                config,
                directory,
                stopped,
                log,
                parse_extra_flags(prepared.extra_flags),
            )
        except ReinventSamplingCancelled:
            log("Sampling stopped.")
            return outcome_from_csv(output, prepared, cancelled=True)
        if return_code != 0:
            raise ReinventSamplingError(
                f"REINVENT exited with status {return_code}. See the log for details."
            )
        if not output.is_file():
            raise ReinventSamplingError("REINVENT did not write a sampling CSV.")
        return outcome_from_csv(output, prepared, cancelled=False)
    finally:
        if owns_dir:
            shutil.rmtree(directory, ignore_errors=True)


def _smiles_with_attachment(mol, atom_index: int) -> str | None:
    """Copy *mol* with ``*`` bonded in place of one hydrogen on *atom_index*."""
    from rdkit import Chem

    try:
        edited = Chem.RWMol(mol)
        atom = edited.GetAtomWithIdx(atom_index)
        if atom.GetNumExplicitHs():
            atom.SetNumExplicitHs(0)
        dummy = edited.AddAtom(Chem.Atom(0))
        edited.AddBond(atom_index, dummy, Chem.BondType.SINGLE)
        Chem.SanitizeMol(edited)
        smiles = Chem.MolToSmiles(edited)
    except (ValueError, RuntimeError):
        return None
    if not smiles or "*" not in smiles or not smiles_is_parseable(smiles):
        return None
    return smiles


def _validate_seed_line(spec: ReinventGenerator, index: int, line: str) -> str | None:
    if spec.seed_kind == "pair":
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return f"Line {index} needs two fragments separated by |."
        for side in parts:
            if "*" not in side:
                return f"Line {index} fragments each need an attachment point (*)."
            if not smiles_is_parseable(side):
                return f"Line {index} has a fragment RDKit could not read ({side})."
        return None
    if spec.seed_kind == "scaffold" and "*" not in line:
        return f"Line {index} needs an attachment point (*)."
    if not smiles_is_parseable(line):
        return f"Line {index} is not a SMILES RDKit could read."
    return None


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_path(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text
    return Path(text).as_posix()


def _looks_like_header(row: list[str]) -> bool:
    lowered = {cell.strip().lower() for cell in row}
    return bool(lowered & (_SMILES_HEADERS | _NLL_HEADERS | _SEED_HEADERS))


def _split_header(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    if _looks_like_header(rows[0]):
        return rows[0], rows[1:]
    width = max(len(row) for row in rows)
    header = ["SMILES"] + [f"col_{i}" for i in range(1, width)]
    if width > 1:
        header[-1] = "NLL"
    return header, rows


def _column_index(header: list[str], names: set[str], fallback: int | None) -> int | None:
    for index, cell in enumerate(header):
        if cell.strip().lower() in names:
            return index
    return fallback


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return row[index].strip()


def parse_extra_flags(text: str) -> tuple[str, ...]:
    """Split a reinvent option line. Paths keep their backslashes.

    Accepted options are the ones ``reinvent`` itself documents. A bare word,
    or ``--version`` / ``--help``, is rejected because it would not run the config.
    """
    raw = (text or "").strip()
    if not raw:
        return ()
    tokens = tuple(_split_flag_text(raw))
    index = 0
    while index < len(tokens):
        token = tokens[index]
        name, separator, _inline = token.partition("=")
        if token in _STOP_FLAGS or name in _STOP_FLAGS:
            raise ValueError(f"{name} stops REINVENT before the run.")
        if name in _REPEAT_FLAGS:
            if separator:
                index += 1
                continue
            nxt = index + 1
            if nxt >= len(tokens) or tokens[nxt].startswith("-"):
                raise ValueError(f"{token} needs a value.")
            index = nxt + 1
            while index < len(tokens) and not tokens[index].startswith("-"):
                index += 1
            continue
        if name in _VALUE_FLAGS:
            if separator:
                index += 1
                continue
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("-"):
                raise ValueError(f"{token} needs a value.")
            index += 2
            continue
        if token.startswith("-"):
            raise ValueError(f"REINVENT does not take {token}.")
        raise ValueError("Extra flags are options such as --seed 1 or --log-level debug.")
    return tokens


def _split_flag_text(text: str) -> list[str]:
    """Whitespace split that keeps quoted paths and does not treat ``\\`` as an escape."""
    tokens: list[str] = []
    buf: list[str] = []
    quote = ""
    for ch in text:
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if quote:
        raise ValueError("Extra flags have an unmatched quote.")
    if buf:
        tokens.append("".join(buf))
    return tokens


def _run_process(
    executable: str,
    config: Path,
    cwd: Path,
    cancel: Callable[[], bool],
    on_log: Callable[[str], None],
    extra_args: tuple[str, ...] = (),
) -> int:
    if cancel():
        raise ReinventSamplingCancelled("Sampling stopped.")
    command = [executable, "--log-level", "info", *extra_args, str(config)]
    try:
        from ..platform_support.session_runtime import ToolDenied, require_tool

        require_tool(executable, "REINVENT")
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_child_environment(executable),
            creationflags=_CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
        )
    except (OSError, ToolDenied) as exc:
        raise ReinventSamplingError(f"Could not start REINVENT: {exc}") from exc

    lines: queue.Queue[str | None] = queue.Queue()

    def _pump() -> None:
        stream = proc.stdout
        if stream is None:
            lines.put(None)
            return
        try:
            for line in stream:
                lines.put(line)
        except OSError:
            return
        finally:
            lines.put(None)

    thread = threading.Thread(target=_pump, name="reinvent-log", daemon=True)
    thread.start()
    try:
        while True:
            if cancel():
                _kill_process(proc)
                raise ReinventSamplingCancelled("Sampling stopped.")
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            text = line.rstrip("\r\n")
            if text:
                on_log(text)
        try:
            return int(proc.wait(timeout=30))
        except subprocess.TimeoutExpired as exc:
            _kill_process(proc)
            raise ReinventSamplingError("REINVENT did not exit after it stopped writing.") from exc
    finally:
        if proc.poll() is None:
            _kill_process(proc)
        thread.join(timeout=2)


def _app_python_problem(executable: str) -> str | None:
    """Refuse MolManager's own interpreter. REINVENT cannot share this environment."""
    try:
        same = Path(executable).resolve() == Path(sys.executable).resolve()
    except OSError:
        return None
    if not same:
        return None
    return (
        "That program is the Python running MolManager. REINVENT needs its own "
        "environment. Point Settings → Configure → REINVENT at the reinvent command "
        "in that environment."
    )


def _child_environment(executable: str) -> dict[str, str]:
    """Environment for the REINVENT command, without this app's Python path.

    A conda or virtualenv layout next to the command gets its library directory
    on PATH so RDKit can load without activating that environment in a shell.
    """
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONNOUSERSITE"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    root = _env_root(Path(executable))
    if root is None:
        return env
    extra = [root, root / "Library" / "bin", root / "Scripts", root / "bin"]
    prefix = os.pathsep.join(str(path) for path in extra if path.is_dir())
    if prefix:
        env["PATH"] = prefix + os.pathsep + env.get("PATH", "")
    return env


def _env_root(executable: Path) -> Path | None:
    parent = executable.parent
    root = parent.parent if parent.name.lower() in {"bin", "scripts"} else parent
    if (root / "conda-meta").is_dir() or (root / "pyvenv.cfg").is_file():
        return root
    return None


def _kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return
