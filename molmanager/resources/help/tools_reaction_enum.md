# Reaction Enumeration

Reaction Enumeration applies reaction SMARTS to reactant sets (files or SMILES text) and writes products to the table and/or a file, with a max-products cap.

## Goal

Generate product libraries in silico from defined chemistry instead of drawing each analog.

## When to use

Use **Chemistry → Reaction → Reaction Based Enumeration** for combinatorial expansions, reagent scans, or validating a reaction SMARTS on small reactant lists.

## Inputs / scope

Reaction SMARTS plus reactant inputs (structure file or SMILES text per reactant). Optional product constraints; outputs to table and/or file.

## Options

- **Reaction** / **Reaction SMARTS** (paste, **Load RXN…** from an MDL ``.rxn``/``.rdf``, or prefilled from a selected table row with a **Reaction SMARTS** column).
- **Reactant 1/2** - input mode **Structure file** / **SMILES text**, **Browse...**.
- **Max products** - cap on enumerated outputs.
- Optional **Product constraints**.
- **Add products to table** / **Save products to file** (+ **Browse...**).
- **OK** / **Cancel**.

## Workflow

1. Enter a validated reaction SMARTS, load an RXN file, or use SMARTS from a selected table row.
2. Supply reactants for each role.
3. Set **Max products** and output destinations.
4. Run, then filter/deduplicate products in the table.

## Use cases

- Enumerate amide couplings from acid/amine lists.
- Smoke-test a SMARTS on two reactants before a huge reagent set.
- Save products to SDF while also appending to the session.

## Tips and limits

Combinatorial blow-up is real - keep **Max products** sane. Reaction SMARTS must be RDKit-valid and role-correct. Stereo/regio outcomes follow the SMARTS, not lab intuition.
