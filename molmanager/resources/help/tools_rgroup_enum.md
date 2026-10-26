# R-Group Enumeration

R-Group Enumeration attaches a list of building blocks at each numbered point on a core and appends the products as new rows.

## Goal

Make the set of compounds you would get by putting each reagent on the core, without writing a reaction SMARTS for every point.

## When to use

Use when the core is already drawn and the question is which amines, acids, or other blocks to put on R1, R2, and so on. Named reactions and BRICS recomposition are for bond-making rules. This is the direct “these blocks on this core” step.

## Inputs / scope

One core SMILES, with attachment points written as `[*:1]`, `[*:2]`, and so on. An unnumbered `*` is labeled in atom order. Each point has an attachment-point field (`R1`, `1`, or `[*:1]`) and a building-block file. A block puts `*` on the atom that should bond to the core (`CCN*` attaches through nitrogen). The file does not number that `*` to match the core; the attachment-point field does. `*`, `[H]`, or `[*:1][H]` caps that point.

## Options

- **Core / Sketcher** - the scaffold. **Core ID** is stored on every product row and defaults to the core SMILES.
- **Building blocks** - one row per core point. **Attachment point** selects the core label. **Browse** loads SDF, SMILES, or CSV. Each record needs one `*`. A name after the SMILES, or an id/name column or SDF title, becomes the reagent id. Otherwise the id is `R1-1`, `R1-2`, and so on.
- **Max products** - stop after this many unique product SMILES.
- **Product constraints** - the same property limits as fragment recomposition (MW, LogP, TPSA, and the rest). All conditions are AND.
- **Output** - append rows to the table, write an SDF, or both. Table columns are the structure, **Core_ID**, and **R1**, **R2**, … with the reagent id used at that point.

## Workflow

1. Open **Chemistry → Structure Enumeration → R-Group**.
2. Sketch or paste the core. One file row appears for each attachment point.
3. Set the attachment point and browse to that point's building-block file. Cap a point you are not varying with a file that contains `*`.
4. Optionally set property limits and a maximum number of products.
5. Run the enumeration and review the new rows.

## Use cases

- Put a short amine list and a short acid list on a two-point core.
- Cap R2 with hydrogen and vary only R1.
- Keep products inside a molecular-weight and LogP window before they are added to the table.

## Tips and limits

Up to eight attachment points. Each point needs at least one block, and each block needs exactly one `*`, unless it is a hydrogen cap. Products that fail sanitization or the property limits are omitted, and a repeated canonical SMILES is kept once. The run stops at **Max products** and, when limits are set, after a bounded number of combinations. This does not check stock or synthetic accessibility.
