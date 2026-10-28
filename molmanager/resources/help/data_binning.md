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
- **Names** — optional labels for those bins, from low to high, separated by commas (`Inactive, Active`). The count must match the bins the edges produce, including the open-end bins. Leave blank for the default class names.
- **Open ends** — for custom edges, add a bin below the first cut and a bin at or above the last cut. Turn it off to leave values outside the cuts blank. The bins are listed under the checkbox.
- **Selected Rows Only** — write labels only for the current selection.

The range is written to a column named after the source plus `_bin`, and the class to the source plus `_class`. An existing name gets a `(1)` suffix. Class names run from the low bin to the high bin: two bins are Inactive and Active, three are Low, Medium, and High, four are Low, Medium, High, and Very high, and any other count is Class 1, Class 2, and so on. **Names** overrides these for custom edges.

## Workflow

1. Choose the numeric column and a method.
2. Set the bin count, width, or edges. For custom edges, optionally name each bin and check the bins listed under Open ends.
3. Apply and inspect the new columns.

## Use cases

- Band pIC50 with edges `5, 6, 7` and open ends (`< 5`, `[5, 6)`, `[6, 7)`, `≥ 7`).
- Label two activity bins `Inactive, Active` in Names for a classification model.
- Split LogP into five equal-width ranges.
- Mark quartile groups with equal-count bins labeled `1`–`4`.

## Tips and limits

Bins are half-open: a value on an interior edge goes in the higher bin, and the last finite bin includes its upper edge. Identical values stay in the same equal-count bin, so ties can produce fewer bins than requested. At most 256 bins. Cells that are not plain numbers (blank, text, inequalities) stay blank.
