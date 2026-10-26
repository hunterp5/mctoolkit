# Fingerprint Similarity

Fingerprint Similarity scores every scoped molecule against a query (from a table row or SMILES) using chosen fingerprint and metric, writing a similarity column. Open it from **Data → Similarity**.

## Goal

Rank the library by chemical similarity to a reference for nearest-neighbor triage.

## When to use

Use for hit expansion, duplicate hunting, or prioritizing analogs around a lead.

## Inputs / scope

Structure source molecules; query from **From Table Row** or **SMILES Input**. Optional compare-to-selected-rows scope.

## Options

- **Structure source** - molecules to score.
- **Fingerprint** - fingerprint type.
- **Similarity metric** - **Tanimoto** / **Dice** / **Cosine**.
- **Output column** - where scores are written.
- **Query** - **From Table Row** or **SMILES Input**.
- **Only compare to selected rows** - limit targets.
- **Compute and Add Column** - run.

## Workflow

1. Choose fingerprint + metric and output column name.
2. Set the query (row or SMILES).
3. Optionally limit to selected rows.
4. Compute and sort the table by the new score column.

## Use cases

- Find nearest neighbors to a clinical lead.
- Flag near-duplicates before purchasing.
- Compare Dice vs Tanimoto rankings on the same FP.

## Tips and limits

Fingerprint choice changes the chemical notion of "similar." Scores are not activity predictions. Invalid query SMILES aborts scoring - validate first.
