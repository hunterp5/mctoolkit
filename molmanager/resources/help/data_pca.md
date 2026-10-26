# PCA

PCA projects feature/fingerprint space onto principal components for a linear overview of variance in the library.

## Goal

Embed high-dimensional molecular/feature space into a 2D plot for visual structure of the library (PCA).

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
- **Components** - number of principal components.
- **Run PCA**.
- Footer: gear (**Plot Options**), **Clear Selection**, then Add/Send glyph and **Close Plot** (pane **×** when docked).

## Workflow

1. **Data → Dimensionality Reduction → Principal Component Analysis** opens **Plot Options** (the empty plot window stays closed).
2. Select feature columns and optional fingerprint.
3. Set standardization, color-by, and method parameters.
4. Run the embedding; the plot window opens when results are ready.
5. Select points to highlight rows back in the table when linked.

## Use cases

- Color embeddings by activity or cluster labels.
- Compare selected series against the full library.
- Use FP-only embeddings when descriptors are incomplete.

## Tips and limits

PCA is linear - nonlinear manifolds may need t-SNE/UMAP. Standardize when mixing units. Interpret axes as variance directions, not automatic chemical labels. Table filters hide points after Run; the embedding is fit on all rows (or **Selected Rows Only**).
