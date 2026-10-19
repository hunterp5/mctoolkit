# Edit

The Edit menu covers undo/redo, clipboard operations, and selection commands that change table contents or the current selection set.

## Goal

Correct mistakes safely and move values or selections efficiently while editing the compound table.

## When to use

Use after accidental deletes/edits, when copying cells/structures, or when selecting all / inverting selection for scoped tools.

## Inputs / scope

Operates on the current table and selection. Undo depth depends on recent editable actions.

## Options

- **Undo** / **Redo** - reverse or reapply recent table edits.
- **Copy** / **Paste** - copy a rectangular cell block as tab-separated text (Excel-compatible). Paste at the top-left of the current selection. Multi-cell clipboards ask whether to fill this cell only or multiple cells; overwriting populated cells requires confirmation. Extra rows/columns that do not fit the table are skipped. Structure cells still need SMILES, InChI, or a MolBlock.
- **Invert Selection** - select every row that is not currently selected, including rows hidden by filters.
- **Clear Selection** - clear the current cell or row selection.
- **Delete Selection** - delete selected rows, delete selected columns (when no rows are selected), or clear values from selected cells. When both rows and columns are selected, choose which to delete. Structure cannot be removed as a column.
- Related edit actions exposed in the menu for the active table focus.

## Workflow

1. Make an edit or selection change.
2. Use **Undo** if the result is wrong.
3. Copy values as needed for Excel or another app; paste a copied block from the top-left cell.
4. Shape selection before running **Selected Rows Only** tools.

## Use cases

- Undo a bulk column clear.
- Select all visible hits then invert to exclude them.
- Copy a 2×2 of descriptors and paste it into empty cells.

## Tips and limits

Not every background tool result is undoable the same way as cell edits - prefer session duplicates before destructive bulk jobs. Paste validity still depends on column types (structure cells need a parseable molecule). Numeric columns store pasted text as-is, matching Edit Value. Keep focus on the table for edit shortcuts to apply.
