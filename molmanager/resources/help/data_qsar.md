# QSAR

QSAR trains and applies regression or classification models on table features (numeric columns and optional 2D fingerprints), with train fraction, CV, and algorithm-specific parameters.

## Goal

Build a predictive model from your labeled rows and write predictions back as a column for triage.

## When to use

Open it from **Data → QSAR → Generate Model**. Use it when you have enough labeled molecules and want to choose the features and algorithm yourself.

## Inputs / scope

Labeled rows with an **Activity (Y)** column; features from checked numeric columns and an optional fingerprint. **Selected Rows Only** limits training and prediction to the current selection; otherwise every table row is used.

## Options

- **Activity (Y)** - **Column**, **Task** (Auto / Regression / Classification), **Selected Rows Only**.
- **Features (X)** - numeric column checklist, **Fingerprint** (None, or a 2D fingerprint), **Structure** (used when a fingerprint is chosen).
- **Algorithm** - e.g. Ridge, Lasso, MLR, PLS, KNN, SVR, Random forest, Gradient boosting (classification: Logistic, RF, GB, SVM).
- **Train fraction**, **CV folds**, **Standardize numeric features**.
- Algorithm **Parameters** (Alpha, Components, Neighbors, Kernel, C, Trees, ...).
- **Prediction column**; **Train/Evaluate**; **Add predictions to table**.

## Workflow

1. Select the modeling set if you want **Selected Rows Only**.
2. Choose activity column, task, feature columns, and an optional fingerprint.
3. Pick algorithm, train fraction, CV, and parameters.
4. Train/Evaluate, then add predictions for triage/plots.

## Use cases

- Regress pIC50 on descriptors + Morgan FP.
- Classify actives/inactives with random forest.
- Compare PLS vs ridge on a small congeneric set.

## Tips and limits

Small N overfits easily - trust CV more than training score. Task Auto can mis-detect labels; set Regression/Classification explicitly when needed. Predictions are only as good as labels and features; this is not automatic SAR truth.
