# Bemis–Murcko

**Chemistry → Substructure → Bemis–Murcko** writes scaffold columns for the chosen structures.

## Goal

See the ring-and-linker skeleton shared by a series, and how many rows use each one.

## When to use

Use after the table has structures, when fingerprint clusters are splitting a series that still shares a core.

## Inputs / scope

Rows with valid molecules in the chosen **Target Column**. **Selected Rows Only** limits the run to the selection. Scaffold count is how many rows in that run share the scaffold.

## Options

- **Murcko scaffold** - rings and the linkers between them, with atom types kept. Drawn in 2D when the run finishes. Blank when the structure has no rings.
- **Murcko framework** - that skeleton as carbon with single bonds. Drawn in 2D.
- **Murcko ring systems** - the scaffold with linker atoms removed. Separate systems are joined with a dot. Drawn in 2D.
- **Scaffold count** - how many rows in the same run share the scaffold. `0` when there are no rings. This column stays a number.

All four start checked. Clear a box to skip that column.

## Workflow

1. Choose the structure column and whether to use the selection.
2. Leave the columns you want checked.
3. Run the calculation. Depictions follow the structure columns.

## Use cases

- Color a plot by scaffold, or pick one example from each skeleton.
- Compare frameworks when atom type should not split the series.

## Tips and limits

A structure with no rings gets a blank scaffold and a count of `0`. Invalid structures write **N/A**. Re-running writes `Name (1)` when the previous column is already filled.
