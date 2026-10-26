# R-Group Decomposition

R-Group Decomposition matches a core (SMARTS/SMILES) across molecules and writes R-group columns for the variable substituents.

## Goal

Tabulate substituents around a shared core for SAR tables and series analysis.

## When to use

Use **Chemistry → Structure Decomposition → Core-Based Decomposition** on a congeneric series when you can express the core and attachment pattern.

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
