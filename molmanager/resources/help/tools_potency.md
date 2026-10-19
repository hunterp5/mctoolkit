# Potency Standardization

Potency Standardization reads an activity value and the unit on that row, writes the value in nM or uM, and can add pActivity. An IC50 can also become a Ki with the Cheng–Prusoff equation.

## Goal

Put mixed assay units on one scale so QSAR, SALI, and Free-Wilson see the same kind of number.

## When to use

Use when a table mixes nM, µM, M, and mass/volume units such as mg/mL or g/L, or when an IC50 should be compared as pIC50 or as a Ki.

## Inputs / scope

A numeric data column and a unit column. The unit column holds the unit for each row: nM, uM, mol/L, or a mass/volume unit such as mg/mL, µg/mL, g/L, or kg/m^3. Mass/volume rows use **Molecular Weight**, either the structure's average weight or a g/mol column. Applies to all rows or **Selected Rows Only**.

## Options

- **Data Column / Unit Column / Molecular Weight / Measure** - the source values, the per-row unit, the g/mol source for mass/volume units, and whether the output is named IC50, EC50, Ki, or Kd.
- **Desired Unit** - nM or uM. The activity column is written in that unit.
- **pActivity** - −log10 of the molar value (pIC50, pKi, and so on), to three decimal places.
- **Cheng–Prusoff** - for an IC50, Ki = IC50 / (1 + Σ concentration / Km or Kd). Use **Add assay concentration** for each concentration that enters the correction. Each one can be a constant or a column, with its own unit.
- **Selected Rows Only** - limit the write to the selection.

## Workflow

1. Open **Tools → Potency Standardization**.
2. Choose the data column and the column that stores each row's unit.
3. Leave molecular weight on **From structure**, or pick a g/mol column when the table already has one.
4. Choose nM or uM, leave pActivity checked when you want it, and turn on Cheng–Prusoff only when the assay concentrations are known.
5. **Apply to Table**.

## Use cases

- Turn a CRO table whose units vary by row into one nM column and pIC50 before a QSAR model.
- Convert mixed µM and nM Ki values onto one uM scale.
- Estimate Ki from IC50 when the assay substrate concentration and Km, or a radioligand concentration and Kd, are known.

## Tips and limits

Blank cells stay blank. A leading <, >, or ~ is left blank so a censored value is not treated as exact. Zero and negative activities are left blank because pActivity is undefined there. A mass/volume unit is left blank when that row has no positive molecular weight. g/mol in the unit column is a molar mass, not a concentration, so it is left blank. Cheng–Prusoff here is the competitive form and is offered only for IC50. A concentration of zero adds nothing to the correction. Each Km or Kd must be positive.
