# QSAR

QSAR trains and applies regression or classification models on table features (numeric columns and optional 2D fingerprints), with train fraction, CV, and algorithm-specific parameters.

## Goal

Build a predictive model from your labeled rows and write predictions back as a column for triage.

## When to use

Open it from **Data → QSAR → Generate Model**. Use it when you have enough labeled molecules and want to choose the features and algorithm yourself.

## Inputs / scope

Labeled rows with an **Activity (Y)** column; features from selected columns and/or fingerprints. Scope: **Visible Rows Only** and/or **Selected Rows Only**.

## Options

- **Visible Rows Only** / **Selected Rows Only** / **Refresh columns**.
- **Activity (Y)** - **Column**, **Task** (Auto / Regression / Classification).
- **Features (X)** - column checklist, **All** / **None**, **Include 2D fingerprints**, **Fingerprint**, **Structure**.
- **Algorithm** - e.g. Ridge, Lasso, MLR, PLS, KNN, SVR, Random forest, Gradient boosting (classification: Logistic, RF, GB, SVM).
- **Train fraction**, **CV folds**, **Standardize numeric features**.
- Algorithm **Parameters** (Alpha, Components, Neighbors, Kernel, C, Trees, ...).
- **Prediction column**; **Train & evaluate**; **Add predictions to table**.

## Workflow

1. Filter/select the modeling set and refresh columns.
2. Choose activity column, task, features, and FP settings.
3. Pick algorithm, train fraction, CV, and parameters.
4. Train & evaluate, then add predictions for triage/plots.

## Use cases

- Regress pIC50 on descriptors + Morgan FP.
- Classify actives/inactives with random forest.
- Compare PLS vs ridge on a small congeneric set.

## Tips and limits

Small N overfits easily - trust CV more than training score. Task Auto can mis-detect labels; set Regression/Classification explicitly when needed. Predictions are only as good as labels and features; this is not automatic SAR truth.
