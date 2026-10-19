# Overview

MolManager is a desktop chemical table workspace for loading, preparing, analyzing, and exporting small-molecule data with RDKit-backed structure tools.

## Goal

Orient yourself in the main window so you can move between the compound table, filters/search, tools, charts, and background processes without losing context.

## When to use

Open this topic first when learning the app, after a layout change, or when you need a map of menus and workspace controls.

## Inputs / scope

Works on the current session table (structures plus property columns). Most tools can target all rows or only the current selection when **Selected Rows Only** is available.

## Options

- **File** - open/import data, sessions, export, selection browser.
- **Edit** - undo/redo, clipboard, and selection commands.
- **Tools** - calculator, potency standardization, random numbers and molecules, notepad, **Query Database** (SQL, PubChem, ChEMBL, vendors, patents), and the sketcher.
- **Chemistry** - calculate descriptors, prepare structures, conformations, fingerprints, substructure (Bemis–Murcko scaffolds and common core), reactions, R-group enumeration, and predictors (pKa, permeability, SOM).
- **Protein** - 3D structure viewer for PDB, mmCIF, and related crystallographic files, **Sequence** for MAFFT multiple-sequence alignment, docking, and interaction fingerprints for stored poses.
- **Data** - table operations, lists, statistics, clustering, plotter, MedChem plots, dimensionality reduction, QSAR, MPO, SAR matrix, filters, and table search.
- **Settings** - theme, fonts, hotkeys, WSL executable for Linux-only tools, and **Help**.
- **Layout** - rearrange or restore workspace panes.
- **Log** - inspect running/queued background jobs and the session log (tool output, status history, warnings).
- **Settings → Help** - User Guide and Citations. F1 also opens the guide.

## Workflow

1. Load or open a session with structures in the table.
2. Optionally filter or select the rows you care about.
3. Run a tool from **Chemistry** / **Tools** / **Data**; watch **Log** for long jobs and the transcript below the job table.
4. Inspect new columns, plots, or docked panes; export or save the session.

## Use cases

- Keep a working library open while clustering, scoring, and plotting subsets.
- Use the same session across docking prep, QSAR, and export without reloading files.
- Teach new users the menu map before diving into specialized dialogs.

## Tips and limits

Long jobs run in the background; cancel or clear them from **Log**, which also keeps the full transcript. Structure-dependent tools need a valid structure source column. Layout changes are session UI state - save the session if you want the table data preserved.
