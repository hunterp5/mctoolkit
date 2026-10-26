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

"""Run AiZynthFinder in a separate Python environment and read its checkpoint.

The search stays on this machine: policy models and the stock file come from the
config the user points at. Configs that turn on a remote policy server or a
non-local MongoDB stock are rejected before the process starts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..platform_support.tool_paths import (
    TOOL_AIZYNTH_CONFIG,
    TOOL_AIZYNTH_PYTHON,
    configured_executable,
)

COLUMN_SOLVED = "AiZynth Solved"
COLUMN_SOLVED_ROUTES = "AiZynth Solved Routes"
COLUMN_SCORE = "AiZynth Score"
COLUMN_STEPS = "AiZynth Steps"
COLUMN_TIME = "AiZynth Time (s)"
COLUMN_IN_STOCK = "AiZynth Precursors in Stock"
COLUMN_NOT_IN_STOCK = "AiZynth Precursors not in Stock"
COLUMN_FIRST_SOLUTION_TIME = "AiZynth First Solution (s)"
COLUMN_FIRST_SOLUTION_ITERATION = "AiZynth First Solution Iteration"
COLUMN_NODES = "AiZynth Nodes"
COLUMN_MAX_TRANSFORMS = "AiZynth Max Transforms"
COLUMN_MAX_CHILDREN = "AiZynth Max Children"
COLUMN_ROUTES = "AiZynth Routes"
COLUMN_PRECURSORS = "AiZynth Precursors"
COLUMN_PRECURSORS_IN_STOCK_N = "AiZynth Precursors in Stock Count"
COLUMN_AVAILABILITY = "AiZynth Precursor Availability"
COLUMN_POLICIES = "AiZynth Policies"
COLUMN_STOCK = "AiZynth Stock"
COLUMN_PROFILING = "AiZynth Profiling"

OUTPUT_COLUMNS: tuple[str, ...] = (
    COLUMN_SOLVED,
    COLUMN_SOLVED_ROUTES,
    COLUMN_SCORE,
    COLUMN_STEPS,
    COLUMN_TIME,
    COLUMN_IN_STOCK,
    COLUMN_NOT_IN_STOCK,
    COLUMN_FIRST_SOLUTION_TIME,
    COLUMN_FIRST_SOLUTION_ITERATION,
    COLUMN_NODES,
    COLUMN_MAX_TRANSFORMS,
    COLUMN_MAX_CHILDREN,
    COLUMN_ROUTES,
    COLUMN_PRECURSORS,
    COLUMN_PRECURSORS_IN_STOCK_N,
    COLUMN_AVAILABILITY,
    COLUMN_POLICIES,
    COLUMN_STOCK,
    COLUMN_PROFILING,
)

# Statistics already given a named column. Anything else AiZynthFinder reports is kept too.
_MAPPED_STATS = frozenset(
    {
        "is_solved",
        "number_of_solved_routes",
        "top_score",
        "number_of_steps",
        "search_time",
        "precursors_in_stock",
        "precursors_not_in_stock",
        "first_solution_time",
        "first_solution_iteration",
        "number_of_nodes",
        "max_transforms",
        "max_children",
        "number_of_routes",
        "number_of_precursors",
        "number_of_precursors_in_stock",
        "precursors_availability",
        "policy_used_counts",
        "stock_info",
        "profiling",
    }
)
# The route trees are stored separately. The target SMILES is already the table row.
_SKIP_STATS = frozenset({"trees", "target"})

_IMPORT_SNIPPET = "import importlib.metadata as m; print(m.version('aizynthfinder'))"
_REMOTE_MODELS = re.compile(r"use_remote_models\s*:\s*true\b", re.IGNORECASE)
_MONGO_STOCK = re.compile(r"type\s*:\s*mongodb\b", re.IGNORECASE)
_HOST_LINE = re.compile(r"^\s*host\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_TAIL_LIMIT = 4000

CancelFn = Callable[[], bool]
ProgressFn = Callable[[int, int], None]


class AizynthRunError(RuntimeError):
    """The search did not produce a route summary."""


@dataclass(frozen=True)
class SearchResult:
    """Column maps and compact routes keyed by the SMILES written to the input file."""

    summaries: dict[str, dict[str, str]]
    warning: str = ""
    cancelled: bool = False
    routes: dict[str, list[dict]] = field(default_factory=dict)


def configured_python() -> str:
    return configured_executable(TOOL_AIZYNTH_PYTHON)


def configured_config() -> str:
    return configured_executable(TOOL_AIZYNTH_CONFIG)


def resolve_python(text: str = "") -> str:
    """Return an interpreter path, or ``""`` when *text* and the saved path are unset."""
    raw = (text or "").strip() or configured_python()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if path.is_file():
        return str(path)
    found = shutil.which(raw)
    return found or ""


def resolve_config(text: str = "") -> Path | None:
    raw = (text or "").strip() or configured_config()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def _same_as_app_python(python: str) -> bool:
    try:
        return Path(python).resolve() == Path(sys.executable).resolve()
    except OSError:
        return False


def config_text_problem(text: str) -> str | None:
    """Return a user-facing reason to refuse *text*, or ``None`` when it can run locally."""
    if _REMOTE_MODELS.search(text):
        return (
            "This config sets use_remote_models to true. "
            "AiZynthFinder would send each policy prediction to a server. "
            "Leave use_remote_models false so the ONNX models run locally."
        )
    if _MONGO_STOCK.search(text):
        for raw_host in _HOST_LINE.findall(text):
            host = raw_host.strip().strip("\"'").split(":", 1)[0].strip("[]")
            if host.lower() not in _LOCAL_HOSTS:
                return (
                    f"This config uses a MongoDB stock on {raw_host}. "
                    "Use a local HDF5, CSV, or text stock so buyable-precursor "
                    "lookups stay on this machine."
                )
    if "expansion" not in text and "stock" not in text:
        return (
            "This file has no expansion or stock section, so it does not look "
            "like an AiZynthFinder config.yml."
        )
    return None


def ready_message(python_text: str = "", config_text: str = "") -> str | None:
    """Fast path/config check. Does not start the other interpreter."""
    python = resolve_python(python_text)
    if not python:
        return (
            "AiZynthFinder is not configured. Set its Python interpreter and "
            "config.yml under Settings → Configure → AiZynthFinder."
        )
    if _same_as_app_python(python):
        return (
            "That Python is the one running MolManager. AiZynthFinder needs its "
            "own environment (Python 3.10–3.12 and RDKit 2023.x)."
        )
    config = resolve_config(config_text)
    if config is None:
        return "Choose the AiZynthFinder config.yml from download_public_data."
    try:
        body = config.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Could not read {config.name}: {exc}"
    return config_text_problem(body)


def child_environment(python: Path) -> dict[str, str]:
    """Environment for the AiZynthFinder interpreter, without this app's Python path.

    A conda layout gets its ``Library/bin`` (Windows) or env root on ``PATH`` so
    RDKit and HDF5 libraries load without activating the env in a shell.
    """
    env = os.environ.copy()
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "CONDA_PYTHON_EXE",
    ):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    root = _conda_root(python)
    if root is None:
        return env
    extra = [
        root,
        root / "Library" / "bin",
        root / "Scripts",
        root / "bin",
    ]
    prefix = os.pathsep.join(str(path) for path in extra if path.is_dir())
    if prefix:
        env["PATH"] = prefix + os.pathsep + env.get("PATH", "")
    env["CONDA_PREFIX"] = str(root)
    return env


def aizynthcli_command(
    python: str,
    config: Path,
    smiles_file: Path,
    output: Path,
    checkpoint: Path,
) -> list[str]:
    """Argv for one local ``aizynthcli`` batch. A file is used even for one SMILES."""
    return [
        python,
        "-c",
        "from aizynthfinder.interfaces.aizynthcli import main; main()",
        "--smiles",
        str(smiles_file),
        "--config",
        str(config),
        "--output",
        str(output),
        "--checkpoint",
        str(checkpoint),
    ]


def summary_columns(stats: dict) -> dict[str, str]:
    """Map one AiZynthFinder statistics record onto table cells.

    Named columns cover the statistics the CLI always writes. Any other field,
    except the route trees and the target SMILES, is kept under its own column.
    """
    columns = {
        COLUMN_SOLVED: _solved(stats.get("is_solved")),
        COLUMN_SOLVED_ROUTES: _count(stats.get("number_of_solved_routes")),
        COLUMN_SCORE: _number(stats.get("top_score"), 3),
        COLUMN_STEPS: _count(stats.get("number_of_steps")),
        COLUMN_TIME: _number(stats.get("search_time"), 1),
        COLUMN_IN_STOCK: _listish(stats.get("precursors_in_stock")),
        COLUMN_NOT_IN_STOCK: _listish(stats.get("precursors_not_in_stock")),
        COLUMN_FIRST_SOLUTION_TIME: _number(stats.get("first_solution_time"), 1),
        COLUMN_FIRST_SOLUTION_ITERATION: _count(stats.get("first_solution_iteration")),
        COLUMN_NODES: _count(stats.get("number_of_nodes")),
        COLUMN_MAX_TRANSFORMS: _count(stats.get("max_transforms")),
        COLUMN_MAX_CHILDREN: _count(stats.get("max_children")),
        COLUMN_ROUTES: _count(stats.get("number_of_routes")),
        COLUMN_PRECURSORS: _count(stats.get("number_of_precursors")),
        COLUMN_PRECURSORS_IN_STOCK_N: _count(stats.get("number_of_precursors_in_stock")),
        COLUMN_AVAILABILITY: _format_value(stats.get("precursors_availability")),
        COLUMN_POLICIES: _format_value(stats.get("policy_used_counts")),
        COLUMN_STOCK: _format_value(stats.get("stock_info")),
        COLUMN_PROFILING: _format_value(stats.get("profiling")),
    }
    for key, value in stats.items():
        if key in _MAPPED_STATS or key in _SKIP_STATS:
            continue
        header = _extra_column_name(str(key))
        if header in columns:
            continue
        columns[header] = _format_value(value)
    return columns


def summaries_from_checkpoint(path: Path) -> dict[str, dict[str, str]]:
    """Parse the JSONL checkpoint. Incomplete trailing lines are skipped."""
    return _load_checkpoint(path)[0]


def routes_from_checkpoint(path: Path) -> dict[str, list[dict]]:
    """Compact routes from the same checkpoint, keyed by processed SMILES."""
    return _load_checkpoint(path)[1]


def summaries_from_output(path: Path) -> dict[str, dict[str, str]]:
    """Parse an ``aizynthcli`` JSON or JSON.GZ table when the checkpoint is empty."""
    return _load_output(path)[0]


def routes_from_output(path: Path) -> dict[str, list[dict]]:
    """Compact routes from an ``aizynthcli`` output table."""
    return _load_output(path)[1]


def routes_from_trees(trees: object, stock_info: object = None) -> list[dict]:
    """Turn AiZynthFinder route dicts into score, solved, steps, and a nested tree.

    Each route keeps every score and the route metadata. Each reaction keeps the
    template metadata, including the policy probability. *stock_info* maps a
    SMILES string to the stock names AiZynthFinder reported for it.
    """
    if not isinstance(trees, list):
        return []
    stocks = stock_info if isinstance(stock_info, dict) else {}
    routes: list[dict] = []
    for tree in trees:
        if not isinstance(tree, dict):
            continue
        smiles = str(tree.get("smiles") or "").strip()
        if not smiles:
            continue
        scores = tree.get("scores") if isinstance(tree.get("scores"), dict) else {}
        route = {
            "score": _route_score(scores),
            "solved": _route_is_solved(tree),
            "steps": _reaction_steps(tree),
            "tree": _compact_mol(tree, stocks),
        }
        plain_scores = _plain_dict(scores)
        if plain_scores:
            route["scores"] = plain_scores
        metadata = _route_metadata(tree)
        if metadata:
            route["metadata"] = metadata
        routes.append(route)
    return sort_routes(routes)


def sort_routes(routes: list[dict]) -> list[dict]:
    """Solved routes first, then higher score."""

    def _key(route: dict) -> tuple[int, float]:
        solved = 1 if route.get("solved") else 0
        try:
            score = float(route.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        return solved, score

    return sorted(routes, key=_key, reverse=True)


def route_tree(route: dict) -> dict | None:
    """Nested molecule tree for *route*, rebuilt from ``steps`` when needed."""
    tree = route.get("tree")
    if isinstance(tree, dict) and str(tree.get("smiles") or "").strip():
        return tree
    return tree_from_steps(list(route.get("steps") or []))


def tree_from_steps(steps: list[dict]) -> dict | None:
    """Rebuild a molecule tree from flat reaction steps. Each step is consumed once."""
    if not steps:
        return None
    unused = [dict(step) for step in steps if isinstance(step, dict)]
    if not unused:
        return None

    def pop_step(product: str) -> dict | None:
        for index, step in enumerate(unused):
            if str(step.get("product") or "").strip() == product:
                return unused.pop(index)
        return None

    def build(smiles: str, in_stock: bool) -> dict:
        step = pop_step(smiles)
        reactions: list[dict] = []
        if step is not None:
            reactants = []
            for item in step.get("reactants") or []:
                if not isinstance(item, dict):
                    continue
                reactants.append(
                    build(
                        str(item.get("smiles") or "").strip(),
                        bool(item.get("in_stock")),
                    )
                )
            reaction: dict = {"reactants": reactants}
            reaction_smiles = str(step.get("reaction") or "").strip()
            if reaction_smiles:
                reaction["smiles"] = reaction_smiles
            metadata = step.get("metadata")
            if isinstance(metadata, dict) and metadata:
                reaction["metadata"] = _plain_dict(metadata)
            reactions.append(reaction)
        return {"smiles": smiles, "in_stock": in_stock, "reactions": reactions}

    root_smiles = str(unused[0].get("product") or "").strip()
    if not root_smiles:
        return None
    return build(root_smiles, False)


def leaf_stock_counts(route: dict) -> tuple[int, int]:
    """Return ``(in_stock, total)`` for the leaves of *route*."""
    tree = route_tree(route)
    if tree is None:
        return 0, 0
    flags = _compact_leaves(tree)
    if not flags:
        return 0, 0
    return sum(1 for flag in flags if flag), len(flags)


def _load_checkpoint(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, list[dict]]]:
    summaries: dict[str, dict[str, str]] = {}
    routes: dict[str, list[dict]] = {}
    if not path.is_file():
        return summaries, routes
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return summaries, routes
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        smiles = str(row.get("processed_smiles") or "").strip()
        stats = row.get("results")
        if not smiles or not isinstance(stats, dict):
            continue
        summaries[smiles] = summary_columns(stats)
        parsed = routes_from_trees(stats.get("trees"), stock_info=stats.get("stock_info"))
        if parsed:
            routes[smiles] = parsed
    return summaries, routes


def _load_output(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, list[dict]]]:
    summaries: dict[str, dict[str, str]] = {}
    routes: dict[str, list[dict]] = {}
    if not path.is_file():
        return summaries, routes
    try:
        payload = json.loads(_read_maybe_gzip(path))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return summaries, routes
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return summaries, routes
    for row in data:
        if not isinstance(row, dict):
            continue
        smiles = str(row.get("target") or row.get("processed_smiles") or "").strip()
        if not smiles:
            continue
        summaries[smiles] = summary_columns(row)
        parsed = routes_from_trees(row.get("trees"), stock_info=row.get("stock_info"))
        if parsed:
            routes[smiles] = parsed
    return summaries, routes


def _compact_mol(node: dict, stocks: dict) -> dict:
    reactions: list[dict] = []
    for child in node.get("children") or []:
        if not isinstance(child, dict) or not _is_reaction_node(child):
            continue
        reactants = []
        for reactant in child.get("children") or []:
            if isinstance(reactant, dict):
                reactants.append(_compact_mol(reactant, stocks))
        reaction: dict = {"reactants": reactants}
        reaction_smiles = str(child.get("smiles") or "").strip()
        if reaction_smiles:
            reaction["smiles"] = reaction_smiles
        metadata = _plain_dict(child.get("metadata"))
        if metadata:
            reaction["metadata"] = metadata
        reactions.append(reaction)
    smiles = str(node.get("smiles") or "").strip()
    compact = {
        "smiles": smiles,
        "in_stock": bool(node.get("in_stock")),
        "reactions": reactions,
    }
    stock_names = _stock_names(smiles, stocks)
    if stock_names:
        compact["stock"] = stock_names
    return compact


def _compact_leaves(node: dict) -> list[bool]:
    reactions = [reaction for reaction in node.get("reactions") or [] if isinstance(reaction, dict)]
    if not reactions:
        return [bool(node.get("in_stock"))]
    flags: list[bool] = []
    for reaction in reactions:
        for reactant in reaction.get("reactants") or []:
            if isinstance(reactant, dict):
                flags.extend(_compact_leaves(reactant))
    return flags


def _reaction_steps(mol_node: dict) -> list[dict]:
    steps: list[dict] = []
    _collect_steps(mol_node, steps)
    return steps


def _collect_steps(mol_node: dict, steps: list[dict]) -> None:
    for child in mol_node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if not _is_reaction_node(child):
            _collect_steps(child, steps)
            continue
        reactants = []
        pending: list[dict] = []
        for reactant in child.get("children") or []:
            if not isinstance(reactant, dict):
                continue
            reactants.append(
                {
                    "smiles": str(reactant.get("smiles") or "").strip(),
                    "in_stock": bool(reactant.get("in_stock")),
                }
            )
            pending.append(reactant)
        step = {
            "product": str(mol_node.get("smiles") or "").strip(),
            "reaction": str(child.get("smiles") or "").strip(),
            "reactants": reactants,
        }
        metadata = _plain_dict(child.get("metadata"))
        if metadata:
            step["metadata"] = metadata
        steps.append(step)
        for reactant in pending:
            _collect_steps(reactant, steps)


def _is_reaction_node(node: dict) -> bool:
    return node.get("type") == "reaction" or bool(node.get("is_reaction"))


def _route_is_solved(mol_node: dict) -> bool:
    leaves: list[bool] = []

    def walk(node: dict) -> None:
        reactions = [
            child
            for child in node.get("children") or []
            if isinstance(child, dict) and _is_reaction_node(child)
        ]
        if not reactions:
            leaves.append(bool(node.get("in_stock")))
            return
        for reaction in reactions:
            for reactant in reaction.get("children") or []:
                if isinstance(reactant, dict):
                    walk(reactant)

    walk(mol_node)
    return bool(leaves) and all(leaves)


def _route_metadata(tree: dict) -> dict:
    merged: dict = {}
    for key in ("metadata", "route_metadata"):
        raw = tree.get(key)
        if isinstance(raw, dict):
            merged.update(_plain_dict(raw))
    return merged


def _stock_names(smiles: str, stocks: dict) -> list[str]:
    if not smiles or smiles not in stocks:
        return []
    raw = stocks.get(smiles)
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text or text.lower() == "not in stock":
        return []
    return [text]


def _plain_dict(value: object) -> dict:
    plain = _plain(value)
    return plain if isinstance(plain, dict) else {}


def _plain(value: object):
    """JSON-safe copy of an AiZynthFinder field."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _plain(item())
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _extra_column_name(key: str) -> str:
    words = key.replace("_", " ").strip()
    if not words:
        return "AiZynth"
    return f"AiZynth {words[:1].upper()}{words[1:]}"


def _format_value(value: object) -> str:
    """One table cell for a statistic that is not a dedicated column."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return _number(value, 4)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _format_value(item)
            if text:
                parts.append(f"{key}: {text}")
        return "; ".join(parts)
    if isinstance(value, (list, tuple)):
        return ", ".join(text for item in value if (text := _format_value(item)))
    return str(value).strip()


def _route_score(scores: dict) -> str:
    if not scores:
        return ""
    for key in ("state score", "State score"):
        if key in scores:
            return _number(scores[key], 3)
    return _number(next(iter(scores.values())), 3)


def probe_install(python_text: str = "", config_text: str = "") -> tuple[bool, str]:
    """Check paths, refuse remote configs, and import ``aizynthfinder`` in that interpreter."""
    problem = ready_message(python_text, config_text)
    if problem:
        return False, problem
    python = resolve_python(python_text)
    config = resolve_config(config_text)
    assert config is not None
    try:
        proc = subprocess.run(
            [python, "-c", _IMPORT_SNIPPET],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
            env=child_environment(Path(python)),
            cwd=str(config.parent),
            **_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not start {python}: {exc}"
    version = (proc.stdout or "").strip().splitlines()
    if proc.returncode == 0 and version:
        return True, f"OK: aizynthfinder {version[0]} ({config.name})"
    detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    tail = detail[-_TAIL_LIMIT:] if detail else f"exit code {proc.returncode}"
    return False, f"That Python could not import aizynthfinder.\n{tail}"


def run_search(
    *,
    python: str,
    config: Path,
    smiles: list[str],
    cancel: CancelFn | None = None,
    on_progress: ProgressFn | None = None,
) -> SearchResult:
    """Search *smiles* locally. Raises :class:`AizynthRunError` when nothing was saved."""
    targets = [item.strip() for item in smiles if item and item.strip()]
    if not targets:
        raise AizynthRunError("No SMILES to search.")
    problem = ready_message(python, str(config))
    if problem:
        raise AizynthRunError(problem)
    with tempfile.TemporaryDirectory(prefix="molmanager-aizynth-") as tmp:
        work = Path(tmp)
        smiles_file = work / "smiles.txt"
        smiles_file.write_text("\n".join(targets) + "\n", encoding="utf-8")
        output = work / "output.json.gz"
        checkpoint = work / "checkpoint.jsonl"
        command = aizynthcli_command(python, config, smiles_file, output, checkpoint)
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(config.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_environment(Path(python)),
                **_no_window_kwargs(),
            )
        except OSError as exc:
            raise AizynthRunError(f"Could not start {python}: {exc}") from exc
        tails = {"stdout": "", "stderr": ""}
        threads = [
            threading.Thread(target=_drain, args=(proc.stdout, tails, "stdout"), daemon=True),
            threading.Thread(target=_drain, args=(proc.stderr, tails, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()
        total = len(targets)
        cancelled = False
        try:
            while True:
                if cancel is not None and cancel():
                    cancelled = True
                    _kill_process(proc)
                    break
                if proc.poll() is not None:
                    break
                if on_progress is not None:
                    on_progress(_checkpoint_count(checkpoint), total)
                time.sleep(0.4)
        finally:
            if proc.poll() is None:
                _kill_process(proc)
            for thread in threads:
                thread.join(timeout=2)
        if on_progress is not None:
            on_progress(_checkpoint_count(checkpoint), total)
        summaries, routes = _load_checkpoint(checkpoint)
        if not summaries:
            summaries, routes = _load_output(output)
    if cancelled and not summaries:
        raise AizynthRunError("Cancelled.")
    if not summaries:
        raise AizynthRunError(_failure_text(proc.returncode, tails))
    warning = ""
    if not cancelled and proc.returncode not in (0, None):
        warning = _failure_text(proc.returncode, tails)
    return SearchResult(summaries, warning=warning, cancelled=cancelled, routes=routes)


def _conda_root(python: Path) -> Path | None:
    parent = python.parent
    if (parent / "conda-meta").is_dir():
        return parent
    if parent.name.lower() in {"bin", "scripts"} and (parent.parent / "conda-meta").is_dir():
        return parent.parent
    return None


def _no_window_kwargs() -> dict:
    if sys.platform.startswith("win") and _CREATE_NO_WINDOW:
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}


def _kill_process(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.SubprocessError:
        return


def _drain(pipe, tails: dict[str, str], key: str) -> None:
    if pipe is None:
        return
    kept: list[str] = []
    size = 0
    try:
        while True:
            line = pipe.readline()
            if not line:
                break
            kept.append(line)
            size += len(line)
            while size > _TAIL_LIMIT and kept:
                size -= len(kept.pop(0))
    except OSError:
        return
    tails[key] = "".join(kept)


def _checkpoint_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except (OSError, UnicodeError):
        return 0


def _read_maybe_gzip(path: Path) -> str:
    if path.name.endswith(".gz"):
        import gzip

        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return handle.read()
    return path.read_text(encoding="utf-8")


def _failure_text(returncode: int | None, tails: dict[str, str]) -> str:
    detail = (tails.get("stderr") or tails.get("stdout") or "").strip()
    if detail:
        return detail[-_TAIL_LIMIT:]
    code = "unknown" if returncode is None else str(returncode)
    return f"AiZynthFinder stopped without a route summary (exit code {code})."


def _solved(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "yes", "1"}:
            return "yes"
        if low in {"false", "no", "0"}:
            return "no"
        return value.strip()
    return "yes" if value else "no"


def _count(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return str(int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value).strip()


def _number(value: object, digits: int) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.{digits}f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value).strip()


def _listish(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()
