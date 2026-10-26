# Extract Reaction Info

Extract Reaction Info splits a reaction SMARTS / SMIRKS column into one new column per reactant and/or product.

## Goal

Turn packed reaction cells into individual structure columns for filtering, enumeration, or depiction.

## When to use

Use **Chemistry → Extract Reaction Info** after loading an RXN file, sketching a reaction into the table, or importing SMIRKS when you need the components as separate fields.

## Inputs / scope

One table column whose cells contain reaction SMARTS or SMIRKS (`>>`, or reactant `>` agent `>` product). Optional **Selected Rows Only**. The source column is left unchanged. Agents between the two `>` marks are ignored.

## Options

- **Column** — reaction SMARTS / SMIRKS source. Defaults to **Reaction SMARTS** when that header exists.
- **Extract** — **Reactants**, **Products**, or **Both**. Each component is written to its own column (`Reactant 1`, `Reactant 2`, `Product 1`, …). Rows with fewer components leave the extra columns blank.
- **Selected Rows Only** — write values only for the current selection; other rows stay empty in the new columns.
- **OK** / **Cancel**.

## Workflow

1. Select the reaction column (or keep the Reaction SMARTS default).
2. Choose reactants, products, or both.
3. Optionally restrict to selected rows.
4. Apply and inspect the new columns. Use **Chemistry → Render 2D** if you want depictions.

## Use cases

- Pull products out of sketched reactions for a product-only table view.
- Split multi-reactant SMARTS into reagent columns before Reaction Enumeration.
- Export individual components after opening an MDL ``.rxn`` file.

## Tips and limits

Concrete molecules are written as SMILES; query templates keep SMARTS. Column names that already exist get a ``(1)`` suffix. Invalid or empty cells leave the new columns blank for that row.
