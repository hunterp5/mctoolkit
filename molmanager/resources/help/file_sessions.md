# Sessions

Sessions let you open, save, create, and duplicate MolManager project states so table data and related workspace context can be revisited later. Session commands live under **File → Session**. Sessions you have opened or saved also appear under **File → Open Recent**.

## Goal

Persist a working library and return to it without rebuilding filters, columns, and tool outputs from scratch.

## When to use

Use at natural breakpoints: after cleaning structures, before long QSAR runs, or when branching an experiment into a duplicate session.

## Inputs / scope

The current in-memory table and session metadata. Open loads from a saved session file; New starts clean; Duplicate copies the current state; **Save Selected to Session** writes only the currently selected table rows. Docked and floating plots (including custom pane titles), filters, workspace layout, and an open **Search** panel with its query rows are included. The **Protein Viewer** is included only after **File → Save to Session** in that window, and is restored when you open **Protein → Viewer**.

## Options

- **Open Session** - load an existing session.
- **Open Recent** - **File → Open Recent** lists those sessions (and data files) so you can reopen one without browsing. Duplicate Session's temporary copy is not listed. **Clear Recent** empties the list.
- **Save Session** - write the current session to disk.
- **Save Selected to Session** - write a new session file that contains only the selected table rows (does not replace or clear the current session).
- **New Session** - start a fresh session.
- **Duplicate Session** - clone the current session for parallel what-if work.

## Workflow

1. Build or import your table and optional tool columns.
2. **File → Session → Save Session** with a clear name.
3. Later **File → Session → Open Session** to resume.
4. **Duplicate Session** before risky bulk edits or alternate model settings.
5. Select rows and **Save Selected to Session** to hand off a subset without changing the open workspace.

## Use cases

- Checkpoint before protonation or fragment disconnection.
- Duplicate a parent library for separate MPO vs QSAR tracks.
- Hand a saved session to a collaborator with the same MolManager version.

## Tips and limits

Session files are not a substitute for raw data archives - keep original SDFs/CSVs. Opening a session keeps a full-workspace loading page up until rows, filters, Search, and plot widgets are in place, then shows the table, plots, Search, and filter panel together. Plotly views and **SOM Map** images may finish drawing after the overlay lifts. When structures still need drawing, the workspace appears once the rows on screen are drawn, and auto **Render 2D** fills in the rest in the background. **Structure** molecules are stored as compact RDKit binaries (plus SMILES) so Open does not re-parse SMILES; they are not rebuilt from **Protonated** or other tool columns. Filter min/max bounds are stored so slider cards restore without a full-table scan. Column order, widths, hidden columns, 2D pixmap chemistry columns, sort, filters, an active **Search** (panel visibility, columns, queries, AND/OR/NOT, and match options), workspace layout (including plot/table splitter positions), **docked plots**, and **floating plot windows** are restored: Plotter settings, PCA/t-SNE/UMAP/SOM embeddings, BOILED-Egg / Golden Triangle, SALI, Activity Cliff, and MMP Neighborhood maps (including pane layout, active page, and custom pane titles). Predict SOM maps (SMILES, sites, and atom scores) are stored so **SOM Map** images and the Predict SOM Browser can be restored on open. Successful Uni-pKa ionization ensembles are stored in the session so Protonate, Generate Protomers, LogD/LogS 7.4, CNS MPO, and AB-MPS can reuse them after Open / Duplicate without re-running inference. Failed predictions are not saved, so they can be retried. The last **MMP** run (matched pairs for the Transform Ledger) is stored so right-click **Transform Ledger** on MMP table columns works after Open / Duplicate. The last **Gnina** docking run (docked poses, scores, and receptor/crystal paths) is stored with packed **poses** table columns so **Protein → Dock Ligand → Pose Browser** can reopen after Open / Duplicate. Drawn **Structure** depictions are saved too, so a reopened session paints them without redrawing; Render 2D redraws them only after a MolManager update changes how structures are drawn. A `.cms` is a single SQLite file (**version 4**). Open reads it on a background thread and installs the table in one step, then restores filters, plots, and tool sidecars. Saving runs in the background as well, so you can keep working. Sessions saved by older MolManager versions (version 1–3 `.cms` files and session CSVs) no longer open directly. Convert them once with `python scripts/convert_session.py <file>`, which rewrites the file in place and keeps a `.bak` copy. Opening replaces the current unsaved work unless you saved first.
