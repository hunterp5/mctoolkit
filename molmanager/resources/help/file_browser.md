# Selection Browser

The Selection Browser summarizes and navigates the current table selection so you can review chosen compounds before acting on them.

## Goal

Confirm which rows are selected and operate on that set with confidence before export, tooling, or deletion.

## When to use

Use when the main grid selection is large or hard to see, or when preparing a focused list for a scoped tool run.

## Inputs / scope

The active selection in the compound table (and associated structures/properties).

## Options

- **Current-row table** - compact copy of the visible table columns for the row being browsed (structure stays in the preview above).
- **Browse Selected** - walk only the current selection, or the whole table when unchecked.
- **Live sync** - updates when the main table selection or data change while open.

## Workflow

1. Select rows in the table (or via filters/search).
2. Open **Data → Browser** (Selection Browser) to inspect the set.
3. Adjust selection in the table if needed.
4. Run a **Selected Rows Only** tool or **File → Save Selected**.

## Use cases

- Audit a multi-select before clustering.
- Review hits from a substructure filter.
- Confirm an export selection matches the intended series.

## Tips and limits

The browser reflects selection, not filter visibility alone - rows can be selected even when scrolled off-screen. Clearing selection empties the browser. Very large selections may be slower to list.
