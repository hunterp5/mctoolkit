# Diverse Subset

Diverse Subset picks a chemically diverse subset of rows using MaxMin-style algorithms (Auto / Exact / Fast) with optional rank column and table selection. Open it from **Data → Similarity**.

## Goal

Reduce a large hit list to a smaller set that still covers chemical space.

## When to use

Use before expensive assays, docking, or visual review when the library is too redundant.

## Inputs / scope

Fingerprints from the chosen structure source and fingerprint type; optional **Selected Rows Only** as the pool to pick from.

## Options

- **Structure source** and **Fingerprint**.
- **Algorithm** - **Auto** (exact when small, Fast when large), **Exact MaxMin**, **Fast** (staged prefilter + MaxMin).
- **Subset size** - how many rows to pick.
- **Selected Rows Only** - restrict the candidate pool.
- **Select subset in table** - apply selection to picks.
- **Add rank column** / **Rank column** - write selection order ranks.
- **Pick Diverse Subset** - run.

## Workflow

1. Filter to the candidate pool (or select rows).
2. Choose FP + algorithm and **Subset size**.
3. Optionally enable rank column and table selection.
4. Run and export or analyze the diverse picks.

## Use cases

- Pick 50 diverse actives from 5,000 hits.
- Build a screening plate with broad coverage.
- Downsample before clustering visualization.

## Tips and limits

Diversity is fingerprint-space diversity, not guaranteed property diversity. Exact MaxMin is costly on huge pools - use **Fast** or **Auto**. If the pool is smaller than subset size, you get the whole pool.
