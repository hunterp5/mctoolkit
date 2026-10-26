# Common Core

**Chemistry → Substructure → Common Core** finds one maximum common substructure over the chosen rows.

## Goal

Get a core you can paste into **Core-Based Decomposition** or **Free-Wilson**, and see which rows do not contain it.

## When to use

Use on a series when the shared core is not obvious, or when a few structures should not force the core to shrink.

## Inputs / scope

At least two valid molecules in the chosen **Target Column**. **Selected Rows Only** limits the search to the selection.

## Options

- **Outliers to ignore** - how many structures may lack the core. The search still requires the core in at least two molecules.
- **Time limit** - stop the search if it runs longer than this. The default is 30 seconds.
- **Complete rings only** - keep the core from ending in the middle of a ring. Leave this on when the core will be used for R-group decomposition.

## Workflow

1. Select the series, or clear **Selected Rows Only** to use every row.
2. Set how many outliers to ignore.
3. Run the search.

## Use cases

- Propose the core for a Free-Wilson analysis.
- Copy the core SMARTS into **Chemistry → R-Group Decomposition → Core-Based Decomposition**.

## Tips and limits

The run writes three columns:

- **Common core** - the core as SMARTS, drawn in 2D. The same core is written on every row in the run.
- **Core atom map** - atom indices in that row that match the core. Blank when the row does not match.
- **Core match** - `yes` or `no`. Filter on `no` to see the outliers.

Invalid structures write **N/A** and are left out of the search. If the search times out, raise the time limit or search fewer rows.
