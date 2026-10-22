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

"""Pack / unpack conformer ensembles for the ``confs`` table column and 3D viewer."""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from rdkit import Chem

logger = logging.getLogger(__name__)

CONFS_PACK_VERSION = 1
# Lightweight cell: metadata only; coordinate payload lives in app ``confs_sidecar`` (see demote/rehydrate).
CONFS_PACK_SIDECAR_VERSION = 2
# Compact JSON-only summary (errors, counts without coordinates).
CONFS_CELL_JSON_MAX = 2000
# 0 = do not truncate packed ensembles (coordinates live in EnsembleStore).
CONFS_CELL_PACK_MAX_CHARS = 0
PACKED_ENSEMBLE_BASES = ("confs", "superpose", "poses")
_PACKED_ENSEMBLE_HEADER_RE = re.compile(
    r"^(?:" + "|".join(PACKED_ENSEMBLE_BASES) + r")(?:_\d+| \(\d+\))?$",
    re.IGNORECASE,
)


def is_packed_ensemble_header(name: str) -> bool:
    """True for ``confs`` / ``superpose`` / ``poses`` and numbered copies (``confs (1)``, ``poses_2``)."""
    low = (name or "").strip()
    if not low:
        return False
    return _PACKED_ENSEMBLE_HEADER_RE.match(low) is not None


def conformer_is_3d(conf, *, z_eps: float = 1e-3) -> bool:
    """True when *conf* is marked 3D or has a non-negligible Z coordinate."""
    try:
        if bool(conf.Is3D()):
            return True
    except Exception:
        pass
    try:
        n = int(conf.GetNumAtoms())
    except Exception:
        return False
    for i in range(n):
        try:
            if abs(float(conf.GetAtomPosition(i).z)) > z_eps:
                return True
        except Exception:
            continue
    return False


def mol_has_3d_coordinates(mol: Chem.Mol | None, *, z_eps: float = 1e-3) -> bool:
    """True when *mol* has at least one conformer with 3D coordinates."""
    if mol is None:
        return False
    try:
        confs = list(mol.GetConformers())
    except Exception:
        return False
    for conf in confs:
        try:
            if conformer_is_3d(conf, z_eps=z_eps):
                return True
        except Exception:
            continue
    return False


def mol_coordinates_fill_blank_confs(mol: Chem.Mol | None, confs_cell: str | None) -> bool:
    """True when a structure's coordinates should occupy an empty ``confs`` cell.

    Structure files such as SDF can carry a ``confs`` column with no ensemble.
    The mol block is still one conformation. ``confs_cell`` is ``None`` when the
    file has no ``confs`` column; those rows are left alone.
    """
    if confs_cell is None or str(confs_cell).strip():
        return False
    if mol is None or mol_has_3d_coordinates(mol):
        return False
    try:
        return int(mol.GetNumConformers()) > 0
    except Exception:
        return False


_META_KEYS = (
    "ok",
    "n_requested",
    "n_embedded",
    "n_kept",
    "ewin_kcal",
    "ff",
    "e_min_kcal",
    "e_max_kept_kcal",
    "seed",
    "err",
    "truncated",
    "n_packed",
    # superpose / generic tool metadata
    "op",
    "ref_cid",
    "ref_clamped",
    "n_conf",
    "rms_mean",
    "rms_max",
    "heavy",
    "reflect",
    "max_align_iters",
    "n_align_atoms",
    "align_smarts",
    "align_pattern",
)


def format_confs_table_cell(meta: dict) -> str:
    """Single-line JSON for the ``confs`` table cell when no multi-conformer payload is stored."""
    d = {k: meta[k] for k in _META_KEYS if k in meta}
    try:
        s = json.dumps(d, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        s = '{"ok":false,"err":"serialize"}'
    if len(s) > CONFS_CELL_JSON_MAX:
        s = s[: CONFS_CELL_JSON_MAX - 1] + "…"
    return s


def conformer_mol_blocks_b64_json(mol: Chem.Mol) -> str:
    """Base64(JSON list of base64(mol block per conformer)), same encoding as the 3Dmol viewer."""
    try:
        m = Chem.Mol(mol)
    except Exception:
        return base64.b64encode(json.dumps([]).encode("utf-8")).decode("ascii")
    blocks: list[str] = []
    try:
        ids = sorted(c.GetId() for c in m.GetConformers())
    except Exception:
        ids = list(range(int(m.GetNumConformers())))
    for cid in ids:
        try:
            block = Chem.MolToMolBlock(m, confId=int(cid))
            blocks.append(base64.b64encode(block.encode("utf-8")).decode("ascii"))
        except Exception:
            continue
    payload = json.dumps(blocks).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def sd_blocks_b64_json_from_mols(mols: list[Chem.Mol]) -> str:
    """Base64(JSON list of base64(SDF record)) so each docked pose keeps its properties."""
    from io import StringIO

    blocks: list[str] = []
    for mol in mols:
        if mol is None:
            continue
        try:
            buf = StringIO()
            writer = Chem.SDWriter(buf)
            writer.write(mol)
            writer.close()
            text = buf.getvalue()
        except (RuntimeError, ValueError, OSError):
            continue
        if not text.strip():
            continue
        blocks.append(base64.b64encode(text.encode("utf-8")).decode("ascii"))
    return base64.b64encode(json.dumps(blocks).encode("utf-8")).decode("ascii")


def mols_from_blocks_b64(blocks_b64: str) -> list[Chem.Mol]:
    """One molecule per packed block, keeping SDF properties when the record has them."""
    from io import BytesIO

    try:
        encoded = json.loads(base64.b64decode(str(blocks_b64).encode("ascii")))
    except (json.JSONDecodeError, ValueError, TypeError):
        return []
    if not isinstance(encoded, list):
        return []
    out: list[Chem.Mol] = []
    for item in encoded:
        if not isinstance(item, str):
            continue
        try:
            text = base64.b64decode(item.encode("ascii")).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        mol = None
        try:
            supplier = Chem.ForwardSDMolSupplier(
                BytesIO(text.encode("utf-8")), sanitize=True, removeHs=False
            )
            mol = next(iter(supplier), None)
        except (RuntimeError, ValueError, OSError):
            mol = None
        if mol is None:
            try:
                mol = Chem.MolFromMolBlock(text, sanitize=True, removeHs=False)
            except (RuntimeError, ValueError):
                mol = None
        if mol is not None and int(mol.GetNumConformers()) > 0:
            out.append(mol)
    return out


def mol_blocks_b64_json_from_mols(mols: list[Chem.Mol]) -> str:
    """Base64(JSON list of base64(mol block)) for one structure per molecule (first conformer)."""
    blocks: list[str] = []
    for mol in mols:
        if mol is None:
            continue
        try:
            m = Chem.Mol(mol)
        except Exception:
            continue
        try:
            if int(m.GetNumConformers()) < 1:
                continue
            cid = int(m.GetConformer().GetId())
            block = Chem.MolToMolBlock(m, confId=cid)
            blocks.append(base64.b64encode(block.encode("utf-8")).decode("ascii"))
        except Exception:
            continue
    return base64.b64encode(json.dumps(blocks).encode("utf-8")).decode("ascii")


def pack_mols_as_confs_cell(
    meta: dict,
    mols: list[Chem.Mol],
    *,
    max_chars: int = CONFS_CELL_PACK_MAX_CHARS,
) -> str:
    """
    Pack one or more molecules into a ``confs``/``superpose`` cell for the 3D viewer.

    When every molecule has the same atom count, coordinates are merged into a multi-conformer
    mol so Strain Energy / RMSD tools can rebuild them. Otherwise each molecule is stored as its
    own mol block (viewer still works; same-topology tools may not).
    """
    base = format_confs_table_cell(meta)
    singles: list[Chem.Mol] = []
    for mol in mols:
        if mol is None:
            continue
        try:
            m = Chem.Mol(mol)
        except Exception:
            continue
        try:
            if int(m.GetNumConformers()) < 1:
                continue
            conf = Chem.Conformer(m.GetConformer())
            m.RemoveAllConformers()
            m.AddConformer(conf, assignId=True)
            singles.append(m)
        except Exception:
            continue
    if not singles:
        return base
    atom_counts = {int(m.GetNumAtoms()) for m in singles}
    if len(atom_counts) == 1 and len(singles) >= 1:
        try:
            merged = Chem.Mol(singles[0])
            merged.RemoveAllConformers()
            for m in singles:
                merged.AddConformer(Chem.Conformer(m.GetConformer(0)), assignId=True)
            pose_blocks = None
            if str((meta or {}).get("op") or "") == "gnina":
                pose_blocks = sd_blocks_b64_json_from_mols(singles)
            return pack_confs_cell(meta, merged, max_chars=max_chars, blocks_b64=pose_blocks)
        except Exception:
            logger.debug("pack_mols_as_confs_cell: multi-conf merge failed", exc_info=True)
    blocks_b64 = mol_blocks_b64_json_from_mols(singles)
    meta_out = {k: meta[k] for k in _META_KEYS if k in meta}
    meta_out["n_kept"] = len(singles)
    meta_out["n_packed"] = len(singles)
    inner: dict[str, Any] = {"v": CONFS_PACK_VERSION, "m": meta_out, "b": blocks_b64}
    try:
        s = json.dumps(inner, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        return base
    limit = int(max_chars)
    if limit <= 0 or len(s) <= limit:
        return s
    return base


def pack_confs_cell(
    meta: dict,
    mol: Chem.Mol | None,
    *,
    max_chars: int = CONFS_CELL_PACK_MAX_CHARS,
    blocks_b64: str | None = None,
) -> str:
    """
    Store generation metadata plus, when possible, all conformers as mol blocks for later 3D viewing.

    Falls back to :func:`format_confs_table_cell` when there are no conformers or packing fails.
    A single minimized conformer is packed so the 3D viewer can load it.
    When *max_chars* is 0 or negative, the payload is not truncated.
    """
    base = format_confs_table_cell(meta)
    if mol is None:
        return base
    try:
        nconf = int(mol.GetNumConformers())
    except Exception:
        nconf = 0
    if nconf < 1:
        return base
    if not blocks_b64:
        try:
            blocks_b64 = conformer_mol_blocks_b64_json(mol)
        except (RuntimeError, ValueError, TypeError):
            logger.exception("pack_confs_cell: mol block serialization failed")
            return base
    meta_out = {k: meta[k] for k in _META_KEYS if k in meta}
    inner: dict[str, Any] = {"v": CONFS_PACK_VERSION, "m": meta_out, "b": blocks_b64}
    s = json.dumps(inner, separators=(",", ":"), ensure_ascii=True)
    limit = int(max_chars)
    if limit <= 0 or len(s) <= limit:
        return s
    try:
        blocks = json.loads(base64.b64decode(blocks_b64.encode("ascii")))
    except Exception:
        return base
    if not isinstance(blocks, list) or len(blocks) < 2:
        return base
    meta_mut = dict(meta_out)
    while len(blocks) >= 1:
        meta_mut["truncated"] = True
        meta_mut["n_packed"] = len(blocks)
        new_b64 = base64.b64encode(json.dumps(blocks).encode("utf-8")).decode("ascii")
        inner = {"v": CONFS_PACK_VERSION, "m": meta_mut, "b": new_b64}
        s = json.dumps(inner, separators=(",", ":"), ensure_ascii=True)
        if len(s) <= max_chars:
            return s
        if len(blocks) <= 1:
            return base
        blocks.pop()
    return base


def unpack_confs_blocks_json_b64(cell_text: str) -> str | None:
    """
    If *cell_text* is a packed ``confs`` cell (v1 with ``b``), return the inner ``blocks_json_b64`` string
    expected by :class:`~MolManager.ui.mol_viewer_3d.Molecule3DViewerDialog` ``multi_conf_blocks_json_b64``.
    """
    s = (cell_text or "").strip()
    if not s or len(s) < 10:
        return None
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    if int(d.get("v", 0)) != CONFS_PACK_VERSION:
        return None
    b = d.get("b")
    if not isinstance(b, str) or not b.strip():
        return None
    try:
        inner = json.loads(base64.b64decode(b.encode("ascii")))
    except Exception:
        return None
    if not isinstance(inner, list) or len(inner) < 1:
        return None
    return b


def demote_v1_cell_to_sidecar(cell_text: str, column_key: str) -> tuple[str, str | None]:
    """
    Split a legacy v1 packed cell (``v`` 1 with embedded ``b``) into a short v2 cell plus the blocks payload.

    Returns ``(new_cell_text, blocks_b64_or_none)``. If *cell_text* is not a splittable v1 pack, returns
    ``(cell_text, None)`` unchanged.
    """
    s = (cell_text or "").strip()
    if not s:
        return cell_text, None
    b = unpack_confs_blocks_json_b64(s)
    if b is None:
        return cell_text, None
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return cell_text, None
    if not isinstance(d, dict) or int(d.get("v", 0)) != CONFS_PACK_VERSION:
        return cell_text, None
    m = d.get("m")
    if not isinstance(m, dict):
        m = {}
    light = {"v": CONFS_PACK_SIDECAR_VERSION, "h": str(column_key), "m": m}
    try:
        out = json.dumps(light, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        return cell_text, None
    return out, b


def make_sidecar_cell(column_key: str, meta: dict | None = None) -> str:
    """Short v2 table cell: metadata only; coordinates live in the ensemble store."""
    payload = {
        "v": CONFS_PACK_SIDECAR_VERSION,
        "h": str(column_key),
        "m": {k: meta[k] for k in _META_KEYS if meta and k in meta},
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def rehydrate_v1_confs_cell(
    cell_text: str,
    column_key: str,
    oid: int,
    sidecar: dict[tuple[int, str], str],
) -> str:
    """Rebuild a legacy v1 JSON string for workers that expect embedded ``b`` (e.g. superpose)."""
    s = (cell_text or "").strip()
    if not s:
        return s
    if unpack_confs_blocks_json_b64(s) is not None:
        return s
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return s
    if not isinstance(d, dict) or int(d.get("v", 0)) != CONFS_PACK_SIDECAR_VERSION:
        return s
    if str(d.get("h") or "") != str(column_key):
        return s
    b64 = sidecar.get((int(oid), str(column_key)))
    if not isinstance(b64, str) or not b64.strip():
        return s
    m = d.get("m")
    if not isinstance(m, dict):
        m = {}
    inner = {"v": CONFS_PACK_VERSION, "m": m, "b": b64}
    try:
        return json.dumps(inner, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        return s


def resolve_blocks_b64_for_viewer(
    cell_text: str,
    column_key: str,
    oid: int | None,
    sidecar: dict[tuple[int, str], str],
) -> str | None:
    """Inner mol-blocks base64 string for the 3D viewer, from embedded v1 or v2 + *sidecar*."""
    b = unpack_confs_blocks_json_b64(cell_text)
    if b is not None:
        return b
    if oid is None:
        return None
    try:
        d = json.loads((cell_text or "").strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or int(d.get("v", 0)) != CONFS_PACK_SIDECAR_VERSION:
        return None
    if str(d.get("h") or "") != str(column_key):
        return None
    b2 = sidecar.get((int(oid), str(column_key)))
    if isinstance(b2, str) and b2.strip():
        return b2
    return None


def serialize_confs_sidecar(store: dict[tuple[int, str], str]) -> dict[str, str]:
    """JSON-friendly dict for session documents (keys ``\"{oid}:{column}\"``).

    :class:`~molmanager.storage.EnsembleStore` snapshots are stored as a SQLite
    zip member instead of this JSON map.
    """
    from ..storage.ensemble_store import EnsembleStore

    if isinstance(store, EnsembleStore):
        return {}
    out: dict[str, str] = {}
    for (oid, col), b64 in (store or {}).items():
        out[f"{int(oid)}:{str(col)}"] = str(b64)
    return out


def deserialize_confs_sidecar(raw: dict | None) -> dict[tuple[int, str], str]:
    out: dict[tuple[int, str], str] = {}
    for k, v in (raw or {}).items():
        if not isinstance(v, str) or not v.strip():
            continue
        parts = str(k).split(":", 1)
        if len(parts) != 2:
            continue
        try:
            out[(int(parts[0]), str(parts[1]))] = v
        except ValueError:
            continue
    return out


def mol_from_packed_confs_cell(cell_text: str, *, min_conformers: int = 2) -> Chem.Mol | None:
    """
    Rebuild a multi-conformer :class:`rdkit.Chem.Mol` from a packed ``confs`` / ``superpose`` table cell
    (version 1 with coordinate payload ``b``).

    Returns ``None`` if the cell is not packed or has fewer than *min_conformers* conformers
    (default 2, matching superpose).
    """
    b64 = unpack_confs_blocks_json_b64(cell_text)
    if b64 is None:
        return None
    try:
        blocks_enc = json.loads(base64.b64decode(b64.encode("ascii")))
    except Exception:
        return None
    need = max(1, int(min_conformers))
    if not isinstance(blocks_enc, list) or len(blocks_enc) < need:
        return None
    blocks: list[str] = []
    for enc in blocks_enc:
        if not isinstance(enc, str):
            return None
        try:
            blocks.append(base64.b64decode(enc.encode("ascii")).decode("utf-8"))
        except Exception:
            return None
    mol = Chem.MolFromMolBlock(blocks[0], sanitize=True, removeHs=False)
    if mol is None:
        return None
    if mol.GetNumConformers() < 1:
        return None
    na = mol.GetNumAtoms()
    for bi in blocks[1:]:
        frag = Chem.MolFromMolBlock(bi, sanitize=True, removeHs=False)
        if frag is None or frag.GetNumAtoms() != na:
            return None
        if frag.GetNumConformers() < 1:
            return None
        try:
            mol.AddConformer(frag.GetConformer(0), assignId=True)
        except Exception:
            return None
    return mol
