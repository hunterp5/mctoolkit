# Selectivity ratio

Selectivity Ratio writes log selectivity of a primary assay against each off-target column, and flags potent rows whose window is still narrow.

## Goal

See which compounds are potent on the target of interest and still close to an anti-target.

## When to use

Use when the table has two or more assay columns on the same p-scale (pIC50, pKi, pEC50) and sorting on primary potency would hide poor selectivity.

## Inputs / scope

Log selectivity is primary pActivity minus off-target pActivity. A value of 1 is 10-fold. Columns must already be on that p-scale. Scope via **Selected Rows Only** as needed.

## Options

- **Primary** assay column.
- **Off-target** columns. Each checked column gets its own result.
- **Potent at**. Rows at or above this primary value count as potent. The default 6 is about 1 µM for a molar pIC50.
- **Window below**. A potent row is flagged when its smallest log selectivity is under this value. The default 1 is 10-fold.
- **Selected Rows Only**.

## Workflow

1. Standardize assays to a p-scale with **Tools → Potency Standardization** when the source values are still IC50 or Ki.
2. Open **Data → Selectivity Ratio** and choose the primary column and the off-targets.
3. Read `logSel vs …` for each off-target. Positive means more potent on the primary assay.
4. Filter **Narrow window** for `yes` to find potent rows that are not yet selective.

## Use cases

- Rank a series by selectivity instead of primary potency alone.
- Keep one column per anti-target when a panel has several counterscreens.
- Pull the narrow-window rows into a list before the next design cycle.

## Tips and limits

A raw nanomolar column makes the subtraction meaningless. Missing cells stay blank and are left out of the smallest-window test. The flag is `no` when the row can be judged and is either below the potency line or selective enough. It stays blank when the primary value or every off-target value is missing.
