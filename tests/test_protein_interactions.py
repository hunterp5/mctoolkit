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

"""ProLIF protein–ligand overlay mapping and optional live fingerprint."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from molmanager.protein.protein_interactions import (
    FAMILY_HBOND,
    FAMILY_HYDROPHOBIC,
    FAMILY_IONIC,
    FAMILY_PI_STACKING,
    ProteinInteraction,
    contacts_from_ifp,
    detect_prolif_interactions,
    family_for_interaction,
    prolif_available,
    residue_pair_key,
    _prolif_role,
)
from molmanager.protein.structure_component_types import StructureAtom


class _Point(SimpleNamespace):
    pass


class _Conf:
    def __init__(self, coords: dict[int, tuple[float, float, float]]) -> None:
        self._coords = coords

    def GetAtomPosition(self, idx: int):
        x, y, z = self._coords[int(idx)]
        return _Point(x=x, y=y, z=z)


class _Atom:
    def __init__(self, name: str = " OD2", symbol: str = "O", atomic_num: int = 8) -> None:
        self._name = name
        self._symbol = symbol
        self._atomic_num = atomic_num

    def GetPDBResidueInfo(self):
        name = self._name
        return SimpleNamespace(GetName=lambda: name)

    def GetSymbol(self):
        return self._symbol

    def GetAtomicNum(self):
        return self._atomic_num


class _Residue:
    def __init__(
        self,
        name: str,
        number: int,
        chain: str,
        coords: dict[int, tuple[float, float, float]],
        atoms: dict[int, _Atom] | None = None,
    ) -> None:
        self.resid = SimpleNamespace(name=name, number=number, chain=chain, insertion="")
        self._conf = _Conf(coords)
        self._atoms = atoms or {}

    def GetConformer(self):
        return self._conf

    def GetAtomWithIdx(self, idx: int):
        return self._atoms.get(int(idx), _Atom())


class _Mol:
    def __init__(self, residues: dict[str, _Residue]) -> None:
        self._residues = residues

    def __getitem__(self, key):
        return self._residues[str(key)]


def test_family_for_interaction_maps_known_types() -> None:
    assert family_for_interaction("Hydrophobic") == FAMILY_HYDROPHOBIC
    assert family_for_interaction("HBDonor") == FAMILY_HBOND
    assert family_for_interaction("ImplicitHBAcceptor") == FAMILY_HBOND
    assert family_for_interaction("Anionic") == FAMILY_IONIC
    assert family_for_interaction("PiStacking") == FAMILY_PI_STACKING
    assert family_for_interaction("VdWContact") is None
    assert family_for_interaction("") is None


def test_residue_pair_key_is_unordered() -> None:
    a = residue_pair_key("A", "10", "", "SER", "A", "99", "", "LIG")
    b = residue_pair_key("A", "99", "", "LIG", "A", "10", "", "SER")
    assert a == b


def test_protein_interaction_payload_uses_complex_kind() -> None:
    contact = ProteinInteraction(
        family=FAMILY_HYDROPHOBIC,
        interaction="Hydrophobic",
        start=(1.0, 2.0, 3.0),
        end=(4.0, 5.0, 6.0),
        distance=3.21,
        ligand_chain="A",
        ligand_resn="LIG",
        ligand_resi="99",
        ligand_icode="",
        ligand_name="C1",
        ligand_kind="ligand",
        protein_chain="A",
        protein_resn="PHE",
        protein_resi="42",
        protein_icode="",
        protein_name="CZ",
        protein_kind="polymer",
    )
    payload = contact.to_payload()
    assert payload["kind"] == "complex"
    assert payload["family"] == FAMILY_HYDROPHOBIC
    assert payload["color"] == "#E67E22"
    assert payload["start"] == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert payload["end"] == {"x": 4.0, "y": 5.0, "z": 6.0}
    assert payload["distance"] == 3.21


def test_contacts_from_ifp_picks_shortest_and_skips_vdw() -> None:
    lig = _Residue("LIG", 99, "A", {0: (6.0, 0.0, 0.0), 1: (6.2, 0.1, 0.0)})
    prot = _Residue("ASP", 10, "A", {0: (4.0, 0.0, 0.0), 8: (4.1, 0.0, 0.0)})
    ligand_mol = _Mol({"LIG1.A": lig, "LIG99.A": lig})
    protein_mol = _Mol({"ASP10.A": prot})
    atoms = [
        StructureAtom(
            chain="A",
            resn="ASP",
            resi="10",
            icode="",
            name="OD2",
            elem="O",
            x=4.0,
            y=0.0,
            z=0.0,
            het=False,
        ),
        StructureAtom(
            chain="A",
            resn="LIG",
            resi="99",
            icode="",
            name="N1",
            elem="N",
            x=6.0,
            y=0.0,
            z=0.0,
            het=True,
        ),
    ]
    kinds = {
        ("A", "ASP", "10", ""): "polymer",
        ("A", "LIG", "99", ""): "ligand",
    }
    ifp = {
        ("LIG1.A", "ASP10.A"): {
            "HBDonor": (
                {
                    "indices": {"ligand": (0, 1), "protein": (8,)},
                    "distance": 3.2,
                },
                {
                    "indices": {"ligand": (0, 1), "protein": (8,)},
                    "distance": 2.6,
                },
            ),
            "VdWContact": (
                {
                    "indices": {"ligand": (0,), "protein": (0,)},
                    "distance": 3.0,
                },
            ),
        }
    }
    contacts = contacts_from_ifp(ifp, ligand_mol, protein_mol, atoms, kinds)
    assert len(contacts) == 1
    assert contacts[0].family == FAMILY_HBOND
    assert contacts[0].interaction == "HBDonor"
    assert contacts[0].distance == pytest.approx(2.6)
    assert contacts[0].ligand_resn == "LIG"
    assert contacts[0].protein_resn == "ASP"
    payload = contacts[0].to_payload()
    shown = {atom["role"]: atom for atom in payload["showAtoms"]}
    assert set(shown) == {"donor"}
    assert shown["donor"]["atom"] == "N1"
    assert shown["donor"]["resn"] == "LIG"
    assert payload["showResidues"] == [
        {"chain": "A", "resn": "ASP", "resi": "10", "icode": ""}
    ]


def test_hbond_show_atoms_follow_donor_side() -> None:
    lig = _Residue(
        "LIG",
        99,
        "A",
        {0: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (1.0, 1.0, 0.0)},
        atoms={
            0: _Atom(" O1 ", "O", 8),
            2: _Atom(" N1 ", "N", 7),
            3: _Atom(" H1 ", "H", 1),
        },
    )
    prot = _Residue(
        "SER",
        10,
        "A",
        {4: (3.2, 0.0, 0.0), 5: (3.2, 1.0, 0.0)},
        atoms={4: _Atom(" OG ", "O", 8), 5: _Atom(" HG ", "H", 1)},
    )
    atoms = [
        StructureAtom("A", "LIG", "99", "", "O1", "O", 0.0, 0.0, 0.0, True),
        StructureAtom("A", "LIG", "99", "", "N1", "N", 1.0, 0.0, 0.0, True),
        StructureAtom("A", "LIG", "99", "", "H1", "H", 1.0, 1.0, 0.0, True),
        StructureAtom("A", "SER", "10", "", "OG", "O", 3.2, 0.0, 0.0, False),
        StructureAtom("A", "SER", "10", "", "HG", "H", 3.2, 1.0, 0.0, False),
    ]
    kinds = {("A", "LIG", "99", ""): "ligand", ("A", "SER", "10", ""): "polymer"}
    donor_on_ligand = contacts_from_ifp(
        {
            ("LIG99.A", "SER10.A"): {
                "HBDonor": ({"indices": {"ligand": (2, 3), "protein": (4,)}, "distance": 2.2},)
            }
        },
        _Mol({"LIG99.A": lig}),
        _Mol({"SER10.A": prot}),
        atoms,
        kinds,
    )
    donor_payload = donor_on_ligand[0].to_payload()
    roles = {atom["role"]: atom["atom"] for atom in donor_payload["showAtoms"]}
    assert roles == {"donor": "N1", "hydrogen": "H1"}
    assert donor_payload["showResidues"] == [
        {"chain": "A", "resn": "SER", "resi": "10", "icode": ""}
    ]
    donor_on_protein = contacts_from_ifp(
        {
            ("LIG99.A", "SER10.A"): {
                "HBAcceptor": ({"indices": {"ligand": (0,), "protein": (4, 5)}, "distance": 2.4},)
            }
        },
        _Mol({"LIG99.A": lig}),
        _Mol({"SER10.A": prot}),
        atoms,
        kinds,
    )
    acceptor_payload = donor_on_protein[0].to_payload()
    roles = {atom["role"]: atom["atom"] for atom in acceptor_payload["showAtoms"]}
    assert roles == {"acceptor": "O1"}
    assert acceptor_payload["showResidues"] == [
        {"chain": "A", "resn": "SER", "resi": "10", "icode": ""}
    ]


def test_prolif_contact_shows_whole_protein_residue() -> None:
    lig = _Residue("LIG", 99, "A", {0: (6.0, 0.0, 0.0)})
    prot = _Residue("PHE", 42, "B", {0: (4.0, 0.0, 0.0), 1: (4.2, 0.8, 0.0)})
    atoms = [
        StructureAtom("A", "LIG", "99", "", "C1", "C", 6.0, 0.0, 0.0, True),
        StructureAtom("B", "PHE", "42", "", "CZ", "C", 4.0, 0.0, 0.0, False),
        StructureAtom("B", "PHE", "42", "", "HZ", "H", 4.2, 0.8, 0.0, False),
    ]
    kinds = {("A", "LIG", "99", ""): "ligand", ("B", "PHE", "42", ""): "polymer"}
    contacts = contacts_from_ifp(
        {
            ("LIG99.A", "PHE42.B"): {
                "Hydrophobic": ({"indices": {"ligand": (0,), "protein": (0,)}, "distance": 3.4},)
            }
        },
        _Mol({"LIG99.A": lig}),
        _Mol({"PHE42.B": prot}),
        atoms,
        kinds,
        model=1,
    )
    assert len(contacts) == 1
    payload = contacts[0].to_payload()
    assert "showAtoms" not in payload
    assert payload["showResidues"] == [
        {"chain": "B", "resn": "PHE", "resi": "42", "icode": "", "model": 1}
    ]


def test_prolif_role_treats_atom_record_lig_as_ligand() -> None:
    lig = StructureAtom(
        chain="G",
        resn="LIG",
        resi="1",
        icode="",
        name="C1",
        elem="C",
        x=0.0,
        y=0.0,
        z=0.0,
        het=False,
    )
    asp = StructureAtom(
        chain="A",
        resn="ASP",
        resi="10",
        icode="",
        name="OD2",
        elem="O",
        x=1.0,
        y=0.0,
        z=0.0,
        het=False,
    )
    kinds = {
        ("G", "LIG", "1", ""): "polymer",
        ("A", "ASP", "10", ""): "polymer",
    }
    assert _prolif_role(lig, kinds) == "ligand"
    assert _prolif_role(asp, kinds) == "polymer"


def test_detect_prolif_interactions_without_library_is_empty() -> None:
    if prolif_available():
        pytest.skip("ProLIF is installed")
    pdb = """\
ATOM      1  N   ASP A   1       0.000   2.000   0.000  1.00  0.00           N
HETATM  100  N1  LIG A  99       6.400  -0.300   0.000  1.00  0.00           N
END
"""
    assert detect_prolif_interactions(pdb, "pdb") == ()


@pytest.mark.skipif(not prolif_available(), reason="prolif not installed")
def test_detect_prolif_interactions_on_tutorial_complex() -> None:
    import prolif as plf

    rec = plf.datafiles.datapath / "vina" / "rec.pdb"
    lig = plf.datafiles.datapath / "vina" / "lig.pdb"
    if not rec.is_file() or not lig.is_file():
        pytest.skip("ProLIF tutorial PDBs are not installed")
    text = rec.read_text(encoding="utf-8", errors="replace")
    text += "\n" + lig.read_text(encoding="utf-8", errors="replace")
    contacts = detect_prolif_interactions(text, "pdb")
    families = {contact.family for contact in contacts}
    assert contacts
    assert families & {FAMILY_HBOND, FAMILY_HYDROPHOBIC, FAMILY_IONIC, FAMILY_PI_STACKING}


def test_rdkit_ligand_structure_atoms_defaults() -> None:
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    from molmanager.protein.protein_interactions import rdkit_ligand_structure_atoms

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(0.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(1.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(2.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    atoms = rdkit_ligand_structure_atoms(mol)
    assert len(atoms) == 3
    assert all(atom.het and atom.resn == "LIG" and atom.chain == "Z" for atom in atoms)


def test_compute_dock_pose_overlays_ignores_file_ligand() -> None:
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    from molmanager.protein.protein_interactions import compute_dock_pose_overlays

    pdb = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  H   ALA A   1       0.900   0.000   0.000  1.00  0.00           H
ATOM      3  O   ALA A   1       0.000   1.200   0.000  1.00  0.00           O
HETATM  100  O1  LIG A  99       2.800   0.000   0.000  1.00  0.00           O
END
"""
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(40.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(41.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(42.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    hbonds, contacts = compute_dock_pose_overlays(pdb, "pdb", mol, prolif=False)
    assert contacts == ()
    for bond in hbonds:
        assert bond.donor_resi != "99"
        assert bond.acceptor_resi != "99"


@pytest.mark.skipif(not prolif_available(), reason="prolif not installed")
def test_compute_dock_pose_overlays_on_tutorial_ligand() -> None:
    from rdkit import Chem

    import prolif as plf

    from molmanager.protein.protein_interactions import compute_dock_pose_overlays

    rec = plf.datafiles.datapath / "vina" / "rec.pdb"
    lig = plf.datafiles.datapath / "vina" / "lig.pdb"
    if not rec.is_file() or not lig.is_file():
        pytest.skip("ProLIF tutorial PDBs are not installed")
    rec_text = rec.read_text(encoding="utf-8", errors="replace")
    lig_mol = Chem.MolFromPDBFile(str(lig), removeHs=False)
    if lig_mol is None or lig_mol.GetNumConformers() < 1:
        pytest.skip("Could not load tutorial ligand")
    _hbonds, contacts = compute_dock_pose_overlays(rec_text, "pdb", lig_mol)
    assert contacts
    families = {contact.family for contact in contacts}
    assert families & {FAMILY_HBOND, FAMILY_HYDROPHOBIC, FAMILY_IONIC, FAMILY_PI_STACKING}
