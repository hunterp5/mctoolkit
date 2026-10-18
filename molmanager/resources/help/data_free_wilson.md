# Free-Wilson

Free-Wilson fits an additive model of substituent contributions on a shared core, then lists missing R-group combinations and their predicted activity.

## Goal

See how much each substituent adds to activity, and which unmade analogs the same model would score highest or lowest.

## When to use

Use **Data → Free-Wilson…** on a congeneric series when you can draw the core and its attachment points. Use **QSAR** when the series does not share one core. Use **MMP** when you want pairwise transforms rather than one additive model.

## Inputs / scope

Molecules from the chosen structure source, a numeric activity column, and a core SMARTS or SMILES. Optional **Selected Rows Only**. Rows without a numeric activity are left out before the fit.

## Options

- **Core (SMARTS or SMILES)** — label each attachment point with a dummy (`[*:1]`, `[*:2]`, …).
- **Coefficient report** — **Fujita-Ban** (default) is the change versus a reference substituent (hydrogen when that position has it, otherwise the most common). **Free-Wilson** recenters that same fit so the occurrence-weighted coefficients at each position sum to zero. Predictions match either way.
- **Minimum substituent count** — substituents seen fewer times are dropped, and molecules that contain them are not fitted.
- **Max new structures** — cap on missing combinations to list. When there are more, keep the highest or lowest predicted activity.
- **Matching strategy** — Greedy or Exhaustive core matching.
- **Only match at R-groups**.
- **Selected Rows Only**.

## Workflow

1. Filter to the series and enter the core.
2. Choose the activity column, report, and minimum count.
3. Run. Inspect contributions, observed versus predicted, and missing analogs.
4. **Write predictions** to add `FW_Predicted` on fitted rows.
5. **Add selected to table** or **Add all shown** to append missing analogs as new rows.

Nothing is written until you use those buttons.

## Use cases

- Rank R1 and R2 contributions versus hydrogen on a lead series.
- List the unmade combinations the additive model scores highest.
- Add a short list of those structures back onto the table for follow-up.

## Tips and limits

The model is additive: it has no interaction terms. A substituent seen once can fit that point exactly, so raise the minimum count when single-point groups should not drive the list. If the combination count exceeds 1,000,000, the fit is still shown and no partial list of missing analogs is generated. Aliased substituents are marked not identifiable. Log the activity column first when the series needs a log scale.
