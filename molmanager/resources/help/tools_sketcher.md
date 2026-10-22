# Sketcher

The Sketcher is an interactive molecule editor for drawing, editing, and inserting structures into the MolManager workflow.

## Goal

Create or modify a molecule visually when SMILES editing is awkward, then use the result in the table or as a query.

## When to use

Use to prototype analogs, fix a bad import, or draw a query core for R-group or reaction work.

## Inputs / scope

Starts from a blank canvas or an existing molecule when launched in an edit context. Output is a structure you can apply/insert per the dialog actions.

## Options

- **Canvas** - interactive drawing surface with bond/atom tools and a reaction arrow.
- **Element** and **bond order** controls. In Custom, **R1** and **R2** attach a numbered point to the atom you click (exported as `[*:1]` and `[*:2]` for R-group enumeration).
- **Reaction arrow** - drag to split the sketch into reactants (tail) and products (head). **Export to Table** then adds **Reaction SMARTS** and renders the 2D scheme in Structure.
- **Edit** - Undo/Redo, **Copy** / **Paste** of a selected fragment (Ctrl+C / Ctrl+V), and **Delete Selection** (Del, same as **Edit → Delete Selection** on the table). Right-click the canvas for the same Copy / Paste at the top of the menu.
- **Edit tools** - select, erase, and ring templates as provided.
- **Apply / accept** - push the drawn molecule or reaction back to the caller or table.

## Workflow

1. Open **Sketcher** from the tools entry point.
2. Draw or edit the molecule. For a reaction, draw reactants, click the reaction-arrow tool, drag from reactants toward products, then draw products on the head side.
3. Validate valence/stereo visually.
4. **File → Export to Table** adds the sketch as new rows. On the Structure column, right-click **Edit in Sketcher** (under Paste). Closing that sketcher asks whether to replace the row, and that write can be undone.

## Use cases

- Sketch a core SMARTS precursor for R-group decomposition.
- Draw a reaction scheme and add it to the table for Reaction Enumeration.
- Correct a mis-imported structure.
- Design a quick analog and add it as a new row.

## Tips and limits

Sketcher output still must be chemically valid for RDKit tools. Complex stereo may need careful bond markup. For bulk enumeration prefer Reaction Enumeration rather than manual drawing.
