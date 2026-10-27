# R-Group Decomposition

R-group decomposition writes a core column and substituent columns. Core-Based matches a core you draw. Most Central Ring chooses the core on each row.

## Goal

Tabulate substituents around a shared core for SAR tables and series analysis.

## When to use

Use **Chemistry → Structure Decomposition → Core-Based** on a congeneric series when you can express the core and attachment pattern.

## Inputs / scope

Molecules from the chosen structure source; core SMARTS/SMILES must match. Optional **Selected Rows Only**.

## Options

- **Core (SMARTS or SMILES)** - scaffold pattern.
- **Molecules from** - structure source.
- **Column name prefix** - naming for R columns.
- **Only match at R-groups...** - attachment constraints when enabled.
- **Remove hydrogens after match...**.
- **Matching strategy** - Greedy / Exhaustive.
- **Selected Rows Only**.

## Workflow

1. Filter to the series of interest.
2. Enter the core SMARTS/SMILES and prefix.
3. Choose matching strategy and options.
4. Run and inspect R-group columns; refine the core if match rate is low.

## Use cases

- Build an R1/R2 matrix for a lead series, then open **Data → SAR Matrix**.
- Feed R-group columns into category filters.
- Compare greedy vs exhaustive matching on ambiguous cores.

## Tips and limits

Poor cores yield missing R columns - iterate on SMARTS. Exhaustive matching is slower. Molecules that do not match the core are skipped or incomplete.

## Most central ring

Use **Chemistry → Structure Decomposition → Most Central Ring** when the rows do not share one drawn core, or when the core you want is the ring system in the middle of each structure.

The core is the ring with the smallest mean bond distance to the rest of the molecule. If that ring is fused, bridged, or spiro to other rings, those rings stay in the core. A ring attached only by a bond, and every chain, becomes an R group.

Columns are named `PREFIX_Core`, `PREFIX_R1`, `PREFIX_R2`, … The default prefix is `MCR`. Attachment labels are `[*:1]`, `[*:2]`, … in the same form core-based decomposition writes, so the columns can feed the SAR matrix and design studio. R numbers follow the core's canonical attachment order. A row with no ring is left as `N/A`.

Acyclic structures have no core. Symmetric positions on a symmetric core can trade R numbers. Bond distance ignores 3D coordinates, so a conformer does not move the core.
