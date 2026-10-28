# Filters

Filters restrict which rows are visible using stacked filter cards (substructure, slider, text, category) with per-card enable and invert controls.

## Goal

Narrow the library to chemically or numerically interesting subsets without deleting rows, so tools and plots can focus on what remains visible.

## When to use

Use during hit triage, before scoped exports, or whenever you need reusable constraints (e.g. MW range + SMARTS).

## Inputs / scope

All table rows; cards reference structure sources or property columns. Tools that honor visibility/selection still need correct scope checkboxes.

## Options

- **+** / Add Filter dialog - choose **Substructure**, **Slider**, **Text**, or **Category**.
- Card **title** - double-click to rename.
- Drag cards to **reorder** application order.
- **On** - enable/disable a card without deleting it.
- **Invert** - keep the complement of the card's matches.
- **Substructure** - structure source + SMARTS.
- **Slider** - column with **Min** / **Max**.
- **Text** - column, partial/exact, case options, query.
- **Category** - column with category checklist (**All** / **None**).
- Panel actions to enable/disable/delete all filters.

## Workflow

1. Click **+** and pick a filter type.
2. Configure the card (SMARTS, range, text, or categories).
3. Rename and reorder cards; toggle **On** / **Invert** as needed.
4. Select visible rows or run tools on the filtered set.

## Use cases

- Combine Ro5-like slider ranges with a warhead SMARTS.
- Category-filter assay bins then diversify the remainder.
- Invert a substructure filter to exclude a scaffold class.

## Tips and limits

Disabled cards are ignored. A row with no value in the filtered column, or no structure for a substructure card, stays hidden, including when Invert is on. Invert on multiple cards can be easy to misread - rename titles clearly. Substructure performance depends on library size and SMARTS complexity. Filters change visibility; they do not permanently delete data.
