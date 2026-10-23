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

"""Drop a single eligible file onto an empty window to open it."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QMimeData, QPoint, Qt, QUrl
from PyQt5.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent

from molmanager.ui.file_drop import file_drop_kind
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.strings import LOADING_DETAIL_DROP, LOADING_DETAIL_IDLE


def test_file_drop_kind_matches_open_and_session() -> None:
    assert file_drop_kind("sets/approved.sdf") == "file"
    assert file_drop_kind("sets/approved.SDF.GZ") == "file"
    assert file_drop_kind("notes.txt") == "file"
    assert file_drop_kind("rxn/amide.rxn") == "file"
    assert file_drop_kind("work/session.cms") == "session"
    assert file_drop_kind("work/session.CMS") == "session"
    assert file_drop_kind("notes.gz") is None
    assert file_drop_kind("picture.png") is None
    assert file_drop_kind("backup.cms.bak") is None


def _mime(*paths: str) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
    return mime


def _enter(mime: QMimeData) -> QDragEnterEvent:
    return QDragEnterEvent(QPoint(1, 1), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)


def _move(mime: QMimeData) -> QDragMoveEvent:
    return QDragMoveEvent(QPoint(2, 2), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)


def _drop(mime: QMimeData) -> QDropEvent:
    return QDropEvent(QPoint(3, 3), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)


def _drop_target(widget):
    """Nearest ancestor Qt would hand a file drop, matching ``findDnDTarget``."""
    while widget is not None and not widget.isWindow() and not widget.acceptDrops():
        widget = widget.parentWidget()
    if widget is None or not widget.acceptDrops():
        return None
    return widget


def test_idle_cover_and_menu_bar_are_drop_targets(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    assert _drop_target(window._loading_detail) is window._loading_page
    assert window._loading_page.acceptDrops()
    assert _drop_target(window.menuBar()) is window


def test_idle_page_drop_opens_a_table_file(qapp, tmp_path: Path, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    path = tmp_path / "sample.sdf"
    path.write_text("sdf", encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(window, "load_file", opened.append)
    page = window._loading_page
    mime = _mime(str(path))

    enter = _enter(mime)
    page.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert enter.dropAction() == Qt.CopyAction
    assert window._loading_detail.text() == LOADING_DETAIL_DROP
    assert "dashed" in page.styleSheet()

    move = _move(mime)
    page.dragMoveEvent(move)
    assert move.isAccepted()

    drop = _drop(mime)
    page.dropEvent(drop)
    assert drop.isAccepted()
    assert opened == [str(path)]
    assert window._loading_detail.text() == LOADING_DETAIL_IDLE
    assert page.styleSheet() == ""


def test_idle_window_drop_opens_a_session(qapp, tmp_path: Path, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    path = tmp_path / "session.cms"
    path.write_bytes(b"")
    opened: list[str] = []
    monkeypatch.setattr(window, "apply_saved_session_from_file", opened.append)
    monkeypatch.setattr(window, "load_file", lambda _path: opened.append("file"))

    mime = _mime(str(path))
    drop = _drop(mime)
    window.dropEvent(drop)

    assert drop.isAccepted()
    assert opened == [str(path)]


def test_drag_leave_restores_the_idle_message(qapp, tmp_path: Path):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    path = tmp_path / "sample.csv"
    path.write_text("smiles\nCCO\n", encoding="utf-8")
    page = window._loading_page
    mime = _mime(str(path))
    page.dragEnterEvent(_enter(mime))
    page.dragLeaveEvent(QDragLeaveEvent())
    assert window._loading_detail.text() == LOADING_DETAIL_IDLE
    assert page.styleSheet() == ""


def test_occupied_window_ignores_a_file_drop(qapp, tmp_path: Path, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    window.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(0, {"SMILES": "CCO"})
    window._reveal_workspace_ready()
    path = tmp_path / "sample.sdf"
    path.write_text("sdf", encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(window, "load_file", opened.append)

    mime = _mime(str(path))
    enter = _enter(mime)
    window.dragEnterEvent(enter)
    drop = _drop(mime)
    window.dropEvent(drop)

    assert not enter.isAccepted()
    assert not drop.isAccepted()
    assert opened == []
    assert window._loading_detail.text() == LOADING_DETAIL_IDLE


def test_loading_window_ignores_a_file_drop(qapp, tmp_path: Path, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    window._ingest_loading = True
    path = tmp_path / "sample.smi"
    path.write_text("CCO\n", encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(window, "load_file", opened.append)

    mime = _mime(str(path))
    drop = _drop(mime)
    window._loading_page.dropEvent(drop)

    assert not drop.isAccepted()
    assert opened == []


def test_drop_rejects_ineligible_payloads(qapp, tmp_path: Path, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    first = tmp_path / "a.sdf"
    second = tmp_path / "b.sdf"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    folder = tmp_path / "folder.sdf"
    folder.mkdir()
    other = tmp_path / "picture.png"
    other.write_bytes(b"")
    opened: list[str] = []
    monkeypatch.setattr(window, "load_file", opened.append)
    page = window._loading_page

    payloads = (
        _mime(str(first), str(second)),
        _mime(str(folder)),
        _mime(str(other)),
    )
    for mime in payloads:
        enter = _enter(mime)
        page.dragEnterEvent(enter)
        drop = _drop(mime)
        page.dropEvent(drop)
        assert not enter.isAccepted()
        assert not drop.isAccepted()

    remote = QMimeData()
    remote.setUrls([QUrl("https://example.com/a.sdf")])
    drop = _drop(remote)
    page.dropEvent(drop)
    assert not drop.isAccepted()
    assert opened == []
    assert window._loading_detail.text() == LOADING_DETAIL_IDLE
