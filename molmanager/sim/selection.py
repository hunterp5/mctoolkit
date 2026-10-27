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

"""Atom selection language for simulation restraints, solute filters, and observables."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..protein.structure_atoms import parse_structure_atoms

_AMINO = frozenset(
    {
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
        "HID",
        "HIE",
        "HIP",
        "CYX",
        "CYM",
        "ASH",
        "GLH",
        "LYN",
        "MSE",
    }
)
_WATER = frozenset({"HOH", "WAT", "H2O", "TIP", "TIP3", "SOL", "DOD"})
_IONS = frozenset(
    {"NA", "CL", "K", "MG", "ZN", "CA", "IOD", "FE", "CU", "MN", "BR", "CS", "RB", "LI"}
)
_BACKBONE = frozenset({"N", "CA", "C", "O", "OXT"})
_HYDROGEN = frozenset({"H", "D"})
_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<word>[A-Za-z_][A-Za-z0-9_]*)|(?P<sym>[()])|(?P<dash>-)|(?P<bad>\S))"
)
_QUALIFIERS = frozenset({"chain", "resi", "resn", "name", "element", "id"})


class SelectionError(ValueError):
    """The selection text could not be parsed. ``token`` is the offending word."""

    def __init__(self, message: str, token: str = "") -> None:
        self.token = token
        super().__init__(message)


@dataclass(frozen=True)
class AtomRecord:
    """One atom the selection language can name."""

    index: int
    name: str
    resname: str
    chain: str
    resi: int
    icode: str = ""
    element: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    kind: str = ""


def infer_kind(resname: str, name: str) -> str:
    """Classify a residue as protein, water, ion, or ligand from its names."""
    res = (resname or "").strip().upper()
    atom = (name or "").strip().upper()
    if res in _WATER:
        return "water"
    if res in _IONS and atom not in _BACKBONE:
        return "ion"
    if res in _AMINO:
        return "protein"
    return "ligand"


def atoms_from_structure_text(text: str, fmt: str = "pdb") -> list[AtomRecord]:
    """Coordinate records from a PDB or mmCIF string, in file order."""
    records: list[AtomRecord] = []
    for index, atom in enumerate(parse_structure_atoms(text or "", fmt)):
        try:
            resi = int(str(atom.resi).strip() or "0")
        except ValueError:
            resi = 0
        records.append(
            AtomRecord(
                index=index,
                name=(atom.name or "").strip(),
                resname=(atom.resn or "").strip(),
                chain=(atom.chain or "").strip(),
                resi=resi,
                icode=(atom.icode or "").strip(),
                element=(atom.elem or "").strip(),
                x=float(atom.x),
                y=float(atom.y),
                z=float(atom.z),
                kind=infer_kind(atom.resn, atom.name),
            )
        )
    return records


def parse_selection(expression: str):
    """Parse *expression* into an AST. Raises :class:`SelectionError` on bad syntax."""
    text = (expression or "").strip()
    if not text:
        raise SelectionError("Enter a selection.")
    tokens = _tokenize(text)
    parser = _Parser(tokens)
    ast = parser._parse_or()
    if parser.i < len(tokens):
        token = str(tokens[parser.i][1])
        raise SelectionError(f"Unexpected selection token {token!r}.", token=token)
    return ast


def select_atom_indices(expression: str, atoms: Sequence[AtomRecord]) -> list[int]:
    """Indices of *atoms* matched by *expression*, in ascending order."""
    matched = _eval(parse_selection(expression), list(atoms))
    return sorted(matched)


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None:
            snippet = text[pos : pos + 12]
            raise SelectionError(f"Unexpected selection token {snippet!r}.", token=snippet)
        pos = match.end()
        if match.group("bad"):
            bad = match.group("bad")
            raise SelectionError(f"Unexpected selection token {bad!r}.", token=bad)
        if match.group("num"):
            tokens.append(("num", match.group("num")))
        elif match.group("word"):
            tokens.append(("word", match.group("word")))
        elif match.group("sym"):
            tokens.append(("sym", match.group("sym")))
        elif match.group("dash"):
            tokens.append(("dash", "-"))
    if not tokens:
        raise SelectionError("Enter a selection.")
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0

    def _peek(self) -> tuple[str, str] | None:
        if self.i >= len(self.tokens):
            return None
        return self.tokens[self.i]

    def _word_is(self, value: str) -> bool:
        token = self._peek()
        return token is not None and token[0] == "word" and token[1].lower() == value

    def _parse_or(self):
        node = self._parse_and()
        while self._word_is("or"):
            self.i += 1
            node = ("or", node, self._parse_and())
        return node

    def _parse_and(self):
        node = self._parse_not()
        while self._word_is("and"):
            self.i += 1
            node = ("and", node, self._parse_not())
        return node

    def _parse_not(self):
        if self._word_is("not"):
            self.i += 1
            return ("not", self._parse_not())
        return self._parse_primary()

    def _parse_primary(self):
        if self._word_is("within"):
            return self._parse_within()
        token = self._peek()
        if token is not None and token[0] == "sym" and token[1] == "(":
            self.i += 1
            node = self._parse_or()
            if not (self._peek() and self._peek()[0] == "sym" and self._peek()[1] == ")"):
                raise SelectionError("Selection is missing a closing parenthesis.", token="(")
            self.i += 1
            return node
        if token is None:
            raise SelectionError("Selection ended early.")
        if token[0] != "word":
            raise SelectionError(f"Unexpected selection token {token[1]!r}.", token=token[1])
        word = token[1]
        if word.lower() in _QUALIFIERS:
            return self._parse_qualifier()
        self.i += 1
        key = word.lower()
        if key not in {
            "protein",
            "backbone",
            "ca",
            "sidechain",
            "ligand",
            "water",
            "ion",
            "heavy",
            "hydrogen",
        }:
            raise SelectionError(f"Unknown selection word {word!r}.", token=word)
        return ("pred", key)

    def _parse_within(self):
        self.i += 1
        token = self._peek()
        if token is None or token[0] != "num":
            found = token[1] if token else "end"
            raise SelectionError(
                f"within needs a distance in angstroms, found {found!r}.",
                token=str(found),
            )
        radius = float(token[1])
        self.i += 1
        if not self._word_is("of"):
            found = self._peek()[1] if self._peek() else "end"
            raise SelectionError(f"within needs 'of', found {found!r}.", token=str(found))
        self.i += 1
        return ("within", radius, self._parse_primary())

    def _parse_qualifier(self):
        kind = self.tokens[self.i][1].lower()
        self.i += 1
        token = self._peek()
        if token is None:
            raise SelectionError(f"{kind} needs a value.", token=kind)
        if kind == "resi":
            if token[0] != "num":
                raise SelectionError(f"resi needs a number, found {token[1]!r}.", token=token[1])
            start = int(float(token[1]))
            self.i += 1
            if self._peek() and self._peek()[0] == "dash":
                self.i += 1
                end_tok = self._peek()
                if end_tok is None or end_tok[0] != "num":
                    found = end_tok[1] if end_tok else "end"
                    raise SelectionError(
                        f"resi range needs an end number, found {found!r}.", token=str(found)
                    )
                end = int(float(end_tok[1]))
                self.i += 1
                return ("qual", "resi", (start, end))
            return ("qual", "resi", (start, start))
        if kind == "id":
            if token[0] != "num":
                raise SelectionError(f"id needs an atom index, found {token[1]!r}.", token=token[1])
            self.i += 1
            return ("qual", "id", int(float(token[1])))
        if token[0] != "word":
            raise SelectionError(f"{kind} needs a name, found {token[1]!r}.", token=token[1])
        self.i += 1
        return ("qual", kind, token[1])


def _kind_of(atom: AtomRecord) -> str:
    if atom.kind:
        return atom.kind
    return infer_kind(atom.resname, atom.name)


def _element(atom: AtomRecord) -> str:
    if atom.element:
        return atom.element.strip().upper()
    name = atom.name.strip().upper()
    if name.startswith("H") or name.startswith("D"):
        return "H"
    return name[:1]


def _is_backbone(atom: AtomRecord) -> bool:
    return _kind_of(atom) == "protein" and atom.name.strip().upper() in _BACKBONE


def _predicate(name: str) -> Callable[[AtomRecord], bool]:
    if name == "protein":
        return lambda atom: _kind_of(atom) == "protein"
    if name == "backbone":
        return _is_backbone
    if name == "ca":
        return lambda atom: _kind_of(atom) == "protein" and atom.name.strip().upper() == "CA"
    if name == "sidechain":
        return lambda atom: (
            _kind_of(atom) == "protein"
            and not _is_backbone(atom)
            and _element(atom) not in _HYDROGEN
        )
    if name == "ligand":
        return lambda atom: _kind_of(atom) == "ligand"
    if name == "water":
        return lambda atom: _kind_of(atom) == "water"
    if name == "ion":
        return lambda atom: _kind_of(atom) == "ion"
    if name == "heavy":
        return lambda atom: _element(atom) not in _HYDROGEN
    if name == "hydrogen":
        return lambda atom: _element(atom) in _HYDROGEN
    raise SelectionError(f"Unknown selection word {name!r}.", token=name)


def _qualifier(kind: str, value, atom: AtomRecord) -> bool:
    if kind == "chain":
        return atom.chain.strip().upper() == str(value).strip().upper()
    if kind == "resn":
        return atom.resname.strip().upper() == str(value).strip().upper()
    if kind == "name":
        return atom.name.strip().upper() == str(value).strip().upper()
    if kind == "element":
        return _element(atom) == str(value).strip().upper()
    if kind == "id":
        return atom.index == int(value)
    if kind == "resi":
        start, end = value
        return start <= atom.resi <= end
    return False


def _eval(node, atoms: list[AtomRecord]) -> set[int]:
    tag = node[0]
    if tag == "pred":
        pred = _predicate(node[1])
        return {atom.index for atom in atoms if pred(atom)}
    if tag == "qual":
        return {atom.index for atom in atoms if _qualifier(node[1], node[2], atom)}
    if tag == "not":
        matched = _eval(node[1], atoms)
        return {atom.index for atom in atoms if atom.index not in matched}
    if tag == "and":
        return _eval(node[1], atoms) & _eval(node[2], atoms)
    if tag == "or":
        return _eval(node[1], atoms) | _eval(node[2], atoms)
    if tag == "within":
        return _within(float(node[1]), _eval(node[2], atoms), atoms)
    raise SelectionError(f"Unknown selection expression {tag!r}.", token=str(tag))


def _within(radius: float, reference: set[int], atoms: list[AtomRecord]) -> set[int]:
    anchors = [(atom.x, atom.y, atom.z) for atom in atoms if atom.index in reference]
    if not anchors:
        return set()
    limit = radius * radius
    matched: set[int] = set()
    for atom in atoms:
        for x, y, z in anchors:
            dx = atom.x - x
            dy = atom.y - y
            dz = atom.z - z
            if dx * dx + dy * dy + dz * dz <= limit:
                matched.add(atom.index)
                break
    return matched
