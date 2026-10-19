# Cluster

Cluster groups rows by fingerprint similarity, numeric columns, or both. Methods include K-Means, Agglomerative, DBSCAN, Butina, sphere exclusion, and Jarvis-Patrick, with an optional exploratory trial mode.

## Goal

Partition a library into clusters for series assignment, exemplars, or stratified follow-up.

## When to use

Use after cleanup when you need groups based on structure, on calculated properties, or on both.

## Inputs / scope

Fingerprints from **Source** structures, checked **numeric columns**, or both. Optional **Selected Rows Only**. Exploratory mode samples many parameter sets before you apply one trial. Butina, sphere exclusion, and Jarvis-Patrick require a fingerprint and no numeric columns.

## Options

- **Source** - structure column for fingerprints.
- **Selected Rows Only** - scope.
- **Fingerprint** - FP type, or **None** to cluster numeric columns only.
- **Numeric columns** - descriptor columns for K-Means, Agglomerative, and DBSCAN. Combined with a fingerprint, the bit block is rescaled so it does not drown the columns.
- **Standardize numeric columns** - zero mean, unit variance on the checked columns.
- **Exploratory mode** - sample many parameter sets; **Max trials**.
- **Methods to sample** / **Method** - **K-Means**, **Agglomerative**, **DBSCAN**, **Butina (Tanimoto)**, **Sphere exclusion (Leader)**, **Jarvis-Patrick**.
- Method parameters - **Clusters (k)**, **Linkage**, **eps**, **min_samples**, **Distance cutoff**, **Reordering**, **Nearest neighbors (J)**, **Shared neighbors (P)**.
- **Run clustering** / **Apply selected trial**.

## Workflow

1. Choose a fingerprint, numeric columns, or both, then set scope.
2. Either set one method/parameters or enable **Exploratory mode**.
3. Run clustering and review trial/cluster labels.
4. Apply the chosen trial and use cluster IDs in filters/plots.

## Use cases

- Assign series labels for medchem reporting.
- Compare Butina cutoffs in exploratory mode.
- Cluster only selected actives for SAR grouping.
- Group a series by calculated properties (for example MW, logP, TPSA) instead of structure.

## Tips and limits

No single method is best for every library - validate chemically. DBSCAN and Butina parameters are scale-sensitive: fingerprint DBSCAN uses cosine distance, while numeric and combined features use Euclidean distance. Large N × exploratory trials can be slow; watch **Processes**.
