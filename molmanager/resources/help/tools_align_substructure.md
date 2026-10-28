# Align to Substructure

**Chemistry → Substructure → Align to Substructure** redraws matching rows so a substructure you supply sits in one shared orientation. Rows that do not contain the query are left as they are.

## Goal

Give a series one common drawing of a shared core, without changing the stored molecule.

## When to use

Use when default layouts put the same core in different directions, and a later query should orient the rows the first query skipped.

## Inputs / scope

One structure column. The query is a SMILES, SMARTS, molfile, or a sketch. Optional **Selected Rows Only**.

## Options

- **Target column** — pictures to redraw. Structure uses the row molecule. Other columns use that column's text.
- **Query** — the orientation is the query's 2D coordinates. A molfile keeps its coordinates. SMILES and SMARTS start from a default layout.
- **Edit in sketcher**, **Rotate 90°**, **Flip horizontal**, and **Flip vertical** adjust that pose. The query must be one fragment of at least two atoms.
- **Skip rows that already have an orientation** — on by default, so a second query orients only the leftovers. Uncheck it when a molecule contains both substructures and the new query should replace the old pose.
- **Reset orientation** — drop stored coordinates in scope and redraw with the usual layout. No query is required.
- **Selected Rows Only** when a selection exists.

## Workflow

1. Choose the column.
2. Paste or draw the substructure in the orientation you want.
3. Align. The status line reports how many rows were aligned and how many were skipped.
4. Run again with a different query to orient the rows that did not match.
5. Reset orientation when you want the default layout back.

## Use cases

- Line up a shared scaffold across a series before a slide or a comparison.
- Orient one core, then a second core, without moving the first series.
- Clear a stored pose after it no longer matches the chemistry.

## Tips and limits

The stored molecule and its SMILES do not change. Only the picture does. Opening an SDF or molfile keeps that file's flat 2D coordinates as the row's orientation. A hydrogen that carries a wedge, dash, or double-bond stereo stays on the molecule so its coordinates stay with the drawing. Other explicit hydrogens are removed. 3D coordinates stay with the conformers, and the picture uses the usual layout. Those file orientations count as already oriented, so the default skip leaves them in place until you uncheck it or reset. A chemistry edit, paste, or sketcher update of the row drops the pose for that row, because the atoms may no longer line up. Render 2D keeps an existing orientation. Coordinates are 2D depictions: 3D preview, PDB, and PDBQT export ignore them. SDF and MOL export include them. A query that matches nothing leaves those rows unchanged.
