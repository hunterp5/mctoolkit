# t-SNE

t-SNE builds a nonlinear 2D embedding that emphasizes local neighborhoods, useful for visual cluster separation.

## Goal

Embed high-dimensional molecular/feature space into a 2D plot for visual structure of the library (t-SNE).

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
- **Perplexity**, **Learning rate**, **Max iterations**.
- **Max points**, **Random seed**.
- **PCA-compress before embedding** - on by default. **PCA components** (default 50), optional **PCA min. variance**, and **Whiten**. Turn the checkbox off to embed raw columns/fingerprints.
- **Run t-SNE**.
- Footer: gear (**Plot Options**), **Clear Selection**, then Add/Send glyph and **Close Plot** (pane **×** when docked).

## Workflow

1. **Data → DimRed Plots → t-SNE Visualization** opens **Plot Options** (the empty plot window stays closed).
2. Select feature columns and optional fingerprint.
3. Set standardization, color-by, and method parameters.
4. Run the embedding; the plot window opens when results are ready.
5. Select points to highlight rows back in the table when linked.

## Use cases

- Color embeddings by activity or cluster labels.
- Compare selected series against the full library.
- Use FP-only embeddings when descriptors are incomplete.

## Tips and limits

t-SNE distances are not global metrics - do not over-read far-point spacing. Perplexity and seed change layouts; fix seed for comparisons. **Max points** subsamples large sets (default and cap 25,000). Wide inputs (typical fingerprints) are PCA-compressed before embedding unless you uncheck that option; raise **PCA components** or set a variance target if 50 PCs drop too much structure. Table filters hide points after Run; the embedding is fit on all rows (or **Selected Rows Only**).
