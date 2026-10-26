# Binning

Binning assigns each numeric value in a column to a bin and writes two new columns: the bin range and a classification label. Open from **Data → Similarity → Binning**.

## Goal

Turn a continuous column into labels you can filter, color, and group by.

## When to use

Use when a cutoff or a coarse range is easier to work with than the raw number (activity bands, property ranges, quantile groups).

## Inputs / scope

One numeric column in the current table. Optional **Selected Rows Only**. The source column is left unchanged. Non-numeric cells are left blank in the new column.

## Options

- **Column** — values to bin.
- **Method** — **Equal width** (equal spans across the range), **Equal count** (about the same number of values in each bin), or **Custom edges**.
- **Bins** — how many bins to aim for. For equal width, ignored when **Bin width** is set.
- **Bin width** — optional width. With Minimum and Maximum empty, edges line up with histogram bins in the Plotter.
- **Minimum** / **Maximum** — optional ends of an equal-width range. Values outside are left blank.
- **Edges** — custom cut points, such as `5, 6, 7`. They must increase.
- **Open ends** — for custom edges, add a bin below the first cut and a bin at or above the last cut.
- **Range column** — header for the bin range (`[0, 1)`, with the last bin closed). Defaults to the source name plus `_bin`.
- **Class column** — header for the classification. Names run from the low bin to the high bin: two bins are Inactive and Active, three are Low, Medium, and High, four are Low, Medium, High, and Very high, and any other count is Class 1, Class 2, and so on. Defaults to the source name plus `_class`. An existing name gets a `(1)` suffix.
- **Selected Rows Only** — write labels only for the current selection.

## Workflow

1. Choose the numeric column and a method.
2. Set the bin count, width, or edges.
3. Confirm the range and classification column names.
4. Apply and inspect the new columns.

## Use cases

- Band pIC50 with edges `5, 6, 7` and open ends (`< 5`, `[5, 6)`, `[6, 7)`, `≥ 7`).
- Label two activity bins `Inactive` and `Active` for a classification model.
- Split LogP into five equal-width ranges.
- Mark quartile groups with equal-count bins labeled `1`–`4`.

## Tips and limits

Bins are half-open: a value on an interior edge goes in the higher bin, and the last finite bin includes its upper edge. Identical values stay in the same equal-count bin, so ties can produce fewer bins than requested. At most 256 bins. Cells that are not plain numbers (blank, text, inequalities) stay blank.
