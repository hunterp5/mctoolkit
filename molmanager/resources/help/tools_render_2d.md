# Render 2D

Render 2D regenerates 2D depictions for scoped rows as a background batch, refreshing structure images in the table.

## Goal

Repair missing, outdated, or poorly laid-out depictions after imports or structure edits.

## When to use

Use when cells show blank images, after bulk structure changes, or before screenshots/exports that rely on cached pictures.

## Inputs / scope

Structure columns for rows in scope; optional **Selected Rows Only**.

## Options

- Structure source / target column as shown. Reaction SMARTS / SMIRKS columns (`>>`) draw as reaction schemes and use a wider column; molecule depictions keep their usual size.
- **Selected Rows Only** when available.
- Batch render job (monitor under **Processes**).

## Workflow

1. Select rows with bad/missing art (or use all rows).
2. Start **Render 2D**.
3. Wait for the process to finish.
4. Scroll the table to confirm images updated.

## Use cases

- Refresh depictions after Fast Prepare.
- Fix SMILES imports with empty picture caches.
- Redraw a selection before a slide export.

## Tips and limits

Rendering large libraries is CPU-bound - prefer selection scope. Coordinates are 2D only; 3D conformers are separate tools. Invalid molecules still cannot depict. File Open/Import and session restore auto-run Render 2D for every row, drawing the rows on screen first; use this tool afterward to redraw a column or a selection. While a batch runs, rows you scroll to are drawn next.
