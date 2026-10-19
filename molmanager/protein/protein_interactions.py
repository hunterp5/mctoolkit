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

"""ProLIF protein–ligand contacts for Protein Viewer overlays."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable

from .hydrogen_bonds import HBOND_COLORS, HBOND_KIND_COMPLEX
from .structure_components import (
    AMINO_ACIDS,
    NUCLEIC_ACIDS,
    StructureAtom,
    _pdb_from_atoms,
    _residue_kinds_from_atoms,
    parse_structure_atoms,
)

logger = logging.getLogger(__name__)

FAMILY_HBOND = "hbond"
FAMILY_HYDROPHOBIC = "hydrophobic"
FAMILY_IONIC = "ionic"
FAMILY_PI_STACKING = "pi_stacking"
FAMILY_PI_CATION = "pi_cation"
FAMILY_HALOGEN = "halogen"

PROLIF_FAMILIES = (
    FAMILY_HYDROPHOBIC,
    FAMILY_IONIC,
    FAMILY_PI_STACKING,
    FAMILY_PI_CATION,
    FAMILY_HALOGEN,
)

FAMILY_COLORS = {
    FAMILY_HBOND: HBOND_COLORS[HBOND_KIND_COMPLEX],
    FAMILY_HYDROPHOBIC: "#E67E22",
    FAMILY_IONIC: "#E74C3C",
    FAMILY_PI_STACKING: "#9B59B6",
    FAMILY_PI_CATION: "#E359D8",
    FAMILY_HALOGEN: "#FF9F02",
}

_PROLIF_TYPE_TO_FAMILY = {
    "HBDonor": FAMILY_HBOND,
    "HBAcceptor": FAMILY_HBOND,
    "ImplicitHBDonor": FAMILY_HBOND,
    "ImplicitHBAcceptor": FAMILY_HBOND,
    "Hydrophobic": FAMILY_HYDROPHOBIC,
    "Anionic": FAMILY_IONIC,
    "Cationic": FAMILY_IONIC,
    "PiStacking": FAMILY_PI_STACKING,
    "FaceToFace": FAMILY_PI_STACKING,
    "EdgeToFace": FAMILY_PI_STACKING,
    "CationPi": FAMILY_PI_CATION,
    "PiCation": FAMILY_PI_CATION,
    "XBDonor": FAMILY_HALOGEN,
    "XBAcceptor": FAMILY_HALOGEN,
}

_PROLIF_INTERACTIONS = (
    "Hydrophobic",
    "HBDonor",
    "HBAcceptor",
    "PiStacking",
    "Anionic",
    "Cationic",
    "CationPi",
    "PiCation",
    "XBDonor",
    "XBAcceptor",
)

_HBOND_LIGAND_DONOR = frozenset({"HBDonor", "ImplicitHBDonor"})
_HBOND_PROTEIN_DONOR = frozenset({"HBAcceptor", "ImplicitHBAcceptor"})
_LIGAND_DISPLAYED_ATOM = {
    "HBDonor": 1,
    "XBDonor": 1,
}
_PROTEIN_DISPLAYED_ATOM = {
    "HBAcceptor": 1,
    "XBAcceptor": 1,
}
_RING_TYPES = frozenset({"PiStacking", "EdgeToFace", "FaceToFace"})
_LIGAND_RING = _RING_TYPES | {"PiCation"}
_PROTEIN_RING = _RING_TYPES | {"CationPi"}
_MATCH_SQ = 2.0 * 2.0
_PROTEIN_MOL_CACHE_MAX = 4
_PROTEIN_MOL_CACHE: OrderedDict[str, "_ProteinProlifEntry"] = OrderedDict()
_PROTEIN_MOL_CACHE_GUARD = threading.Lock()
_PROLIF_GENERATE_LOCK = threading.Lock()


@dataclass
class _ProteinProlifEntry:
    """Cached ProLIF protein molecule."""

    mol: Any


@dataclass(frozen=True)
class ProteinInteraction:
    """One ProLIF contact with coordinates for a 3Dmol dashed cylinder."""

    family: str
    interaction: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    distance: float
    ligand_chain: str
    ligand_resn: str
    ligand_resi: str
    ligand_icode: str
    ligand_name: str
    ligand_kind: str
    protein_chain: str
    protein_resn: str
    protein_resi: str
    protein_icode: str
    protein_name: str
    protein_kind: str
    model: int | None = None
    show_atoms: tuple[dict[str, str | int], ...] = ()
    show_residues: tuple[dict[str, str | int], ...] = ()

    def to_payload(self, color: str | None = None) -> dict:
        """JSON object consumed by the Protein Viewer interaction overlay."""
        payload = {
            "kind": HBOND_KIND_COMPLEX,
            "family": self.family,
            "interaction": self.interaction,
            "color": color or FAMILY_COLORS.get(self.family, "#7F8C8D"),
            "start": {"x": self.start[0], "y": self.start[1], "z": self.start[2]},
            "end": {"x": self.end[0], "y": self.end[1], "z": self.end[2]},
            "distance": None if self.distance != self.distance else round(self.distance, 3),
            "ligand": _atom_ref(
                self.ligand_chain,
                self.ligand_resn,
                self.ligand_resi,
                self.ligand_icode,
                self.ligand_name,
                self.ligand_kind,
            ),
            "protein": _atom_ref(
                self.protein_chain,
                self.protein_resn,
                self.protein_resi,
                self.protein_icode,
                self.protein_name,
                self.protein_kind,
            ),
        }
        if self.show_atoms:
            payload["showAtoms"] = [dict(atom) for atom in self.show_atoms]
        if self.show_residues:
            payload["showResidues"] = [dict(residue) for residue in self.show_residues]
        return payload


def prolif_available() -> bool:
    """Return True when ProLIF can be imported."""
    try:
        import prolif  # noqa: F401
    except ImportError:
        return False
    return True


def family_for_interaction(name: str) -> str | None:
    """Map a ProLIF interaction class name to a viewer family, or None to skip."""
    return _PROLIF_TYPE_TO_FAMILY.get(str(name or "").strip())


def residue_pair_key(
    chain_a: str,
    resi_a: str,
    icode_a: str,
    resn_a: str,
    chain_b: str,
    resi_b: str,
    icode_b: str,
    resn_b: str,
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str]]:
    """Unordered residue-pair key used to de-duplicate geometric vs ProLIF H-bonds."""
    left = (chain_a, str(resi_a), icode_a or "", resn_a)
    right = (chain_b, str(resi_b), icode_b or "", resn_b)
    return (left, right) if left <= right else (right, left)


def detect_prolif_interactions(
    text: str,
    fmt: str,
    *,
    model: int | None = None,
) -> tuple[ProteinInteraction, ...]:
    """Return protein–ligand ProLIF contacts for the first model of *text*."""
    if not prolif_available():
        return ()
    atoms = parse_structure_atoms(text, fmt)
    return detect_prolif_interactions_from_atoms(atoms, model=model)


def compute_viewer_interaction_overlays(
    text: str,
    fmt: str,
    *,
    model: int | None = None,
    hbonds: bool = True,
    prolif: bool = True,
) -> tuple[tuple, tuple[ProteinInteraction, ...]]:
    """Parse atoms once, then run geometric H-bonds and/or ProLIF."""
    atoms = parse_structure_atoms(text, fmt)
    hbond_hits: tuple = ()
    if hbonds:
        from .hydrogen_bonds import detect_hydrogen_bonds_from_atoms

        hbond_hits = detect_hydrogen_bonds_from_atoms(atoms, model=model)
    prolif_hits: tuple[ProteinInteraction, ...] = ()
    if prolif:
        prolif_hits = detect_prolif_interactions_from_atoms(atoms, model=model)
    return hbond_hits, prolif_hits


def compute_dock_pose_overlays(
    protein_text: str,
    protein_fmt: str,
    ligand_mol,
    *,
    model: int | None = None,
    hbonds: bool = True,
    prolif: bool = True,
) -> tuple[tuple, tuple[ProteinInteraction, ...]]:
    """Score a docked pose against polymer atoms only (file ligands are ignored)."""
    from .hydrogen_bonds import HBOND_KIND_PROTEIN, detect_hydrogen_bonds_from_atoms

    atoms = parse_structure_atoms(protein_text, protein_fmt)
    kinds = _residue_kinds_from_atoms(atoms)
    protein_atoms = [atom for atom in atoms if _prolif_role(atom, kinds) == "polymer"]
    ligand_atoms = rdkit_ligand_structure_atoms(ligand_mol)
    if len(protein_atoms) < 3 or not ligand_atoms:
        return (), ()
    combined = [*protein_atoms, *ligand_atoms]
    hbond_hits: tuple = ()
    if hbonds:
        hbond_hits = tuple(
            bond
            for bond in detect_hydrogen_bonds_from_atoms(combined, model=model)
            if bond.kind != HBOND_KIND_PROTEIN
        )
    prolif_hits: tuple[ProteinInteraction, ...] = ()
    if prolif:
        prolif_hits = detect_prolif_interactions_from_pose(
            protein_atoms, ligand_mol, ligand_atoms, model=model
        )
    return hbond_hits, prolif_hits


def detect_prolif_interactions_from_atoms(
    atoms: Iterable[StructureAtom],
    *,
    model: int | None = None,
) -> tuple[ProteinInteraction, ...]:
    """Run ProLIF on already-parsed coordinate atoms."""
    if not prolif_available():
        return ()
    atom_list = list(atoms)
    if len(atom_list) < 2:
        return ()
    kinds = _residue_kinds_from_atoms(atom_list)
    protein_atoms = [atom for atom in atom_list if _prolif_role(atom, kinds) == "polymer"]
    ligand_atoms = [atom for atom in atom_list if _prolif_role(atom, kinds) == "ligand"]
    if len(protein_atoms) < 3 or not ligand_atoms:
        return ()
    protein_mol = _cached_protein_prolif_mol(protein_atoms)
    ligand_mol = _load_prolif_molecule(_pdb_from_atoms(ligand_atoms), prefer_rdkit=True)
    if protein_mol is None or ligand_mol is None:
        return ()
    return _fingerprint_contacts(
        ligand_mol,
        protein_mol,
        atom_list,
        kinds,
        model=model,
    )


def detect_prolif_interactions_from_pose(
    protein_atoms: list[StructureAtom],
    ligand_mol,
    ligand_atoms: list[StructureAtom] | None = None,
    *,
    model: int | None = None,
) -> tuple[ProteinInteraction, ...]:
    """ProLIF contacts for an RDKit dock pose vs cached polymer atoms."""
    if not prolif_available():
        return ()
    if len(protein_atoms) < 3:
        return ()
    lig_atoms = (
        ligand_atoms if ligand_atoms is not None else rdkit_ligand_structure_atoms(ligand_mol)
    )
    if not lig_atoms:
        return ()
    protein_plf = _cached_protein_prolif_mol(protein_atoms)
    ligand_plf = _ligand_prolif_from_rdkit(ligand_mol)
    if protein_plf is None or ligand_plf is None:
        return ()
    combined = [*protein_atoms, *lig_atoms]
    kinds = _residue_kinds_from_atoms(combined)
    return _fingerprint_contacts(
        ligand_plf,
        protein_plf,
        combined,
        kinds,
        model=model,
    )


def rdkit_ligand_structure_atoms(
    mol,
    *,
    resn: str = "LIG",
    chain: str = "Z",
    resi: str = "1",
) -> list[StructureAtom]:
    """Coordinate atoms for a docked RDKit pose (HETATM / ligand)."""
    if mol is None:
        return []
    try:
        if mol.GetNumAtoms() == 0 or mol.GetNumConformers() < 1:
            return []
        conf = mol.GetConformer()
    except Exception:
        return []
    default_resn = (resn or "LIG").strip().upper() or "LIG"
    default_chain = ((chain or "Z").strip() or "Z")[:1]
    default_resi = str(resi or "1")
    atoms: list[StructureAtom] = []
    for atom in mol.GetAtoms():
        try:
            pos = conf.GetAtomPosition(atom.GetIdx())
        except Exception:
            continue
        info = atom.GetPDBResidueInfo() if hasattr(atom, "GetPDBResidueInfo") else None
        name = (atom.GetSymbol() or "C").strip() or "C"
        atom_resn = default_resn
        atom_chain = default_chain
        atom_resi = default_resi
        icode = ""
        if info is not None:
            raw_name = (info.GetName() or "").strip()
            if raw_name:
                name = raw_name
            raw_resn = (info.GetResidueName() or "").strip().upper()
            if raw_resn:
                atom_resn = raw_resn
            raw_chain = (info.GetChainId() or "").strip()
            if raw_chain:
                atom_chain = raw_chain[:1]
            try:
                atom_resi = str(int(info.GetResidueNumber()))
            except (TypeError, ValueError):
                atom_resi = str(info.GetResidueNumber() or default_resi)
            icode = (info.GetInsertionCode() or "").strip()
        atoms.append(
            StructureAtom(
                chain=atom_chain,
                resn=atom_resn,
                resi=atom_resi or default_resi,
                icode=icode,
                name=name,
                elem=(atom.GetSymbol() or "C").upper(),
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                het=True,
            )
        )
    return atoms


def clear_prolif_protein_cache() -> None:
    """Drop cached ProLIF protein molecules (tests / structure reload)."""
    with _PROTEIN_MOL_CACHE_GUARD:
        _PROTEIN_MOL_CACHE.clear()


def _fingerprint_contacts(
    ligand_mol: Any,
    protein_mol: Any,
    atoms: list[StructureAtom],
    kinds: dict[tuple[str, str, str, str], str],
    *,
    model: int | None,
) -> tuple[ProteinInteraction, ...]:
    implicit = not (_mol_has_hydrogen(protein_mol) and _mol_has_hydrogen(ligand_mol))
    fingerprint = _make_fingerprint(implicit_hydrogens=implicit)
    if fingerprint is None:
        return ()
    try:
        ifp = _generate_ifp(fingerprint, ligand_mol, protein_mol)
    except Exception:
        logger.debug("ProLIF fingerprint generation failed", exc_info=True)
        return ()
    if ifp is None:
        ifp = getattr(fingerprint, "ifp", None)
        if isinstance(ifp, dict) and ifp:
            ifp = next(iter(ifp.values()))
    if not ifp:
        return ()
    return contacts_from_ifp(
        ifp,
        ligand_mol,
        protein_mol,
        atoms,
        kinds,
        model=model,
    )


def _generate_ifp(fingerprint, ligand_mol, protein_mol):
    with _PROLIF_GENERATE_LOCK:
        try:
            return fingerprint.generate(ligand_mol, protein_mol, metadata=True)
        except TypeError:
            return fingerprint.generate(ligand_mol, protein_mol)


def _cached_protein_prolif_mol(protein_atoms: list[StructureAtom]):
    pdb = _pdb_from_atoms(protein_atoms)
    if not pdb.strip():
        return None
    key = hashlib.sha1(pdb.encode("utf-8", errors="replace")).hexdigest()
    with _PROTEIN_MOL_CACHE_GUARD:
        entry = _PROTEIN_MOL_CACHE.get(key)
        if entry is not None:
            _PROTEIN_MOL_CACHE.move_to_end(key)
            return entry.mol
    mol = _load_prolif_molecule(pdb)
    entry = _ProteinProlifEntry(mol=mol)
    with _PROTEIN_MOL_CACHE_GUARD:
        _PROTEIN_MOL_CACHE[key] = entry
        _PROTEIN_MOL_CACHE.move_to_end(key)
        while len(_PROTEIN_MOL_CACHE) > _PROTEIN_MOL_CACHE_MAX:
            _PROTEIN_MOL_CACHE.popitem(last=False)
    return mol


def _ligand_prolif_from_rdkit(mol):
    loaded = _as_prolif_molecule_from_rdkit(mol)
    if loaded is not None:
        return loaded
    atoms = rdkit_ligand_structure_atoms(mol)
    if not atoms:
        return None
    return _load_prolif_molecule(_pdb_from_atoms(atoms), prefer_rdkit=True)


def _as_prolif_molecule_from_rdkit(mol):
    if mol is None or not prolif_available():
        return None
    from rdkit import Chem

    try:
        copied = Chem.Mol(mol)
    except Exception:
        return None
    if copied.GetNumAtoms() == 0:
        return None
    try:
        Chem.SanitizeMol(copied)
    except Exception:
        try:
            copied.UpdatePropertyCache(strict=False)
        except Exception:
            pass
    try:
        import prolif as plf

        return plf.Molecule.from_rdkit(copied, resname="LIG", resnumber=1, chain="Z")
    except Exception:
        logger.debug("ProLIF RDKit pose wrap failed", exc_info=True)
        return _as_prolif_molecule(copied)


def contacts_from_ifp(
    ifp: Any,
    ligand_mol: Any,
    protein_mol: Any,
    atoms: list[StructureAtom],
    kinds: dict[tuple[str, str, str, str], str],
    *,
    model: int | None = None,
) -> tuple[ProteinInteraction, ...]:
    """Convert a ProLIF IFP dict into overlay cylinders."""
    best: dict[tuple, ProteinInteraction] = {}
    for pair, interactions in _iter_ifp_pairs(ifp):
        if not interactions:
            continue
        lig_resid, prot_resid = pair
        lig_res = _get_residue(ligand_mol, lig_resid)
        prot_res = _get_residue(protein_mol, prot_resid)
        if lig_res is None or prot_res is None:
            continue
        for interaction, metadata in _iter_interaction_metadata(interactions):
            family = family_for_interaction(interaction)
            if family is None:
                continue
            contact = _contact_from_metadata(
                interaction,
                family,
                metadata,
                lig_res,
                prot_res,
                atoms,
                kinds,
                model=model,
            )
            if contact is None:
                continue
            key = (family, interaction, _contact_pair_key(contact))
            prev = best.get(key)
            if prev is None or _distance_better(contact.distance, prev.distance):
                best[key] = contact
    return tuple(
        sorted(
            best.values(),
            key=lambda c: (
                c.family,
                c.interaction,
                c.protein_chain,
                c.protein_resi,
                c.ligand_chain,
                c.ligand_resi,
            ),
        )
    )


def _atom_ref(chain: str, resn: str, resi: str, icode: str, name: str, kind: str) -> dict[str, str]:
    return {
        "chain": chain,
        "resn": resn,
        "resi": resi,
        "icode": icode,
        "name": name,
        "kind": kind,
    }


def _res_key(atom: StructureAtom) -> tuple[str, str, str, str]:
    return (atom.chain, atom.resn, atom.resi, atom.icode)


def _prolif_role(atom: StructureAtom, kinds: dict[tuple[str, str, str, str], str]) -> str:
    """Protein vs ligand role for ProLIF, including ATOM-record hetero residues."""
    kind = kinds.get(_res_key(atom), "")
    if kind in {"water", "metal"}:
        return kind
    if kind == "ligand":
        return "ligand"
    resn = (atom.resn or "").upper()
    if resn in AMINO_ACIDS or resn in NUCLEIC_ACIDS:
        return "polymer"
    if kind == "polymer":
        return "ligand"
    return kind or "polymer"


def _contact_pair_key(contact: ProteinInteraction) -> tuple:
    return residue_pair_key(
        contact.ligand_chain,
        contact.ligand_resi,
        contact.ligand_icode,
        contact.ligand_resn,
        contact.protein_chain,
        contact.protein_resi,
        contact.protein_icode,
        contact.protein_resn,
    )


def _distance_better(candidate: float, previous: float) -> bool:
    if candidate != candidate:
        return False
    if previous != previous:
        return True
    return candidate < previous


def _iter_ifp_pairs(ifp: Any) -> Iterable[tuple[tuple[Any, Any], Any]]:
    if ifp is None:
        return
    items = ifp.items() if hasattr(ifp, "items") else []
    for key, value in items:
        if isinstance(key, tuple) and len(key) == 2:
            yield (key[0], key[1]), value
        elif hasattr(value, "ligand") and hasattr(value, "protein"):
            yield (value.ligand, value.protein), {getattr(value, "interaction", ""): value}


def _iter_interaction_metadata(interactions: Any) -> Iterable[tuple[str, dict]]:
    if hasattr(interactions, "items"):
        entries = list(interactions.items())
    else:
        entries = [("", interactions)]
    for name, payload in entries:
        for item in _as_metadata_items(payload):
            if isinstance(item, dict):
                yield str(name), item
                continue
            meta = getattr(item, "metadata", None)
            iname = getattr(item, "interaction", name)
            if isinstance(meta, dict):
                yield str(iname or name), meta


def _as_metadata_items(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, dict) and "indices" in payload:
        return [payload]
    if isinstance(payload, (list, tuple)):
        return list(payload)
    return [payload]


def _contact_from_metadata(
    interaction: str,
    family: str,
    metadata: dict,
    lig_res: Any,
    prot_res: Any,
    atoms: list[StructureAtom],
    kinds: dict[tuple[str, str, str, str], str],
    *,
    model: int | None,
) -> ProteinInteraction | None:
    indices = metadata.get("indices") if isinstance(metadata.get("indices"), dict) else {}
    lig_idx = tuple(indices.get("ligand") or ())
    prot_idx = tuple(indices.get("protein") or ())
    start = _endpoint_xyz(
        lig_res,
        lig_idx,
        interaction,
        _LIGAND_DISPLAYED_ATOM,
        _LIGAND_RING,
    )
    end = _endpoint_xyz(
        prot_res,
        prot_idx,
        interaction,
        _PROTEIN_DISPLAYED_ATOM,
        _PROTEIN_RING,
    )
    if start is None or end is None:
        return None
    lig_atom = _nearest_atom(atoms, start)
    prot_atom = _nearest_atom(atoms, end)
    lig_chain, lig_resn, lig_resi, lig_icode = _residue_fields(lig_res, lig_atom)
    prot_chain, prot_resn, prot_resi, prot_icode = _residue_fields(prot_res, prot_atom)
    lig_kind = kinds.get(_res_key(lig_atom), "ligand") if lig_atom is not None else "ligand"
    prot_kind = kinds.get(_res_key(prot_atom), "polymer") if prot_atom is not None else "polymer"
    if lig_atom is not None and _prolif_role(lig_atom, kinds) != "ligand":
        return None
    if prot_atom is not None and _prolif_role(prot_atom, kinds) != "polymer":
        return None
    distance = metadata.get("distance")
    try:
        dist = float(distance)
    except (TypeError, ValueError):
        dist = float("nan")
    return ProteinInteraction(
        family=family,
        interaction=interaction,
        start=start,
        end=end,
        distance=dist,
        ligand_chain=lig_chain,
        ligand_resn=lig_resn,
        ligand_resi=str(lig_resi),
        ligand_icode=lig_icode,
        ligand_name=_atom_name(lig_res, lig_idx, interaction, _LIGAND_DISPLAYED_ATOM),
        ligand_kind=lig_kind if lig_kind in {"ligand", "polymer"} else "ligand",
        protein_chain=prot_chain,
        protein_resn=prot_resn,
        protein_resi=str(prot_resi),
        protein_icode=prot_icode,
        protein_name=_atom_name(prot_res, prot_idx, interaction, _PROTEIN_DISPLAYED_ATOM),
        protein_kind=prot_kind if prot_kind == "polymer" else "polymer",
        model=model,
        show_atoms=_hbond_show_atoms(
            interaction,
            lig_res,
            lig_idx,
            prot_res,
            prot_idx,
            atoms,
            model=model,
        ),
        show_residues=_protein_show_residue(
            prot_chain,
            prot_resn,
            str(prot_resi),
            prot_icode,
            model=model,
        ),
    )


def _hbond_show_atoms(
    interaction: str,
    lig_res: Any,
    lig_idx: tuple,
    prot_res: Any,
    prot_idx: tuple,
    atoms: list[StructureAtom],
    *,
    model: int | None,
) -> tuple[dict[str, str | int], ...]:
    """Ligand donor, hydrogen, and acceptor atoms to draw for a ProLIF hydrogen bond."""
    if interaction in _HBOND_LIGAND_DONOR:
        specs = (
            (lig_res, lig_idx, 0, "donor"),
            (lig_res, lig_idx, 1, "hydrogen"),
            (prot_res, prot_idx, 0, "acceptor"),
        )
    elif interaction in _HBOND_PROTEIN_DONOR:
        specs = (
            (prot_res, prot_idx, 0, "donor"),
            (prot_res, prot_idx, 1, "hydrogen"),
            (lig_res, lig_idx, 0, "acceptor"),
        )
    else:
        return ()
    shown: list[dict[str, str | int]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for residue, indices, slot, role in specs:
        if residue is not lig_res:
            continue
        if slot >= len(indices):
            continue
        if role == "hydrogen" and not _residue_atom_is_hydrogen(residue, indices[slot]):
            continue
        record = _show_atom_record(residue, int(indices[slot]), atoms, role, model)
        if record is None:
            continue
        key = (
            str(record["chain"]),
            str(record["resi"]),
            str(record["icode"]),
            str(record["atom"]),
            role,
        )
        if key in seen:
            continue
        seen.add(key)
        shown.append(record)
    return tuple(shown)


def _protein_show_residue(
    chain: str,
    resn: str,
    resi: str,
    icode: str,
    *,
    model: int | None,
) -> tuple[dict[str, str | int], ...]:
    """Protein residue to draw in full when ProLIF reports a contact with it."""
    if not str(resi).strip() and not (chain or resn):
        return ()
    record: dict[str, str | int] = {
        "chain": chain,
        "resn": resn,
        "resi": str(resi),
        "icode": icode or "",
    }
    if model is not None:
        record["model"] = model
    return (record,)


def _show_atom_record(
    residue: Any,
    index: int,
    atoms: list[StructureAtom],
    role: str,
    model: int | None,
) -> dict[str, str | int] | None:
    """Map one ProLIF atom onto a structure atom the viewer can select."""
    xyz = _atom_xyz(residue, index)
    hydrogen = _residue_atom_is_hydrogen(residue, index)
    matched = _nearest_atom(atoms, xyz) if xyz is not None else None
    if matched is not None and _structure_atom_is_hydrogen(matched) != hydrogen:
        matched = None
    if matched is not None:
        chain, resn, resi, icode = matched.chain, matched.resn, matched.resi, matched.icode
        name = matched.name.strip()
    elif hydrogen:
        return None
    else:
        chain, resn, resi, icode = _residue_fields(residue, None)
        name = _atom_name(residue, (index,), "", {})
    if not name:
        return None
    record: dict[str, str | int] = {
        "chain": chain,
        "resn": resn,
        "resi": str(resi),
        "icode": icode,
        "atom": name,
        "role": role,
    }
    if model is not None:
        record["model"] = model
    return record


def _atom_xyz(residue: Any, index: int) -> tuple[float, float, float] | None:
    try:
        point = residue.GetConformer().GetAtomPosition(int(index))
    except Exception:
        return None
    return (float(point.x), float(point.y), float(point.z))


def _residue_atom_is_hydrogen(residue: Any, index: int) -> bool:
    try:
        atom = residue.GetAtomWithIdx(int(index))
    except Exception:
        return False
    try:
        if int(atom.GetAtomicNum()) == 1:
            return True
    except Exception:
        pass
    try:
        symbol = str(atom.GetSymbol() or "").strip().upper()
    except Exception:
        symbol = ""
    return symbol in {"H", "D", "T"}


def _structure_atom_is_hydrogen(atom: StructureAtom) -> bool:
    return (atom.elem or "").strip().upper() in {"H", "D", "T"}


def _endpoint_xyz(
    residue: Any,
    indices: tuple,
    interaction: str,
    displayed: dict[str, int],
    ring_types: frozenset[str],
) -> tuple[float, float, float] | None:
    try:
        conf = residue.GetConformer()
    except Exception:
        return None
    if interaction in ring_types and indices:
        return _centroid(conf, indices)
    idx = _displayed_index(indices, displayed.get(interaction, 0))
    try:
        point = conf.GetAtomPosition(int(idx))
    except Exception:
        return None
    return (float(point.x), float(point.y), float(point.z))


def _displayed_index(indices: tuple, preferred: int) -> int:
    if not indices:
        return 0
    if 0 <= preferred < len(indices):
        return int(indices[preferred])
    return int(indices[0])


def _centroid(conf: Any, indices: tuple) -> tuple[float, float, float] | None:
    xs = ys = zs = 0.0
    count = 0
    for idx in indices:
        try:
            point = conf.GetAtomPosition(int(idx))
        except Exception:
            continue
        xs += float(point.x)
        ys += float(point.y)
        zs += float(point.z)
        count += 1
    if count == 0:
        return None
    return (xs / count, ys / count, zs / count)


def _atom_name(residue: Any, indices: tuple, interaction: str, displayed: dict[str, int]) -> str:
    idx = _displayed_index(indices, displayed.get(interaction, 0))
    try:
        atom = residue.GetAtomWithIdx(int(idx))
    except Exception:
        return ""
    info = atom.GetPDBResidueInfo() if hasattr(atom, "GetPDBResidueInfo") else None
    if info is not None:
        name = str(info.GetName() or "").strip()
        if name:
            return name
    return str(atom.GetSymbol() if hasattr(atom, "GetSymbol") else "")


def _residue_fields(residue: Any, matched: StructureAtom | None) -> tuple[str, str, str, str]:
    if matched is not None:
        return matched.chain, matched.resn, matched.resi, matched.icode
    resid = getattr(residue, "resid", None)
    if resid is None:
        return "", "", "", ""
    chain = str(getattr(resid, "chain", "") or "")
    resn = str(getattr(resid, "name", "") or "")
    number = getattr(resid, "number", "")
    icode = str(getattr(resid, "insertion", None) or getattr(resid, "icode", "") or "")
    return chain, resn, str(number), icode


def _nearest_atom(
    atoms: list[StructureAtom], xyz: tuple[float, float, float]
) -> StructureAtom | None:
    x, y, z = xyz
    best: StructureAtom | None = None
    best_d = _MATCH_SQ
    for atom in atoms:
        dist = (atom.x - x) ** 2 + (atom.y - y) ** 2 + (atom.z - z) ** 2
        if dist <= best_d:
            best = atom
            best_d = dist
    return best


def _get_residue(mol: Any, resid: Any) -> Any:
    if mol is None:
        return None
    for key in (resid, str(resid) if resid is not None else None):
        if key is None:
            continue
        try:
            return mol[key]
        except Exception:
            continue
    return None


def _mol_has_hydrogen(mol: Any) -> bool:
    try:
        return any(int(atom.GetAtomicNum()) == 1 for atom in mol.GetAtoms())
    except Exception:
        return False


def _make_fingerprint(*, implicit_hydrogens: bool):
    import prolif as plf

    kwargs: dict[str, Any] = {"count": False}
    try:
        return plf.Fingerprint(
            list(_PROLIF_INTERACTIONS),
            implicit_hydrogens=implicit_hydrogens,
            **kwargs,
        )
    except TypeError:
        return plf.Fingerprint(list(_PROLIF_INTERACTIONS), **kwargs)


def _load_prolif_molecule(pdb_block: str, *, prefer_rdkit: bool = False):
    if not (pdb_block or "").strip():
        return None
    if prefer_rdkit:
        loaded = _as_prolif_molecule(_rdkit_mol_from_pdb(pdb_block))
        if loaded is not None:
            return loaded
    loaded = _load_prolif_molecule_mda(pdb_block)
    if loaded is not None:
        return loaded
    return _as_prolif_molecule(_rdkit_mol_from_pdb(pdb_block))


def _load_prolif_molecule_mda(pdb_block: str):
    try:
        import MDAnalysis as mda
        import prolif as plf
    except ImportError:
        return None
    handle = tempfile.NamedTemporaryFile(
        suffix=".pdb",
        delete=False,
        mode="w",
        encoding="utf-8",
        newline="\n",
    )
    path = handle.name
    try:
        handle.write(pdb_block)
        handle.close()
        universe = mda.Universe(path)
        if universe.atoms.n_atoms == 0:
            return None
        if getattr(universe.atoms, "n_bonds", 0) == 0:
            try:
                universe.atoms.guess_bonds()
            except Exception:
                logger.debug("MDAnalysis guess_bonds failed", exc_info=True)
        return plf.Molecule.from_mda(universe)
    except Exception:
        logger.debug("ProLIF MDAnalysis molecule load failed", exc_info=True)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _rdkit_mol_from_pdb(pdb_block: str):
    from rdkit import Chem

    mol = None
    try:
        mol = Chem.MolFromPDBBlock(pdb_block, removeHs=False, proximityBonding=True, sanitize=False)
    except TypeError:
        mol = Chem.MolFromPDBBlock(pdb_block, removeHs=False, sanitize=False)
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        try:
            mol.UpdatePropertyCache(strict=False)
        except Exception:
            pass
    return mol


def _as_prolif_molecule(rdkit_mol):
    if rdkit_mol is None:
        return None
    import prolif as plf

    for factory in (plf.Molecule.from_rdkit, plf.Molecule):
        try:
            return factory(rdkit_mol)
        except Exception:
            logger.debug("ProLIF RDKit molecule wrap failed", exc_info=True)
    return None
