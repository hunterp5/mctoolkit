# Vendors

Vendors looks up deposited chemical suppliers for a structure and lists each product that PubChem records as in stock.

## Goal

See who sells a structure, with the vendor's product ID and a link to the product page when one was deposited.

## When to use

Use after you have structures in the table and want to know which of them are offered by a chemical vendor.

## Inputs / scope

Needs network access to PubChem. Each query structure is matched by SMILES. A structure with no deposited chemical vendor is left out of the result.

## Options

- **Query** - one SMILES per line, the Sketcher, or **Only Query Selected**.
- **Results** - one row per query. Expand it to see **Vendor**, **Product ID**, and **URL**. Double-click a URL to open the product page. A single query opens expanded.
- **Log** - structures with no vendor, and lookup errors. Those structures are not result rows.
- **Add result(s) to table** - optional. Append every product row to the main table.
- **Add unique products only** - skip a product when that structure, vendor, and product ID is already in the table.

## Workflow

1. Open **Tools → Query Database → Vendors**.
2. Select the rows to check, turn on **Only Query Selected**, or paste SMILES.
3. Press **Query**. Expand a query to see its vendors. Structures with no vendor are named in the log and are not listed.
4. Add product rows to the main table only when you want them in the workspace.

## Use cases

- Check which analogs in a series are offered for purchase.
- Collect product IDs and catalog links next to the structures.
- Drop compounds that have no deposited vendor before ordering.

## Tips and limits

The list is PubChem's Chemical Vendors category: depositors who report a product as in stock. It is not a price list, and it does not include make-on-demand catalogs that were not deposited. The URL is the product page when the depositor supplied one; otherwise that cell is blank. Expand a query in the results list to read vendors without adding them to the table. NCBI request quotas apply, so large selections take time. Cancel stops after the structure that is already in flight.
