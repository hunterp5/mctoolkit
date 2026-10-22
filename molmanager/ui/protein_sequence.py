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

"""Editable protein sequence window linked to the Protein Viewer 3D canvas."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeyEvent, QTextCursor, QTextOption
from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..protein.structure_components import (
    AA_ONE_TO_THREE,
    VALID_SEQUENCE_LETTERS,
    PolymerChain,
    PolymerResidue,
    diff_sequence_edit,
    letter_to_resn,
)
from .qt_widget_utils import make_window_resizable, monospace_text_font

# Canonical mutate targets (skip ambiguous B/Z/X codes).
_MUTATE_AMINO_ACIDS = tuple(
    (letter, resn) for letter, resn in AA_ONE_TO_THREE.items() if letter not in {"B", "Z", "X"}
)


class _ChainSequenceEdit(QPlainTextEdit):
    """One-letter sequence display; right-click Mutate, Delete removes residues."""

    sequence_committed = pyqtSignal(str)
    residue_range_changed = pyqtSignal(int, int)
    focus_requested = pyqtSignal()
    mutate_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAnywhere)
        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.setUndoRedoEnabled(False)
        font = QFont(monospace_text_font())
        font.setPointSize(max(12, font.pointSize() + 2))
        self.setFont(font)
        self.setTabChangesFocus(True)
        self._applying = False
        self._chain_sequence = ""
        self.viewport().setContextMenuPolicy(Qt.CustomContextMenu)
        self.viewport().customContextMenuRequested.connect(self._on_context_menu)
        self.selectionChanged.connect(self._on_selection_changed)
        self.cursorPositionChanged.connect(self._on_selection_changed)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        n = len(self.toPlainText())
        if n == 0:
            super().mouseDoubleClickEvent(event)
            return
        pos = self.cursorForPosition(event.pos()).position()
        pos = max(0, min(pos, n - 1))
        cursor = self.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + 1, QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.focus_requested.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._emit_delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def _emit_delete_selected(self) -> None:
        start, end = self.selected_span()
        seq = self._chain_sequence
        if not seq or start >= end:
            return
        start = max(0, min(start, len(seq)))
        end = max(start, min(end, len(seq)))
        if start >= end:
            return
        self.sequence_committed.emit(seq[:start] + seq[end:])

    def _select_clicked_residue(self, pos) -> None:
        n = len(self.toPlainText())
        if n == 0:
            return
        click_pos = self.cursorForPosition(pos).position()
        click_pos = max(0, min(click_pos, n - 1))
        start, end = self.selected_span()
        if start <= click_pos < end:
            return
        cursor = self.textCursor()
        cursor.setPosition(click_pos)
        cursor.setPosition(click_pos + 1, QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)

    def selection_can_mutate(self) -> bool:
        seq = self.toPlainText()
        start, end = self.selected_span()
        for i in range(start, min(end, len(seq))):
            ch = seq[i]
            if ch.isupper() and ch in VALID_SEQUENCE_LETTERS:
                return True
        return False

    def _make_context_menu(self) -> QMenu:
        menu = QMenu(self)
        mutate_menu = menu.addMenu("&Mutate")
        can_mutate = self.selection_can_mutate()
        mutate_menu.setEnabled(can_mutate)
        for letter, resn in _MUTATE_AMINO_ACIDS:
            act = mutate_menu.addAction(f"{letter}  {resn}")
            act.setEnabled(can_mutate)
            act.triggered.connect(
                lambda _checked=False, code=letter: self.mutate_requested.emit(code)
            )
        return menu

    def _on_context_menu(self, pos) -> None:
        if not self.toPlainText():
            return
        self._select_clicked_residue(pos)
        menu = self._make_context_menu()
        menu.exec_(self.viewport().mapToGlobal(pos))

    def set_sequence(self, sequence: str, *, select_start: int = -1, select_end: int = -1) -> None:
        self._applying = True
        self._chain_sequence = sequence or ""
        self.setPlainText(self._chain_sequence)
        if 0 <= select_start <= len(self._chain_sequence):
            cursor = self.textCursor()
            end = select_end if select_end >= select_start else select_start + 1
            end = min(max(end, select_start), len(self._chain_sequence))
            cursor.setPosition(select_start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
        self._applying = False

    def selected_span(self) -> tuple[int, int]:
        cursor = self.textCursor()
        start = min(cursor.selectionStart(), cursor.selectionEnd())
        end = max(cursor.selectionStart(), cursor.selectionEnd())
        n = len(self.toPlainText())
        if start == end:
            pos = max(0, min(cursor.position(), n))
            if n == 0:
                return (0, 0)
            if pos >= n:
                pos = n - 1
            return (pos, pos + 1)
        return (start, end)

    def _on_selection_changed(self) -> None:
        if self._applying:
            return
        start, end = self.selected_span()
        self.residue_range_changed.emit(start, end)


class ProteinSequenceDialog(QDialog):
    """Modeless sequence viewer/editor for polymer chains in the Protein Viewer."""

    residue_selection_changed = pyqtSignal(list)
    residues_mutated = pyqtSignal(list)
    residues_deleted = pyqtSignal(list)
    focus_residues_requested = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sequence")
        self.resize(640, 280)
        make_window_resizable(self)
        self._chains: list[PolymerChain] = []
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        self.hint = QLabel(
            "Letters are amino acids; lowercase letters are missing from the coordinates "
            "(SEQRES / mmCIF gaps). + ligand/cofactor, * metal, ~ water. "
            "Select characters to highlight them in 3D. Right-click a residue letter to mutate it. "
            "Delete removes residues."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(mid);")
        root.addWidget(self.hint)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self.status = QLabel("No polymer sequence loaded.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def chains(self) -> list[PolymerChain]:
        return list(self._chains)

    def set_chains(self, chains: list[PolymerChain] | tuple[PolymerChain, ...]) -> None:
        current = self.tabs.currentIndex()
        self._chains = [
            PolymerChain(
                chain=c.chain,
                residues=list(c.residues),
                structure_id=c.structure_id,
                structure_name=c.structure_name,
            )
            for c in chains
        ]
        self._syncing = True
        self.tabs.clear()
        if not self._chains:
            self.status.setText("No residues in the current structure.")
            self._syncing = False
            self.residue_selection_changed.emit([])
            return
        for poly in self._chains:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 4, 0, 0)
            caption = QLabel(self._chain_caption(poly))
            layout.addWidget(caption)
            editor = _ChainSequenceEdit()
            editor.set_sequence(poly.sequence)
            editor.residue_range_changed.connect(self._on_editor_range)
            editor.sequence_committed.connect(self._on_editor_committed)
            editor.mutate_requested.connect(self._on_mutate_requested)
            editor.focus_requested.connect(self._on_focus_requested)
            layout.addWidget(editor, 1)
            tab = (
                f"{poly.structure_name} · {poly.chain}"
                if poly.structure_name
                else f"Chain {poly.chain}"
            )
            self.tabs.addTab(page, tab)
        if 0 <= current < self.tabs.count():
            self.tabs.setCurrentIndex(current)
        self._syncing = False
        self._emit_current_selection()

    def _on_focus_requested(self) -> None:
        sels = self.selected_residue_selections()
        if sels:
            self.focus_residues_requested.emit(sels)

    def _chain_caption(self, poly: PolymerChain) -> str:
        n = len(poly.residues)
        if not poly.residues:
            return f"Chain {poly.chain} · 0 residues"
        n_aa = sum(1 for res in poly.residues if res.kind == "polymer")
        n_miss = sum(1 for res in poly.residues if res.kind == "missing")
        n_lig = sum(1 for res in poly.residues if res.kind == "ligand")
        n_met = sum(1 for res in poly.residues if res.kind == "metal")
        n_wat = sum(1 for res in poly.residues if res.kind == "water")
        parts = [f"{n} residue{'s' if n != 1 else ''}"]
        if n_aa:
            parts.append(f"{n_aa} aa")
        if n_miss:
            parts.append(f"{n_miss} missing")
        if n_lig:
            parts.append(f"{n_lig} ligand{'s' if n_lig != 1 else ''}")
        if n_met:
            parts.append(f"{n_met} metal{'s' if n_met != 1 else ''}")
        if n_wat:
            parts.append(f"{n_wat} water{'s' if n_wat != 1 else ''}")
        first = poly.residues[0]
        last = poly.residues[-1]
        base = (
            f"Chain {poly.chain} · {' · '.join(parts)} · "
            f"{first.resn} {first.resi}{first.icode} – {last.resn} {last.resi}{last.icode}"
        )
        if poly.structure_name:
            return f"{poly.structure_name} · {base}"
        return base

    def _editor_at(self, index: int) -> _ChainSequenceEdit | None:
        page = self.tabs.widget(index)
        if page is None:
            return None
        return page.findChild(_ChainSequenceEdit)

    def _current_chain(self) -> PolymerChain | None:
        idx = self.tabs.currentIndex()
        if 0 <= idx < len(self._chains):
            return self._chains[idx]
        return None

    def selected_residues(self) -> list[PolymerResidue]:
        poly = self._current_chain()
        editor = self._editor_at(self.tabs.currentIndex())
        if poly is None or editor is None or not poly.residues:
            return []
        start, end = editor.selected_span()
        start = max(0, min(start, len(poly.residues)))
        end = max(start, min(end, len(poly.residues)))
        return poly.residues[start:end]

    def selected_residue_selections(self) -> list[dict]:
        return [
            {
                **res.selection(),
                "structure_id": res.structure_id,
                "kind": res.kind,
                "resn": res.resn,
            }
            for res in self.selected_residues()
            if res.kind != "missing"
        ]

    def select_residue(
        self,
        chain: str,
        resi: str | int | None,
        icode: str = "",
        structure_id: str = "",
    ) -> None:
        resi_s = str(resi).strip() if resi is not None else ""
        icode_s = (icode or "").strip()
        for i, poly in enumerate(self._chains):
            if poly.chain != chain:
                continue
            if structure_id and poly.structure_id and poly.structure_id != structure_id:
                continue
            for j, res in enumerate(poly.residues):
                if res.resi != resi_s or (res.icode or "") != icode_s:
                    continue
                self._syncing = True
                self.tabs.setCurrentIndex(i)
                editor = self._editor_at(i)
                if editor is not None:
                    editor.set_sequence(poly.sequence, select_start=j, select_end=j + 1)
                self._syncing = False
                self._update_status(poly, j, j + 1)
                self.residue_selection_changed.emit(
                    []
                    if res.kind == "missing"
                    else [
                        {
                            **res.selection(),
                            "structure_id": res.structure_id,
                            "kind": res.kind,
                            "resn": res.resn,
                        }
                    ]
                )
                return

    def _on_tab_changed(self, _index: int) -> None:
        if self._syncing:
            return
        self._emit_current_selection()

    def _on_editor_range(self, start: int, end: int) -> None:
        if self._syncing:
            return
        poly = self._current_chain()
        if poly is None:
            return
        self._update_status(poly, start, end)
        self.residue_selection_changed.emit(self.selected_residue_selections())

    def _on_mutate_requested(self, letter: str) -> None:
        code = (letter or "").strip().upper()
        if letter_to_resn(code) is None:
            return
        poly = self._current_chain()
        editor = self._editor_at(self.tabs.currentIndex())
        if poly is None or editor is None:
            return
        start, end = editor.selected_span()
        seq = list(poly.sequence)
        changed = False
        for i in range(start, min(end, len(seq))):
            ch = seq[i]
            if ch.isupper() and ch in VALID_SEQUENCE_LETTERS:
                seq[i] = code
                changed = True
        if not changed:
            self.status.setText("Right-click an observed amino-acid letter to mutate it.")
            return
        self._on_editor_committed("".join(seq))

    def _on_editor_committed(self, new_seq: str) -> None:
        if self._syncing:
            return
        idx = self.tabs.currentIndex()
        if not (0 <= idx < len(self._chains)):
            return
        poly = self._chains[idx]
        old = poly.sequence
        edit = diff_sequence_edit(old, new_seq)
        editor = self._editor_at(idx)
        if edit.invalid_letter or edit.rejected_insert:
            if editor is not None:
                cursor = editor.textCursor().position()
                editor.set_sequence(old)
                pos = min(cursor, len(old))
                cur = editor.textCursor()
                cur.setPosition(pos)
                editor.setTextCursor(cur)
            if edit.invalid_letter:
                self.status.setText(
                    "Use amino-acid 1-letter codes, or keep + (ligand), * (metal), ~ (water)."
                )
            else:
                self.status.setText(
                    "Inserting amino acids is not supported (no coordinates to place them)."
                )
            return
        if not edit.mutations and not edit.deletions:
            if editor is not None:
                editor._chain_sequence = new_seq
            return
        mutated: list[tuple[PolymerResidue, str]] = []
        for pos, letter in edit.mutations:
            if letter_to_resn(letter) is None:
                if editor is not None:
                    cursor = editor.textCursor().position()
                    editor.set_sequence(old)
                    pos_c = min(cursor, len(old))
                    cur = editor.textCursor()
                    cur.setPosition(pos_c)
                    editor.setTextCursor(cur)
                self.status.setText("Mutations must use amino-acid 1-letter codes (A, C, D, …).")
                return
            if 0 <= pos < len(poly.residues):
                target = poly.residues[pos]
                if target.kind == "missing":
                    continue
                mutated.append((target, letter))
        deleted = [poly.residues[i] for i in edit.deletions if 0 <= i < len(poly.residues)]
        residues = list(poly.residues)
        for pos, letter in sorted(edit.mutations, reverse=True):
            if not (0 <= pos < len(residues)):
                continue
            if residues[pos].kind == "missing":
                continue
            resn = letter_to_resn(letter)
            if not resn:
                continue
            residues[pos] = PolymerResidue(
                chain=residues[pos].chain,
                resn=resn,
                resi=residues[pos].resi,
                icode=residues[pos].icode,
                letter=letter,
                kind=residues[pos].kind,
                structure_id=residues[pos].structure_id,
                model=residues[pos].model,
            )
        for pos in sorted(edit.deletions, reverse=True):
            if 0 <= pos < len(residues):
                del residues[pos]
        poly.residues = residues
        if editor is not None:
            editor._chain_sequence = poly.sequence
            page = self.tabs.widget(idx)
            caption = page.findChild(QLabel) if page is not None else None
            if caption is not None:
                caption.setText(self._chain_caption(poly))
        if mutated:
            self.residues_mutated.emit(mutated)
        coord_deleted = [res for res in deleted if res.kind != "missing"]
        if coord_deleted:
            self.residues_deleted.emit(coord_deleted)
        self._emit_current_selection()

    def _emit_current_selection(self) -> None:
        poly = self._current_chain()
        editor = self._editor_at(self.tabs.currentIndex())
        if poly is None or editor is None:
            self.status.setText("No sequence loaded.")
            self.residue_selection_changed.emit([])
            return
        start, end = editor.selected_span()
        self._update_status(poly, start, end)
        self.residue_selection_changed.emit(self.selected_residue_selections())

    def _update_status(self, poly: PolymerChain, start: int, end: int) -> None:
        if not poly.residues:
            self.status.setText(f"Chain {poly.chain} is empty.")
            return
        start = max(0, min(start, len(poly.residues) - 1))
        end = max(start + 1, min(end, len(poly.residues)))
        first = poly.residues[start]
        if end - start == 1:
            self.status.setText(
                f"{first.letter}  {first.resn} {poly.chain} {first.resi}{first.icode}"
            )
            return
        last = poly.residues[end - 1]
        self.status.setText(
            f"{end - start} residues  {first.resn} {first.resi}{first.icode} – "
            f"{last.resn} {last.resi}{last.icode}  (chain {poly.chain})"
        )
