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

"""MDL RXN / RDF reaction files → table rows (reaction SMARTS + example structures)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

from .molecule_conversion import looks_like_mol_block, mol_to_canonical_smiles

logger = logging.getLogger(__name__)

RXN_SMARTS_HEADER = "Reaction SMARTS"
# Text drawn above and below a sketcher arrow. Not part of the reaction SMARTS.
RXN_ANNOTATION_HEADER = "Reaction Annotation"
RXN_REACTANTS_HEADER = "Reactants"
RXN_PRODUCTS_HEADER = "Products"
RXN_NAME_HEADER = "Reaction Name"
RXN_TABLE_HEADERS: tuple[str, ...] = (
    RXN_SMARTS_HEADER,
    RXN_REACTANTS_HEADER,
    RXN_PRODUCTS_HEADER,
    RXN_NAME_HEADER,
)
RXN_FILE_SUFFIXES = frozenset({".rxn", ".rdf"})

_REACTION_SMARTS_HEADER_ALIASES = frozenset(
    {
        "reaction smarts",
        "rxn smarts",
        "smirks",
        "reaction smiles",
    }
)


@dataclass(frozen=True)
class RxnRecord:
    """One parsed MDL reaction for table ingest."""

    smarts: str
    reactants: str
    products: str
    name: str
    mol: Chem.Mol | None


def is_rxn_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in RXN_FILE_SUFFIXES


def is_reaction_smarts_header(name: str) -> bool:
    n = (name or "").strip().lower()
    return n in _REACTION_SMARTS_HEADER_ALIASES


def looks_like_reaction_smarts(text: str) -> bool:
    """True when cell text looks like reaction SMARTS / SMIRKS (``>>`` or agent ``>``)."""
    t = (text or "").strip()
    if not t or looks_like_mol_block(t):
        return False
    return ">>" in t or t.count(">") >= 2


def parse_reaction_smarts(text: str):
    """Parse reaction SMARTS into an RDKit reaction, or ``None`` if invalid."""
    t = (text or "").strip()
    if not looks_like_reaction_smarts(t):
        return None
    try:
        rxn = AllChem.ReactionFromSmarts(t)
    except Exception:
        return None
    if rxn is None:
        return None
    try:
        n_r = int(rxn.GetNumReactantTemplates())
        n_p = int(rxn.GetNumProductTemplates())
    except Exception:
        return None
    if n_r < 1 and n_p < 1:
        return None
    return rxn


def split_rxn_blocks(text: str) -> list[str]:
    """Split RXN or RDF text into ``$RXN`` blocks (one reaction each)."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if "$RXN" not in raw:
        stripped = raw.strip()
        return [stripped] if stripped else []
    blocks: list[str] = []
    for part in raw.split("$RXN")[1:]:
        block = "$RXN" + part
        if block.strip():
            blocks.append(block)
    return blocks


def _rxn_title(block: str) -> str:
    lines = (block or "").splitlines()
    if not lines:
        return ""
    start = 1 if lines[0].lstrip().startswith("$RXN") else 0
    if start >= len(lines):
        return ""
    name = lines[start].strip()
    if not name or name.startswith("$"):
        return ""
    return name[:120]


def _component_smiles(mols) -> str:
    parts: list[str] = []
    for mol in mols or []:
        if mol is None:
            continue
        try:
            smi = mol_to_canonical_smiles(mol)
        except Exception:
            smi = ""
        if smi:
            parts.append(smi)
    return ".".join(parts)


def _depict_mol(rxn) -> Chem.Mol | None:
    for getter in (rxn.GetProducts, rxn.GetReactants):
        for mol in getter() or []:
            if mol is None:
                continue
            try:
                if int(mol.GetNumAtoms()) < 1:
                    continue
                return Chem.Mol(mol)
            except Exception:
                continue
    return None


def record_from_reaction(
    rxn,
    *,
    name: str = "",
) -> RxnRecord | None:
    """Convert an RDKit reaction into a table record, or ``None`` if unusable."""
    if rxn is None:
        return None
    try:
        AllChem.SanitizeRxn(rxn)
    except Exception:
        logger.debug("SanitizeRxn skipped", exc_info=True)
    try:
        smarts = (AllChem.ReactionToSmarts(rxn) or "").strip()
    except Exception:
        smarts = ""
    reactants = _component_smiles(rxn.GetReactants())
    products = _component_smiles(rxn.GetProducts())
    if not smarts and not reactants and not products:
        return None
    mol = _depict_mol(rxn)
    if mol is not None:
        if smarts:
            mol.SetProp(RXN_SMARTS_HEADER, smarts)
        if reactants:
            mol.SetProp(RXN_REACTANTS_HEADER, reactants)
        if products:
            mol.SetProp(RXN_PRODUCTS_HEADER, products)
        title = (name or "").strip()
        if title:
            mol.SetProp(RXN_NAME_HEADER, title)
        if products:
            mol.SetProp("SMILES", products.split(".", 1)[0])
        elif reactants:
            mol.SetProp("SMILES", reactants.split(".", 1)[0])
    return RxnRecord(
        smarts=smarts,
        reactants=reactants,
        products=products,
        name=(name or "").strip(),
        mol=mol,
    )


def parse_rxn_block(block: str) -> RxnRecord | None:
    text = (block or "").strip()
    if not text:
        return None
    if not text.lstrip().startswith("$RXN"):
        text = "$RXN\n" + text
    name = _rxn_title(text)
    try:
        rxn = AllChem.ReactionFromRxnBlock(text)
    except Exception:
        logger.debug("ReactionFromRxnBlock failed", exc_info=True)
        return None
    return record_from_reaction(rxn, name=name)


def load_rxn_file(path: str | Path) -> list[RxnRecord]:
    """Parse an MDL ``.rxn`` or ``.rdf`` file into table records."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.exception("Could not read reaction file %s", file_path)
        return []
    records: list[RxnRecord] = []
    for block in split_rxn_blocks(text):
        rec = parse_rxn_block(block)
        if rec is not None:
            records.append(rec)
    if records:
        return records
    try:
        rxn = AllChem.ReactionFromRxnFile(str(file_path))
    except Exception:
        logger.debug("ReactionFromRxnFile failed for %s", file_path, exc_info=True)
        return []
    rec = record_from_reaction(rxn, name=file_path.stem)
    return [rec] if rec is not None else []


def load_reaction_smarts_from_rxn_path(path: str | Path) -> tuple[str, int]:
    """Return ``(first_reaction_smarts, n_reactions)`` from an RXN/RDF file."""
    records = load_rxn_file(path)
    if not records:
        raise ValueError("No reactions found in that RXN file.")
    smarts = (records[0].smarts or "").strip()
    if not smarts:
        raise ValueError("The RXN file did not contain reaction SMARTS.")
    return smarts, len(records)


def reaction_smarts_from_app_selection(app) -> str:
    """Reaction SMARTS from the first selected table row, if that column exists."""
    headers = list(getattr(app, "headers", None) or [])
    col = next((h for h in headers if is_reaction_smarts_header(h)), None)
    if col is None:
        return ""
    model = getattr(app, "_table_model", None)
    getter = getattr(app, "_selected_logical_rows", None)
    if model is None or not callable(getter):
        return ""
    rows = list(getter())
    if not rows:
        return ""
    value_fn = getattr(model, "value_for_header", None)
    if not callable(value_fn):
        return ""
    return str(value_fn(int(rows[0]), col) or "").strip()
