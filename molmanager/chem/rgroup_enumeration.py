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

"""Enumerate products by attaching building-block lists to a numbered core.

The core carries one dummy atom per attachment point, numbered ``[*:1]``,
``[*:2]``, and so on (an isotope label such as ``[1*]`` is accepted too).
Each building block carries one ``*`` on the atom that should bond to the
core, for example ``CCN*``. A block that is only ``*`` or hydrogen caps that
point and leaves the implicit hydrogen on the scaffold.
"""

from __future__ import annotations

import csv
import itertools
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem

from .fragment_recomposition_filters import (
    compile_recomposition_filters,
    parse_recomposition_filter_text,
    product_passes_compiled,
)

MAX_ATTACHMENT_POINTS = 8
CORE_ID_HEADER = "Core_ID"

_STRUCTURE_FILE_SUFFIXES = {".sdf", ".sd", ".smi", ".smiles", ".txt", ".csv"}
_HEADER_WORDS = frozenset({"smiles", "smi", "id", "name", "reagent", "reagent_id", "title"})
_SDF_ID_PROPS = ("reagent_id", "ID", "Id", "Name", "_Name", "TITLE")


def reagent_header(label: int) -> str:
    """Table column for the reagent used at one attachment point."""
    return f"R{int(label)}"


@dataclass(frozen=True)
class BuildingBlock:
    """One reagent, already checked for a single attachment dummy or a hydrogen cap."""

    reagent_id: str
    mol: Chem.Mol


@dataclass(frozen=True)
class RGroupPool:
    """Building blocks for one numbered attachment point."""

    label: int
    blocks: tuple[BuildingBlock, ...]


@dataclass(frozen=True)
class RGroupPoolInput:
    """Dialog description of one building-block list (file path or pasted text)."""

    label: int
    mode: str
    file_path: str
    smiles_text: str


@dataclass(frozen=True)
class RGroupEnumerationRequest:
    """Inputs for one R-group enumeration job (dialog → worker)."""

    core_smiles: str
    core_id: str
    pools: tuple[RGroupPoolInput, ...]
    max_products: int
    output_filters: str
    add_to_table: bool
    save_to_file: bool
    save_path: str | None


@dataclass(frozen=True)
class RGroupProduct:
    """One accepted product and the reagents that made it."""

    smiles: str
    core_id: str
    reagent_ids: tuple[tuple[int, str], ...]

    def field_map(self) -> dict[str, str]:
        fields = {CORE_ID_HEADER: self.core_id}
        for label, reagent_id in self.reagent_ids:
            fields[reagent_header(label)] = reagent_id
        return fields


@dataclass(frozen=True)
class RGroupEnumerationJobResult:
    """Worker output consumed by the main window."""

    products: tuple[RGroupProduct, ...]
    skipped: int
    add_to_table: bool
    save_to_file: bool
    save_path: str | None
    written_count: int


def prepare_core(smiles: str) -> tuple[Chem.Mol, tuple[int, ...]]:
    """Parse a core and number every dummy atom.

    Unnumbered ``*`` atoms receive the next free label in atom order. Returns
    the core mol and the attachment labels sorted ascending.
    """
    text = (smiles or "").strip()
    if not text:
        raise ValueError(
            "Enter a core SMILES with numbered attachment points, for example [*:1]c1ccccc1."
        )
    mol = Chem.MolFromSmiles(text) or Chem.MolFromSmiles(text, sanitize=False)
    if mol is None:
        raise ValueError("Could not parse the core SMILES.")
    rw = Chem.RWMol(mol)
    dummies = [atom for atom in rw.GetAtoms() if atom.GetAtomicNum() == 0]
    if not dummies:
        raise ValueError(
            "The core needs at least one attachment point. Number them as [*:1], [*:2], and so on."
        )
    if len(dummies) > MAX_ATTACHMENT_POINTS:
        raise ValueError(
            f"This core has {len(dummies)} attachment points. "
            f"R-group enumeration supports up to {MAX_ATTACHMENT_POINTS}."
        )
    if not any(atom.GetAtomicNum() > 1 for atom in rw.GetAtoms()):
        raise ValueError("The core needs a scaffold bonded to each attachment point.")
    labels_by_idx = _assign_core_labels(dummies)
    for idx, label in labels_by_idx.items():
        atom = rw.GetAtomWithIdx(idx)
        atom.SetAtomMapNum(int(label))
        atom.SetIsotope(0)
        _require_single_scaffold_bond(atom, label)
    prepared = rw.GetMol()
    return prepared, tuple(sorted(labels_by_idx.values()))


def building_blocks_from_text(label: int, text: str) -> tuple[BuildingBlock, ...]:
    """Parse pasted lines into building blocks for attachment point *label*."""
    blocks: list[BuildingBlock] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or _is_header_line(stripped):
            continue
        try:
            mol, ident = _parse_structure_line(stripped)
        except ValueError as exc:
            raise ValueError(f"R{label}: {exc}") from exc
        blocks.append(_block_from_mol(label, mol, ident, len(blocks) + 1))
    if not blocks:
        raise ValueError(f"R{label} has no building blocks.")
    return tuple(blocks)


def building_blocks_from_file(label: int, path: str | Path) -> tuple[BuildingBlock, ...]:
    """Load one building-block list from SDF, SMILES, or CSV."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise ValueError(f"R{label} file not found: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix not in _STRUCTURE_FILE_SUFFIXES:
        raise ValueError(
            f"R{label}: unsupported file type {suffix!r}. Use .sdf, .smi, .txt, or .csv."
        )
    if suffix in {".sdf", ".sd"}:
        blocks = _blocks_from_sdf(label, file_path)
    elif suffix == ".csv":
        blocks = _blocks_from_csv(label, file_path)
    else:
        blocks = building_blocks_from_text(
            label, file_path.read_text(encoding="utf-8", errors="replace")
        )
    if not blocks:
        raise ValueError(f"R{label}: no valid building blocks in {file_path.name}.")
    return blocks


def load_rgroup_pools(request: RGroupEnumerationRequest) -> tuple[RGroupPool, ...]:
    """Load every building-block list and check it against the core."""
    _core, labels = prepare_core(request.core_smiles)
    declared = tuple(sorted(int(pool.label) for pool in request.pools))
    if declared != labels:
        names = ", ".join(f"R{label}" for label in labels)
        raise ValueError(f"Building-block lists must match the core attachment points ({names}).")
    by_label = {int(pool.label): pool for pool in request.pools}
    loaded: list[RGroupPool] = []
    for label in labels:
        source = by_label[label]
        mode = (source.mode or "smiles").strip().lower()
        if mode == "smiles":
            blocks = building_blocks_from_text(label, source.smiles_text)
        elif mode == "file":
            blocks = building_blocks_from_file(label, source.file_path)
        else:
            raise ValueError(f"R{label}: unsupported input mode {source.mode!r}.")
        loaded.append(RGroupPool(label, blocks))
    return tuple(loaded)


def enumerate_rgroups(
    core_smiles: str,
    pools: Sequence[RGroupPool],
    *,
    core_id: str = "",
    max_products: int = 2000,
    output_filters: str = "",
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> tuple[list[RGroupProduct], int, bool]:
    """Attach every combination of building blocks.

    Returns ``(products, n_skipped, cancelled)``. Property limits use the same
    rules as fragment recomposition. Duplicate canonical SMILES are skipped.
    """
    if cancel_event is not None and cancel_event.is_set():
        return [], 0, True
    core, labels = prepare_core(core_smiles)
    ordered = tuple(sorted(pools, key=lambda pool: pool.label))
    if tuple(pool.label for pool in ordered) != labels:
        names = ", ".join(f"R{label}" for label in labels)
        raise ValueError(f"Building-block lists must match the core attachment points ({names}).")
    if any(not pool.blocks for pool in ordered):
        raise ValueError("Each attachment point needs at least one building block.")
    rules = parse_recomposition_filter_text(output_filters)
    compiled = compile_recomposition_filters(rules)
    cap = max(1, int(max_products))
    max_pairs = _candidate_cap(cap, bool(compiled))
    resolved_core_id = (core_id or "").strip() or (core_smiles or "").strip()
    seen: set[str] = set()
    products: list[RGroupProduct] = []
    skipped = 0
    examined = 0
    last_progress = -1

    def _report() -> None:
        nonlocal last_progress
        if progress_callback is None:
            return
        accepted = len(products)
        if accepted == last_progress and examined % 32 != 0:
            return
        last_progress = accepted
        progress_callback(accepted, cap, examined)

    _report()
    block_lists = [pool.blocks for pool in ordered]
    for combo in itertools.product(*block_lists):
        examined += 1
        if cancel_event is not None and cancel_event.is_set():
            return products, skipped, True
        if max_pairs is not None and examined > max_pairs:
            return products, skipped, False
        reagent_ids = tuple((pool.label, block.reagent_id) for pool, block in zip(ordered, combo))
        smiles = _product_smiles(core, ordered, combo, compiled)
        if smiles is None or smiles in seen:
            skipped += 1
            continue
        seen.add(smiles)
        products.append(RGroupProduct(smiles, resolved_core_id, reagent_ids))
        _report()
        if len(products) >= cap:
            return products, skipped, False
    return products, skipped, False


def write_rgroup_products_to_sdf(path: str | Path, products: Sequence[RGroupProduct]) -> int:
    """Write products to SDF, including the core id and reagent id of each point."""
    out_path = Path(path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(out_path))
    written = 0
    try:
        for index, product in enumerate(products):
            text = (product.smiles or "").strip()
            if not text:
                continue
            mol = Chem.MolFromSmiles(text)
            if mol is None:
                continue
            mol.SetProp("_Name", f"product_{index + 1}")
            mol.SetProp("SMILES", text)
            mol.SetProp(CORE_ID_HEADER, product.core_id)
            for label, reagent_id in product.reagent_ids:
                mol.SetProp(reagent_header(label), reagent_id)
            writer.write(mol)
            written += 1
    finally:
        writer.close()
    return written


def _assign_core_labels(dummies: list[Chem.Atom]) -> dict[int, int]:
    assigned: dict[int, int] = {}
    used: set[int] = set()
    for atom in dummies:
        label = int(atom.GetAtomMapNum() or 0) or int(atom.GetIsotope() or 0)
        if label <= 0:
            continue
        if label in used:
            raise ValueError(f"Attachment point {label} is used more than once.")
        assigned[atom.GetIdx()] = label
        used.add(label)
    next_label = 1
    for atom in sorted(dummies, key=lambda item: item.GetIdx()):
        if atom.GetIdx() in assigned:
            continue
        while next_label in used:
            next_label += 1
        assigned[atom.GetIdx()] = next_label
        used.add(next_label)
        next_label += 1
    return assigned


def _require_single_scaffold_bond(atom: Chem.Atom, label: int) -> None:
    if atom.GetDegree() != 1:
        raise ValueError(f"Attachment point R{label} must be bonded to exactly one core atom.")
    neighbor = atom.GetNeighbors()[0]
    if neighbor.GetAtomicNum() == 0:
        raise ValueError(
            f"Attachment point R{label} must be bonded to the scaffold, not another *."
        )


def _is_header_line(text: str) -> bool:
    tokens = [tok.strip().lower() for tok in text.replace(",", " ").split() if tok.strip()]
    return bool(tokens) and all(tok in _HEADER_WORDS for tok in tokens)


def _candidate_mol(token: str) -> Chem.Mol | None:
    text = (token or "").strip()
    if not text or text.lower() in _HEADER_WORDS:
        return None
    return Chem.MolFromSmiles(text) or Chem.MolFromSmiles(text, sanitize=False)


def _chars_outside_brackets(text: str) -> str:
    """Characters that are not inside ``[]``, so a name separator is not part of an atom."""
    depth = 0
    outside: list[str] = []
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif depth == 0:
            outside.append(char)
    return "".join(outside)


def _parse_structure_line(text: str) -> tuple[Chem.Mol, str]:
    """Return ``(mol, reagent id)``. The id is empty when the line is SMILES only.

    RDKit accepts ``CCN* ethylamine`` and discards the name, so a separator
    outside atom brackets is split off before the SMILES parse.
    """
    outside = _chars_outside_brackets(text)
    if "," in outside:
        return _parse_separated_fields([part.strip() for part in text.split(",")], text)
    if any(char.isspace() for char in outside):
        return _parse_separated_fields(text.split(), text)
    mol = _candidate_mol(text)
    if mol is None:
        raise ValueError(
            f"Could not read {text!r} as a building block. Put * on the atom that should attach."
        )
    return mol, ""


def _parse_separated_fields(fields: list[str], original: str) -> tuple[Chem.Mol, str]:
    parsed_fields = [(idx, _candidate_mol(part)) for idx, part in enumerate(fields)]
    hits = [(idx, parsed) for idx, parsed in parsed_fields if parsed is not None]
    if not hits:
        raise ValueError(
            f"Could not read {original!r} as a building block. Put * on the atom that should attach."
        )
    starred = [pair for pair in hits if "*" in fields[pair[0]]]
    idx, chosen = (starred or hits)[0]
    ident = " ".join(part for field_idx, part in enumerate(fields) if field_idx != idx and part)
    return chosen, ident


def _block_from_mol(label: int, mol: Chem.Mol, ident: str, index: int) -> BuildingBlock:
    reagent_id = (ident or "").strip() or f"R{label}-{index}"
    try:
        prepared = _prepare_building_block(mol)
    except ValueError as exc:
        raise ValueError(f"R{label}: {reagent_id} {exc}") from exc
    return BuildingBlock(reagent_id, prepared)


def _prepare_building_block(mol: Chem.Mol) -> Chem.Mol:
    if _is_hydrogen_cap(mol):
        return Chem.Mol(mol)
    dummies = [atom for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
    if len(dummies) != 1:
        raise ValueError("needs one * at the atom that should bond to the core.")
    dummy = dummies[0]
    if dummy.GetDegree() != 1:
        raise ValueError("has a * that is not bonded to exactly one atom.")
    if dummy.GetNeighbors()[0].GetAtomicNum() == 0:
        raise ValueError("has a * bonded to another *, not to an atom.")
    return Chem.Mol(mol)


def _is_hydrogen_cap(mol: Chem.Mol) -> bool:
    atoms = list(mol.GetAtoms())
    if not atoms or any(atom.GetAtomicNum() not in (0, 1) for atom in atoms):
        return False
    return sum(atom.GetAtomicNum() == 0 for atom in atoms) <= 1


def _blocks_from_sdf(label: int, path: Path) -> tuple[BuildingBlock, ...]:
    blocks: list[BuildingBlock] = []
    supplier = Chem.SDMolSupplier(str(path), removeHs=False)
    for mol in supplier:
        if mol is None:
            continue
        ident = _sdf_ident(mol)
        blocks.append(_block_from_mol(label, mol, ident, len(blocks) + 1))
    return tuple(blocks)


def _sdf_ident(mol: Chem.Mol) -> str:
    for key in _SDF_ID_PROPS:
        if not mol.HasProp(key):
            continue
        value = str(mol.GetProp(key) or "").strip()
        if value:
            return value
    return ""


def _blocks_from_csv(label: int, path: Path) -> tuple[BuildingBlock, ...]:
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return ()
    header = [str(cell or "").strip().lower() for cell in rows[0]]
    smiles_col = next((idx for idx, name in enumerate(header) if "smiles" in name), None)
    if smiles_col is None:
        blocks: list[BuildingBlock] = []
        for row in rows:
            line = ",".join(row).strip()
            if not line or line.startswith("#") or _is_header_line(line):
                continue
            try:
                mol, ident = _parse_structure_line(line)
            except ValueError as exc:
                raise ValueError(f"R{label}: {exc}") from exc
            blocks.append(_block_from_mol(label, mol, ident, len(blocks) + 1))
        return tuple(blocks)
    id_col = next(
        (
            idx
            for idx, name in enumerate(header)
            if name in {"id", "name", "reagent", "reagent_id", "title"}
        ),
        None,
    )
    blocks = []
    for row in rows[1:]:
        if smiles_col >= len(row) or not str(row[smiles_col] or "").strip():
            continue
        mol = _candidate_mol(str(row[smiles_col]))
        if mol is None:
            raise ValueError(
                f"R{label}: could not read {row[smiles_col]!r} as a building block. "
                "Put * on the atom that should attach."
            )
        ident = ""
        if id_col is not None and id_col < len(row):
            ident = str(row[id_col] or "").strip()
        blocks.append(_block_from_mol(label, mol, ident, len(blocks) + 1))
    return tuple(blocks)


def _candidate_cap(cap: int, has_filters: bool) -> int | None:
    if not has_filters:
        return None
    from ..platform_support.config import load_config

    cfg = load_config()
    return max(
        int(cfg.recomp_constraint_min_candidates),
        cap * int(cfg.recomp_constraint_candidate_multiplier),
    )


def _product_smiles(core, pools, combo, compiled) -> str | None:
    product = Chem.Mol(core)
    try:
        for pool, block in zip(pools, combo):
            product = _attach(product, block.mol, pool.label)
        Chem.SanitizeMol(product)
    except (ValueError, RuntimeError):
        return None
    if compiled and not product_passes_compiled(product, compiled):
        return None
    try:
        return Chem.MolToSmiles(product) or None
    except (ValueError, RuntimeError):
        return None


def _attach(core: Chem.Mol, block: Chem.Mol, label: int) -> Chem.Mol:
    dummy_idx = _dummy_index(core, label)
    if _is_hydrogen_cap(block):
        edited = Chem.RWMol(core)
        edited.RemoveAtom(dummy_idx)
        return edited.GetMol()
    core_anchor = core.GetAtomWithIdx(dummy_idx).GetNeighbors()[0].GetIdx()
    block_dummy = next(atom.GetIdx() for atom in block.GetAtoms() if atom.GetAtomicNum() == 0)
    block_anchor = block.GetAtomWithIdx(block_dummy).GetNeighbors()[0].GetIdx()
    order = block.GetBondBetweenAtoms(block_dummy, block_anchor).GetBondType()
    combined = Chem.CombineMols(core, block)
    edited = Chem.RWMol(combined)
    offset = core.GetNumAtoms()
    edited.AddBond(core_anchor, block_anchor + offset, order)
    for idx in sorted((dummy_idx, block_dummy + offset), reverse=True):
        edited.RemoveAtom(idx)
    return edited.GetMol()


def _dummy_index(mol: Chem.Mol, label: int) -> int:
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() == 0 and int(atom.GetAtomMapNum()) == int(label):
            return int(atom.GetIdx())
    raise ValueError(f"Attachment point R{label} was not found on the core.")
