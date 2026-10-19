# ChEMBL

ChEMBL access retrieves molecules and associated bioactivity-oriented public data into MolManager for exploration.

## Goal

Use public medicinal chemistry data as context or starting points beside your proprietary table.

## When to use

Use when you need ChEMBL structures/activities for benchmarking or idea generation.

## Inputs / scope

Network access to ChEMBL; queries depend on the dialog (IDs, searches, random fetch elsewhere). Results become table rows/columns.

## Options

- **Identity / Similarity** - lookup the SMILES, or search 2D Tanimoto neighbors. Min. Tanimoto and Max. structures appear only for Similarity.
- **Fields** - Identity, Structures, and the Properties box are always listed. Identity and Structures start checked.
- **Activities and targets** - its own box, with the include checkbox and the per-molecule limits. Activities and Targets tabs appear after a query that asked for them.
- **Results** - one pane with the per-molecule summary and the query log.
- **Add to table** - write the returned rows into the session.

## Workflow

1. Open **Tools → Query Database → ChEMBL**.
2. Search or fetch the records of interest.
3. Select results to keep.
4. Add them to the table and standardize structures if needed.

## Use cases

- Gather public actives for a target as a reference set.
- Compare in-house hits to ChEMBL near neighbors.
- Seed Random Molecule-style exploration with real chemotypes.

## Tips and limits

Activities are heterogeneous across assays - read ChEMBL assay context before modeling. Structures may need neutralization/parenting. API/network failures should be retried with narrower queries.
