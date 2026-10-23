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

"""Tests for bundled Markdown user-manual topics."""

from __future__ import annotations

from molmanager.reference.help_markdown import (
    help_dir,
    load_help_markdown,
    markdown_to_html_fragment,
    missing_topic_html,
)
from molmanager.ui.user_guides import (
    GUIDE_MENU,
    GUIDE_SECTIONS,
    guide_entry,
    guide_html,
    iter_guide_entries,
    open_user_guide_dialog,
)


def test_every_guide_id_has_markdown_file():
    ids = [e.guide_id for e in iter_guide_entries()]
    assert ids
    missing = [gid for gid in ids if load_help_markdown(gid) is None]
    assert missing == [], f"Missing help Markdown for: {missing}"
    on_disk = {p.stem for p in help_dir().glob("*.md")}
    assert on_disk == set(ids)


def test_guide_sections_cover_menu():
    flat = list(iter_guide_entries())
    assert len(flat) == len(GUIDE_MENU)
    assert {e.guide_id for e in flat} == {gid for gid, _ in GUIDE_MENU}
    assert sum(len(s.entries) for s in GUIDE_SECTIONS) == len(flat)


def test_guide_html_renders_required_headings():
    h = guide_html("tools_filter")
    assert "Topic unavailable" not in h
    assert "Filters" in h
    assert "Goal" in h
    assert "Options" in h
    assert "Use cases" in h
    assert "<h1>" in h or "<h2>" in h


def test_guide_html_pubchem_and_smina():
    pub = guide_html("ext_pubchem")
    assert "PubChem" in pub and "Topic unavailable" not in pub
    smina = guide_html("tools_gnina")
    assert "Gnina" in smina and "PDBQT" in smina
    mets = guide_html("tools_predict_metabolites")
    assert "BioTransformer" in mets and "Topic unavailable" not in mets


def test_markdown_renderer_basics():
    frag = markdown_to_html_fragment(
        "# Title\n\nParagraph with **bold** and `code`.\n\n"
        "- Item one\n- Item two\n\n"
        "> Tip text\n\n"
        "1. Step\n"
    )
    assert "<h1>" in frag and "<b>bold</b>" in frag and "<code>code</code>" in frag
    assert "<ul>" in frag and "<ol>" in frag and 'class="tip"' in frag


def test_missing_topic_html():
    body = missing_topic_html("no_such_topic")
    assert "no_such_topic" in body
    assert "unavailable" in body.lower()
    h = guide_html("no_such_topic_zzz")
    assert "Topic unavailable" in h


def test_open_user_guide_dialog_by_id(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    host = QWidget()
    open_user_guide_dialog(host, guide_id="tools_gnina")
    dlg = host._user_guide_dialog
    assert dlg is not None
    assert "Gnina" in dlg.windowTitle()
    entry = guide_entry("tools_gnina")
    assert entry is not None
    # Reopen with another topic reuses the same dialog.
    open_user_guide_dialog(host, guide_id="overview")
    assert host._user_guide_dialog is dlg
    assert "Overview" in dlg.windowTitle()
    dlg.close()


def test_user_guide_dialog_does_not_cycle_with_its_host(qapp):  # noqa: ARG001
    """See the same guard in test_citations_catalog: a cycle here crashes Qt on collect."""
    import weakref

    from PyQt5.QtWidgets import QWidget

    host = QWidget()
    open_user_guide_dialog(host, guide_id="overview")
    host._user_guide_dialog.close()
    host_ref = weakref.ref(host)
    del host
    assert host_ref() is None
