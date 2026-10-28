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

import re

# Upper bound for attempting RDKit parses from a single table cell (mol blocks, etc.).
_CELL_TEXT_MAX_PARSE_CHARS = 2_000_000
_NON_STRUCTURE_PREFIXES = ("http://", "https://", "ftp://", "file://", "www.")


def looks_like_mol_block(text: str) -> bool:
    """Heuristic: cell text resembles an MDL mol block."""
    t = text or ""
    return "V2000" in t or "V3000" in t or ("M  END" in t and "\n" in t)


def looks_like_structure_cell_text(raw: str) -> bool:
    """False for URLs, JSON, and HTML that should not be fed to RDKit."""
    t = (raw or "").strip()
    if not t:
        return False
    if t.startswith(("{", "<")):
        return False
    lo = t.lower()
    if lo.startswith(_NON_STRUCTURE_PREFIXES) or "://" in t:
        return False
    return True


def _rdkit_log_blocker():
    """Silence RDKit C++ logs for speculative parses (destructor restores)."""
    try:
        from rdkit.rdBase import BlockLogs

        return BlockLogs()
    except Exception:
        return None


def parse_molecule_from_cell_text(raw: str):
    """
    Best-effort RDKit molecule from arbitrary table cell text: SMILES, InChI, MolBlock, simple PDB.

    Returns ``None`` when nothing parses. Import RDKit lazily so non-chemistry code paths stay light.
    """
    from rdkit import Chem

    raw = (raw or "").strip()
    if not raw:
        return None
    if len(raw) > _CELL_TEXT_MAX_PARSE_CHARS:
        return None
    if not looks_like_structure_cell_text(raw):
        return None
    blocker = _rdkit_log_blocker()
    try:
        try:
            m = Chem.MolFromSmiles(raw)
            if m is not None:
                return m
        except Exception:
            pass
        try:
            m = Chem.MolFromInchi(raw)
            if m is not None:
                return m
        except Exception:
            pass
        if looks_like_mol_block(raw):
            # ``strip()`` drops the blank title line that ``MolToMolBlock`` writes, which
            # shifts the counts line and makes an otherwise valid mol block fail to parse.
            for candidate in (raw, "\n" + raw):
                try:
                    m = Chem.MolFromMolBlock(candidate)
                except Exception:
                    m = None
                if m is not None:
                    return m
        head = raw[:200]
        if "ATOM  " in head or raw.startswith("COMPND") or raw.startswith("HEADER"):
            try:
                m = Chem.MolFromPDBBlock(raw)
                if m is not None:
                    return m
            except Exception:
                pass
        # SMARTS / reaction SMARTS (SMILES already attempted; skip huge mol blocks that contain '[').
        if (
            len(raw) < 600
            and not looks_like_mol_block(raw)
            and ("[" in raw or ">>" in raw or raw.startswith("^"))
        ):
            try:
                from .smarts_macropatterns import mol_from_smarts

                m = mol_from_smarts(raw)
                if m is not None:
                    return m
            except Exception:
                pass
        return None
    finally:
        del blocker


def redact_sqlalchemy_url(url: str) -> str:
    """Mask ``user:password`` in a SQLAlchemy URL, including one embedded in an error."""
    if not url or "@" not in url:
        return url
    # scheme://user:pass@host -> scheme://user:***@host
    return re.sub(r"(://[^/?#:@\s]+):([^@/?#\s]+)@", r"\1:***@", url)


def safe_float(value):
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def mol_to_canonical_smiles(mol, *, isomeric: bool = True) -> str:
    """Canonical SMILES for ``mol`` (explicit ``canonical=True`` for all app-generated SMILES)."""
    if mol is None:
        return ""
    from rdkit import Chem

    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=isomeric)


def mol_to_inchi(mol) -> str:
    """Standard InChI, or empty string if RDKit cannot generate one."""
    if mol is None:
        return ""
    from rdkit import Chem

    blocker = _rdkit_log_blocker()
    try:
        return (Chem.MolToInchi(mol) or "").strip()
    except Exception:
        return ""
    finally:
        del blocker


def mol_to_inchi_key(mol) -> str:
    """Standard InChIKey, or empty string if RDKit cannot generate one."""
    if mol is None:
        return ""
    from rdkit import Chem

    blocker = _rdkit_log_blocker()
    try:
        return (Chem.MolToInchiKey(mol) or "").strip()
    except Exception:
        return ""
    finally:
        del blocker


def mol_to_molblock(mol) -> str:
    """MDL molfile (V2000). Adds 2D coords when the molecule has no conformer."""
    if mol is None:
        return ""
    from rdkit import Chem

    blocker = _rdkit_log_blocker()
    try:
        copy = Chem.Mol(mol)
        if copy.GetNumConformers() == 0:
            try:
                from rdkit.Chem import rdDepictor

                rdDepictor.Compute2DCoords(copy)
            except Exception:
                pass
        block = Chem.MolToMolBlock(copy) or ""
        return block if block.strip() else ""
    except Exception:
        return ""
    finally:
        del blocker


def mol_to_smarts(mol) -> str:
    """SMARTS for ``mol``, or empty string if RDKit cannot generate one."""
    if mol is None:
        return ""
    from rdkit import Chem

    blocker = _rdkit_log_blocker()
    try:
        return (Chem.MolToSmarts(mol) or "").strip()
    except Exception:
        return ""
    finally:
        del blocker


def mol_structure_copy_texts(mol) -> dict[str, str]:
    """Clipboard strings for the structure Copy submenu, keyed by format id."""
    smiles = ""
    if mol is not None:
        try:
            smiles = mol_to_canonical_smiles(mol).strip()
        except Exception:
            smiles = ""
    return {
        "smiles": smiles,
        "inchi": mol_to_inchi(mol),
        "inchikey": mol_to_inchi_key(mol),
        "molfile": mol_to_molblock(mol),
        "smarts": mol_to_smarts(mol),
    }


def mol_graph_binary(mol) -> bytes | None:
    """RDKit binary for the connection table only (no conformers).

    Used in ``.cms`` sessions so Open can skip ``MolFromSmiles``. Conformers stay in
    ``confs_sidecar``; dropping them keeps the structure blob small.
    """
    if mol is None:
        return None
    from rdkit import Chem

    try:
        copy = Chem.Mol(mol)
        copy.RemoveAllConformers()
        blob = copy.ToBinary()
    except Exception:
        return None
    return blob or None


def morgan_tanimoto_to_query(
    query_smiles: str,
    hit_smiles: str,
    *,
    radius: int = 2,
    n_bits: int = 2048,
) -> float | None:
    """
    Tanimoto similarity between two SMILES strings using RDKit Morgan bit vectors.

    Used when an external service (e.g. PubChem 2D similarity) does not return a
    per-hit coefficient in the client library; values are comparable for ranking
    but may not match the remote fingerprint definition exactly.
    """
    from rdkit import Chem, DataStructs
    from rdkit.Chem import AllChem

    q = (query_smiles or "").strip()
    h = (hit_smiles or "").strip()
    if not q or not h:
        return None
    mq = Chem.MolFromSmiles(q)
    mh = Chem.MolFromSmiles(h)
    if mq is None or mh is None:
        return None
    try:
        fp1 = AllChem.GetMorganFingerprintAsBitVect(mq, radius, nBits=n_bits)
        fp2 = AllChem.GetMorganFingerprintAsBitVect(mh, radius, nBits=n_bits)
        return float(DataStructs.TanimotoSimilarity(fp1, fp2))
    except Exception:
        return None


def safe_mol_prop_string(mol, name: str) -> str:
    """Read an RDKit string property without crashing on non-UTF-8 SD field data."""
    if mol is None or not mol.HasProp(name):
        return ""
    try:
        v = mol.GetProp(name)
        return "" if v is None else str(v)
    except UnicodeDecodeError:
        # RDKit's Python binding decodes SD tags as UTF-8; some files use Latin-1 or raw bytes.
        return ""
    except Exception:
        return ""


def row_cells_from_mol(mol, data_headers: list[str]) -> dict[str, str]:
    """Build table cell values for ``data_headers`` from one molecule.

    Shared by the GUI ingest path and the load worker (which pre-builds cells off the GUI
    thread). ``data_headers`` are the header names from column 2 onward (excludes id/Structure).
    """
    values: dict[str, str] = {}
    for name in data_headers:
        if mol is None:
            txt = ""
        elif name == "SMILES":
            if mol.HasProp("SMILES"):
                txt = (safe_mol_prop_string(mol, "SMILES") or "").strip()
            else:
                try:
                    txt = mol_to_canonical_smiles(mol)
                except Exception:
                    txt = ""
        else:
            txt = safe_mol_prop_string(mol, name)
        values[name] = txt
    return values


def canonical_structure_key_from_smiles(smiles: str) -> str | None:
    """Canonical isomeric SMILES key for duplicate detection; ``None`` if not parseable."""
    smiles = (smiles or "").strip()
    if not smiles:
        return None
    mol = parse_molecule_from_cell_text(smiles)
    if mol is None:
        return None
    try:
        key = mol_to_canonical_smiles(mol).strip()
    except Exception:
        return None
    return key or None


def mol_from_binary_blob(blob) -> object | None:
    """Rebuild an RDKit molecule from a worker binary payload (``Mol.ToBinary()``)."""
    if not blob:
        return None
    from rdkit import Chem

    try:
        return Chem.Mol(bytes(blob))
    except Exception:
        return None


def mol_from_tool_input(item) -> object | None:
    """Molecule for one tool job input: a live mol, a stored ``ToBinary`` blob, or cell text.

    The GUI thread hands workers stored blobs / text (see ``_structure_tool_inputs``) and the
    worker thread rebuilds molecules here, so large tables never hydrate on the GUI thread.
    """
    if item is None:
        return None
    if isinstance(item, (bytes, bytearray, memoryview)):
        return mol_from_binary_blob(item)
    if isinstance(item, str):
        text = item.strip()
        return parse_molecule_from_cell_text(text) if text else None
    return item


def tool_structure_result(oid: int, mol) -> tuple[int, bytes, str] | None:
    """``(oid, blob, canonical_smiles)`` built on the worker so the GUI stores results in bulk."""
    if mol is None:
        return None
    blob = mol_graph_binary(mol)
    if not blob:
        try:
            blob = mol.ToBinary()
        except Exception:
            return None
    try:
        smiles = mol_to_canonical_smiles(mol)
    except Exception:
        smiles = ""
    return int(oid), bytes(blob), smiles
