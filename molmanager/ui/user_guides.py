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

"""In-app User Manual for MolManager (TOC + Markdown topic loader)."""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
)

from ..reference.help_markdown import (
    load_help_markdown,
    markdown_to_html_fragment,
    missing_topic_html,
)
from .qt_widget_utils import make_window_minimizable

if TYPE_CHECKING:
    from PyQt5.QtWidgets import QWidget


@dataclass(frozen=True)
class GuideEntry:
    """One help topic: stable id, short label, sidebar label, and tooltip."""

    guide_id: str
    menu_label: str
    list_label: str
    blurb: str


@dataclass(frozen=True)
class GuideSection:
    """A group of related help topics shown in the sidebar."""

    title: str
    entries: tuple[GuideEntry, ...]


def _e(guide_id: str, menu_label: str, list_label: str, blurb: str) -> GuideEntry:
    return GuideEntry(guide_id, menu_label, list_label, blurb)


GUIDE_SECTIONS: tuple[GuideSection, ...] = (
    GuideSection(
        "1 — Start here",
        (
            _e(
                "overview",
                "Overview",
                "Overview",
                "What MolManager is and how the main window is organized.",
            ),
            _e(
                "processes",
                "Log",
                "Log",
                "Running and queued background jobs, plus the session log.",
            ),
            _e(
                "log",
                "Log (transcript)",
                "Log",
                "Session-wide tool output, status history, and application logging in Log.",
            ),
            _e(
                "settings",
                "Settings",
                "Settings",
                "Theme, fonts, status bar, keyboard shortcuts, WSL, and Help.",
            ),
        ),
    ),
    GuideSection(
        "2 — File and sessions",
        (
            _e(
                "file_open",
                "Open File",
                "Open File",
                "Load SDF, MOL, SMILES, CSV, RXN, and related formats.",
            ),
            _e(
                "file_import",
                "Import Data",
                "Import Data",
                "Append or merge data into the current table.",
            ),
            _e(
                "file_sessions",
                "Sessions",
                "Sessions",
                "Open, save, save selected rows, create, duplicate, and close sessions.",
            ),
            _e(
                "file_export",
                "Save File",
                "Save File",
                "Save all or selected rows to common formats.",
            ),
            _e(
                "file_browser",
                "Selection Browser",
                "Selection Browser",
                "Browse selected (or all) table rows with RDKit 2D, 3Dmol 2D, or 3Dmol 3D "
                "structure preview and a compact row table.",
            ),
        ),
    ),
    GuideSection(
        "3 — Edit and table",
        (
            _e("edit_menu", "Edit", "Edit", "Undo/redo, clipboard, and selection commands."),
            _e("table", "Table", "Table", "Columns, sorting, context menus, and precision."),
            _e(
                "tools_filter",
                "Filters",
                "Filters",
                "Filter panel cards, titles, reorder, and enable/disable.",
            ),
            _e("tools_search", "Search", "Search", "Multi-column search with AND/OR criteria."),
        ),
    ),
    GuideSection(
        "4 — Prepare and structures",
        (
            _e(
                "tools_calc_descriptors",
                "Calculate Descriptors",
                "Calculate Descriptors",
                "RDKit descriptors, structural alerts, and 3D shape when confs exist.",
            ),
            _e(
                "tools_fast_prepare",
                "Fast Prepare",
                "Fast Prepare",
                "Largest fragment, optional neutralize, and redraw in one job.",
            ),
            _e(
                "tools_disconnect_fragments",
                "Disconnect Fragments",
                "Disconnect Fragments",
                "Split disconnected components into rows.",
            ),
            _e(
                "tools_add_explicit_h",
                "Explicit Hydrogens — Add",
                "Add Explicit Hydrogens",
                "Chemistry → Prepare Structures → Explicit Hydrogens → Add.",
            ),
            _e(
                "tools_remove_explicit_h",
                "Explicit Hydrogens — Remove",
                "Remove Explicit Hydrogens",
                "Chemistry → Prepare Structures → Explicit Hydrogens → Remove.",
            ),
            _e(
                "tools_render_2d",
                "Render 2D",
                "Render 2D",
                "Regenerate 2D depictions as a background batch.",
            ),
            _e(
                "tools_protonate",
                "Protonate",
                "Protonate",
                "Dominant protomer at a chosen pH (Chemistry → Prepare Structures → Protonate).",
            ),
            _e(
                "tools_generate_protomers",
                "Generate Protomers",
                "Generate Protomers",
                "Enumerate protomers/tautomers (Chemistry → Prepare Structures → Protonate).",
            ),
            _e(
                "tools_neutralize",
                "Neutralize",
                "Neutralize",
                "Zero net formal charge (Chemistry → Prepare Structures → Protonate → Neutralize).",
            ),
            _e(
                "tools_calculator",
                "Calculator",
                "Calculator",
                "New numeric column from a math expression.",
            ),
            _e(
                "tools_potency",
                "Potency Standardization",
                "Potency Standardization",
                "Convert mixed activity units, including mg/mL via molecular weight, to nM or uM.",
            ),
            _e(
                "tools_sketcher",
                "Sketcher",
                "Sketcher",
                "Draw molecules and reactions interactively.",
            ),
            _e(
                "tools_gen_conformations",
                "Generate Conformations",
                "Generate Conformations",
                "Build 3D conformer ensembles (Chemistry → Conformations → Generate → Stochastic).",
            ),
            _e(
                "tools_gen_conformations_systematic",
                "Systematic Conformations",
                "Systematic Conformations",
                "Build 3D ensembles (Chemistry → Conformations → Generate → Systematic).",
            ),
            _e(
                "tools_gen_conformations_conforge",
                "CONFORGE Conformations",
                "CONFORGE Conformations",
                "Build 3D ensembles (Chemistry → Conformations → Generate → CONFORGE).",
            ),
            _e(
                "tools_superpose",
                "Superpose",
                "Superpose",
                "Align conformers or structures (Chemistry → Conformations → Superpose).",
            ),
            _e(
                "tools_pharmacophore_screen",
                "Screen Pharmacophore",
                "Screen Pharmacophore",
                "Match packed conformation ensembles to a 3D pharmacophore JSON.",
            ),
        ),
    ),
    GuideSection(
        "5 — Substructure",
        (
            _e(
                "tools_bemis_murcko",
                "Bemis–Murcko",
                "Bemis–Murcko",
                "Scaffold, framework, ring systems, and scaffold count.",
            ),
            _e(
                "tools_common_core",
                "Common Core",
                "Common Core",
                "Maximum common substructure over the chosen rows.",
            ),
        ),
    ),
    GuideSection(
        "6 — Fingerprints",
        (
            _e(
                "tools_fp_similarity",
                "Fingerprint Similarity",
                "Fingerprint Similarity",
                "Similarity scores vs a query molecule.",
            ),
            _e(
                "tools_diverse_subset",
                "Diverse Subset",
                "Diverse Subset",
                "Pick a chemically diverse subset of rows.",
            ),
        ),
    ),
    GuideSection(
        "7 — Dock Ligand",
        (
            _e(
                "tools_prepare_pdb",
                "Prepare PDB",
                "Prepare PDB",
                "Clean and complete protein PDB files.",
            ),
            _e(
                "tools_prepare_pdbqt",
                "Prepare PDBQT",
                "Prepare PDBQT",
                "Build receptor/ligand PDBQT (SDF, PDB, SMILES, or table rows).",
            ),
            _e(
                "tools_gnina",
                "Gnina",
                "Gnina",
                "Run Gnina from a ligand file or selected table rows (CNN scoring).",
            ),
        ),
    ),
    GuideSection(
        "8 — Protein",
        (
            _e(
                "protein_viewer",
                "Protein Viewer",
                "Protein Viewer",
                "Load PDB/mmCIF structures, manage chains in 3D, prepare docking-ready receptors, and minimize complexes.",
            ),
            _e(
                "protein_pharmacophore",
                "Pharmacophore",
                "Pharmacophore",
                "Build 3D pharmacophore features in Protein Viewer and apply them in Gnina.",
            ),
            _e(
                "protein_sequence",
                "Protein Sequence",
                "Protein Sequence",
                "Align FASTA or Viewer polymer chains with a local MAFFT install.",
            ),
        ),
    ),
    GuideSection(
        "9 — Design and modeling",
        (
            _e(
                "tools_rgroup",
                "R-Group Decomposition",
                "R-Group Decomposition",
                "Match a core and extract R-group columns.",
            ),
            _e(
                "tools_rgroup_enum",
                "R-Group Enumeration",
                "R-Group Enumeration",
                "Attach building-block lists to a numbered core and append the products.",
            ),
            _e(
                "tools_activity_cliff",
                "MMP Activity Cliffs",
                "Activity Cliffs",
                "Cliff scatter from Transform Ledger pairs.",
            ),
            _e(
                "tools_mmp_neighborhood",
                "MMP Pair Network",
                "Pair Network",
                "Neighborhood graph from Transform Ledger pairs.",
            ),
            _e(
                "tools_reaction_extract",
                "Extract",
                "Reaction Extract",
                "Split reaction SMARTS into reactant and product columns.",
            ),
            _e(
                "tools_reaction_enum",
                "Reaction Enumeration",
                "Reaction Enumeration",
                "Enumerate products from reaction SMARTS.",
            ),
            _e(
                "tools_predict_som",
                "Predict SOM",
                "SOM",
                "FAME3R sites of metabolism; reopen maps from Predict → SOM → Viewer.",
            ),
            _e(
                "tools_predict_metabolites",
                "Predict Metabolites",
                "Metabolites",
                "BioTransformer metabolite structures; reopen from Predict → Metabolites → Viewer.",
            ),
            _e(
                "tools_pka",
                "Predict pKa",
                "pKa",
                "Uni-pKa macro pKa values from a structure column or SMILES.",
            ),
            _e("data_qsar", "QSAR", "QSAR", "Train and apply QSAR models on table features."),
            _e(
                "data_free_wilson",
                "Free-Wilson",
                "Free-Wilson",
                "Additive substituent contributions and predicted missing analogs.",
            ),
            _e("data_mpo", "MPO Scoring", "MPO Scoring", "Multi-parameter desirability scores."),
        ),
    ),
    GuideSection(
        "10 — Random",
        (
            _e(
                "tools_random_number",
                "Random Number",
                "Random Number",
                "Fill a column with random numbers.",
            ),
            _e(
                "tools_random_molecule",
                "Random Molecule",
                "Random Molecule",
                "Fetch random molecules from ChEMBL, PubChem, or ZINC.",
            ),
        ),
    ),
    GuideSection(
        "11 — Charts and analysis",
        (
            _e(
                "data_analyze_table",
                "Statistics",
                "Statistics",
                "Summary statistics for table columns.",
            ),
            _e(
                "data_split_column",
                "Split Column",
                "Split Column",
                "Split a delimited column into new columns.",
            ),
            _e(
                "data_join_columns",
                "Join Columns",
                "Join Columns",
                "Join two columns with a delimiter into a new column.",
            ),
            _e(
                "tools_cluster",
                "Cluster",
                "Cluster",
                "Data → Cluster. Group rows by fingerprint, numeric columns, or both.",
            ),
            _e(
                "data_pca",
                "PCA",
                "PCA",
                "Data → DimRed Plots → Principal Component Analysis.",
            ),
            _e(
                "data_tsne",
                "t-SNE",
                "t-SNE",
                "Data → DimRed Plots → t-SNE Visualization.",
            ),
            _e(
                "data_umap",
                "UMAP",
                "UMAP",
                "Data → DimRed Plots → UMAP Visualization.",
            ),
            _e(
                "data_som",
                "SOM",
                "Self-Organizing Map",
                "Data → DimRed Plots → Self-Organizing Map.",
            ),
            _e(
                "data_boiled_egg",
                "BOILED-Egg",
                "BOILED-Egg",
                "Data → MedChem Plots → BOILED-Egg plot.",
            ),
            _e(
                "data_golden_triangle",
                "Golden Triangle",
                "Golden Triangle",
                "Data → MedChem Plots → Golden Triangle plot.",
            ),
            _e(
                "data_sali",
                "SALI",
                "SALI",
                "Fingerprint similarity vs |Δactivity| colored by SALI.",
            ),
            _e(
                "tools_mmp",
                "MMP Transform Ledger",
                "MMP",
                "Matched molecular pair transform ledger.",
            ),
            _e(
                "data_plotter",
                "Plotter",
                "Plotter",
                "Scatter, histogram, heatmap, box, violin, radar.",
            ),
        ),
    ),
    GuideSection(
        "12 — Query Database",
        (
            _e(
                "ext_sql", "SQL Database", "SQL Database", "Load query results from a SQL database."
            ),
            _e("ext_pubchem", "PubChem", "PubChem", "Lookup and similarity search in PubChem."),
            _e("ext_chembl", "ChEMBL", "ChEMBL", "Molecules and bioactivity from ChEMBL."),
            _e(
                "ext_vendors",
                "Vendors",
                "Vendors",
                "Chemical vendors, product IDs, and product links.",
            ),
            _e("ext_patents", "Patents", "Patents", "SureChEMBL patent chemistry similarity."),
        ),
    ),
)

GUIDE_MENU: tuple[tuple[str, str], ...] = tuple(
    (e.guide_id, e.list_label) for s in GUIDE_SECTIONS for e in s.entries
)


def iter_guide_entries() -> list[GuideEntry]:
    out: list[GuideEntry] = []
    for section in GUIDE_SECTIONS:
        out.extend(section.entries)
    return out


def guide_entry(guide_id: str) -> GuideEntry | None:
    for entry in iter_guide_entries():
        if entry.guide_id == guide_id:
            return entry
    return None


def _guide_style_sheet(palette: QPalette | None = None) -> str:
    pal = palette or QApplication.palette()
    text = pal.color(QPalette.WindowText).name()
    mid = pal.color(QPalette.Mid).name()
    base = pal.color(QPalette.Base).name()
    window = pal.color(QPalette.Window).name()
    highlight = pal.color(QPalette.Highlight).name()
    tip_bg = pal.color(QPalette.AlternateBase).name()
    tip_border = highlight
    h2_color = text
    link = highlight
    return f"""
body {{ font-family: Segoe UI, sans-serif; font-size: 13px; color: {text};
       background: {base}; margin: 12px 16px; line-height: 1.45; }}
h2 {{ color: {h2_color}; font-size: 1.35em; margin: 0 0 0.6em 0; padding-bottom: 0.35em;
     border-bottom: 2px solid {mid}; }}
h1 {{ color: {h2_color}; font-size: 1.5em; margin: 0 0 0.55em 0; padding-bottom: 0.35em;
     border-bottom: 2px solid {mid}; }}
h3 {{ color: {text}; font-size: 1.05em; margin: 1.1em 0 0.45em 0; }}
p {{ margin: 0.55em 0; }}
ul, ol {{ margin: 0.4em 0 0.9em 0; padding-left: 1.35em; }}
li {{ margin: 0.4em 0; }}
b {{ color: {text}; }}
code {{ background: {window}; color: {text}; padding: 1px 5px; border-radius: 3px;
       font-size: 0.92em; border: 1px solid {mid}; }}
pre {{ background: {window}; border: 1px solid {mid}; border-radius: 4px;
      padding: 8px 10px; overflow-x: auto; }}
pre code {{ border: none; padding: 0; background: transparent; }}
table {{ border-collapse: collapse; margin: 0.6em 0 1em 0; width: 100%; }}
th, td {{ border: 1px solid {mid}; padding: 4px 8px; text-align: left; }}
th {{ background: {window}; }}
.tip {{ background: {tip_bg}; border-left: 3px solid {tip_border}; padding: 8px 12px;
       margin: 0.8em 0; color: {text}; }}
a {{ color: {link}; }}
hr {{ border: none; border-top: 1px solid {mid}; margin: 1em 0; }}
"""


def guide_html(guide_id: str, palette: QPalette | None = None) -> str:
    """Return a full HTML document for the given help topic."""
    md = load_help_markdown(guide_id)
    if md is None:
        body = missing_topic_html(guide_id)
    else:
        body = markdown_to_html_fragment(md)
    return (
        f"<html><head><style>{_guide_style_sheet(palette)}</style></head><body>{body}</body></html>"
    )


def _populate_guide_list(lst: QListWidget, *, select_guide_id: str | None = None) -> None:
    lst.clear()
    select_row = 0
    row = 0
    header_font = QFont(lst.font())
    header_font.setBold(True)

    for section in GUIDE_SECTIONS:
        header = QListWidgetItem(section.title)
        header.setFlags(Qt.NoItemFlags)
        header.setFont(header_font)
        header.setForeground(lst.palette().mid())
        lst.addItem(header)
        row += 1

        for entry in section.entries:
            it = QListWidgetItem(entry.list_label)
            it.setData(Qt.UserRole, entry.guide_id)
            it.setToolTip(entry.blurb)
            lst.addItem(it)
            if select_guide_id and entry.guide_id == select_guide_id:
                select_row = row
            row += 1

    lst.setCurrentRow(select_row)


def open_user_guide_dialog(parent: QWidget | None, guide_id: str | None = "overview") -> None:
    """Open the user guide (modeless). Reuses an existing window when possible."""
    topic = (guide_id or "overview").strip() or "overview"
    host = parent
    dlg = getattr(host, "_user_guide_dialog", None) if host is not None else None
    if dlg is not None:
        try:
            _show_guide_dialog(dlg, topic)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        except RuntimeError:
            if host is not None:
                host._user_guide_dialog = None

    dlg = QDialog(parent)
    dlg.setWindowTitle("MolManager — Help")
    dlg.resize(900, 620)
    dlg.setModal(False)
    dlg.setWindowModality(Qt.NonModal)

    content = QHBoxLayout(dlg)
    lst = QListWidget()
    lst.setMinimumWidth(280)
    _populate_guide_list(lst, select_guide_id=topic)

    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    content.addWidget(lst)
    content.addWidget(browser, 1)

    dlg._guide_list = lst  # type: ignore[attr-defined]
    dlg._guide_browser = browser  # type: ignore[attr-defined]

    def on_pick(current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            return
        gid = current.data(Qt.UserRole)
        if isinstance(gid, str):
            _show_guide_dialog(dlg, gid)

    lst.currentItemChanged.connect(on_pick)
    make_window_minimizable(dlg)

    if host is not None:
        host._user_guide_dialog = dlg
        # Weak: see the same slot in citations_dialog.py. A strong capture makes host and
        # dialog a reference cycle that the cyclic collector frees in a crashing order.
        host_ref = weakref.ref(host)

        def forget_dialog(*_args: object) -> None:
            owner = host_ref()
            if owner is not None:
                owner._user_guide_dialog = None

        dlg.destroyed.connect(forget_dialog)

    _show_guide_dialog(dlg, topic)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


def _show_guide_dialog(dlg: QDialog, guide_id: str) -> None:
    lst = getattr(dlg, "_guide_list", None)
    browser = getattr(dlg, "_guide_browser", None)
    if browser is not None:
        browser.setHtml(guide_html(guide_id, dlg.palette()))
    entry = guide_entry(guide_id)
    if entry is not None:
        dlg.setWindowTitle(f"MolManager — Help: {entry.menu_label}")
    else:
        dlg.setWindowTitle("MolManager — Help")
    if lst is not None:
        for i in range(lst.count()):
            it = lst.item(i)
            if it is not None and it.data(Qt.UserRole) == guide_id:
                lst.setCurrentRow(i)
                break
