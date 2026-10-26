# Search

Search builds multi-criterion queries with AND/OR/NOT logic. Quoted text searches a column. Unquoted SMILES or SMARTS searches structures.

## Goal

Find rows matching one or more textual or structural criteria quickly, then select or inspect the matches.

## When to use

Use for ad-hoc lookup (ID, name fragment, SMARTS) when a standing filter card is unnecessary.

## Inputs / scope

Searches the current table columns. Structure criteria need a valid structure/SMARTS-capable column.

## Options

- Every criterion row has **AND** / **OR** / **NOT**. On the first row, **NOT** selects rows that do not match; **AND** and **OR** both start from the matches. On later rows, **NOT** removes rows that match that criterion from the matches so far.
- **Column** chooser and query field. The column applies to quoted text. Unquoted SMILES/SMARTS searches loaded structures.
- **Partial Match** and **Case Sensitive** apply to quoted column text.
- **Add** / **−** on every criterion row. **−** on the last remaining row deletes that search and closes Search.
- Closing Search from the menu or shortcut hides the panel but keeps query rows until they are deleted.

## Workflow

1. Open **Search** and set the first column + query.
2. Quote column text (`"eth*"`, `>10`). Leave a structure query unquoted (`c1ccccc1`, `[F,Cl]`).
3. Add more criteria with **AND**, **OR**, or **NOT**. Use **NOT** on the first row to keep rows that fail that query.
4. Jump to or select matches, then optionally promote logic into Filters.

## Use cases

- Find all rows whose ID contains a lot prefix.
- OR across synonym name columns.
- SMARTS-search a reactive motif before MMP analysis.

## Tips and limits

AND/OR/NOT mixes follow the criterion list order - keep queries simple when unsure. Invalid SMARTS yield no matches. Search is complementary to Filters; use Filters for persistent constraints. To edit cell text, including wildcards and comparisons, use Edit → Find and Replace (Ctrl+H). An open Search panel and its active query rows are stored in the session file and restored on Open. Toggling Search off keeps the current queries; use **−** to delete a row, or the last **−** to clear Search and close the panel.
