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

"""Chunked SDF/MOL2 parsing into ingest records, in file order."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.chem import ingest_records
from molmanager.chem.ingest_records import parse_structure_chunk, structure_file_chunks
from molmanager.workers import load_render
from molmanager.workers.load_render import UniversalLoadWorker
from molmanager.workers.signals import WorkerSignals

SMILES = ["CCO", "c1ccccc1", "CC(=O)O", "CCN", "C1CC1", "OCCO", "CCCl"]


def _write_sdf(path: Path) -> None:
    writer = Chem.SDWriter(str(path))
    for i, smi in enumerate(SMILES):
        mol = Chem.MolFromSmiles(smi)
        AllChem.Compute2DCoords(mol)
        mol.SetProp("ID", str(i))
        writer.write(mol)
    writer.close()


def _write_mol2(path: Path) -> None:
    blocks = []
    for i, smi in enumerate(SMILES[:3]):
        atoms = "\n".join(
            f"{a + 1} C{a + 1} {a:.4f} 0.0000 0.0000 C.3 1 MOL 0.0000" for a in range(i + 1)
        )
        bonds = "\n".join(f"{b + 1} {b + 1} {b + 2} 1" for b in range(i))
        blocks.append(
            f"@<TRIPOS>MOLECULE\nm{i}\n{i + 1} {i} 0 0 0\nSMALL\nNO_CHARGES\n\n"
            f"@<TRIPOS>ATOM\n{atoms}\n@<TRIPOS>BOND\n{bonds}\n"
        )
    path.write_text("".join(blocks), encoding="utf-8")


def test_sdf_chunks_cover_every_record_in_order(tmp_path: Path) -> None:
    sdf = tmp_path / "set.sdf"
    _write_sdf(sdf)
    chunks = structure_file_chunks(str(sdf), "sdf", records_per_chunk=3)
    assert len(chunks) == 3
    assert chunks[0][0] == 0 and chunks[-1][1] == sdf.stat().st_size
    assert all(a[1] == b[0] for a, b in zip(chunks, chunks[1:]))
    records = [
        rec
        for start, end in chunks
        for rec in parse_structure_chunk((str(sdf), "sdf", start, end, ["ID"]))
    ]
    assert [rec.cells["ID"] for rec in records] == [str(i) for i in range(len(SMILES))]
    assert [rec.smiles for rec in records] == [
        Chem.MolToSmiles(Chem.MolFromSmiles(s)) for s in SMILES
    ]
    assert all(rec.depiction and not rec.ensemble for rec in records)
    assert all(Chem.Mol(rec.structure).GetNumConformers() == 0 for rec in records)


def test_mol2_chunks_split_on_molecule_markers(tmp_path: Path) -> None:
    mol2 = tmp_path / "set.mol2"
    _write_mol2(mol2)
    chunks = structure_file_chunks(str(mol2), "mol2", records_per_chunk=2)
    assert len(chunks) == 2
    records = [
        rec
        for start, end in chunks
        for rec in parse_structure_chunk((str(mol2), "mol2", start, end, []))
    ]
    assert [Chem.Mol(rec.structure).GetNumAtoms() for rec in records] == [1, 2, 3]


def test_load_worker_parses_chunks_in_a_pool_in_file_order(qapp, tmp_path, monkeypatch) -> None:  # noqa: ARG001
    sdf = tmp_path / "set.sdf"
    _write_sdf(sdf)
    pool = ThreadPoolExecutor(max_workers=3)
    monkeypatch.setattr(load_render, "_PARALLEL_PARSE_MIN_BYTES", 0)
    monkeypatch.setattr(ingest_records, "RECORDS_PER_CHUNK", 2)
    monkeypatch.setattr(
        load_render,
        "structure_file_chunks",
        lambda path, kind: structure_file_chunks(path, kind, records_per_chunk=2),
    )
    monkeypatch.setattr(load_render, "ensure_render2d_process_pool", lambda: pool)
    signals = WorkerSignals()
    batches: list[tuple[list, list]] = []
    signals.mols_loaded.connect(lambda batch, headers, _f, _l: batches.append((batch, headers)))
    try:
        UniversalLoadWorker(str(sdf), signals, batch_size=100).run()
    finally:
        pool.shutdown()
    assert batches[0][1] == ["ID_HIDDEN", "Structure", "ID"]
    ids = [rec.cells["ID"] for batch, _headers in batches for rec in batch]
    assert ids == [str(i) for i in range(len(SMILES))]
