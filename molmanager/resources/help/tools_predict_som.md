# Predict SOM

Predict SOM runs FAME3R (via the NERDD service) to score atoms as likely **sites of metabolism** and draws a 2D map with those sites highlighted.

## Goal

See where a xenobiotic is most likely to be metabolized (Phase 1, Phase 2, or CYP-focused models) without leaving the table.

## When to use

Use after structures are loaded, when you need metabolic soft-spot maps for design, metabolite planning, or to compare substitution sites.

## Inputs / scope

Rows with valid molecules in the chosen structure **Source**, or a single **SMILES string**. Optional **Selected Rows Only**. Requires network access to NERDD.

## Options

- **Input** - table rows or a SMILES string.
- **Source** - structure column to read (table mode).
- **Selected Rows Only** - limit to the current selection.
- **Metabolism** - Phase 1 and 2 (default; two NERDD jobs), Phase 1, Phase 2, or CYP-mediated.
- **SOM threshold** - probability cutoff for calling an atom a SOM (FAME3R default 0.30).
- **Compute FAME score** - optional applicability-domain score (slower).
- **Predict** - queue the background job.

## Workflow

1. Choose table rows or paste SMILES.
2. Pick the metabolism subset and threshold.
3. Run **Predict** and wait on **Processes**.
4. Review maps in the **Predict SOM Browser** (large structure preview, color scale beside the map, **←** / **→**). Click an atom row to emphasize that atom. Click an atom-table column header to sort numerically or alphabetically. **Browse Only Selected** limits the browser to the current table selection. Reopen it from **Chemistry → Predict → SOM → Viewer** when SOM columns are already in the table. Right-click a **SOM Map** cell for **Browse** (open this row in the browser) or **Export** (save the map image). SOM sites are labeled with atom number and probability. Maps use a yellow–red probability scale. **Phase 1 and 2** also writes **SOM Sites Phase 1**, **SOM Sites Phase 2**, and **SOM Phase**.

## Use cases

- Flag likely metabolic soft spots on a lead series.
- Separate Phase 1 vs Phase 2 sites for the same structure in one **Phase 1 and 2** run (two NERDD jobs).
- Preview one SMILES before running the full table.

## Tips and limits

This is **not** Data → DimRed Plots → Self-Organizing Map. Predictions use FAME3R models hosted on NERDD; they are free for non-commercial research. Highlighted atom indices match the preprocessed structure on the map. Failed molecules leave N/A text and no image. **Cancel** keeps completed molecules: they are written to the table and opened in the browser. If you cancel a **Phase 1 and 2** run after Phase 1 finishes, Phase 1 sites are still written. **Save Session** stores SOM maps so they redraw when the session is opened. Dock the browser with **Add to Main Window** if you want it beside the table.
