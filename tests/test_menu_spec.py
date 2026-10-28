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

"""Qt-free tests for the declarative main-window menu tree."""

from __future__ import annotations

from pathlib import Path

from molmanager.ui.main_window.menu_spec import (
    HELP_MENU,
    MAIN_WINDOW_MENUS,
    find_submenu,
    menu_outline,
)

_MENU_SPEC = (
    Path(__file__).resolve().parents[1] / "molmanager" / "ui" / "main_window" / "menu_spec.py"
)


def test_menu_spec_source_does_not_import_qt():
    text = _MENU_SPEC.read_text(encoding="utf-8")
    assert "PyQt5" not in text
    assert "QtWidgets" not in text


def test_protein_menu_includes_simulation():
    protein = find_submenu(MAIN_WINDOW_MENUS, "Protein")
    labels = menu_outline(protein.items)
    assert "Simulation…" in labels
    simulation = next(item for item in protein.items if item.slot == "open_simulation")
    assert simulation.tooltip.startswith("Edit a simulation document")


def test_top_level_menu_order():
    labels = []
    for item in MAIN_WINDOW_MENUS:
        outline = menu_outline((item,))[0]
        if isinstance(outline, dict):
            labels.extend(outline.keys())
        else:
            labels.append(outline)
    assert labels == [
        "File",
        "Edit",
        "Tools",
        "Chemistry",
        "Protein",
        "Data",
        "Settings",
    ]


def test_file_menu_includes_open_recent():
    file_menu = find_submenu(MAIN_WINDOW_MENUS, "File")
    labels = menu_outline(file_menu.items)
    assert labels[0] == "Open File..."
    assert labels[1] == {"Open Recent": []}
    recent = find_submenu(file_menu.items, "Open Recent")
    assert recent.about_to_show == "_populate_recent_menu"
    assert recent.attr == "_recent_menu"
    assert recent.tooltips_visible is True


def test_file_session_submenu_outline():
    file_menu = find_submenu(MAIN_WINDOW_MENUS, "File")
    labels = menu_outline(file_menu.items)
    assert "Session" in [x if isinstance(x, str) else next(iter(x)) for x in labels]
    session = find_submenu(file_menu.items, "Session")
    assert menu_outline(session.items) == [
        "Open Session…",
        "Save Session…",
        "Save Selected to Session…",
        "New Session",
        "Duplicate Session",
        "Send Selected to New Session",
        "Close Session",
    ]


def test_edit_selection_actions_are_on_edit_menu():
    edit = find_submenu(MAIN_WINDOW_MENUS, "Edit")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(edit.items)]
    assert "Selection" not in labels
    assert "Find and Replace…" in labels
    assert labels[-3:] == ["Invert Selection", "Clear Selection", "Delete Selection"]


def test_conformations_menu_outline():
    tools = find_submenu(MAIN_WINDOW_MENUS, "Chemistry")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(tools.items)]
    assert "Generate Conformations" not in labels
    assert "Conformations" in labels
    assert not any(lbl.startswith("Superpose") for lbl in labels)
    conf = find_submenu(tools.items, "Conformations")
    assert menu_outline(conf.items) == [
        {"Generate": ["Stochastic…", "Systematic…", "CONFORGE…"]},
        "",
        "Superpose…",
        "Screen Pharmacophore…",
    ]


def test_prepare_is_one_chemistry_command():
    tools = find_submenu(MAIN_WINDOW_MENUS, "Chemistry")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(tools.items)]
    assert "Prepare…" in labels
    assert "Prepare Structures" not in labels
    assert "Fast Prepare…" not in labels
    predict = find_submenu(tools.items, "Predict")
    predict_labels = [
        x if isinstance(x, str) else next(iter(x)) for x in menu_outline(predict.items)
    ]
    assert "pKa…" in predict_labels
    assert "Align to Substructure…" in labels


def test_substructure_menu_sits_between_conformations_and_predict():
    tools = find_submenu(MAIN_WINDOW_MENUS, "Chemistry")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(tools.items)]
    assert "Fingerprints" not in labels
    assert "Similarity" not in labels
    assert labels.index("Substructure") == labels.index("Conformations") + 1
    assert labels.index("Substructure") + 1 == labels.index("Predict")
    sub = find_submenu(tools.items, "Substructure")
    assert menu_outline(sub.items) == [
        "Bemis–Murcko…",
        "Common Core…",
    ]


def test_reaction_menu_outline():
    tools = find_submenu(MAIN_WINDOW_MENUS, "Chemistry")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(tools.items)]
    assert "Reaction" not in labels
    assert "Extract Info…" not in labels
    assert "Reaction Based…" not in labels
    assert labels.index("Structure Decomposition") == labels.index("Predict") + 1
    assert labels.index("Structure Enumeration") == labels.index("Structure Decomposition") + 1
    assert labels.index("REINVENT") == labels.index("Structure Enumeration") + 1
    assert labels.index("Extract Reaction Info…") == labels.index("REINVENT") + 1
    reinvent = find_submenu(tools.items, "REINVENT")
    assert menu_outline(reinvent.items) == ["Sampling…", "Learning…"]
    assert labels.index("Retrosynthesis") == labels.index("Extract Reaction Info…") + 1
    retrosynthesis = find_submenu(tools.items, "Retrosynthesis")
    assert menu_outline(retrosynthesis.items) == ["Search…", "Routes…"]
    decomp = find_submenu(tools.items, "Structure Decomposition")
    assert menu_outline(decomp.items) == [
        "Core-Based…",
        "Most Central Ring…",
        "BRICS…",
        "RECAP…",
    ]
    central = next(item for item in decomp.items if item.title == "Most Central Ring…")
    assert central.slot == "open_central_ring_decomposition"
    enum = find_submenu(tools.items, "Structure Enumeration")
    assert menu_outline(enum.items) == [
        "R-Group…",
        "BRICS…",
        "RECAP…",
        "Reaction Based…",
    ]


def test_lists_menu_sits_under_data_below_table():
    labels = []
    for item in MAIN_WINDOW_MENUS:
        outline = menu_outline((item,))[0]
        labels.append(next(iter(outline)) if isinstance(outline, dict) else outline)
    assert "Lists" not in labels
    assert labels[labels.index("Data") + 1] == "Settings"
    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    data_labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(data.items)]
    assert data_labels.index("Lists") == data_labels.index("Table") + 1
    table = find_submenu(data.items, "Table")
    assert "Lists" not in [
        x if isinstance(x, str) else next(iter(x)) for x in menu_outline(table.items)
    ]
    lists = find_submenu(data.items, "Lists")
    assert lists.attr == "_lists_menu"
    assert lists.about_to_show == "_rebuild_lists_menu"
    add_to_list = next(item for item in lists.items if item.title == "Add Selected to List…")
    assert add_to_list.hotkey == "data.add_to_list"
    assert menu_outline(lists.items) == [
        "Add Selected to List…",
        "Remove Selected from List…",
        "",
        "Manage Lists…",
    ]


def test_help_menu_sits_inside_settings():
    labels = []
    for item in MAIN_WINDOW_MENUS:
        outline = menu_outline((item,))[0]
        labels.append(next(iter(outline)) if isinstance(outline, dict) else outline)
    assert labels[-1] == "Settings"
    assert "Help" not in labels
    assert menu_outline(HELP_MENU.items) == ["User Guide", "Citations"]
    assert HELP_MENU.attr == "_help_menu"


def test_similarity_menu_contains_cluster():
    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(data.items)]
    assert "Cluster…" not in labels
    assert "Binning…" not in labels
    similarity = find_submenu(data.items, "Similarity")
    assert menu_outline(similarity.items) == [
        "Fingerprint Similarity...",
        "Diverse Subset…",
        "Cluster…",
        "Binning…",
    ]
    fp = next(item for item in similarity.items if item.title == "Fingerprint Similarity...")
    assert fp.hotkey == "tools.fingerprint_similarity"
    cluster = next(item for item in similarity.items if item.title == "Cluster…")
    assert cluster.hotkey == "data.cluster"
    binning = next(item for item in similarity.items if item.title == "Binning…")
    assert binning.hotkey == "data.binning"


def test_selectivity_ratio_follows_sali():
    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(data.items)]
    assert labels.index("Selectivity Ratio…") == labels.index("SALI…") + 1
    item = next(
        entry for entry in data.items if getattr(entry, "title", "") == "Selectivity Ratio…"
    )
    assert item.slot == "open_selectivity_ratio_dialog"


def test_hansch_follows_free_wilson():
    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(data.items)]
    assert labels.index("Hansch…") == labels.index("Free-Wilson…") + 1
    assert labels.index("SAR Matrix…") == labels.index("Hansch…") + 1
    assert "Design Studio…" not in labels


def test_data_table_operations_submenu():
    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    table = find_submenu(data.items, "Table")
    assert menu_outline(table.items) == [
        {
            "Operations": [
                "Add Row…",
                "Add Column…",
                "",
                "Split Column…",
                "Join Columns…",
            ]
        },
        "Statistics…",
    ]


def test_tools_menu_expands_calculator_random_and_notepad():
    tools = find_submenu(MAIN_WINDOW_MENUS, "Tools")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(tools.items)]
    assert "Utilities" not in labels
    assert "Calculate Descriptors…" not in labels
    assert labels == [
        "Query Database",
        "",
        "Random",
        "Calculator…",
        "Macros…",
        "Potency Standardization…",
        "Notepad",
        "",
        "Sketcher…",
        "Design Studio…",
    ]
    random = find_submenu(tools.items, "Random")
    assert menu_outline(random.items) == ["Number…", "Molecule…"]


def test_query_database_menu_outline():
    tools = find_submenu(MAIN_WINDOW_MENUS, "Tools")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(tools.items)]
    assert "External" not in labels
    assert labels[0] == "Query Database"
    assert labels[1] == ""
    data_labels = [
        x if isinstance(x, str) else next(iter(x))
        for x in menu_outline(find_submenu(MAIN_WINDOW_MENUS, "Data").items)
    ]
    assert data_labels[-2:] == ["", "Browser…"]
    query = find_submenu(tools.items, "Query Database")
    assert menu_outline(query.items) == [
        "PubChem…",
        "ChEMBL…",
        "Vendors…",
        "Patents…",
        "",
        "SQL…",
    ]


def test_data_menu_filter_and_search_group_is_last():
    tools = find_submenu(MAIN_WINDOW_MENUS, "Tools")
    tools_labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(tools.items)]
    assert "Filter" not in tools_labels
    assert "Search…" not in tools_labels
    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(data.items)]
    assert labels[-5:] == ["", "Filter", "Search…", "", "Browser…"]
    filt = find_submenu(data.items, "Filter")
    assert menu_outline(filt.items)[0] == "Toggle Panel"


def test_data_menu_plot_submenu_titles():
    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(data.items)]
    assert "MedChem" not in labels
    assert "DimRed Plots" not in labels
    assert "MedChem Plots" in labels
    assert "Dimensionality Reduction" in labels
    assert "Plotter…" in labels
    assert labels.index("Dimensionality Reduction") == labels.index("MedChem Plots") + 1
    assert labels.index("Plotter…") == labels.index("Dimensionality Reduction") + 2
    assert labels[labels.index("Dimensionality Reduction") + 1] == ""
    medchem = find_submenu(data.items, "MedChem Plots")
    assert menu_outline(medchem.items) == [
        "BOILED-Egg…",
        "Golden Triangle…",
        "LipE…",
    ]
    dimred = find_submenu(data.items, "Dimensionality Reduction")
    assert menu_outline(dimred.items) == [
        "Principal Component Analysis…",
        "t-SNE Visualization…",
        "UMAP Visualization…",
        "Self-Organizing Map…",
    ]
