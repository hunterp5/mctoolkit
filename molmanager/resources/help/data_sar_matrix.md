# SAR Matrix

SAR Matrix pivots two R-group columns into a grid and colors each filled cell by an activity column. A third substituent becomes pages. An empty cell is a combination that is not in the table.

## Goal

See the series as the R1 × R2 table used in a review, including the combinations nobody has made.

## When to use

Use **Data → SAR Matrix** after **Chemistry → Reaction → R-Group Decomposition** has written R columns. Use **Free-Wilson** when you want a predicted activity for those empty cells.

## Inputs / scope

Two substituent columns and one numeric activity column. Optional third substituent and **Selected Rows Only**. Rows hidden by a filter are left out. A row with a blank or N/A substituent is left out.

## Options

**Grid**

- **Row substituent** — usually R1. These labels run down the side.
- **Column substituent** — usually R2. These labels run across the top.
- **Page substituent** — optional R3. Each value is its own grid, and the R1 and R2 labels stay in the same places.

**Activity**

- **Activity column** — number used to color a filled cell. Several compounds in one cell show their mean and a count.
- **Higher values are better** — the largest number is the darkest green. Clear this for IC50 and other columns where smaller is better.
- **Selected Rows Only**.

## Workflow

1. Decompose the series so the table has R1 and R2 columns.
2. Open **Data → SAR Matrix** and check the suggested columns.
3. Click a filled cell to select those rows.
4. Use the page list when a third substituent is set.
5. **Export…** writes the current page as CSV. Blank cells were not made.

## Use cases

- Review which R1/R2 pairs are still missing.
- Jump from a dark cell back to the compounds that made it.
- Hand the same grid to someone as a CSV.

## Tips and limits

Each axis stops at 60 substituents; filter the series if a column is wider than that. The color scale uses the cells on every page, so a page can be compared with the next one. The mean hides a spread: the cell tooltip lists each row.
