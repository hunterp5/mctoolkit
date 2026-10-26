# LipE

LipE (lipophilic efficiency) plots pActivity against LogP. Parallel lines are constant LipE, where LipE = pActivity − LogP.

## Goal

See whether potency is coming from lipophilicity or from a more efficient interaction. Higher LipE sits above the higher diagonal.

## When to use

Use when a series has both a pActivity column (pIC50, pKi, or pEC50) and structures or a LogP column, and you want to compare compounds on efficiency rather than potency alone.

## Inputs / scope

pActivity is read from the column you choose. LogP is taken from a LogP column when one exists, and filled from the structure when that cell is empty. Scope via **Selected Rows Only** as needed.

## Options

- **Selected Rows Only**.
- **Structure from**.
- **pActivity from**.
- **Color by**, **Spectrum**, **Min** / **Max**.
- **Size by**, marker **Min size** / **Max size** (pixels).
- **LipE ≥ 5** selects compounds on or above that reference line.
- Footer: gear (**Plot Options**), **Clear Selection**, then Add/Send glyph and **Close Plot** (pane **×** when docked).

## Workflow

1. Use a p-scale activity column. Raw IC50 or Ki is not LipE.
2. Open **Data → MedChem Plots → LipE**. Settings open so you can choose the activity column.
3. Choose **pActivity from**, then **Run**.
4. Read the diagonals: the solid line is LipE 5. The in-scope count and how many compounds reach LipE 5 are written to the in-app Log.
5. Use **LipE ≥ 5** to focus follow-up tools.

## Use cases

- Compare analogs that differ in both potency and LogP.
- Color by series and see which series climbs above LipE 5.
- Select the efficient subset before an MPO or Free-Wilson run.

## Tips and limits

LipE depends on the pActivity definition and on the LogP method. A column that is still in nM or µM will draw a meaningless plot. Rows with a missing pActivity are left off the plot. Table filters hide points after Run; coordinates are computed for all rows (or **Selected Rows Only**).
