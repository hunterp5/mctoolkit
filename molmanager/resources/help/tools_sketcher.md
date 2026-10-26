# Sketcher

The Sketcher is an interactive molecule editor for drawing, editing, and inserting structures into the MolManager workflow.

## Goal

Create or modify a molecule visually when SMILES editing is awkward, then use the result in the table or as a query.

## When to use

Use to prototype analogs, fix a bad import, or draw a query core for R-group or reaction work.

## Inputs / scope

Starts from a blank canvas or an existing molecule when launched in an edit context. Output is a structure you can apply/insert per the dialog actions.

## Options

- **Canvas** - interactive drawing surface. The structure is drawn with the same depiction as the Structure column. The mouse wheel zooms toward the cursor. Drag with the middle button, or hold Space and drag, to pan. Arrow keys nudge a selection.
- **Draw** - a blank sketch opens here. A sketch opened from a table row opens in Select.
- **Chain** - drag to grow a zigzag carbon chain on the 30° grid. A short click places one carbon. The whole chain is one undo step.
- **Bond** - one button opens single, double, triple, wedge, hash, wavy, and dative. Keys 1, 2, and 3 set the bond order. Dative bonds are dashed.
- **Rings** - one button opens carbocycles, heterocycles, and fused systems (naphthalene, indole, quinoline, isoquinoline, benzimidazole, purine). Drop a template on a bond to fuse it, or on empty canvas to place it.
- **Groups** - contract CF3, CN, N3, CO2H, SO3H, PO3H2, OMe, or Boc onto an atom. The same groups are the ones the Structure column can contract. The canvas keeps every atom you placed until you contract one yourself.
- **Elements** - the left rail is the common set (C, N, O, S, F, Cl, Br, I, P, H) plus `*`, `?`, R1, R2, and Rn. **More…** lists the rest of the saved element set. Rn asks for a number and exports as `[*:n]`.
- **Clipboard** - paste a molfile or SMILES onto the canvas, and copy a molfile or a PNG of the structure. The PNG is the depiction, without the selection frame.
- **Reaction arrow** - drag to split the sketch into reactants (tail) and products (head). Double-click the arrow, or right-click it, to write text above and below it. **Export to Table** adds **Reaction SMARTS** (the structures only) and, when you wrote text, **Reaction Annotation**. The 2D scheme is rendered in Structure.
- **Edit** - While the sketcher window is active, Ctrl+Z undoes the sketch, Ctrl+Y or Ctrl+Shift+Z redoes it, Ctrl+C / Ctrl+V copy and paste a selected fragment, and Del deletes the atom or bond under the cursor or the current selection. The same keys edit the table when this window is not active. Right-click the canvas for Copy / Paste. A selected fragment shows a frame; drag the handle above it to rotate.
- **Clean Up** - lays the sketch out the same way a structure without saved coordinates is laid out for the table.
- **Status bar** - reports the last edit: atoms selected, deleted, copied, pasted, undone, and similar actions.
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
