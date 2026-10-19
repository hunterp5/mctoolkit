# Interaction Fingerprint

Interaction Fingerprint types the first stored pose on each row against a receptor and writes the contacts as a fingerprint plus a residue list.

## Goal

See which residues a pose touches, so two poses with the same score can be told apart by their contact pattern.

## When to use

Use **Protein → Interaction Fingerprint** after a docking run has written a **poses** column. The receptor is the protein the poses were docked into.

## Inputs / scope

A receptor PDB or mmCIF, and a packed **poses** column. Optional **Selected Rows Only**. Rows hidden by a filter are left out. The first pose in the cell is typed. When docking wrote poses best-first, that is the best-ranked pose.

## Options

- **Receptor** — polymer chains are used. Crystal ligands and waters in the file are ignored.
- **Pose column** — packed poses, usually **poses**.
- **Column prefix** — writes that column and **prefix Residues**. The default prefix is **IFP**.
- **Selected Rows Only**.

## Workflow

1. Dock the series, or import a table that already has a poses column.
2. Open **Protein → Interaction Fingerprint** and choose the receptor file.
3. Run. Each contact is `chain:resname:resid:family`, separated by semicolons.
4. Filter or plot the residue list. A later series contact map can count those residues.

## Use cases

- Compare which residues the best pose of each analog touches.
- Find rows whose pose makes no hydrogen bond to a chosen residue.
- Keep the contact pattern next to the assay column.

## Tips and limits

ProLIF is required (`pip install prolif`). A row with no pose is written as **N/A**. A pose that was typed and makes no contacts is left blank. Families are hydrogen bond, hydrophobic, salt bridge (`ionic`), pi-stacking, pi-cation, and halogen. The fingerprint is the set of contacts, not a count of how many times a residue is touched.
