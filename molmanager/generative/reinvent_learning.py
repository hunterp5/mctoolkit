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

"""One-stage REINVENT 4 reinforcement learning.

REINVENT stays a separate command. This module writes a ``staged_learning``
config, runs it, and keeps the highest-scoring unique SMILES from the summary
CSV. Scoring is limited to RDKit components that ship with REINVENT
(QED, molecular weight, SlogP, SA score, Tanimoto similarity, and SMARTS alerts).
"""

from __future__ import annotations

import csv
import io
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .reinvent_sampling import (
    ReinventSamplingCancelled,
    ReinventSamplingError,
    _app_python_problem,
    _run_process,
    _toml_bool,
    _toml_path,
    _toml_str,
    SCAFFOLD_DECORATION_NOTE,
    decoration_seeds,
    effective_seeds,
    generator_by_key,
    parse_extra_flags,
    scaffold_error,
    scaffold_scoring_smarts,
    smarts_is_parseable,
    smiles_is_parseable,
    smiles_matches_scaffold,
    validate_seeds,
)

# Ask before a run would score more molecules than this (steps times batch size).
CONFIRM_LEARNING_COUNT = 20_000

# REINVENT's published de novo alert list. A match scores zero and is filtered out.
UNWANTED_SMARTS: tuple[str, ...] = (
    "[*;r{8-17}]",
    "[#8][#8]",
    "[#6;+]",
    "[#16][#16]",
    "[#7;!n][S;!$(S(=O)=O)]",
    "[#7;!n][#7;!n]",
    "C#C",
    "C(=[O,S])[O,S]",
    "[#7;!n][C;!$(C(=[O,N])[N,O])][#16;!s]",
    "[#7;!n][C;!$(C(=[O,N])[N,O])][#7;!n]",
    "[#7;!n][C;!$(C(=[O,N])[N,O])][#8;!o]",
    "[#8;!o][C;!$(C(=[O,N])[N,O])][#16;!s]",
    "[#8;!o][C;!$(C(=[O,N])[N,O])][#8;!o]",
    "[#16;!s][C;!$(C(=[O,N])[N,O])][#16;!s]",
)

_AGGREGATIONS = frozenset({"geometric_mean", "arithmetic_mean"})
DIVERSITY_FILTERS: tuple[tuple[str, str], ...] = (
    ("IdenticalMurckoScaffold", "Identical Murcko scaffold"),
    ("IdenticalTopologicalScaffold", "Identical topological scaffold"),
    ("ScaffoldSimilarity", "Similar scaffolds"),
    ("PenalizeSameSmiles", "Same SMILES"),
)
_DIVERSITY_TYPES = frozenset(key for key, _label in DIVERSITY_FILTERS)
_SKIP_FIELDS = frozenset({"smiles", "smiles_state", "agent", "prior", "target", "score", "step"})
_SEED_FIELDS = ("input_smiles", "input_scaffold", "warheads")


class ReinventLearningError(ReinventSamplingError):
    """The learning config is invalid or REINVENT did not produce a summary."""


@dataclass(frozen=True)
class LearningRequest:
    """One staged-learning run. The agent starts from ``model_file``."""

    generator: str
    model_file: str
    device: str
    batch_size: int
    max_steps: int
    min_steps: int
    max_score: float
    sigma: int
    rate: float
    randomize_smiles: bool
    diversity_filter: bool
    aggregation: str
    keep: int
    qed: bool
    molecular_weight: bool
    mw_low: float
    mw_high: float
    slogp: bool
    slogp_low: float
    slogp_high: float
    sa_score: bool
    similarity: bool
    similarity_smiles: tuple[str, ...]
    unwanted_groups: bool
    extra_smarts: tuple[str, ...]
    sample_strategy: str
    temperature: float
    distance_threshold: int
    seeds: tuple[str, ...] = ()
    agent_output: str = ""
    scaffold_smarts: str = ""
    qed_weight: float = 1.0
    mw_weight: float = 1.0
    slogp_weight: float = 1.0
    sa_weight: float = 1.0
    similarity_weight: float = 1.0
    seed: int = 0
    isomeric_smiles: bool = False
    extra_flags: str = ""
    diversity_type: str = "IdenticalMurckoScaffold"
    diversity_bucket: int = 25
    diversity_minscore: float = 0.4
    diversity_minsimilarity: float = 0.4
    diversity_penalty: float = 0.5
    similarity_radius: int = 2
    similarity_counts: bool = False
    similarity_features: bool = False


@dataclass(frozen=True)
class LearningOutcome:
    """Molecules kept from the summary, plus how many CSV rows were dropped."""

    records: tuple[tuple[str, dict[str, str]], ...]
    parsed: int
    skipped_invalid: int
    cancelled: bool
    skipped_scaffold: int = 0


def prepare_learning_request(request: LearningRequest) -> LearningRequest:
    """Decorate a de novo SMILES scaffold with LibInvent.

    The Reinvent prior cannot be aimed at a core. A molecule scaffold is
    learned as R-groups on that core. SMARTS that is not a molecule stays a
    score and a filter on the de novo run.
    """
    if request.generator != "denovo":
        return request
    seeds = decoration_seeds(request.scaffold_smarts)
    if not seeds:
        return request
    return replace(
        request,
        generator="libinvent",
        model_file=generator_by_key("libinvent").default_model,
        sample_strategy="multinomial",
        seeds=seeds,
    )


def validate_request(request: LearningRequest) -> str | None:
    """Return a user-facing error, or ``None`` when *request* can be written."""
    request = prepare_learning_request(request)
    try:
        spec = generator_by_key(request.generator)
    except KeyError:
        return "Choose a generator."
    if not (request.model_file or "").strip():
        return "Enter a REINVENT prior id or a model file."
    if not (request.device or "").strip():
        return "Choose a device (cpu or cuda:0)."
    if int(request.batch_size) < 1:
        return "Use a batch size of at least 1."
    if int(request.max_steps) < 1:
        return "Run at least one learning step."
    if int(request.min_steps) < 0:
        return "The minimum number of steps cannot be negative."
    if int(request.min_steps) > int(request.max_steps):
        return "The minimum number of steps cannot exceed the maximum."
    if not 0.0 < float(request.max_score) <= 1.0:
        return "The stop score must be greater than 0 and at most 1."
    if int(request.sigma) < 1:
        return "Sigma must be at least 1."
    if float(request.rate) <= 0:
        return "The learning rate must be greater than 0."
    if int(request.keep) < 1:
        return "Keep at least one molecule."
    if request.aggregation not in _AGGREGATIONS:
        return "Choose geometric mean or arithmetic mean."
    if spec.key == "mol2mol" and request.sample_strategy not in {"multinomial", "beamsearch"}:
        return "Choose multinomial or beam search."
    pattern_error = scaffold_error(request.scaffold_smarts)
    if pattern_error:
        return pattern_error
    seed_error = validate_seeds(
        request.generator,
        effective_seeds(request.generator, request.seeds, request.scaffold_smarts),
    )
    if seed_error:
        return seed_error
    if request.molecular_weight and float(request.mw_low) >= float(request.mw_high):
        return "Molecular weight needs a low value below the high value."
    if request.slogp and float(request.slogp_low) >= float(request.slogp_high):
        return "SlogP needs a low value below the high value."
    if int(request.seed) < 0:
        return "The random seed cannot be negative."
    if request.diversity_filter:
        if request.diversity_type not in _DIVERSITY_TYPES:
            return "Choose a diversity filter."
        if int(request.diversity_bucket) < 1:
            return "The diversity bucket size must be at least 1."
        if not 0.0 <= float(request.diversity_minscore) <= 1.0:
            return "The diversity minimum score must be from 0 to 1."
        if not 0.0 <= float(request.diversity_minsimilarity) <= 1.0:
            return "The scaffold similarity cutoff must be from 0 to 1."
        if not 0.0 <= float(request.diversity_penalty) <= 1.0:
            return "The repeated-SMILES penalty must be from 0 to 1."
    weight_error = _weight_error(request)
    if weight_error:
        return weight_error
    if request.similarity and int(request.similarity_radius) < 1:
        return "The fingerprint radius must be at least 1."
    try:
        parse_extra_flags(request.extra_flags)
    except ValueError as exc:
        return str(exc)
    if request.similarity and not request.similarity_smiles:
        return "Similarity needs at least one reference SMILES."
    for index, smiles in enumerate(request.similarity_smiles, start=1):
        if not smiles_is_parseable(smiles):
            return f"Reference {index} is not a SMILES RDKit could read."
    smarts = _alert_smarts(request)
    for index, pattern in enumerate(smarts, start=1):
        if not smarts_is_parseable(pattern):
            return f"SMARTS pattern {index} is not a pattern RDKit could read ({pattern})."
    if not _has_scorer(request):
        return "Choose at least one score: QED, molecular weight, SlogP, SA score, or similarity."
    destination = (request.agent_output or "").strip()
    if destination and Path(destination).is_dir():
        return "The agent path is a folder. Choose a file name for the checkpoint."
    return None


def estimated_learning_count(request: LearningRequest) -> int:
    """How many SMILES a full run scores: steps times the batch size."""
    return max(0, int(request.max_steps)) * max(0, int(request.batch_size))


def render_learning_toml(
    request: LearningRequest,
    *,
    summary_prefix: Path,
    checkpoint: Path,
    smiles_file: Path | None,
) -> str:
    """TOML for one ``staged_learning`` stage. Paths use forward slashes."""
    spec = generator_by_key(request.generator)
    model = _toml_str(_toml_path(request.model_file))
    lines = [
        'run_type = "staged_learning"',
        f"device = {_toml_str(request.device.strip())}",
    ]
    if int(request.seed) > 0:
        lines.append(f"seed = {int(request.seed)}")
    lines.extend(
        [
            "",
            "[parameters]",
            f"prior_file = {model}",
            f"agent_file = {model}",
            f"summary_csv_prefix = {_toml_str(summary_prefix.as_posix())}",
            "use_checkpoint = false",
            "purge_memories = false",
            f"batch_size = {int(request.batch_size)}",
            f"randomize_smiles = {_toml_bool(request.randomize_smiles)}",
            f"isomeric_smiles = {_toml_bool(request.isomeric_smiles)}",
        ]
    )
    if smiles_file is not None:
        lines.append(f"smiles_file = {_toml_str(smiles_file.as_posix())}")
    if spec.key == "mol2mol":
        lines.append(f"sample_strategy = {_toml_str(request.sample_strategy or 'multinomial')}")
        lines.append(f"temperature = {_toml_float(request.temperature)}")
        lines.append(f"distance_threshold = {int(request.distance_threshold)}")
    lines.extend(
        [
            "",
            "[learning_strategy]",
            'type = "dap"',
            f"sigma = {int(request.sigma)}",
            f"rate = {_toml_float(request.rate)}",
            "",
        ]
    )
    if request.diversity_filter:
        lines.extend(
            [
                "[diversity_filter]",
                f"type = {_toml_str(request.diversity_type)}",
                f"bucket_size = {int(request.diversity_bucket)}",
                f"minscore = {_toml_float(request.diversity_minscore)}",
                f"minsimilarity = {_toml_float(request.diversity_minsimilarity)}",
                f"penalty_multiplier = {_toml_float(request.diversity_penalty)}",
                "",
            ]
        )
    lines.extend(
        [
            "[[stage]]",
            f"chkpt_file = {_toml_str(checkpoint.as_posix())}",
            'termination = "simple"',
            f"max_score = {_toml_float(request.max_score)}",
            f"min_steps = {int(request.min_steps)}",
            f"max_steps = {int(request.max_steps)}",
            "",
            "[stage.scoring]",
            f"type = {_toml_str(request.aggregation)}",
            "",
        ]
    )
    lines.extend(_scoring_blocks(request))
    return "\n".join(lines).rstrip() + "\n"


def write_learning_inputs(directory: Path, request: LearningRequest) -> tuple[Path, Path, Path]:
    """Write the config, optional seeds, and return config, summary CSV, and checkpoint paths."""
    request = prepare_learning_request(request)
    directory.mkdir(parents=True, exist_ok=True)
    smiles_path: Path | None = None
    if generator_by_key(request.generator).needs_seeds:
        smiles_path = directory / "seeds.smi"
        seeds = effective_seeds(request.generator, request.seeds, request.scaffold_smarts)
        smiles_path.write_text("\n".join(seeds) + "\n", encoding="utf-8", newline="\n")
    summary = directory / "summary_1.csv"
    checkpoint = directory / "agent.chkpt"
    config = directory / "staged_learning.toml"
    config.write_text(
        render_learning_toml(
            request,
            summary_prefix=directory / "summary",
            checkpoint=checkpoint,
            smiles_file=smiles_path,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return config, summary, checkpoint


def parse_learning_csv(path: Path) -> tuple[list[dict[str, str]], int]:
    """Read a staged-learning summary. Return rows and how many were invalid.

    Invalid means SMILES state 0 or a SMILES RDKit cannot build. Duplicate
    SMILES are kept here; :func:`outcome_from_summary` collapses them.
    """
    if not path.is_file():
        return [], 0
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        return [], 0
    header = [cell.strip() for cell in rows[0]]
    lowered = [cell.lower() for cell in header]
    if "smiles" not in lowered:
        return [], 0
    parsed: list[dict[str, str]] = []
    skipped = 0
    for raw in rows[1:]:
        record = {
            header[index]: raw[index].strip()
            for index in range(min(len(header), len(raw)))
            if header[index]
        }
        smiles = _record_value(record, "smiles")
        if not smiles:
            continue
        state = _record_value(record, "smiles_state")
        if state == "0" or not smiles_is_parseable(smiles):
            skipped += 1
            continue
        parsed.append(record)
    return parsed, skipped


def outcome_from_summary(
    path: Path,
    request: LearningRequest,
    *,
    cancelled: bool,
) -> LearningOutcome:
    """Keep the highest-scoring unique molecules, up to ``request.keep``."""
    parsed, skipped = parse_learning_csv(path)
    spec = generator_by_key(request.generator)
    missed_scaffold = 0
    best: dict[str, tuple[float, int, str, dict[str, str]]] = {}
    for record in parsed:
        smiles = _record_value(record, "smiles")
        if not smiles_matches_scaffold(smiles, request.scaffold_smarts):
            missed_scaffold += 1
            continue
        key = _canonical_smiles(smiles) or smiles
        score = _as_float(_record_value(record, "score"))
        step = int(_as_float(_record_value(record, "step")))
        current = best.get(key)
        if current is None or (score, step) >= (current[0], current[1]):
            best[key] = (score, step, smiles, record)
    ranked = sorted(best.values(), key=lambda item: (item[0], item[1]), reverse=True)
    records: list[tuple[str, dict[str, str]]] = []
    for score, step, smiles, record in ranked[: int(request.keep)]:
        fields = {
            "REINVENT_Score": f"{score:.4f}",
            "REINVENT_Step": str(step),
            "REINVENT_Generator": spec.label,
            "REINVENT_Model": request.model_file.strip(),
        }
        agent = _record_value(record, "agent")
        prior = _record_value(record, "prior")
        if agent:
            fields["REINVENT_Agent_NLL"] = agent
        if prior:
            fields["REINVENT_Prior_NLL"] = prior
        seed = ""
        for name in _SEED_FIELDS:
            seed = _record_value(record, name)
            if seed:
                break
        if seed:
            fields["REINVENT_Seed"] = seed
        for name, value in record.items():
            lowered = name.lower()
            if lowered in _SKIP_FIELDS or lowered in _SEED_FIELDS or lowered.endswith(" (raw)"):
                continue
            if not value:
                continue
            fields[_field_name(name)] = value
        records.append((smiles, fields))
    return LearningOutcome(
        records=tuple(records),
        parsed=len(parsed) + skipped,
        skipped_invalid=skipped,
        cancelled=cancelled,
        skipped_scaffold=missed_scaffold,
    )


def execute_learning(
    executable: str,
    request: LearningRequest,
    *,
    cancel: Callable[[], bool] | None = None,
    on_log: Callable[[str], None] | None = None,
    work_dir: Path | None = None,
) -> LearningOutcome:
    """Write a temp config, run *executable*, and read the summary CSV."""
    prepared = prepare_learning_request(request)
    message = validate_request(prepared)
    if message:
        raise ReinventLearningError(message)
    shared = _app_python_problem(executable)
    if shared:
        raise ReinventLearningError(shared)
    owns_dir = work_dir is None
    directory = (
        Path(work_dir)
        if work_dir is not None
        else Path(tempfile.mkdtemp(prefix="molmanager-reinvent-rl-"))
    )
    log = on_log or (lambda _line: None)
    stopped = cancel or (lambda: False)
    try:
        if prepared.generator != request.generator:
            log(SCAFFOLD_DECORATION_NOTE)
        config, summary, checkpoint = write_learning_inputs(directory, prepared)
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
            log("Learning stopped.")
            _copy_agent(checkpoint, prepared.agent_output, log)
            return outcome_from_summary(summary, prepared, cancelled=True)
        outcome = outcome_from_summary(summary, prepared, cancelled=False)
        _copy_agent(checkpoint, prepared.agent_output, log)
        if return_code != 0 and not outcome.records:
            raise ReinventLearningError(
                f"REINVENT exited with status {return_code}. See the log for details."
            )
        if return_code != 0:
            log(f"REINVENT exited with status {return_code}. Kept molecules written before that.")
        elif not summary.is_file():
            raise ReinventLearningError("REINVENT did not write a learning summary.")
        return outcome
    finally:
        if owns_dir:
            shutil.rmtree(directory, ignore_errors=True)


def _weight_error(request: LearningRequest) -> str | None:
    named = (
        (request.qed, "QED", request.qed_weight),
        (request.molecular_weight, "molecular weight", request.mw_weight),
        (request.slogp, "SlogP", request.slogp_weight),
        (request.sa_score, "SA score", request.sa_weight),
        (request.similarity, "similarity", request.similarity_weight),
    )
    for enabled, label, weight in named:
        if enabled and float(weight) < 0:
            return f"The {label} weight cannot be negative."
    return None


def _has_scorer(request: LearningRequest) -> bool:
    return any(
        (
            request.qed,
            request.molecular_weight,
            request.slogp,
            request.sa_score,
            request.similarity,
        )
    )


def _alert_smarts(request: LearningRequest) -> tuple[str, ...]:
    patterns: list[str] = []
    if request.unwanted_groups:
        patterns.extend(UNWANTED_SMARTS)
    patterns.extend(pattern.strip() for pattern in request.extra_smarts if pattern.strip())
    return tuple(patterns)


def _scoring_blocks(request: LearningRequest) -> list[str]:
    blocks: list[str] = []
    if request.qed:
        blocks.extend(
            _component(
                "Qed",
                "QED",
                request.qed_weight,
            )
        )
    if request.molecular_weight:
        blocks.extend(
            _component(
                "MolecularWeight",
                "Molecular weight",
                request.mw_weight,
                transform=[
                    'transform.type = "double_sigmoid"',
                    f"transform.low = {_toml_float(request.mw_low)}",
                    f"transform.high = {_toml_float(request.mw_high)}",
                    "transform.coef_div = 500.0",
                    "transform.coef_si = 20.0",
                    "transform.coef_se = 20.0",
                ],
            )
        )
    if request.slogp:
        blocks.extend(
            _component(
                "SlogP",
                "SlogP",
                request.slogp_weight,
                transform=[
                    'transform.type = "double_sigmoid"',
                    f"transform.low = {_toml_float(request.slogp_low)}",
                    f"transform.high = {_toml_float(request.slogp_high)}",
                    "transform.coef_div = 100.0",
                    "transform.coef_si = 150.0",
                    "transform.coef_se = 150.0",
                ],
            )
        )
    if request.sa_score:
        blocks.extend(
            _component(
                "SAScore",
                "SA score",
                request.sa_weight,
                transform=[
                    'transform.type = "reverse_sigmoid"',
                    "transform.low = 2.0",
                    "transform.high = 5.0",
                    "transform.k = 0.5",
                ],
            )
        )
    scaffold = (request.scaffold_smarts or "").strip()
    if scaffold:
        blocks.extend(
            _component(
                "MatchingSubstructure",
                "Scaffold match",
                1.0,
                params=[
                    f"params.smarts = [{_toml_str(scaffold_scoring_smarts(scaffold))}]",
                    "params.use_chirality = false",
                ],
            )
        )
    if request.similarity:
        endpoints: list[str] = []
        for index, smiles in enumerate(request.similarity_smiles, start=1):
            endpoints.extend(
                [
                    "[[stage.scoring.component.TanimotoSimilarity.endpoint]]",
                    f"name = {_toml_str(f'Similarity {index}')}",
                    f"weight = {_toml_float(request.similarity_weight)}",
                    f"params.smiles = [{_toml_str(smiles)}]",
                    f"params.radius = {int(request.similarity_radius)}",
                    f"params.use_counts = {_toml_bool(request.similarity_counts)}",
                    f"params.use_features = {_toml_bool(request.similarity_features)}",
                    "",
                ]
            )
        blocks.extend(
            [
                "[[stage.scoring.component]]",
                "[stage.scoring.component.TanimotoSimilarity]",
                "",
                *endpoints,
            ]
        )
    smarts = _alert_smarts(request)
    if smarts:
        quoted = ", ".join(_toml_str(pattern) for pattern in smarts)
        blocks.extend(
            [
                "[[stage.scoring.component]]",
                "[stage.scoring.component.CustomAlerts]",
                "",
                "[[stage.scoring.component.CustomAlerts.endpoint]]",
                'name = "Unwanted SMARTS"',
                f"params.smarts = [{quoted}]",
                "",
            ]
        )
    return blocks


def _component(
    key: str,
    name: str,
    weight: float,
    *,
    transform: list[str] | None = None,
    params: list[str] | None = None,
) -> list[str]:
    lines = [
        "[[stage.scoring.component]]",
        f"[stage.scoring.component.{key}]",
        "",
        f"[[stage.scoring.component.{key}.endpoint]]",
        f"name = {_toml_str(name)}",
        f"weight = {_toml_float(weight)}",
    ]
    if transform:
        lines.extend(transform)
    if params:
        lines.extend(params)
    lines.append("")
    return lines


def _copy_agent(source: Path, destination: str, log: Callable[[str], None]) -> None:
    text = (destination or "").strip()
    if not text:
        return
    if not source.is_file():
        log("REINVENT did not write an agent checkpoint.")
        return
    dest = Path(text)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    log(f"Saved agent to {dest}")


def _toml_float(value: float) -> str:
    text = f"{float(value):.8g}"
    if "e" not in text.lower() and "." not in text:
        text += ".0"
    return text


def _field_name(header: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in header.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return "REINVENT_" + cleaned.strip("_")


def _record_value(record: dict[str, str], name: str) -> str:
    for key, value in record.items():
        if key.lower() == name:
            return value.strip()
    return ""


def _as_float(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


def _canonical_smiles(smiles: str) -> str:
    from rdkit import Chem, rdBase

    blocker = rdBase.BlockLogs()
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return ""
        return Chem.MolToSmiles(mol, canonical=True)
    finally:
        del blocker
