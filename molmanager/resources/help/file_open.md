# Open File

Open File loads a molecule, reaction, or data file into a new or current workspace table (SDF, MOL, MOL2, SMILES, CSV/TSV, Excel, PDBQT, MDL RXN/RDF, and related formats).

## Goal

Bring an external library into MolManager as the working compound table with structures and properties ready for tools.

## When to use

Start a new analysis from disk, replace the current table with a fresh file, or reload a cleaned export.

## Inputs / scope

File on disk. Structure columns are parsed when the format carries molecules; CSV/TSV/Excel tables with a SMILES or structure column (comma, semicolon, tab, or pipe). Gzip (``.gz``) wrappers of those text/SDF files are accepted. MDL ``.rxn`` / ``.rdf`` files load as rows with **Reaction SMARTS**, reactant/product SMILES, and a product (or reactant) depiction.

## Options

- **File browser** / path selection for supported chemistry and table formats (SDF/SD/MOL, MOL2, SMILES, CSV/TSV, Excel ``.xlsx``, TDT, PDB, PDBQT, RXN/RDF, including ``.gz``).
- **Format parsing** - multi-molecule SDF/MOL2/PDBQT, SMILES lists, delimited or Excel tables with structure columns, and MDL reaction files.
- **Main table** columns and depictions populated after a successful load.
- **Open Recent** — **File → Open Recent** lists files and sessions you have opened or saved (ten of each, newest first). Choosing a file opens it the same way as **Open File**. **Clear Recent** empties the list. A path that is missing or unreadable is dropped when you choose it.

## Workflow

1. Choose **File → Open** (or equivalent) and select a file.
2. Confirm the table populated with expected columns and depictions.
3. Fix structure source if needed, then filter or run tools.
4. Save a session if you will continue later.

## Use cases

- Load an HTS SDF (or ``.sdf.gz``) for clustering and diverse subset picking.
- Open a CSV or Excel sheet of SMILES plus assay columns for QSAR.
- Open an MDL ``.rxn`` file to inspect the transform as **Reaction SMARTS** and run **Chemistry → Reaction → Reaction Based Enumeration**.
- Reload a vendor catalog before fingerprint similarity searches.
- Bring Gnina ligand PDBQT or MOL2 files into the table.

## Tips and limits

Very large files may take time and memory; prefer filtered exports when possible. Malformed SMILES rows may appear empty or invalid for structure tools. Opening typically replaces or defines the working table - use Import when you need to append. A loading page stays up until the table is built and filter bounds are ready; auto **Render 2D** continues in the background (skipped when the row count is over the auto-2D limit). CSV/TSV tables may use comma, semicolon (common for ChEMBL downloads), tab, or pipe; the delimiter is detected from the header.
