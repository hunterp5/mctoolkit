# Save File

Save File writes the table (all rows or the current selection) to common chemistry and spreadsheet formats for sharing or downstream tools.

## Goal

Produce a portable file of structures and properties without leaving MolManager's current analysis state behind.

## When to use

Use after filtering to a hit list, after adding scores/descriptors, or when handing molecules to docking or ELN systems.

## Inputs / scope

Current table columns and structures. Choose all rows or selected rows depending on the save dialog scope.

## Options

- Save **all** rows (**File → Save File**) or **selected** rows (**File → Save Selected**).
- Format choice appropriate to the destination (SDF, MOL, MOL2, SMILES, CSV, TSV, Excel, TDT, PDB, PDBQT).
- Destination path / file name. A successful save is added to **File → Open Recent** under Files.

## Workflow

1. Select rows if you only need a subset.
2. Choose **File → Save File** or **File → Save Selected**, then pick format.
3. Choose the output path and run the save (may appear under **Processes**).
4. Verify the file in the target application.

## Use cases

- Save a diverse subset for external vendor quoting.
- Send selected docking candidates as SDF.
- Dump scored QSAR predictions to CSV for a report.

## Tips and limits

Hidden or filter-excluded rows may or may not be included depending on whether you save the full table vs selection - check scope. Some formats drop depiction caches and keep connection tables only. Large saves can be slow; watch Processes.
