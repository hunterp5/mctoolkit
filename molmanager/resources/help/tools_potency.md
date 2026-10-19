# Potency Standardization

Potency Standardization converts an activity column into mol/L and a pActivity, and can turn an IC50 into a Ki with the Cheng–Prusoff equation.

## Goal

Put mixed assay units on one scale so QSAR, SALI, and Free-Wilson see the same kind of number.

## When to use

Use when a table mixes nM, µM, and M, or when an IC50 should be compared as pIC50 or as a Ki.

## Inputs / scope

One numeric activity column, and the unit that column is in. Applies to all rows or **Selected Rows Only**.

## Options

- **Column / Unit / Measure** - the source values and whether the output is named IC50, EC50, Ki, or Kd.
- **Molar activity** - the same number in mol/L.
- **pActivity** - −log10 of the molar value (pIC50, pKi, and so on), to three decimal places.
- **Cheng–Prusoff** - for an IC50, Ki = IC50 / (1 + [S]/Km). Substrate and Km can be one value for every row or their own columns, each with a unit.
- **Selected Rows Only** - limit the write to the selection.

## Workflow

1. Open **Tools → Potency Standardization**.
2. Choose the activity column and the unit it is already in.
3. Leave molar activity and pActivity checked, and turn on Cheng–Prusoff only when [S] and Km are known.
4. **Apply to Table**.

## Use cases

- Turn a CRO IC50 in nM into pIC50 before a QSAR model.
- Convert µM Ki values to mol/L so two assays share a column scale.
- Estimate Ki from IC50 when the assay substrate concentration and Km are known.

## Tips and limits

Blank cells stay blank. A leading <, >, or ~ is left blank so a censored value is not treated as exact. Zero and negative activities are left blank because pActivity is undefined there. Cheng–Prusoff here is the competitive-inhibition form; it is offered only for IC50. Substrate may be zero, which leaves Ki equal to IC50. Km must be positive.
