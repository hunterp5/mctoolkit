# AutoQSAR

AutoQSAR searches descriptors and models for one activity column, then writes predictions for the winner.

## Goal

Choose a useful feature set and algorithm without setting fingerprints, hyperparameters, or a column checklist.

## When to use

Open it from **Data → QSAR → AutoQSAR**. Use it when labeled rows are available and the goal is a first model. Use **Generate Model** when the feature columns and algorithm should stay under manual control.

## Inputs / scope

- **Visible Rows Only** / **Selected Rows Only** / **Refresh columns**.
- **Activity (Y)** column. **Task**: Auto, Regression, or Classification.
- **Effort**: Quick (default hyperparameters, 3-fold CV) or Standard (a short second-stage grid, 5-fold CV).
- **Structure** source, used to calculate descriptors and fingerprint blocks.
- **Prediction column**, default `AutoQSAR_<activity>`.

The training fraction is fixed at 80%. Selection never uses the hold-out rows.

## What the search tries

- Numeric columns already on the table, except the activity column and fingerprint on-bit counts.
- 2D catalog descriptors (physiochemical, counts, complexity, electronic, QED, and Ro5). LogD, LogS at pH 7.4, and other ionization-backed scores are not calculated.
- 3D descriptors only when a 3D pose exists for at least 80% of the structures.
- Morgan and MACCS fingerprint blocks. Standard also tries the RDKit fingerprint, then a short hyperparameter grid on the best candidates.
- The best numeric set combined with Morgan.

Columns that are already filled are reused. A column is written back only when the winning model uses a descriptor this search calculated.

## Workflow

1. Filter or select the modeling set (at least 8 rows).
2. Choose the activity column, task, and effort.
3. Run AutoQSAR and read the leaderboard. The top row is the winner. Trust the hold-out score more than the selection CV.
4. Add predictions to the table. Any new descriptors the winner uses are written in the same step.

## Tips and limits

Small sets overfit. The selection score is training-set CV; the hold-out number is the one that was not used to pick the model. Fingerprints are tried as whole blocks, not as individual bits. Quick skips SVR. This is not a deep-learning AutoQSAR and it does not estimate an applicability domain.
