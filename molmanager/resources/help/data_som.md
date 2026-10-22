# Self-Organizing Map

Self-Organizing Map (SOM) places molecules on a learned grid for topological visualization of chemical/feature space.

## Goal

Embed high-dimensional molecular/feature space into a 2D plot for visual structure of the library (Self-Organizing Map).

## When to use

Use when tabular columns alone do not reveal groupings, or to compare chemical space coverage across subsets.

## Inputs / scope

Feature columns and/or fingerprints from a structure source; optional **Selected Rows Only**. Color-by column for overlays.

## Options

- **Features** - column list to include.
- **Fingerprint** - None or an FP type.
- **Structure from** - structure source when FP is used.
- **Selected Rows Only**.
- **Standardize features** - zero mean, unit variance.
- **Color by**, **Spectrum**, color **Min** / **Max**.
- **Size by**, marker **Min size** / **Max size** (pixels).
- **Map width**, **Map height**, **Epochs**.
- **Learning rate**, **Sigma**, **Point jitter**.
- **Max points**, **Random seed**.
- **PCA-compress before embedding** - on by default. **PCA components** (default 50), optional **PCA min. variance**, and **Whiten**. Turn the checkbox off to train on raw columns/fingerprints.
- **Run SOM**.
- Footer: gear (**Plot Options**), **Clear Selection**, then Add/Send glyph and **Close Plot** (pane **×** when docked).

## Workflow

1. **Data → DimRed Plots → Self-Organizing Map** opens **Plot Options** (the empty plot window stays closed).
2. Select feature columns and optional fingerprint.
3. Set standardization, color-by, and method parameters.
4. Run the embedding; the plot window opens when results are ready.
5. Select points to highlight rows back in the table when linked.

## Use cases

- Color embeddings by activity or cluster labels.
- Compare selected series against the full library.
- Use FP-only embeddings when descriptors are incomplete.

## Tips and limits

Grid size vs library size matters - too small collapses distinctions. Training epochs increase cost. **Max points** subsamples large sets (default and cap 25,000). Wide inputs (typical fingerprints) are PCA-compressed before training unless you uncheck that option; raise **PCA components** or set a variance target if 50 PCs drop too much structure. Jitter helps separate overlapping points visually but is not chemical distance. Table filters hide points after Run; the embedding is fit on all rows (or **Selected Rows Only**).
