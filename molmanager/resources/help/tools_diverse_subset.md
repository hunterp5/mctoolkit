# Diverse Subset

Diverse Subset picks a chemically diverse subset of rows using MaxMin-style algorithms (Auto / Exact / Fast) with optional rank column and table selection. Open it from **Data → Similarity**.

## Goal

Reduce a large hit list to a smaller set that still covers chemical space.

## When to use

Use before expensive assays, docking, or visual review when the library is too redundant.

## Inputs / scope

A fingerprint, one or more numeric columns, or both. Fingerprints come from the chosen structure source. Numeric columns must be complete on a row for that row to stay in the pool. Optional **Selected Rows Only** limits the pool.

## Options

- **Structure source** and **Fingerprint**. **None** uses numeric columns only.
- **Numeric columns**. Checked columns are part of the distance. **Standardize Numeric Columns** puts them on a common scale. With a fingerprint, the bits are rescaled so those columns still affect the pick.
- **Algorithm** - **Auto** (exact when small, Fast when large), **Exact MaxMin**, **Fast** (staged prefilter + MaxMin).
- **Subset size** - how many rows to pick.
- **Selected Rows Only** - restrict the candidate pool.
- **Select subset in table** - apply selection to picks.
- **Add rank column** / **Rank column** - write selection order ranks.
- **Pick Diverse Subset** - run.

## Workflow

1. Filter to the candidate pool (or select rows).
2. Choose a fingerprint, numeric columns, or both, then the algorithm and **Subset size**.
3. Optionally enable rank column and table selection.
4. Run and export or analyze the diverse picks.

## Use cases

- Pick 50 diverse actives from 5,000 hits.
- Build a screening plate with broad coverage.
- Downsample before clustering visualization.

## Tips and limits

Fingerprint-only picks use Tanimoto distance. Numeric columns, alone or combined with a fingerprint, use Euclidean distance. **Fast** on a numeric or combined pool MaxMin-picks inside a random candidate sample. Exact MaxMin is costly on huge pools. If the pool is smaller than the subset size, you get the whole pool.
