# PubChem

PubChem integration looks up compounds and runs similarity-oriented retrieval from PubChem into your workspace.

## Goal

Bring public structures and identifiers into the table for comparison with internal series.

## When to use

Use for quick public analogs, CID lookups, or expanding a query into PubChem neighbors.

## Inputs / scope

Needs network access to PubChem. Queries start from identifiers/SMILES/structures as the dialog requires.

## Options

- **Identity / Similarity** - lookup the SMILES, or search 2D Tanimoto neighbors. Min. Tanimoto and Max. structures appear only for Similarity.
- **Fields** - every column is listed in groups: identifiers and names, structures, physchem, and counts. CID, common name, and isomeric SMILES start checked. Common Name is PubChem's preferred name (Title); Synonyms are the ranked synonym list.
- **Query** - SMILES box, Sketcher, or **Only Query Selected**.
- **Results** - log of the lookup, then **Add result(s) to table**.

## Workflow

1. Open **Tools → Query Database → PubChem**.
2. Enter the query (ID or structure-based search as offered).
3. Review returned compounds.
4. Add useful rows to the main table and annotate source.

## Use cases

- Pull public analogs of a lead SMILES.
- Resolve a name/CID to a structure for the sketcher/table.
- Build a small reference set for FP similarity.

## Tips and limits

PubChem content is public and may include salts/mixtures - clean after import. Service availability and quotas apply. Similarity in PubChem is not identical to in-app FP settings.
